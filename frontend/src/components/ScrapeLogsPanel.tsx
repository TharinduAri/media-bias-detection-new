"use client";

import { useState } from "react";
import { fetchScrapeLogs, ScrapeRunLogData } from "@/lib/api";

interface Props {
  initialLogs: ScrapeRunLogData[];
}

export default function ScrapeLogsPanel({ initialLogs }: Props) {
  const [logs, setLogs] = useState<ScrapeRunLogData[]>(initialLogs);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshLogs = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchScrapeLogs(10);
      setLogs(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh logs.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-4 shadow-sm transition-colors duration-200">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Scrape Run Logs</h2>
          <p className="text-sm text-gray-600 dark:text-gray-400">Saved console output from recent scraper runs.</p>
        </div>
        <button
          onClick={refreshLogs}
          disabled={loading}
          className="px-3 py-1.5 bg-gray-900 text-white text-xs font-medium rounded-md hover:bg-black disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400 mb-2">{error}</p>}

      {logs.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">No scrape runs logged yet.</p>
      ) : (
        <div className="space-y-3">
          {logs.map((run) => {
            const startedAt = new Date(run.started_at).toLocaleString();
            const finishedAt = new Date(run.finished_at).toLocaleString();
            const statusClass =
              run.status === "done"
                ? "text-green-600 dark:text-green-400"
                : run.status === "error"
                  ? "text-red-600 dark:text-red-400"
                  : "text-gray-600 dark:text-gray-300";

            return (
              <details key={run.id} className="border border-gray-200 dark:border-gray-700 rounded-md">
                <summary className="cursor-pointer list-none p-3 flex items-center justify-between gap-4">
                  <div>
                    <p className="text-sm text-gray-800 dark:text-gray-100 font-medium">Run #{run.id}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">{startedAt} {"->"} {finishedAt}</p>
                  </div>
                  <span className={`text-xs font-semibold uppercase ${statusClass}`}>{run.status}</span>
                </summary>
                <div className="px-3 pb-3">
                  {run.error && (
                    <p className="text-xs text-red-600 dark:text-red-400 mb-2">{run.error}</p>
                  )}
                  <pre className="bg-gray-950 text-gray-200 text-xs rounded-md p-3 overflow-auto max-h-64 whitespace-pre-wrap border border-gray-800">
                    {run.log_lines.join("\n")}
                  </pre>
                </div>
              </details>
            );
          })}
        </div>
      )}
    </section>
  );
}
