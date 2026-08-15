"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AnalysisType,
  ClusteringProvider,
  ExternalClusterMappingStats,
  fetchBiasRunStatus,
  fetchClusteringProvidersStatus,
  fetchEmbeddingStatus,
  triggerBiasAnalysisSelected,
} from "@/lib/api";

type RunStatus = "idle" | "running" | "done" | "error";

export default function BiasAnalysisButton() {
  const router = useRouter();
  const [isRunning, setIsRunning] = useState(false);
  const [status, setStatus] = useState<RunStatus>("idle");
  const [logs, setLogs] = useState<string[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const [embeddingCount, setEmbeddingCount] = useState<number | null>(null);
  const [lastComputed, setLastComputed] = useState<string | null>(null);
  const [clusterProvider, setClusterProvider] = useState<ClusteringProvider>("internal");
  const [externalAvailable, setExternalAvailable] = useState<boolean | null>(null);
  const [externalError, setExternalError] = useState<string | null>(null);
  const [mappingStats, setMappingStats] = useState<ExternalClusterMappingStats | null>(null);
  const [lastCompletedProvider, setLastCompletedProvider] = useState<ClusteringProvider | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetchEmbeddingStatus()
      .then((d) => {
        setEmbeddingCount(d.count);
        setLastComputed(d.last_computed_at);
      })
      .catch(() => {});
    fetchClusteringProvidersStatus()
      .then((providers) => {
        setExternalAvailable(providers.external.available);
        setExternalError(providers.external.error);
      })
      .catch((error) => {
        setExternalAvailable(false);
        setExternalError(error instanceof Error ? error.message : "External API unavailable");
      });
    fetchBiasRunStatus()
      .then((state) => {
        if (state.status === "done" && state.cluster_provider) {
          setLastCompletedProvider(state.cluster_provider);
          setMappingStats(state.mapping_stats ?? null);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  const startPolling = () => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const state = await fetchBiasRunStatus();
        setLogs(state.logs);
        setStatus(state.status);
        setMappingStats(state.mapping_stats ?? null);
        if (!state.running) {
          stopPolling();
          setIsRunning(false);
          // Refresh embedding count after a full run
          fetchEmbeddingStatus().then((d) => {
            setEmbeddingCount(d.count);
            setLastComputed(d.last_computed_at);
          }).catch(() => {});
          if (state.status === "done") {
            setLastCompletedProvider(state.cluster_provider ?? clusterProvider);
            router.refresh();
          }
        }
      } catch { /* ignore */ }
    }, 1000);
  };

  useEffect(() => () => stopPolling(), []);

  const handleRun = (fast: boolean, analysisType: AnalysisType) => {
    setIsRunning(true);
    setStatus("running");
    setLogs([]);
    setShowLogs(true);
    setMappingStats(null);

    triggerBiasAnalysisSelected({
      analysis_type: analysisType,
      embedding_mode: fast ? "reuse" : "full",
      clustering_provider: clusterProvider,
    })
      .then((result) => {
        setMappingStats(result.mapping_stats ?? null);
        setLastCompletedProvider(result.cluster_provider);
      })
      .catch((error) => {
        setStatus("error");
        setLogs((prev) => [...prev, `Error: ${error instanceof Error ? error.message : "Unknown error"}`]);
        stopPolling();
        setIsRunning(false);
      });

    startPolling();
  };

  const toggleClusterProvider = () => {
    const nextProvider: ClusteringProvider = clusterProvider === "internal" ? "external" : "internal";
    setClusterProvider(nextProvider);
  };

  const statusColor: Record<RunStatus, string> = {
    idle: "text-gray-400", running: "text-amber-400", done: "text-emerald-400", error: "text-red-400",
  };
  const statusLabel: Record<RunStatus, string> = {
    idle: "", running: "Running…", done: "Done", error: "Error",
  };

  const hasEmbeddings = embeddingCount !== null && embeddingCount > 0;

  return (
    <div className="flex flex-col items-end gap-2 w-full">
      {/* Embedding status indicator */}
      {hasEmbeddings && (
        <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" />
          <span>
            {embeddingCount} embeddings saved
            {lastComputed && (
              <span className="text-gray-400 dark:text-gray-500 ml-1">
                · {new Date(lastComputed).toLocaleDateString()}
              </span>
            )}
          </span>
        </div>
      )}

      <div className="flex items-center gap-2 text-xs">
        <span className="text-gray-500 dark:text-gray-400">Next run</span>
        <button
          type="button"
          onClick={toggleClusterProvider}
          disabled={isRunning}
          title="Switch between the built-in clustering implementation and the external API"
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
            clusterProvider === "external"
              ? "border-violet-500 bg-violet-600 text-white"
              : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-200"
          }`}
        >
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              clusterProvider === "external"
                ? externalAvailable === false
                  ? "bg-red-300"
                  : "bg-emerald-300"
                : "bg-indigo-500"
            }`}
          />
          {clusterProvider === "external" ? "External API" : "Internal"}
        </button>
        {clusterProvider === "external" && externalAvailable === false && (
          <span className="text-red-500" title={externalError ?? undefined}>Unavailable</span>
        )}
        {lastCompletedProvider && (
          <span className="text-gray-400 dark:text-gray-500">
            Current results: {lastCompletedProvider === "external" ? "External API" : "Internal"}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2">
        {showLogs && (
          <button
            onClick={() => setShowLogs((v) => !v)}
            className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 underline"
          >
            Hide logs
          </button>
        )}

        {/* Fast run button — only shown when embeddings exist */}
        {hasEmbeddings && (
          <button
            onClick={() => handleRun(true, "general")}
            disabled={isRunning}
            title="Skip embedding step — use saved embeddings"
            className="inline-flex items-center gap-2 rounded-full bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isRunning ? "Running…" : "Run Fast"}
          </button>
        )}

        <button
          onClick={() => handleRun(false, "general")}
          disabled={isRunning}
          className="inline-flex items-center gap-2 rounded-full bg-amber-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isRunning ? "Running Bias Analysis…" : "Run Bias Analysis"}
        </button>
        {hasEmbeddings && (
          <button
            onClick={() => handleRun(true, "financial")}
            disabled={isRunning}
            title="Skip embedding step and score Economy Next/LBO with FinBERT"
            className="inline-flex items-center gap-2 rounded-full bg-teal-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isRunning ? "Running..." : "Run Financial Fast"}
          </button>
        )}

        <button
          onClick={() => handleRun(false, "financial")}
          disabled={isRunning}
          title="Analyze Economy Next and LBO with ProsusAI/finbert"
          className="inline-flex items-center gap-2 rounded-full bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-70"
        >
          {isRunning ? "Running Financial Analysis..." : "Run Financial Analysis"}
        </button>
      </div>

      {mappingStats && clusterProvider === "external" && (
        <div className="w-full max-w-2xl rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-xs text-violet-800 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-300">
          Matched {mappingStats.matched_local_articles} of {mappingStats.local_articles} local articles; {" "}
          {mappingStats.matched_clustered_local_articles} are clustered across {mappingStats.mapped_clusters_with_two_articles} usable groups.
          {mappingStats.external_fetch_truncated && " External results were truncated by the configured page limit."}
        </div>
      )}

      {showLogs && (
        <div className="w-full max-w-2xl rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-950 overflow-hidden text-left">
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
            <div className="flex items-center gap-2">
              {isRunning && <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />}
              <span className={`text-xs font-medium ${statusColor[status]}`}>
                {statusLabel[status] || "Bias Analysis Log"}
              </span>
            </div>
            <button onClick={() => setShowLogs(false)} className="text-gray-600 hover:text-gray-300 text-xs">✕</button>
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
                  className={line.startsWith("Error") ? "text-red-400" : line === "Done." ? "text-emerald-400" : "text-gray-300"}
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
