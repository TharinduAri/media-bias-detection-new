"use client";

import { useEffect, useMemo, useState } from "react";
import {
  compareBiasProfiles,
  fetchBiasArticles,
  fetchArticleBiasScore,
  fetchBiasProfile,
  ArticleBiasScoreData,
  ArticleBiasWithArticleData,
  OutletBiasProfileData,
} from "@/lib/api";

interface Props {
  outlets: string[];
}

function formatBias(score: number): string {
  const magnitude = Math.abs(score);
  if (magnitude >= 0.6) return score > 0 ? "Strongly positive" : "Strongly negative";
  if (magnitude >= 0.35) return score > 0 ? "Moderately positive" : "Moderately negative";
  if (magnitude >= 0.15) return score > 0 ? "Slightly positive" : "Slightly negative";
  return "Neutral";
}

function formatSentiment(label: string, confidence: number): string {
  const clean = label.replace(/_/g, " ");
  const cap = clean.charAt(0).toUpperCase() + clean.slice(1);
  if (confidence >= 0.75) return `${cap} (high confidence)`;
  if (confidence >= 0.55) return `${cap} (medium confidence)`;
  return `${cap} (low confidence)`;
}

export default function BiasResultsPanel({ outlets }: Props) {
  const [selectedOutlet, setSelectedOutlet] = useState(outlets[0] ?? "");
  const [profile, setProfile] = useState<OutletBiasProfileData | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);

  const [compareSelections, setCompareSelections] = useState<string[]>([]);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareResults, setCompareResults] = useState<OutletBiasProfileData[]>([]);
  const [compareMessage, setCompareMessage] = useState<string | null>(null);

  const [articleId, setArticleId] = useState("");
  const [articleLoading, setArticleLoading] = useState(false);
  const [articleResult, setArticleResult] = useState<ArticleBiasScoreData | null>(null);
  const [articleMessage, setArticleMessage] = useState<string | null>(null);

  const [biasArticles, setBiasArticles] = useState<ArticleBiasWithArticleData[]>([]);
  const [biasLoading, setBiasLoading] = useState(false);
  const [biasMessage, setBiasMessage] = useState<string | null>(null);
  const [biasOffset, setBiasOffset] = useState(0);
  const [biasHasMore, setBiasHasMore] = useState(true);
  const [biasOutletFilter, setBiasOutletFilter] = useState("");
  const [biasSort, setBiasSort] = useState<"most_biased" | "newest" | "outlet">("most_biased");

  const compareEnabled = compareSelections.length >= 2;
  const biasLimit = 50;

  const profileStats = useMemo(() => {
    if (!profile) return [] as Array<{ label: string; value: string }>;
    return [
      { label: "Sentiment bias avg", value: profile.sentiment_bias_avg.toFixed(3) },
      { label: "Sentiment score avg", value: profile.sentiment_score_avg.toFixed(3) },
      { label: "Articles scored", value: String(profile.articles_scored) },
      { label: "Topics covered", value: String(profile.topics_covered) },
      { label: "Topics considered", value: String(profile.topics_considered) },
      { label: "Coverage missing (majority)", value: String(profile.coverage_missing_majority) },
      { label: "Coverage bias rate", value: profile.coverage_bias_rate.toFixed(3) },
    ];
  }, [profile]);

  const loadProfile = async () => {
    if (!selectedOutlet) return;
    setProfileLoading(true);
    setProfileMessage(null);
    setProfile(null);
    try {
      const data = await fetchBiasProfile(selectedOutlet);
      setProfile(data);
    } catch (error) {
      setProfileMessage(error instanceof Error ? error.message : "Failed to load outlet profile.");
    } finally {
      setProfileLoading(false);
    }
  };

  const loadCompare = async () => {
    if (!compareEnabled) return;
    setCompareLoading(true);
    setCompareMessage(null);
    setCompareResults([]);
    try {
      const data = await compareBiasProfiles(compareSelections);
      setCompareResults(data);
    } catch (error) {
      setCompareMessage(error instanceof Error ? error.message : "Failed to compare outlets.");
    } finally {
      setCompareLoading(false);
    }
  };

  const loadArticleBias = async () => {
    const trimmed = articleId.trim();
    if (!trimmed) return;
    setArticleLoading(true);
    setArticleMessage(null);
    setArticleResult(null);
    try {
      const data = await fetchArticleBiasScore(Number(trimmed));
      setArticleResult(data);
    } catch (error) {
      setArticleMessage(error instanceof Error ? error.message : "Failed to load article bias.");
    } finally {
      setArticleLoading(false);
    }
  };

  const toggleCompareOutlet = (outlet: string) => {
    setCompareSelections((prev) =>
      prev.includes(outlet) ? prev.filter((item) => item !== outlet) : [...prev, outlet]
    );
  };

  const loadBiasArticles = async (newOffset: number, replace: boolean) => {
    setBiasLoading(true);
    setBiasMessage(null);
    try {
      const data = await fetchBiasArticles(
        biasLimit,
        newOffset,
        biasOutletFilter ? biasOutletFilter : undefined
      );
      setBiasArticles((prev) => (replace ? data : [...prev, ...data]));
      setBiasHasMore(data.length === biasLimit);
      setBiasOffset(newOffset + data.length);
    } catch (error) {
      setBiasMessage(error instanceof Error ? error.message : "Failed to load bias articles.");
    } finally {
      setBiasLoading(false);
    }
  };

  useEffect(() => {
    setBiasOffset(0);
    setBiasHasMore(true);
    loadBiasArticles(0, true);
  }, [biasOutletFilter]);

  const sortedBiasArticles = useMemo(() => {
    const items = [...biasArticles];
    if (biasSort === "newest") {
      return items.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    }
    if (biasSort === "outlet") {
      return items.sort((a, b) => a.outlet.localeCompare(b.outlet));
    }
    return items.sort((a, b) => Math.abs(b.sentiment_bias) - Math.abs(a.sentiment_bias));
  }, [biasArticles, biasSort]);

  return (
    <section className="space-y-6">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800">
          <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">Bias Analysis Results</h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Inspect the latest bias profiles and article-level scores.
          </p>
        </div>

        <div className="p-5 grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-4 space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Outlet Profile</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Returns the outlet's current bias profile.
              </p>
            </div>
            <div className="space-y-2">
              <select
                value={selectedOutlet}
                onChange={(event) => setSelectedOutlet(event.target.value)}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm"
              >
                {outlets.map((outlet) => (
                  <option key={outlet} value={outlet}>
                    {outlet}
                  </option>
                ))}
              </select>
              <button
                onClick={loadProfile}
                disabled={profileLoading || !selectedOutlet}
                className="w-full rounded-lg bg-blue-600 text-white text-sm font-semibold py-2 hover:bg-blue-700 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {profileLoading ? "Loading..." : "Load Profile"}
              </button>
            </div>
            {profileMessage && (
              <p className="text-xs text-red-600 dark:text-red-400">{profileMessage}</p>
            )}
            {profile && (
              <div className="space-y-2 text-xs text-slate-600 dark:text-slate-300">
                {profileStats.map((item) => (
                  <div key={item.label} className="flex items-center justify-between">
                    <span>{item.label}</span>
                    <span className="font-semibold text-slate-900 dark:text-slate-100">{item.value}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-4 space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Compare Outlets</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Returns side-by-side comparison for selected outlets.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 max-h-36 overflow-y-auto pr-1">
              {outlets.map((outlet) => (
                <label key={outlet} className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={compareSelections.includes(outlet)}
                    onChange={() => toggleCompareOutlet(outlet)}
                  />
                  <span className="truncate">{outlet}</span>
                </label>
              ))}
            </div>
            <button
              onClick={loadCompare}
              disabled={compareLoading || !compareEnabled}
              className="w-full rounded-lg bg-slate-900 dark:bg-white text-white dark:text-slate-900 text-sm font-semibold py-2 hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {compareLoading ? "Comparing..." : "Compare Profiles"}
            </button>
            {!compareEnabled && (
              <p className="text-[11px] text-slate-400">Select at least two outlets.</p>
            )}
            {compareMessage && (
              <p className="text-xs text-red-600 dark:text-red-400">{compareMessage}</p>
            )}
            {compareResults.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left text-slate-600 dark:text-slate-300">
                  <thead className="text-[11px] uppercase text-slate-400">
                    <tr>
                      <th className="pb-2">Outlet</th>
                      <th className="pb-2">Sentiment Bias</th>
                      <th className="pb-2">Coverage Bias</th>
                    </tr>
                  </thead>
                  <tbody>
                    {compareResults.map((row) => (
                      <tr key={row.outlet} className="border-t border-slate-200/60 dark:border-slate-700/60">
                        <td className="py-2 font-semibold text-slate-900 dark:text-slate-100">
                          {row.outlet}
                        </td>
                        <td className="py-2">{row.sentiment_bias_avg.toFixed(3)}</td>
                        <td className="py-2">{row.coverage_bias_rate.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-4 space-y-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Article Bias</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Returns the bias score for a single article.
              </p>
            </div>
            <div className="flex gap-2">
              <input
                value={articleId}
                onChange={(event) => setArticleId(event.target.value)}
                placeholder="Article ID"
                className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm"
              />
              <button
                onClick={loadArticleBias}
                disabled={articleLoading || !articleId.trim()}
                className="rounded-lg bg-amber-600 text-white text-sm font-semibold px-3 hover:bg-amber-700 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {articleLoading ? "..." : "Fetch"}
              </button>
            </div>
            {articleMessage && (
              <p className="text-xs text-red-600 dark:text-red-400">{articleMessage}</p>
            )}
            {articleResult && (
              <div className="space-y-2 text-xs text-slate-600 dark:text-slate-300">
                <div className="flex items-center justify-between">
                  <span>Outlet</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100">{articleResult.outlet}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Sentiment label</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100">{articleResult.sentiment_label}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Sentiment score</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100">
                    {articleResult.sentiment_score.toFixed(3)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Sentiment bias</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100">
                    {articleResult.sentiment_bias.toFixed(3)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Coverage majority</span>
                  <span className="font-semibold text-slate-900 dark:text-slate-100">
                    {articleResult.coverage_majority ? "Yes" : "No"}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="px-5 pb-6">
          <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900/40 p-4 space-y-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  All Bias-Scored Articles
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  All articles with their latest bias scores.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <select
                  value={biasOutletFilter}
                  onChange={(event) => setBiasOutletFilter(event.target.value)}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-xs"
                >
                  <option value="">All outlets</option>
                  {outlets.map((outlet) => (
                    <option key={outlet} value={outlet}>
                      {outlet}
                    </option>
                  ))}
                </select>
                <select
                  value={biasSort}
                  onChange={(event) => setBiasSort(event.target.value as "most_biased" | "newest" | "outlet")}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-xs"
                >
                  <option value="most_biased">Most biased</option>
                  <option value="newest">Newest</option>
                  <option value="outlet">Outlet</option>
                </select>
                <button
                  onClick={() => loadBiasArticles(0, true)}
                  disabled={biasLoading}
                  className="rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-60"
                >
                  Refresh
                </button>
              </div>
            </div>

            {biasMessage && (
              <p className="text-xs text-red-600 dark:text-red-400">{biasMessage}</p>
            )}

            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left text-slate-600 dark:text-slate-300">
                <thead className="text-[11px] uppercase text-slate-400">
                  <tr>
                    <th className="pb-2">Title</th>
                    <th className="pb-2">Outlet</th>
                    <th className="pb-2">Sentiment</th>
                    <th className="pb-2">Bias</th>
                    <th className="pb-2">Coverage</th>
                    <th className="pb-2">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedBiasArticles.map((row) => (
                    <tr key={row.id} className="border-t border-slate-200/60 dark:border-slate-700/60">
                      <td className="py-2 min-w-[220px]">
                        <a
                          href={row.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-slate-900 dark:text-slate-100 font-medium hover:underline"
                        >
                          {row.title}
                        </a>
                      </td>
                      <td className="py-2 font-semibold text-slate-900 dark:text-slate-100">{row.outlet}</td>
                      <td className="py-2">
                        {formatSentiment(row.sentiment_label, row.sentiment_score)}
                      </td>
                      <td className="py-2">
                        {formatBias(row.sentiment_bias)} ({row.sentiment_bias.toFixed(3)})
                      </td>
                      <td className="py-2">{row.coverage_majority ? "Covered by most outlets" : "Limited coverage"}</td>
                      <td className="py-2">
                        {new Date(row.date).toLocaleDateString("en-GB")}
                      </td>
                    </tr>
                  ))}
                  {biasArticles.length === 0 && !biasLoading && (
                    <tr>
                      <td colSpan={6} className="py-6 text-center text-slate-400">
                        No bias scores found yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{biasLoading ? "Loading..." : `${biasArticles.length} articles loaded`}</span>
              {biasHasMore && (
                <button
                  onClick={() => loadBiasArticles(biasOffset, false)}
                  disabled={biasLoading}
                  className="rounded-lg bg-slate-900 dark:bg-white text-white dark:text-slate-900 px-3 py-1.5 text-xs font-semibold hover:opacity-90 disabled:opacity-60"
                >
                  Load more
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
