"use client";

import { useState } from "react";
import { BarChart3, FileText, Flame, Grid3X3, Scale } from "lucide-react";
import BsiLeaderboard from "@/components/BsiLeaderboard";
import BiasResultsPanel from "@/components/BiasResultsPanel";
import CoverageHeatmap from "@/components/CoverageHeatmap";
import ManualArticleBiasPanel from "@/components/ManualArticleBiasPanel";
import TopicValidationPanel from "@/components/TopicValidationPanel";

interface Props {
  outlets: string[];
}

type BiasTab = "single" | "leaderboard" | "profiles" | "topics" | "heatmap";

const tabs: Array<{
  key: BiasTab;
  label: string;
  icon: typeof FileText;
}> = [
  { key: "single", label: "Single Article Reading", icon: FileText },
  { key: "leaderboard", label: "Source Trust Leaderboard", icon: Flame },
  { key: "profiles", label: "Outlet Profiles", icon: Scale },
  { key: "topics", label: "Topic-Group Bias Calculation", icon: BarChart3 },
  { key: "heatmap", label: "Topic Coverage Heatmap", icon: Grid3X3 },
];

export default function BiasPageTabs({ outlets }: Props) {
  const [activeTab, setActiveTab] = useState<BiasTab>("single");

  return (
    <section className="space-y-6">
      <div className="border-b border-slate-200 dark:border-slate-800">
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

      {activeTab === "single" && <ManualArticleBiasPanel outlets={outlets} />}
      {activeTab === "leaderboard" && <BsiLeaderboard />}
      {activeTab === "profiles" && <BiasResultsPanel outlets={outlets} mode="profiles" />}
      {activeTab === "topics" && <TopicValidationPanel />}
      {activeTab === "heatmap" && <CoverageHeatmap />}
    </section>
  );
}
