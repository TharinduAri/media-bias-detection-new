"use client";

import { useEffect, useState } from "react";
import { fetchOutletRegistry, OutletRegistryEntry } from "@/lib/api";

function StrategyPill({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800">
      {label}
    </span>
  );
}

function DomainBadge({ domain }: { domain: string }) {
  return (
    <span className="font-mono text-xs text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
      {domain}
    </span>
  );
}

function ClassChip({ name }: { name: string }) {
  return (
    <span className="font-mono text-[11px] text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-800 px-2 py-0.5 rounded-full">
      {name}
    </span>
  );
}

function RegistryCard({ entry }: { entry: OutletRegistryEntry }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/60 transition-all duration-200 overflow-hidden">
      <div className="flex items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <p className="mb-2 text-sm font-bold text-slate-900 dark:text-slate-100">
            {entry.name}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <DomainBadge domain={entry.domain} />
            <ClassChip name={entry.scraper_class} />
          </div>
        </div>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="shrink-0 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors text-xs mt-0.5"
          aria-label="Toggle details"
        >
          {expanded ? "▲ hide" : "▼ details"}
        </button>
      </div>

      <div className="px-4 pb-3 flex flex-wrap gap-1.5">
        <StrategyPill label={`🔍 ${entry.discovery.split("→")[0].trim()}`} />
        {entry.discovery.includes("→") &&
          entry.discovery
            .split("→")
            .slice(1)
            .map((step, i) => (
              <StrategyPill key={i} label={`↩ ${step.trim()}`} />
            ))}
      </div>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-slate-100 dark:border-slate-700/50 space-y-2 text-xs text-slate-600 dark:text-slate-400">
          <div>
            <span className="font-semibold text-slate-800 dark:text-slate-200">Extraction:</span>{" "}
            {entry.extraction}
          </div>
          <div>
            <span className="font-semibold text-slate-800 dark:text-slate-200">Notes:</span>{" "}
            {entry.notes}
          </div>
        </div>
      )}
    </div>
  );
}

export default function OutletManager() {
  const [registry, setRegistry] = useState<OutletRegistryEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchOutletRegistry()
      .then(setRegistry)
      .catch(() => setRegistry([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800">
        <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">
          Registered Scrapers
        </h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
          Each outlet has a dedicated specialist scraper. Discovery and extraction are fully customised per domain.
        </p>
      </div>

      <div className="p-5 grid grid-cols-1 lg:grid-cols-2 gap-3">
        {loading && (
          <p className="col-span-2 text-sm text-slate-400 text-center py-6">Loading…</p>
        )}
        {!loading && registry.length === 0 && (
          <p className="col-span-2 text-sm text-slate-400 text-center py-6">No scrapers registered.</p>
        )}
        {registry.map((entry) => (
          <RegistryCard key={entry.domain} entry={entry} />
        ))}
      </div>
    </div>
  );
}
