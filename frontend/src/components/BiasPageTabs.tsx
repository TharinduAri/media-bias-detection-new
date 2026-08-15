"use client";

import { useEffect, useState } from "react";
import { BarChart3, Scale } from "lucide-react";
import BiasResultsPanel from "@/components/BiasResultsPanel";
import TopicValidationPanel from "@/components/TopicValidationPanel";
import { AnalysisType, fetchAllProfiles, TopicSummaryData } from "@/lib/api";

interface Props {
  initialProfileOutlets: string[];
  initialTopics: TopicSummaryData[];
}

type BiasTab = "topics" | "profiles";

const tabs: Array<{
  key: BiasTab;
  label: string;
  icon: typeof BarChart3;
}> = [
  { key: "topics", label: "Topic-Group Bias Calculation", icon: BarChart3 },
  { key: "profiles", label: "Outlet Profiles", icon: Scale },
];

export default function BiasPageTabs({ initialProfileOutlets, initialTopics }: Props) {
  const [activeTab, setActiveTab] = useState<BiasTab>("topics");
  const [analysisType, setAnalysisType] = useState<AnalysisType>("general");
  const [profileState, setProfileState] = useState<{
    analysisType: AnalysisType;
    outlets: string[];
    error: string | null;
  }>({
    analysisType: "general",
    outlets: initialProfileOutlets,
    error: null,
  });

  const profileOutlets = profileState.analysisType === analysisType ? profileState.outlets : [];
  const profilesLoading = profileState.analysisType !== analysisType;
  const profilesError = profileState.analysisType === analysisType ? profileState.error : null;

  useEffect(() => {
    let cancelled = false;

    fetchAllProfiles(analysisType)
      .then((data) => {
        if (!cancelled) {
          setProfileState({
            analysisType,
            outlets: data.profiles.map((profile) => profile.outlet),
            error: null,
          });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProfileState({
            analysisType,
            outlets: [],
            error: "Failed to load outlet profiles.",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [analysisType]);

  return (
    <section className="space-y-6">
      <div className="border-b border-slate-200 dark:border-slate-800">
        <div className="mb-3 inline-flex rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-700 dark:bg-slate-900">
          {(["general", "financial"] as AnalysisType[]).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => setAnalysisType(type)}
              className={`h-8 rounded-md px-3 text-xs font-semibold capitalize transition-colors ${
                analysisType === type
                  ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
                  : "text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
              }`}
            >
              {type}
            </button>
          ))}
        </div>
        <div className="flex gap-2 overflow-x-auto pb-3">
          {tabs.map(({ key, label, icon: Icon }) => {
            const active = activeTab === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setActiveTab(key)}
                className={`inline-flex h-10 shrink-0 items-center gap-2 rounded-lg border px-3 text-sm font-semibold transition-colors ${
                  active
                    ? "border-slate-900 bg-slate-900 text-white dark:border-white dark:bg-white dark:text-slate-900"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {activeTab === "topics" && (
        <TopicValidationPanel analysisType={analysisType} initialTopics={initialTopics} />
      )}
      {activeTab === "profiles" && (
        <div className="space-y-3">
          {profilesLoading && (
            <p className="text-xs text-slate-500 dark:text-slate-400">Loading outlet profiles…</p>
          )}
          {profilesError && (
            <p className="text-xs text-red-600 dark:text-red-400">{profilesError}</p>
          )}
          <BiasResultsPanel outlets={profileOutlets} mode="profiles" analysisType={analysisType} />
        </div>
      )}
    </section>
  );
}
