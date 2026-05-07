"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Eye } from "lucide-react";
import { fetchOmissions, OutletOmissionData, AllOmissionsData } from "@/lib/api";

function bsiColor(bsi: number | null | undefined): string {
  if (bsi == null) return "text-slate-400";
  if (bsi >= 0.6) return "text-rose-600 dark:text-rose-400";
  if (bsi >= 0.3) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function OmissionScoreCell({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="text-slate-300 dark:text-slate-600">—</span>;
  const pct = (score * 100).toFixed(1);
  if (score > 0.005) {
    return (
      <span className="font-semibold text-rose-600 dark:text-rose-400">
        +{pct}%
      </span>
    );
  }
  if (score < -0.005) {
    return (
      <span className="font-semibold text-emerald-600 dark:text-emerald-400">
        {pct}%
      </span>
    );
  }
  return <span className="text-slate-500 dark:text-slate-400">{pct}%</span>;
}

function SystematicFlag({ flag }: { flag: boolean | null | undefined }) {
  if (flag === true) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300">
        <AlertTriangle className="w-2.5 h-2.5" />
        Systematic
      </span>
    );
  }
  if (flag === false) {
    return <span className="text-slate-300 dark:text-slate-600">—</span>;
  }
  return <span className="text-slate-300 dark:text-slate-600">—</span>;
}

export default function BiasOmissionsPanel() {
  const [data, setData] = useState<AllOmissionsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchOmissions()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const sorted = data
    ? [...data.omissions].sort(
        (a, b) => (b.omission_score ?? -Infinity) - (a.omission_score ?? -Infinity)
      )
    : [];

  const systematicCount = sorted.filter((o) => o.systematic_omission === true).length;

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Eye className="w-4 h-4 text-slate-500" />
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
            Omission Detection
          </h2>
        </div>
        {data && (
          <div className="flex items-center gap-2">
            {systematicCount > 0 ? (
              <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300">
                <AlertTriangle className="w-3 h-3" />
                {systematicCount} systematic {systematicCount === 1 ? "omission" : "omissions"}
              </span>
            ) : (
              <span className="text-xs text-slate-400">No systematic omissions detected</span>
            )}
            {data.last_run_at && (
              <span className="text-[10px] text-slate-400">
                Last run: {new Date(data.last_run_at).toLocaleString()}
              </span>
            )}
          </div>
        )}
      </div>

      {loading && (
        <p className="text-xs text-slate-400 text-center py-8">Loading omission data…</p>
      )}
      {error && (
        <p className="text-xs text-rose-500 text-center py-4">{error}</p>
      )}

      {!loading && !error && sorted.length === 0 && (
        <p className="text-xs text-slate-400 text-center py-8">
          No omission data yet. Run bias analysis at least once to populate this panel.
        </p>
      )}

      {!loading && !error && sorted.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-wider text-slate-400 border-b border-slate-100 dark:border-slate-700">
                <th className="pb-2 pr-3">Outlet</th>
                <th className="pb-2 pr-3">BSI Score</th>
                <th className="pb-2 pr-3">Coverage Gap</th>
                <th className="pb-2 pr-3">Omission Score</th>
                <th className="pb-2 pr-3">vs Baseline</th>
                <th className="pb-2 pr-3">Baseline Runs</th>
                <th className="pb-2">Flag</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((o) => (
                <tr
                  key={o.outlet}
                  className={`border-b border-slate-50 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
                    o.systematic_omission === true
                      ? "bg-rose-50/40 dark:bg-rose-900/10"
                      : ""
                  }`}
                >
                  <td className="py-2 pr-3 font-medium text-slate-700 dark:text-slate-200">
                    {o.outlet}
                  </td>
                  <td className={`py-2 pr-3 font-semibold ${bsiColor(o.current_bsi_score)}`}>
                    {o.current_bsi_score?.toFixed(3) ?? "—"}
                  </td>
                  <td className="py-2 pr-3 text-slate-600 dark:text-slate-300">
                    {(o.current_coverage_bias_rate * 100).toFixed(1)}%
                  </td>
                  <td className="py-2 pr-3">
                    <OmissionScoreCell score={o.omission_score} />
                  </td>
                  <td className="py-2 pr-3 text-slate-500 dark:text-slate-400">
                    {o.omission_score != null && o.baseline_used_runs != null
                      ? `${((o.current_coverage_bias_rate - (o.omission_score != null ? o.current_coverage_bias_rate - o.omission_score : 0)) * 100).toFixed(1)}% avg`
                      : "—"}
                  </td>
                  <td className="py-2 pr-3 text-slate-500 dark:text-slate-400">
                    {o.baseline_used_runs ?? "—"}
                  </td>
                  <td className="py-2">
                    <SystematicFlag flag={o.systematic_omission} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[10px] text-slate-400 mt-3">
        Omission score = current coverage gap − historical average ({">"}15% = systematic).
        Requires ≥2 bias runs for baseline comparison.
      </p>
    </div>
  );
}
