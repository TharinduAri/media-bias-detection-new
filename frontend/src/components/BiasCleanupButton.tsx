"use client";

import { useState } from "react";
import { triggerBiasCleanup } from "@/lib/api";

export default function BiasCleanupButton() {
  const [isRunning, setIsRunning] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

  const handleCleanup = async () => {
    const confirmed = window.confirm("Clear all bias analysis data? This cannot be undone.");
    if (!confirmed) return;

    setIsRunning(true);
    setMessage(null);
    try {
      const result = await triggerBiasCleanup();
      setMessage({ text: result.message, type: "success" });
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : "Failed to clear bias analysis data.",
        type: "error",
      });
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="flex flex-col items-end gap-2">
      <button
        onClick={handleCleanup}
        disabled={isRunning}
        className="inline-flex items-center gap-2 rounded-full border border-red-200 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 shadow-sm transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-70"
      >
        {isRunning ? "Clearing..." : "Clear Bias Data"}
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
