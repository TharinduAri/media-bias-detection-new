"use client";

import { useEffect, useState } from "react";
import { fetchAllProfiles, OutletBiasProfileData } from "@/lib/api";

function barColor(score: number) {
  if (score >= 0.5) return "bg-rose-500";
  if (score >= 0.3) return "bg-amber-500";
  return "bg-emerald-500";
}

function scoreColor(score: number) {
  if (score >= 0.5) return "text-rose-600 dark:text-rose-400";
  if (score >= 0.3) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function trustColor(score: number | null | undefined) {
  if (score == null) return "text-slate-400";
  if (score >= 0.75) return "text-emerald-600 dark:text-emerald-400";
  if (score >= 0.55) return "text-amber-600 dark:text-amber-400";
  return "text-rose-600 dark:text-rose-400";
}

function Badge({ text, variant }: { text: string; variant: "red" | "green" }) {
  return (
    <span
      className={`ml-1.5 text-[10px] font-bold px-1.5 py-0.5 rounded leading-none ${
        variant === "red"
          ? "bg-rose-100 dark:bg-rose-900/40 text-rose-700 dark:text-rose-300"
          : "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300"
      }`}
    >
      {text}
    </span>
  );
}

export default function BsiLeaderboard() {
  const [profiles, setProfiles] = useState<OutletBiasProfileData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAllProfiles()
      .then((data) => {
        const sorted = [...data.profiles]
          .filter((p) => p.bsi_score != null || p.source_trust_score != null)
          .sort((a, b) => (b.source_trust_score ?? 0) - (a.source_trust_score ?? 0));
        setProfiles(sorted);
      })
      .catch(() => setError("Failed to load profiles."))
      .finally(() => setLoading(false));
  }, []);

  if (loading)
    return (
      <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-8 text-center">
        <p className="text-sm text-gray-400 dark:text-gray-500">Loading leaderboard…</p>
      </div>
    );

  if (error)
    return (
      <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-8 text-center">
        <p className="text-sm text-rose-500">{error}</p>
      </div>
    );

  if (profiles.length === 0)
    return (
      <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-8 text-center">
        <p className="text-sm text-gray-400 dark:text-gray-500">
          No profiles yet. Run bias analysis to generate them.
        </p>
      </div>
    );

  const maxBsi = Math.max(...profiles.map((p) => p.bsi_score ?? 0), 0.01);

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      <div className="px-6 py-5 border-b border-gray-100 dark:border-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
          Source Trust Leaderboard
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
          Source trust per outlet, with BSI shown as the underlying bias signal. Higher trust = lower detected risk.
        </p>
      </div>

      <div className="px-6 py-6 space-y-4">
        {profiles.map((p, idx) => {
          const score = p.bsi_score ?? 0;
          const trust = p.source_trust_score ?? null;
          const widthPct = (score / maxBsi) * 100;
          const isFirst = idx === 0;
          const isLast = idx === profiles.length - 1;

          return (
            <div key={p.outlet} className="flex items-center gap-3">
              <div className="w-36 shrink-0 flex items-center">
                <span className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">
                  {p.outlet}
                </span>
                {isFirst && <Badge text="MOST TRUST" variant="green" />}
                {isLast && <Badge text="LOWEST TRUST" variant="red" />}
              </div>

              <div className="flex-1 h-6 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${barColor(score)}`}
                  style={{ width: `${widthPct}%`, transition: "width 0.7s ease" }}
                />
              </div>

              <div className="w-40 shrink-0 flex items-center gap-3 justify-end">
                <span
                  className={`text-sm font-mono font-semibold tabular-nums ${scoreColor(score)}`}
                >
                  {score.toFixed(3)}
                </span>
                <span
                  className={`text-sm font-mono font-semibold tabular-nums ${trustColor(trust)}`}
                  title="Source trust score"
                >
                  {trust != null ? Math.round(trust * 100) : "--"}
                </span>
                <span className="text-xs text-gray-400 dark:text-gray-500 tabular-nums">
                  {p.articles_scored} art.
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="px-6 pb-5 pt-1 border-t border-gray-100 dark:border-gray-800 flex items-center gap-5">
        {(
          [
            { color: "bg-emerald-500", label: "Low  < 0.3" },
            { color: "bg-amber-500", label: "Medium  0.3 – 0.5" },
            { color: "bg-rose-500", label: "High  > 0.5" },
          ] as const
        ).map(({ color, label }) => (
          <span key={label} className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
            <span className={`w-3 h-3 rounded-sm inline-block ${color}`} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
