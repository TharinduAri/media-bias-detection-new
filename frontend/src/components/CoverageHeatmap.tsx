"use client";

import React, { useEffect, useMemo, useState } from "react";
import { AnalysisType, fetchBiasScores, OutletTopicBSIData } from "@/lib/api";

const CELL = 22;
const GAP = 3;
const LABEL_W = 200;
const HEADER_H = 96;
const DEFAULT_LIMIT = 40;

interface TopicRow {
  topicKey: string;
  topicLabel: string;
  coverage: Map<string, boolean>;
  coveredCount: number;
}

type SortMode = "most-covered" | "most-missing";

export default function CoverageHeatmap({ analysisType = "general" }: { analysisType?: AnalysisType }) {
  const [scores, setScores] = useState<OutletTopicBSIData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<SortMode>("most-missing");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    fetchBiasScores({ analysis_type: analysisType })
      .then((d) => setScores(d.scores))
      .catch(() => setError("Failed to load coverage data."))
      .finally(() => setLoading(false));
  }, [analysisType]);

  const { outlets, rows } = useMemo(() => {
    if (!scores.length) return { outlets: [], rows: [] as TopicRow[] };

    const outletSet = new Set<string>();
    const topicMap = new Map<string, { label: string; coverage: Map<string, boolean> }>();

    for (const s of scores) {
      outletSet.add(s.outlet);
      if (!topicMap.has(s.topic_key)) {
        topicMap.set(s.topic_key, {
          label: s.topic_label || s.topic_key,
          coverage: new Map(),
        });
      }
      topicMap.get(s.topic_key)!.coverage.set(s.outlet, s.coverage_present);
    }

    const outlets = [...outletSet].sort();

    const rows: TopicRow[] = [...topicMap.entries()].map(([topicKey, { label, coverage }]) => ({
      topicKey,
      topicLabel: label,
      coverage,
      coveredCount: [...coverage.values()].filter(Boolean).length,
    }));

    rows.sort((a, b) =>
      sortMode === "most-covered"
        ? b.coveredCount - a.coveredCount
        : a.coveredCount - b.coveredCount
    );

    return { outlets, rows };
  }, [scores, sortMode]);

  const visibleRows = showAll ? rows : rows.slice(0, DEFAULT_LIMIT);

  const fullCoverage = rows.filter((r) => r.coveredCount === outlets.length).length;
  const partial = rows.filter(
    (r) => r.coveredCount > 0 && r.coveredCount < outlets.length
  ).length;
  const totalMissed = rows.reduce((acc, r) => acc + (outlets.length - r.coveredCount), 0);

  if (loading)
    return (
      <Shell>
        <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-12">
          Loading heatmap…
        </p>
      </Shell>
    );

  if (error)
    return (
      <Shell>
        <p className="text-sm text-rose-500 text-center py-12">{error}</p>
      </Shell>
    );

  if (!rows.length)
    return (
      <Shell>
        <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-12">
          No data yet. Run bias analysis first.
        </p>
      </Shell>
    );

  const gridCols = `${LABEL_W}px repeat(${outlets.length}, ${CELL}px) auto`;

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-5 border-b border-gray-100 dark:border-gray-800 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Topic Coverage Heatmap
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Each row is a news topic scored across all outlets.{" "}
            <span className="font-medium text-emerald-600 dark:text-emerald-400">Green</span> = covered,{" "}
            <span className="font-medium text-rose-500 dark:text-rose-400">Red</span> = not covered.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-gray-400 dark:text-gray-500">Sort:</span>
          {(
            [
              { mode: "most-missing" as SortMode, label: "Most missing ↑" },
              { mode: "most-covered" as SortMode, label: "Most covered ↑" },
            ]
          ).map(({ mode, label }) => (
            <button
              key={mode}
              onClick={() => setSortMode(mode)}
              className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
                sortMode === mode
                  ? mode === "most-missing"
                    ? "bg-rose-50 dark:bg-rose-900/30 border-rose-200 dark:border-rose-700 text-rose-700 dark:text-rose-300"
                    : "bg-emerald-50 dark:bg-emerald-900/30 border-emerald-200 dark:border-emerald-700 text-emerald-700 dark:text-emerald-300"
                  : "border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Grid */}
      <div className="px-6 pt-5 pb-2 overflow-x-auto">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: gridCols,
            columnGap: GAP,
            rowGap: GAP,
            alignItems: "center",
          }}
        >
          {/* ── Header row ── */}
          <div /> {/* label column corner */}
          {outlets.map((outlet) => (
            <div
              key={outlet}
              title={outlet}
              style={{
                writingMode: "vertical-lr",
                height: HEADER_H,
                width: CELL,
                overflow: "hidden",
              }}
              className="text-xs text-gray-500 dark:text-gray-400 font-medium flex items-end pb-1"
            >
              {outlet}
            </div>
          ))}
          <div /> {/* count corner */}

          {/* ── Data rows ── */}
          {visibleRows.map((row) => (
            <React.Fragment key={row.topicKey}>
              {/* Topic label */}
              <div
                title={row.topicLabel}
                className="text-xs text-gray-600 dark:text-gray-300 truncate text-right pr-2"
              >
                {row.topicLabel}
              </div>

              {/* Coverage cells */}
              {outlets.map((outlet) => {
                const covered = row.coverage.get(outlet) ?? false;
                return (
                  <div
                    key={outlet}
                    title={`${outlet} — ${row.topicLabel}: ${covered ? "✓ covered" : "✗ not covered"}`}
                    className={`rounded-sm cursor-default transition-opacity hover:opacity-70 ${
                      covered
                        ? "bg-emerald-500 dark:bg-emerald-500"
                        : "bg-rose-300 dark:bg-rose-800/80"
                    }`}
                    style={{ width: CELL, height: CELL }}
                  />
                );
              })}

              {/* Coverage ratio */}
              <div
                className="text-xs font-mono tabular-nums pl-1"
                style={{
                  color:
                    row.coveredCount === outlets.length
                      ? "#10b981"
                      : row.coveredCount === 0
                      ? "#f43f5e"
                      : "#f59e0b",
                }}
              >
                {row.coveredCount}/{outlets.length}
              </div>
            </React.Fragment>
          ))}
        </div>

        {/* Show all / show fewer */}
        {rows.length > DEFAULT_LIMIT && (
          <div className="mt-4 text-center">
            <button
              onClick={() => setShowAll((v) => !v)}
              className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              {showAll
                ? "Show fewer topics"
                : `Show all ${rows.length} topics (${rows.length - DEFAULT_LIMIT} more)`}
            </button>
          </div>
        )}
      </div>

      {/* Summary stats footer */}
      <div className="px-6 py-4 border-t border-gray-100 dark:border-gray-800 flex flex-wrap items-center gap-6">
        <Stat label="Topics scored" value={rows.length} />
        <Stat label="Outlets" value={outlets.length} />
        <Stat label="Full coverage" value={fullCoverage} color="emerald" />
        <Stat label="Partially missed" value={partial} color="amber" />
        <Stat label="Total gaps" value={totalMissed} color="rose" />
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  color = "default",
}: {
  label: string;
  value: number;
  color?: "default" | "emerald" | "amber" | "rose";
}) {
  const colors = {
    default: "text-gray-900 dark:text-white",
    emerald: "text-emerald-700 dark:text-emerald-400",
    amber: "text-amber-700 dark:text-amber-400",
    rose: "text-rose-700 dark:text-rose-400",
  };
  return (
    <div className="flex flex-col">
      <span className={`text-sm font-semibold ${colors[color]}`}>{value}</span>
      <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800">
      {children}
    </div>
  );
}
