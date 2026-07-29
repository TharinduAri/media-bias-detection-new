from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict

import numpy as np
import torch
from datasets import DatasetDict, load_dataset
from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
    set_seed,
)


NEWSMTSC_BASE_URL = (
    "https://raw.githubusercontent.com/fhamborg/NewsMTSC/"
    "6b838e00f54423c253806327a0ae24dbffa24c9e/"
    "NewsSentiment/experiments/default/datasets/"
)
RW_FILES = {
    "train": f"{NEWSMTSC_BASE_URL}newsmtsc-rw-hf/train.jsonl",
    "validation": f"{NEWSMTSC_BASE_URL}newsmtsc-rw-hf/dev.jsonl",
    "test": f"{NEWSMTSC_BASE_URL}newsmtsc-rw-hf/test.jsonl",
}
MT_TEST_FILE = f"{NEWSMTSC_BASE_URL}newsmtsc-mt-hf/test.jsonl"

ID2LABEL = {0: "negative", 1: "neutral", 2: "positive"}
LABEL2ID = {label: label_id for label_id, label in ID2LABEL.items()}


def parse_args() -> argparse.Namespace:
    backend_root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Fine-tune DeBERTa-v3 for target-dependent sentiment on NewsMTSC."
    )
    parser.add_argument(
        "--base-model",
        default="microsoft/deberta-v3-base",
        help="Hugging Face base model ID.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=backend_root / "models" / "deberta-v3-newsmtsc",
    )
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument(
        "--max-steps",
        type=int,
        default=-1,
        help="Override total training steps; use 1 for a quick smoke test.",
    )
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def compute_metrics(eval_prediction) -> Dict[str, float]:
    logits, labels = eval_prediction
    predictions = np.argmax(logits, axis=-1)
    precision, recall, per_class_f1, _ = precision_recall_fscore_support(
        labels,
        predictions,
        labels=[0, 1, 2],
        average=None,
        zero_division=0,
    )
    return {
        "accuracy": float(accuracy_score(labels, predictions)),
        "macro_f1": float(f1_score(labels, predictions, average="macro")),
        "negative_f1": float(per_class_f1[0]),
        "neutral_f1": float(per_class_f1[1]),
        "positive_f1": float(per_class_f1[2]),
        "macro_precision": float(np.mean(precision)),
        "macro_recall": float(np.mean(recall)),
    }


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cuda_available = torch.cuda.is_available()
    if cuda_available:
        torch.backends.cuda.matmul.allow_tf32 = True
        device_name = torch.cuda.get_device_name(0)
        memory_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        print(f"Training device: CUDA - {device_name} ({memory_gb:.1f} GB)")
    else:
        print("Training device: CPU (CUDA-enabled PyTorch was not detected)")

    dataset: DatasetDict = load_dataset("json", data_files=RW_FILES)
    mt_test = load_dataset("json", data_files={"test": MT_TEST_FILE})["test"]
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)

    def tokenize(batch):
        encoded = tokenizer(
            batch["mention"],
            batch["sentence"],
            truncation=True,
            max_length=args.max_length,
        )
        encoded["labels"] = [int(polarity) + 1 for polarity in batch["polarity"]]
        return encoded

    remove_columns = dataset["train"].column_names
    tokenized = dataset.map(
        tokenize,
        batched=True,
        remove_columns=remove_columns,
        desc="Tokenizing NewsMTSC real-world split",
    )
    tokenized_mt_test = mt_test.map(
        tokenize,
        batched=True,
        remove_columns=mt_test.column_names,
        desc="Tokenizing NewsMTSC multi-target test split",
    )

    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model,
        num_labels=3,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        dtype=torch.float32,
    )

    updates_per_epoch = math.ceil(
        len(tokenized["train"])
        / (args.batch_size * args.gradient_accumulation_steps)
    )
    planned_steps = (
        args.max_steps
        if args.max_steps > 0
        else math.ceil(updates_per_epoch * args.epochs)
    )
    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=max(args.batch_size, 16),
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        weight_decay=0.01,
        warmup_steps=max(1, round(planned_steps * 0.1)),
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_strategy="steps",
        logging_steps=50,
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        save_total_limit=2,
        fp16=cuda_available,
        tf32=cuda_available,
        gradient_checkpointing=True,
        optim="adamw_torch_fused" if cuda_available else "adamw_torch",
        seed=args.seed,
        data_seed=args.seed,
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["validation"],
        processing_class=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=2)],
    )

    trainer.train()
    trainer.remove_callback(EarlyStoppingCallback)
    metrics = {
        "rw_test": trainer.evaluate(tokenized["test"], metric_key_prefix="rw_test"),
        "mt_test": trainer.evaluate(
            tokenized_mt_test,
            metric_key_prefix="mt_test",
        ),
    }
    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))

    metrics_path = args.output_dir / "evaluation_metrics.json"
    metrics_path.write_text(
        json.dumps(metrics, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Saved target sentiment model to {args.output_dir}")
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
