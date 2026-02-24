#!/usr/bin/env python3
"""
run_pipeline.py

Runs the full data pipeline sequentially:
  1. src/collection/scraper.py
  2. src/processing/preprocessor.py
  3. src/extraction/bias_extractor.py
  4. src/aggregation/aggregator.py
  5. src/explainability/explainer.py

Usage:
  python run_pipeline.py         # execute all stages (stop on first failure)
  python run_pipeline.py --dry-run    # only print commands
  python run_pipeline.py --continue-on-error  # continue even if a stage fails
"""
import argparse
import logging
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

STAGES = [
    ("scraper", "src/collection/scraper.py"),
    ("preprocessor", "src/processing/preprocessor.py"),
    ("bias_extractor", "src/extraction/bias_extractor.py"),
    ("aggregator", "src/aggregation/aggregator.py"),
    ("explainer", "src/explainability/explainer.py"),
]


def run_stage(script_path, python_exec=sys.executable):
    cmd = [python_exec, script_path]
    logging.info("Running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    logging.info("Stage exit code: %s", proc.returncode)
    if out:
        logging.info("Stdout (truncated to 2000 chars):\n%s", out[:2000])
    if err:
        logging.warning("Stderr (truncated to 2000 chars):\n%s", err[:2000])
    return proc.returncode


def main():
    parser = argparse.ArgumentParser(description="Run the full media-bias pipeline.")
    parser.add_argument("--dry-run", action="store_true", help="Print the commands without executing them")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue to next stage even if a stage fails")
    parser.add_argument("--stages", type=str, default="all", help="Comma-separated list of stage keys to run (e.g. 'scraper,aggregator') or 'all'")
    args = parser.parse_args()

    selected = [s for s, _ in STAGES]
    if args.stages != "all":
        wanted = [p.strip() for p in args.stages.split(",") if p.strip()]
        selected = [s for s, _ in STAGES if s in wanted]
        if not selected:
            logging.error("No matching stages found for '%s'", args.stages)
            sys.exit(2)

    # Build the ordered list of (name, path) to run
    to_run = [(name, path) for name, path in STAGES if name in selected]

    logging.info("Pipeline run start. Stages: %s", ", ".join([n for n, _ in to_run]))
    start_time = time.time()

    for name, path in to_run:
        if args.dry_run:
            print(f"DRY-RUN: python {path}")
            continue

        rc = run_stage(path)
        if rc != 0:
            logging.error("Stage '%s' failed (exit %s).", name, rc)
            if not args.continue_on_error:
                logging.info("Aborting pipeline due to failure. You can re-run with --continue-on-error to proceed anyway.")
                sys.exit(rc)
            else:
                logging.info("Continuing to next stage due to --continue-on-error flag.")

    elapsed = time.time() - start_time
    logging.info("Pipeline finished in %.1f seconds.", elapsed)


if __name__ == "__main__":
    main()
