"use client";

import { useEffect, useState } from "react";
import { fetchAllProfiles, fetchBiasScores, OutletBiasProfileData } from "@/lib/api";

interface OutletCard {
  profile: OutletBiasProfileData;
  coveredTopics: string[];
}

function sentimentMeta(score: number): { label: string; className: string } {
  if (score > 0.05) return { label: "Positive", className: "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300" };
  if (score < -0.05) return { label: "Negative", className: "bg-rose-50 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300" };
  return { label: "Neutral", className: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400" };
}

function trustMeta(score: number | null | undefined): { label: string; className: string } {
  if (score == null) return { label: "No trust score", className: "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400" };
  if (score >= 0.75) return { label: `Trust ${Math.round(score * 100)}`, className: "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300" };
  if (score >= 0.55) return { label: `Trust ${Math.round(score * 100)}`, className: "bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300" };
  return { label: `Trust ${Math.round(score * 100)}`, className: "bg-rose-50 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300" };
}

export default function OutletProfilesPanel() {
  const [cards, setCards] = useState<OutletCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [profilesData, scoresData] = await Promise.all([
          fetchAllProfiles(),
          fetchBiasScores(),
        ]);

        // Build a map: outlet → topic labels where coverage_present = true
        const topicsByOutlet = new Map<string, string[]>();
        for (const score of scoresData.scores) {
          if (!score.coverage_present) continue;
          const label = score.topic_label || score.topic_key;
          const list = topicsByOutlet.get(score.outlet) ?? [];
          list.push(label);
          topicsByOutlet.set(score.outlet, list);
        }

        const built: OutletCard[] = profilesData.profiles.map((profile) => ({
          profile,
          coveredTopics: topicsByOutlet.get(profile.outlet) ?? [],
        }));

        // Sort by most topics covered descending
        built.sort((a, b) => b.coveredTopics.length - a.coveredTopics.length);
        setCards(built);
      } catch {
        setError("Failed to load outlet profiles.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-8 text-center">
        <p className="text-sm text-gray-400 dark:text-gray-500">Loading outlet profiles…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-8 text-center">
        <p className="text-sm text-red-500">{error}</p>
      </div>
    );
  }

  if (cards.length === 0) {
    return (
      <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-8 text-center">
        <p className="text-sm text-gray-400 dark:text-gray-500">
          No outlet profiles yet. Run bias analysis to generate them.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
      <div className="px-6 py-5 border-b border-gray-100 dark:border-gray-800">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Outlet Profiles</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
          Topics covered and average sentiment per outlet.
        </p>
      </div>

      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        {cards.map(({ profile, coveredTopics }) => {
          const sentiment = sentimentMeta(profile.sentiment_score_avg);
          const trust = trustMeta(profile.source_trust_score);
          return (
            <div key={profile.outlet} className="px-6 py-4 flex flex-col gap-2">
              <div className="flex items-center gap-3">
                <span className="font-semibold text-gray-900 dark:text-white text-sm">
                  {profile.outlet}
                </span>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${sentiment.className}`}>
                  {sentiment.label}
                </span>
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${trust.className}`}>
                  {trust.label}
                </span>
                <span className="text-xs text-gray-400 dark:text-gray-500 ml-auto">
                  {coveredTopics.length} topic{coveredTopics.length !== 1 ? "s" : ""}
                </span>
              </div>

              {coveredTopics.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {coveredTopics.map((topic) => (
                    <span
                      key={topic}
                      className="px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs"
                    >
                      {topic}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-gray-400 dark:text-gray-500 italic">No topics scored for this outlet.</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
