"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  OUTLET_NAMES,
  fetchPipelineStatus,
  triggerScrape,
  PipelineStatus,
} from "@/lib/api";

const POLL_MS = 1500;

// ── Progress modal (reused pattern from CleanScrapeButton) ──────────────────
function ProgressModal({
  status,
  onClose,
}: {
  status: PipelineStatus;
  onClose: () => void;
}) {
  const logRef = useRef<HTMLDivElement>(null);
  const isDone = status.status === "done";
  const isError = status.status === "error";
  const isRunning = status.status === "running";

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [status.logs]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
      <div className="relative w-full max-w-2xl bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* Header */}
        <div
          className={`px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between ${
            isDone
              ? "bg-green-50 dark:bg-green-900/20"
              : isError
              ? "bg-red-50 dark:bg-red-900/20"
              : "bg-gray-50 dark:bg-gray-800"
          }`}
        >
          <div className="flex items-center gap-3">
            {isRunning && (
              <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin shrink-0" />
            )}
            {isDone && <span className="text-xl">✅</span>}
            {isError && <span className="text-xl">❌</span>}
            <div>
              <h2 className="font-bold text-gray-900 dark:text-white text-base">
                {isDone ? "Scrape Complete" : isError ? "Scrape Error" : "Scraping…"}
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {isError ? (status.error ?? "An error occurred.") : isRunning ? "Fetching articles…" : "Done."}
              </p>
            </div>
          </div>
          {(isDone || isError) && (
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-700 dark:hover:text-white transition-colors text-xl ml-4"
            >
              ✕
            </button>
          )}
        </div>

        {/* Live log */}
        <div className="px-6 py-5">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">
            Live Output
          </p>
          <div
            ref={logRef}
            className="h-52 overflow-y-auto rounded-lg bg-gray-950 dark:bg-black border border-gray-800 p-3 font-mono text-xs text-gray-300 space-y-0.5"
          >
            {status.logs.length === 0 ? (
              <span className="text-gray-600">Waiting for output…</span>
            ) : (
              status.logs.map((line, i) => (
                <div
                  key={i}
                  className={`whitespace-pre-wrap leading-relaxed ${
                    line.toLowerCase().includes("error") || line.toLowerCase().includes("failed")
                      ? "text-red-400"
                      : line.toLowerCase().includes("complete") || line.toLowerCase().includes("success")
                      ? "text-green-400"
                      : "text-gray-400"
                  }`}
                >
                  {line}
                </div>
              ))
            )}
            {isRunning && (
              <div className="flex items-center gap-1.5 text-gray-600 mt-1">
                <div className="flex gap-0.5">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="w-1 h-1 rounded-full bg-gray-500 animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </div>
                <span>Processing…</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────
export default function ScrapeOutletsPanel() {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const s = await fetchPipelineStatus();
        setPipelineStatus(s);
        if (s.status === "done" || s.status === "error") stopPolling();
      } catch {
        /* ignore */
      }
    }, POLL_MS);
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const toggleOutlet = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(OUTLET_NAMES));
  const clearAll = () => setSelected(new Set());

  const handleScrape = async () => {
    setError(null);
    setIsScraping(true);
    try {
      const outlets = selected.size > 0 ? [...selected] : undefined;
      await triggerScrape(outlets);
      const initial = await fetchPipelineStatus().catch(() => null);
      setPipelineStatus(initial);
      setShowModal(true);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start scraper.");
    } finally {
      setIsScraping(false);
    }
  };

  const allSelected = selected.size === OUTLET_NAMES.length;
  const noneSelected = selected.size === 0;

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
        <div>
          <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">
            Scrape Outlets
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Select one or more outlets to scrape. Existing articles are not deleted.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={allSelected ? clearAll : selectAll}
            className="px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          >
            {allSelected ? "Deselect All" : "Select All"}
          </button>
        </div>
      </div>

      {/* Outlet grid */}
      <div className="p-5 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
        {OUTLET_NAMES.map((name) => {
          const isChecked = selected.has(name);
          return (
            <button
              key={name}
              onClick={() => toggleOutlet(name)}
              className={`flex items-center gap-2 px-3 py-2.5 rounded-xl border text-left text-sm font-medium transition-all duration-150 ${
                isChecked
                  ? "bg-indigo-50 dark:bg-indigo-900/30 border-indigo-300 dark:border-indigo-700 text-indigo-800 dark:text-indigo-200"
                  : "bg-slate-50 dark:bg-slate-800/60 border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-600"
              }`}
            >
              <div
                className={`w-4 h-4 rounded shrink-0 flex items-center justify-center border transition-colors ${
                  isChecked
                    ? "bg-indigo-600 border-indigo-600"
                    : "border-slate-300 dark:border-slate-600"
                }`}
              >
                {isChecked && (
                  <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 10 8">
                    <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </div>
              <span className="truncate">{name}</span>
            </button>
          );
        })}
      </div>

      {/* Footer */}
      <div className="px-5 pb-5 flex items-center justify-between gap-4">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {noneSelected
            ? "No outlets selected — will scrape all 13"
            : `${selected.size} outlet${selected.size === 1 ? "" : "s"} selected`}
        </p>
        <div className="flex items-center gap-3">
          {error && <span className="text-xs text-red-600 dark:text-red-400">{error}</span>}
          {!noneSelected && (
            <button
              onClick={clearAll}
              className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
            >
              Clear
            </button>
          )}
          <button
            onClick={handleScrape}
            disabled={isScraping}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-lg shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isScraping
              ? "Starting…"
              : noneSelected
              ? "Scrape All"
              : `Scrape ${selected.size === 1 ? selected.values().next().value : `${selected.size} Outlets`}`}
          </button>
        </div>
      </div>

      {showModal && pipelineStatus && (
        <ProgressModal
          status={pipelineStatus}
          onClose={() => {
            stopPolling();
            setShowModal(false);
          }}
        />
      )}
    </div>
  );
}
