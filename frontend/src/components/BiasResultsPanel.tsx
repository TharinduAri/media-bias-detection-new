"use client";

import { useMemo, useState } from "react";
import {
  compareBiasProfiles,
  fetchArticleBiasScore,
  fetchBiasProfile,
  ArticleBiasScoreData,
  OutletBiasProfileData,
} from "@/lib/api";

interface Props {
  outlets: string[];
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

  const compareEnabled = compareSelections.length >= 2;

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
      </div>
    </section>
  );
}
