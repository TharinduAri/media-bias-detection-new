"use client";

import { useEffect, useState } from "react";
import { triggerBiasAnalysis } from "@/lib/api";

type EmbeddingProvider = "local" | "gemini";
type LocalEmbeddingKey = "minilm_l6" | "minilm_l12" | "mpnet_v2" | "multilingual_minilm";

export default function BiasAnalysisButton() {
  const [isRunning, setIsRunning] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);
  const [provider, setProvider] = useState<EmbeddingProvider>("local");
  const [localModel, setLocalModel] = useState<LocalEmbeddingKey>("minilm_l6");

  useEffect(() => {
    const storedProvider = window.localStorage.getItem("bias_embedding_provider");
    if (storedProvider === "local" || storedProvider === "gemini") {
      setProvider(storedProvider);
    }
    const storedModel = window.localStorage.getItem("bias_local_embedding_model");
    if (
      storedModel === "minilm_l6" ||
      storedModel === "minilm_l12" ||
      storedModel === "mpnet_v2" ||
      storedModel === "multilingual_minilm"
    ) {
      setLocalModel(storedModel);
    }
  }, []);

  const handleRun = async () => {
    setIsRunning(true);
    setMessage(null);
    try {
      const result = await triggerBiasAnalysis(provider, localModel);
      setMessage({
        text: `${result.message} Provider: ${result.embedding_provider}. Model: ${result.embedding_model}. Embeddings saved: ${result.embeddings_saved}. Topics: ${result.topics_processed}. Articles scored: ${result.processed_articles}.`,
        type: "success",
      });
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : "Failed to run bias analysis.",
        type: "error",
      });
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex items-center gap-2">
        <label htmlFor="embedding-provider" className="text-xs text-gray-500 dark:text-gray-400">
          Embeddings
        </label>
        <select
          id="embedding-provider"
          value={provider}
          onChange={(event) => {
            const next = event.target.value as EmbeddingProvider;
            setProvider(next);
            window.localStorage.setItem("bias_embedding_provider", next);
          }}
          disabled={isRunning}
          className="rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 text-xs text-slate-700 dark:text-slate-200"
        >
          <option value="local">Local</option>
          <option value="gemini">Gemini</option>
        </select>
        {provider === "local" && (
          <select
            value={localModel}
            onChange={(event) => {
              const next = event.target.value as LocalEmbeddingKey;
              setLocalModel(next);
              window.localStorage.setItem("bias_local_embedding_model", next);
            }}
            disabled={isRunning}
            className="rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1 text-xs text-slate-700 dark:text-slate-200"
          >
            <option value="minilm_l6">all-MiniLM-L6-v2 (fast baseline)</option>
            <option value="minilm_l12">all-MiniLM-L12-v2 (stronger MiniLM)</option>
            <option value="mpnet_v2">all-mpnet-base-v2 (best quality local)</option>
            <option value="multilingual_minilm">paraphrase-multilingual-MiniLM-L12-v2</option>
          </select>
        )}
      </div>
      <button
        onClick={handleRun}
        disabled={isRunning}
        className="inline-flex items-center gap-2 rounded-full bg-amber-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {isRunning ? "Running Bias Analysis..." : "Run Bias Analysis"}
      </button>
      {message && (
        <p
          className={`text-xs ${message.type === "success" ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}
        >
          {message.text}
        </p>
      )}
    </div>
  );
}
