"use client";

import { useEffect, useMemo, useState } from "react";
import {
  compareBiasProfiles,
  fetchBiasArticles,
  fetchBiasProfile,
  ArticleBiasWithArticleData,
  OutletBiasProfileData,
} from "@/lib/api";

interface Props {
  outlets: string[];
}

// ─── Formatting helpers ───────────────────────────────────────────────────────

function biasLabel(score: number): string {
  const m = Math.abs(score);
  if (m >= 0.6) return score > 0 ? "Strongly positive" : "Strongly negative";
  if (m >= 0.35) return score > 0 ? "Moderately positive" : "Moderately negative";
  if (m >= 0.15) return score > 0 ? "Slightly positive" : "Slightly negative";
  return "Neutral";
}

function biasColor(score: number): string {
  const m = Math.abs(score);
  if (m >= 0.35) return score > 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
  if (m >= 0.15) return score > 0 ? "text-emerald-500 dark:text-emerald-500" : "text-rose-500 dark:text-rose-500";
  return "text-slate-500 dark:text-slate-400";
}

function pct(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

function emphasisLabel(v: number): string {
  const p = Math.round(Math.abs(v) * 100);
  if (p < 5) return "Average length";
  return v > 0 ? `${p}% longer than peers` : `${p}% shorter than peers`;
}

function emphasisColor(v: number): string {
  if (Math.abs(v) < 0.05) return "text-slate-500 dark:text-slate-400";
  return v > 0 ? "text-blue-600 dark:text-blue-400" : "text-orange-500 dark:text-orange-400";
}

// Centered bar: left half = negative (rose), right half = positive (emerald)
function BiasBar({ value, maxAbs = 1 }: { value: number; maxAbs?: number }) {
  const half = 50;
  const fill = Math.min((Math.abs(value) / maxAbs) * half, half);
  return (
    <div className="relative w-20 h-2 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
      <div className="absolute left-1/2 top-0 bottom-0 w-px bg-slate-300 dark:bg-slate-600" />
      {value >= 0 ? (
        <div className="absolute top-0 h-full bg-emerald-400 rounded-r-full" style={{ left: "50%", width: `${fill}%` }} />
      ) : (
        <div className="absolute top-0 h-full bg-rose-400 rounded-l-full" style={{ right: "50%", width: `${fill}%` }} />
      )}
    </div>
  );
}

// ─── Outlet Profile Card ──────────────────────────────────────────────────────

function OutletProfileCard({ outlets }: { outlets: string[] }) {
  const [selected, setSelected] = useState(outlets[0] ?? "");
  const [profile, setProfile] = useState<OutletBiasProfileData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (outlet: string) => {
    if (!outlet) return;
    setLoading(true);
    setError(null);
    setProfile(null);
    try {
      setProfile(await fetchBiasProfile(outlet));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load profile.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Outlet Profile</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Bias metrics for a single outlet.</p>
      </div>

      <div className="flex gap-2">
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm"
        >
          {outlets.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <button
          onClick={() => load(selected)}
          disabled={loading || !selected}
          className="rounded-lg bg-blue-600 text-white text-sm font-semibold px-4 py-2 hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {loading ? "…" : "Load"}
        </button>
      </div>

      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}

      {profile && (
        <div className="space-y-3">
          {/* Sentiment bias — the headline metric */}
          <div className="rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-3 flex items-center justify-between gap-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Sentiment Bias</p>
              <p className={`text-lg font-bold mt-0.5 ${biasColor(profile.sentiment_bias_avg)}`}>
                {profile.sentiment_bias_avg > 0 ? "+" : ""}{profile.sentiment_bias_avg.toFixed(3)}
              </p>
              <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">{biasLabel(profile.sentiment_bias_avg)} vs. topic peers</p>
            </div>
            <BiasBar value={profile.sentiment_bias_avg} />
          </div>

          {/* Coverage bias */}
          <div className="rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Coverage Gaps</p>
            <p className="text-lg font-bold text-slate-900 dark:text-slate-100 mt-0.5">
              {profile.coverage_missing_majority} of {profile.topics_considered}
              <span className="text-sm font-normal text-slate-500 ml-2">major stories missed</span>
            </p>
            <div className="mt-2 w-full h-1.5 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-amber-500 rounded-full"
                style={{ width: pct(Math.min(profile.coverage_bias_rate, 1)) }}
              />
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">{pct(profile.coverage_bias_rate)} gap rate</p>
          </div>

          {/* Emphasis bias */}
          {profile.emphasis_bias_avg != null && (
            <div className="rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Story Emphasis</p>
                <p className={`text-sm font-semibold mt-0.5 ${emphasisColor(profile.emphasis_bias_avg)}`}>
                  {emphasisLabel(profile.emphasis_bias_avg)}
                </p>
                <p className="text-[11px] text-slate-400 mt-0.5">Relative article length vs. topic peers</p>
              </div>
              <BiasBar value={profile.emphasis_bias_avg} maxAbs={0.5} />
            </div>
          )}

          {/* BSI Score */}
          {profile.bsi_score != null && (
            <div className="rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Bias Signal Index</p>
                <p className={`text-lg font-bold mt-0.5 ${
                  profile.bsi_score >= 0.6
                    ? "text-rose-600 dark:text-rose-400"
                    : profile.bsi_score >= 0.3
                    ? "text-amber-600 dark:text-amber-400"
                    : "text-emerald-600 dark:text-emerald-400"
                }`}>
                  {profile.bsi_score.toFixed(3)}
                </p>
                <p className="text-[11px] text-slate-400 mt-0.5">Composite bias score [0–1]</p>
              </div>
              <div className="w-20 h-2 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    profile.bsi_score >= 0.6
                      ? "bg-rose-400"
                      : profile.bsi_score >= 0.3
                      ? "bg-amber-400"
                      : "bg-emerald-400"
                  }`}
                  style={{ width: `${Math.min(profile.bsi_score * 100, 100)}%` }}
                />
              </div>
            </div>
          )}

          {/* Counts */}
          <div className="grid grid-cols-2 gap-2 text-center text-xs">
            <div className="rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-2">
              <p className="text-[10px] text-slate-400 uppercase">Articles scored</p>
              <p className="text-base font-bold text-slate-900 dark:text-slate-100">{profile.articles_scored}</p>
            </div>
            <div className="rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-2">
              <p className="text-[10px] text-slate-400 uppercase">Topics covered</p>
              <p className="text-base font-bold text-slate-900 dark:text-slate-100">{profile.topics_covered}</p>
            </div>
          </div>

          {/* Missed topics */}
          {profile.missed_topics && profile.missed_topics.length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-1.5">Missed Major Stories</p>
              <div className="max-h-28 overflow-y-auto space-y-1 pr-1">
                {profile.missed_topics.map((t, i) => (
                  <div key={i} className="flex items-start gap-2 text-[11px] text-slate-600 dark:text-slate-400">
                    <span className="mt-1 w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                    {t}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Compare Card ─────────────────────────────────────────────────────────────

function CompareCard({ outlets }: { outlets: string[] }) {
  const [selections, setSelections] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<OutletBiasProfileData[]>([]);
  const [error, setError] = useState<string | null>(null);

  const toggle = (o: string) =>
    setSelections((prev) => prev.includes(o) ? prev.filter((x) => x !== o) : [...prev, o]);

  const run = async () => {
    if (selections.length < 2) return;
    setLoading(true);
    setError(null);
    try {
      setResults(await compareBiasProfiles(selections));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Compare failed.");
    } finally {
      setLoading(false);
    }
  };

  const maxSentBias = results.length ? Math.max(...results.map((r) => Math.abs(r.sentiment_bias_avg)), 0.01) : 1;
  const maxCovBias = results.length ? Math.max(...results.map((r) => r.coverage_bias_rate), 0.01) : 1;
  const hasEmphasis = results.some((r) => r.emphasis_bias_avg != null);
  const maxEmph = hasEmphasis ? Math.max(...results.map((r) => Math.abs(r.emphasis_bias_avg ?? 0)), 0.01) : 1;

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Compare Outlets</h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Side-by-side bias comparison.</p>
      </div>

      <div className="grid grid-cols-2 gap-2 max-h-36 overflow-y-auto pr-1">
        {outlets.map((o) => (
          <label key={o} className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300 cursor-pointer">
            <input type="checkbox" checked={selections.includes(o)} onChange={() => toggle(o)} />
            <span className="truncate">{o}</span>
          </label>
        ))}
      </div>

      <button
        onClick={run}
        disabled={loading || selections.length < 2}
        className="w-full rounded-lg bg-slate-900 dark:bg-white text-white dark:text-slate-900 text-sm font-semibold py-2 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? "Comparing…" : "Compare"}
      </button>
      {selections.length < 2 && <p className="text-[11px] text-slate-400">Select at least two outlets.</p>}
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}

      {results.length > 0 && (
        <div className="space-y-3">
          {/* Sentiment bias */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">Sentiment Bias (deviation from topic mean)</p>
            {results.map((r) => (
              <div key={r.outlet} className="flex items-center gap-2 mb-1.5">
                <span className="w-28 text-xs font-medium text-slate-700 dark:text-slate-300 truncate">{r.outlet}</span>
                <div className="flex-1 h-3 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden relative">
                  <div className="absolute left-1/2 top-0 bottom-0 w-px bg-slate-300 dark:bg-slate-600" />
                  {r.sentiment_bias_avg >= 0 ? (
                    <div className="absolute top-0 h-full bg-emerald-400 rounded-r-full" style={{ left: "50%", width: `${(r.sentiment_bias_avg / maxSentBias) * 50}%` }} />
                  ) : (
                    <div className="absolute top-0 h-full bg-rose-400 rounded-l-full" style={{ right: "50%", width: `${(Math.abs(r.sentiment_bias_avg) / maxSentBias) * 50}%` }} />
                  )}
                </div>
                <span className={`text-xs font-bold w-12 text-right ${biasColor(r.sentiment_bias_avg)}`}>
                  {r.sentiment_bias_avg > 0 ? "+" : ""}{r.sentiment_bias_avg.toFixed(3)}
                </span>
              </div>
            ))}
          </div>

          {/* Coverage bias */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">Coverage Gap (% of major stories missed)</p>
            {results.map((r) => (
              <div key={r.outlet} className="flex items-center gap-2 mb-1.5">
                <span className="w-28 text-xs font-medium text-slate-700 dark:text-slate-300 truncate">{r.outlet}</span>
                <div className="flex-1 h-3 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div className="h-full bg-amber-400 rounded-full" style={{ width: `${(r.coverage_bias_rate / maxCovBias) * 100}%` }} />
                </div>
                <span className="text-xs font-bold w-12 text-right text-amber-600 dark:text-amber-400">{pct(r.coverage_bias_rate)}</span>
              </div>
            ))}
          </div>

          {/* Emphasis bias */}
          {hasEmphasis && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">Story Emphasis (relative article length)</p>
              {results.map((r) => {
                const v = r.emphasis_bias_avg ?? 0;
                return (
                  <div key={r.outlet} className="flex items-center gap-2 mb-1.5">
                    <span className="w-28 text-xs font-medium text-slate-700 dark:text-slate-300 truncate">{r.outlet}</span>
                    <div className="flex-1 h-3 bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden relative">
                      <div className="absolute left-1/2 top-0 bottom-0 w-px bg-slate-300 dark:bg-slate-600" />
                      {v >= 0 ? (
                        <div className="absolute top-0 h-full bg-blue-400 rounded-r-full" style={{ left: "50%", width: `${(v / maxEmph) * 50}%` }} />
                      ) : (
                        <div className="absolute top-0 h-full bg-orange-400 rounded-l-full" style={{ right: "50%", width: `${(Math.abs(v) / maxEmph) * 50}%` }} />
                      )}
                    </div>
                    <span className={`text-xs font-bold w-12 text-right ${emphasisColor(v)}`}>
                      {v > 0 ? "+" : ""}{Math.round(v * 100)}%
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Articles Table ───────────────────────────────────────────────────────────

function ArticlesTable({ outlets }: { outlets: string[] }) {
  const [articles, setArticles] = useState<ArticleBiasWithArticleData[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [outletFilter, setOutletFilter] = useState("");
  const [sort, setSort] = useState<"most_biased" | "newest" | "outlet" | "topic">("most_biased");
  const limit = 50;

  const load = async (newOffset: number, replace: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchBiasArticles(limit, newOffset, outletFilter || undefined);
      setArticles((prev) => replace ? data : [...prev, ...data]);
      setHasMore(data.length === limit);
      setOffset(newOffset + data.length);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load articles.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setOffset(0);
    setHasMore(true);
    load(0, true);
  }, [outletFilter]);

  const sorted = useMemo(() => {
    const items = [...articles];
    if (sort === "newest") return items.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    if (sort === "outlet") return items.sort((a, b) => a.outlet.localeCompare(b.outlet));
    if (sort === "topic") return items.sort((a, b) => (a.topic_label || a.topic_key).localeCompare(b.topic_label || b.topic_key));
    return items.sort((a, b) => Math.abs(b.sentiment_bias) - Math.abs(a.sentiment_bias));
  }, [articles, sort]);

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/40 p-4 space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">All Bias-Scored Articles</h3>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Every article with its latest bias score and topic.</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={outletFilter}
            onChange={(e) => setOutletFilter(e.target.value)}
            className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-xs"
          >
            <option value="">All outlets</option>
            {outlets.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
            className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-xs"
          >
            <option value="most_biased">Most biased first</option>
            <option value="newest">Newest first</option>
            <option value="outlet">By outlet</option>
            <option value="topic">By topic</option>
          </select>
          <button
            onClick={() => load(0, true)}
            disabled={loading}
            className="rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-60"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}

      <div className="overflow-x-auto">
        <table className="w-full text-xs text-left text-slate-600 dark:text-slate-300">
          <thead className="text-[11px] uppercase text-slate-400">
            <tr>
              <th className="pb-2 pr-3">Title</th>
              <th className="pb-2 pr-3">Outlet</th>
              <th className="pb-2 pr-3">Topic</th>
              <th className="pb-2 pr-3 text-center">Sentiment</th>
              <th className="pb-2 pr-3 text-center">Bias vs. peers</th>
              <th className="pb-2 pr-3 text-center">Story emphasis</th>
              <th className="pb-2 text-center">Coverage</th>
              <th className="pb-2">Date</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.id} className="border-t border-slate-200/60 dark:border-slate-700/60 hover:bg-slate-50 dark:hover:bg-slate-800/30">
                <td className="py-2 pr-3 min-w-50">
                  <a href={row.url} target="_blank" rel="noopener noreferrer"
                    className="text-slate-900 dark:text-slate-100 font-medium hover:text-blue-600 dark:hover:text-blue-400 hover:underline line-clamp-2">
                    {row.title}
                  </a>
                </td>
                <td className="py-2 pr-3 font-semibold whitespace-nowrap text-slate-700 dark:text-slate-300">{row.outlet}</td>
                <td className="py-2 pr-3 max-w-35">
                  <span className="text-[11px] text-slate-500 dark:text-slate-400 line-clamp-1">{row.topic_label || row.topic_key}</span>
                </td>
                <td className="py-2 pr-3 text-center">
                  <span className={`font-semibold ${row.sentiment_score > 0.1 ? "text-emerald-600 dark:text-emerald-400" : row.sentiment_score < -0.1 ? "text-rose-600 dark:text-rose-400" : "text-slate-500"}`}>
                    {row.sentiment_score > 0 ? "+" : ""}{row.sentiment_score.toFixed(2)}
                  </span>
                  <div className="text-[10px] text-slate-400 capitalize">{row.sentiment_label}</div>
                </td>
                <td className="py-2 pr-3">
                  <div className="flex flex-col items-center gap-1">
                    <span className={`font-bold ${biasColor(row.sentiment_bias)}`}>
                      {row.sentiment_bias > 0 ? "+" : ""}{row.sentiment_bias.toFixed(3)}
                    </span>
                    <BiasBar value={row.sentiment_bias} />
                    <span className="text-[10px] text-slate-400">{biasLabel(row.sentiment_bias)}</span>
                  </div>
                </td>
                <td className="py-2 pr-3 text-center">
                  {row.emphasis_bias != null ? (
                    <span className={`text-[11px] font-medium ${emphasisColor(row.emphasis_bias)}`}>
                      {row.emphasis_bias > 0 ? "+" : ""}{Math.round(row.emphasis_bias * 100)}%
                    </span>
                  ) : (
                    <span className="text-[11px] text-slate-300 dark:text-slate-600">—</span>
                  )}
                </td>
                <td className="py-2 pr-3 text-center">
                  {row.coverage_majority ? (
                    <span className="text-[10px] font-medium text-emerald-600 dark:text-emerald-400">Major story</span>
                  ) : (
                    <span className="text-[10px] text-slate-400">Niche</span>
                  )}
                </td>
                <td className="py-2 whitespace-nowrap">{new Date(row.date).toLocaleDateString("en-GB")}</td>
              </tr>
            ))}
            {articles.length === 0 && !loading && (
              <tr>
                <td colSpan={8} className="py-8 text-center text-slate-400">No bias scores found yet. Run bias analysis first.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>{loading ? "Loading…" : `${articles.length} articles loaded`}</span>
        {hasMore && (
          <button
            onClick={() => load(offset, false)}
            disabled={loading}
            className="rounded-lg bg-slate-900 dark:bg-white text-white dark:text-slate-900 px-3 py-1.5 text-xs font-semibold hover:opacity-90 disabled:opacity-60"
          >
            Load more
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export default function BiasResultsPanel({ outlets }: Props) {
  return (
    <section className="space-y-6">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800">
          <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Bias Analysis Results</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Outlet profiles, side-by-side comparison, and every scored article.
          </p>
        </div>

        <div className="p-5 grid grid-cols-1 lg:grid-cols-2 gap-5">
          <OutletProfileCard outlets={outlets} />
          <CompareCard outlets={outlets} />
        </div>

        <div className="px-5 pb-6">
          <ArticlesTable outlets={outlets} />
        </div>
      </div>
    </section>
  );
}
