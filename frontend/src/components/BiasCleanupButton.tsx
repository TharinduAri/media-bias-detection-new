"use client";

import { useState } from "react";
import { triggerBiasCleanup, triggerCleanupKeepEmbeddings } from "@/lib/api";

export default function BiasCleanupButton() {
  const [isRunning, setIsRunning] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

  const handleCleanup = async (keepEmbeddings: boolean) => {
    const msg = keepEmbeddings
      ? "Clear all bias results? Embeddings will be preserved."
      : "Clear ALL bias data including embeddings? This cannot be undone.";
    if (!window.confirm(msg)) return;

    setIsRunning(true);
    setMessage(null);
    try {
      const result = keepEmbeddings
        ? await triggerCleanupKeepEmbeddings()
        : await triggerBiasCleanup();
      setMessage({ text: result.message, type: "success" });
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : "Failed to clear data.",
        type: "error",
      });
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex items-center gap-2">
        <button
          onClick={() => handleCleanup(true)}
          disabled={isRunning}
          className="inline-flex items-center gap-2 rounded-full border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-2 text-sm font-semibold text-gray-600 dark:text-gray-400 shadow-sm transition hover:bg-gray-50 dark:hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isRunning ? "Clearing…" : "Clear Results"}
        </button>
        <button
          onClick={() => handleCleanup(false)}
          disabled={isRunning}
          className="inline-flex items-center gap-2 rounded-full border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 shadow-sm transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isRunning ? "Clearing…" : "Clear All"}
        </button>
      </div>
      {message && (
        <p className={`text-xs ${message.type === "success" ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
          {message.text}
        </p>
      )}
    </div>
  );
}
