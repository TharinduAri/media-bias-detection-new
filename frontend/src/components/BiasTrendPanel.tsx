"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Minus, AlertTriangle } from "lucide-react";
import { fetchOutletTrend, OutletBiasSnapshotData } from "@/lib/api";

interface Props {
  outlets: string[];
}

type DaysOption = 30 | 90 | 180;

function bsiColor(bsi: number | null | undefined): string {
  if (bsi == null) return "text-slate-400";
  if (bsi >= 0.6) return "text-rose-600 dark:text-rose-400";
  if (bsi >= 0.3) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function bsiBarColor(bsi: number | null | undefined): string {
  if (bsi == null) return "bg-slate-300";
  if (bsi >= 0.6) return "bg-rose-400";
  if (bsi >= 0.3) return "bg-amber-400";
  return "bg-emerald-400";
}

function DeltaPill({ value, label }: { value: number | null; label: string }) {
  if (value == null) return null;
  const pct = (value * 100).toFixed(1);
  const positive = value > 0.005;
  const negative = value < -0.005;
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="text-[10px] text-slate-400 uppercase tracking-wider">{label}</span>
      <span
        className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
          positive
            ? "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300"
            : negative
            ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
            : "bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400"
        }`}
      >
        {positive ? "+" : ""}
        {pct}%
      </span>
    </div>
  );
}

function Sparkline({ snapshots }: { snapshots: OutletBiasSnapshotData[] }) {
  const values = snapshots
    .map((s) => s.bsi_score)
    .filter((v): v is number => v != null);

  if (values.length < 2) {
    return (
      <div className="flex items-center justify-center h-16 text-xs text-slate-400">
        Not enough data for trend
      </div>
    );
  }

  const W = 300;
  const H = 60;
  const pad = 5;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 0.001;

  const toX = (i: number) => pad + (i / (values.length - 1)) * (W - 2 * pad);
  const toY = (v: number) => H - pad - ((v - min) / range) * (H - 2 * pad);

  const points = values.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(" ");
  const lastBsi = values[values.length - 1];

  return (
    <div className="w-full">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-16" preserveAspectRatio="none">
        <polyline
          points={points}
          fill="none"
          stroke={lastBsi >= 0.6 ? "#f87171" : lastBsi >= 0.3 ? "#fbbf24" : "#34d399"}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {values.map((v, i) => (
          <circle
            key={i}
            cx={toX(i)}
            cy={toY(v)}
            r="3"
            fill={v >= 0.6 ? "#f87171" : v >= 0.3 ? "#fbbf24" : "#34d399"}
          />
        ))}
      </svg>
      <div className="flex justify-between text-[10px] text-slate-400 mt-1">
        <span>{snapshots[0] ? new Date(snapshots[0].snapshot_date).toLocaleDateString() : ""}</span>
        <span>
          {snapshots[snapshots.length - 1]
            ? new Date(snapshots[snapshots.length - 1].snapshot_date).toLocaleDateString()
            : ""}
        </span>
      </div>
    </div>
  );
}

export default function BiasTrendPanel({ outlets }: Props) {
  const [selectedOutlet, setSelectedOutlet] = useState<string>(outlets[0] ?? "");
  const [daysBack, setDaysBack] = useState<DaysOption>(90);
  const [snapshots, setSnapshots] = useState<OutletBiasSnapshotData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedOutlet) return;
    setLoading(true);
    setError(null);
    fetchOutletTrend(selectedOutlet, daysBack)
      .then(setSnapshots)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selectedOutlet, daysBack]);

  const first = snapshots[0];
  const last = snapshots[snapshots.length - 1];

  const bsiDelta =
    first?.bsi_score != null && last?.bsi_score != null
      ? last.bsi_score - first.bsi_score
      : null;
  const covDelta =
    first != null && last != null ? last.coverage_bias_rate - first.coverage_bias_rate : null;
  const sentDelta =
    first != null && last != null
      ? last.sentiment_bias_avg - first.sentiment_bias_avg
      : null;

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-5">
      <div className="flex items-center gap-2 mb-4">
        <TrendingUp className="w-4 h-4 text-slate-500" />
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          Longitudinal Bias Trends
        </h2>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <select
          value={selectedOutlet}
          onChange={(e) => setSelectedOutlet(e.target.value)}
          className="text-sm rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {outlets.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
        <div className="flex rounded-lg overflow-hidden border border-slate-200 dark:border-slate-600">
          {([30, 90, 180] as DaysOption[]).map((d) => (
            <button
              key={d}
              onClick={() => setDaysBack(d)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                daysBack === d
                  ? "bg-blue-600 text-white"
                  : "bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <p className="text-xs text-slate-400 text-center py-8">Loading trend data…</p>
      )}
      {error && (
        <p className="text-xs text-rose-500 text-center py-4">{error}</p>
      )}

      {!loading && !error && snapshots.length === 0 && (
        <p className="text-xs text-slate-400 text-center py-8">
          No snapshot data yet. Run bias analysis to start building trends.
        </p>
      )}

      {!loading && !error && snapshots.length > 0 && (
        <>
          {/* Sparkline */}
          <div className="mb-4">
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">
              BSI Score over time
            </p>
            <Sparkline snapshots={snapshots} />
          </div>

          {/* Deltas */}
          {snapshots.length >= 2 && (
            <div className="flex gap-4 mb-5 p-3 rounded-lg bg-slate-50 dark:bg-slate-800">
              <DeltaPill value={bsiDelta} label="BSI change" />
              <DeltaPill value={covDelta} label="Coverage gap Δ" />
              <DeltaPill value={sentDelta} label="Sentiment Δ" />
              <div className="flex flex-col items-center gap-0.5">
                <span className="text-[10px] text-slate-400 uppercase tracking-wider">Runs</span>
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">
                  {snapshots.length}
                </span>
              </div>
            </div>
          )}

          {/* Snapshot table */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-slate-400 border-b border-slate-100 dark:border-slate-700">
                  <th className="pb-2 pr-3">Date</th>
                  <th className="pb-2 pr-3">BSI</th>
                  <th className="pb-2 pr-3">Coverage Gap</th>
                  <th className="pb-2 pr-3">Sentiment Bias</th>
                  <th className="pb-2 pr-3">Omission Score</th>
                  <th className="pb-2">Flag</th>
                </tr>
              </thead>
              <tbody>
                {[...snapshots].reverse().map((s) => (
                  <tr
                    key={s.id}
                    className="border-b border-slate-50 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50"
                  >
                    <td className="py-1.5 pr-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      {new Date(s.snapshot_date).toLocaleDateString()}
                    </td>
                    <td className={`py-1.5 pr-3 font-semibold ${bsiColor(s.bsi_score)}`}>
                      {s.bsi_score?.toFixed(3) ?? "—"}
                    </td>
                    <td className="py-1.5 pr-3 text-slate-600 dark:text-slate-300">
                      {(s.coverage_bias_rate * 100).toFixed(1)}%
                    </td>
                    <td className="py-1.5 pr-3 text-slate-600 dark:text-slate-300">
                      {s.sentiment_bias_avg.toFixed(3)}
                    </td>
                    <td className="py-1.5 pr-3">
                      {s.omission_score != null ? (
                        <span
                          className={
                            s.omission_score > 0
                              ? "text-rose-500"
                              : "text-emerald-500"
                          }
                        >
                          {s.omission_score > 0 ? "+" : ""}
                          {(s.omission_score * 100).toFixed(1)}%
                        </span>
                      ) : (
                        <span className="text-slate-300 dark:text-slate-600">—</span>
                      )}
                    </td>
                    <td className="py-1.5">
                      {s.systematic_omission === true ? (
                        <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300">
                          <AlertTriangle className="w-2.5 h-2.5" />
                          Systematic
                        </span>
                      ) : s.systematic_omission === false ? (
                        <span className="text-slate-300 dark:text-slate-600">—</span>
                      ) : (
                        <span className="text-slate-300 dark:text-slate-600">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
