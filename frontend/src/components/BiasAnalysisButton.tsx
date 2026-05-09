"use client";

import { useState } from "react";
import { triggerBiasAnalysis } from "@/lib/api";

export default function BiasAnalysisButton() {
  const [isRunning, setIsRunning] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

  const handleRun = async () => {
    setIsRunning(true);
    setMessage(null);
    try {
      const result = await triggerBiasAnalysis();
      setMessage({
        text: `${result.message} Topics: ${result.topics_processed}. Articles scored: ${result.processed_articles}.`,
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
      <button
        onClick={handleRun}
        disabled={isRunning}
        className="inline-flex items-center gap-2 rounded-full bg-amber-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {isRunning ? "Running Bias Analysis..." : "Run Bias Analysis"}
      </button>
      {message && (
        <p className={`text-xs ${message.type === "success" ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
          {message.text}
        </p>
      )}
    </div>
  );
}
