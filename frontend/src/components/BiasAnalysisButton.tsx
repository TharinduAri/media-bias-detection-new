"use client";

import { useEffect, useRef, useState } from "react";
import { fetchBiasRunStatus, triggerBiasAnalysis } from "@/lib/api";

type RunStatus = "idle" | "running" | "done" | "error";

export default function BiasAnalysisButton() {
  const [isRunning, setIsRunning] = useState(false);
  const [status, setStatus] = useState<RunStatus>("idle");
  const [logs, setLogs] = useState<string[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Auto-scroll log window to bottom when new lines arrive
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = () => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const state = await fetchBiasRunStatus();
        setLogs(state.logs);
        setStatus(state.status);
        if (!state.running) {
          stopPolling();
          setIsRunning(false);
        }
      } catch {
        // ignore poll failures
      }
    }, 1000);
  };

  useEffect(() => () => stopPolling(), []);

  const handleRun = async () => {
    setIsRunning(true);
    setStatus("running");
    setLogs([]);
    setShowLogs(true);

    // Fire-and-forget — let polling track progress and detect completion
    triggerBiasAnalysis().catch((error) => {
      setStatus("error");
      setLogs((prev) => [
        ...prev,
        `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
      ]);
      stopPolling();
      setIsRunning(false);
    });

    startPolling();
  };

  const statusColor: Record<RunStatus, string> = {
    idle: "text-gray-400",
    running: "text-amber-400",
    done: "text-emerald-400",
    error: "text-red-400",
  };

  const statusLabel: Record<RunStatus, string> = {
    idle: "",
    running: "Running…",
    done: "Done",
    error: "Error",
  };

  return (
    <div className="flex flex-col items-end gap-2 w-full">
      <div className="flex items-center gap-2">
        {showLogs && (
          <button
            onClick={() => setShowLogs((v) => !v)}
            className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 underline"
          >
            {showLogs ? "Hide logs" : "Show logs"}
          </button>
        )}
        <button
          onClick={handleRun}
          disabled={isRunning}
          className="inline-flex items-center gap-2 rounded-full bg-amber-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isRunning ? "Running Bias Analysis…" : "Run Bias Analysis"}
        </button>
      </div>

      {showLogs && (
        <div className="w-full max-w-2xl rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-950 overflow-hidden text-left">
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
            <div className="flex items-center gap-2">
              {isRunning && (
                <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
              )}
              <span className={`text-xs font-medium ${statusColor[status]}`}>
                {statusLabel[status] || "Bias Analysis Log"}
              </span>
            </div>
            <button
              onClick={() => setShowLogs(false)}
              className="text-gray-600 hover:text-gray-300 text-xs"
            >
              ✕
            </button>
          </div>
          <div
            ref={logRef}
            className="h-56 overflow-y-auto px-3 py-2 font-mono text-xs leading-relaxed text-gray-300 space-y-0.5"
          >
            {logs.length === 0 ? (
              <span className="text-gray-600">Waiting for output…</span>
            ) : (
              logs.map((line, i) => (
                <div
                  key={i}
                  className={
                    line.startsWith("Error")
                      ? "text-red-400"
                      : line === "Done."
                      ? "text-emerald-400"
                      : "text-gray-300"
                  }
                >
                  <span className="text-gray-600 select-none mr-2">{String(i + 1).padStart(2, "0")}</span>
                  {line}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
