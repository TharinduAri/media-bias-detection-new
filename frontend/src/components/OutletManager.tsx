"use client";

import { useEffect, useState } from "react";
import {
  createOutlet,
  deleteOutlet,
  fetchOutlets,
  fetchOutletRegistry,
  OutletData,
  OutletRegistryEntry,
} from "@/lib/api";

// ── Scraper strategy pill ────────────────────────────────────────────────────
function StrategyPill({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800">
      {label}
    </span>
  );
}

// ── Domain badge ─────────────────────────────────────────────────────────────
function DomainBadge({ domain }: { domain: string }) {
  return (
    <span className="font-mono text-xs text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
      {domain}
    </span>
  );
}

// ── Scraper class chip ───────────────────────────────────────────────────────
function ClassChip({ name }: { name: string }) {
  return (
    <span className="font-mono text-[11px] text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-800 px-2 py-0.5 rounded-full">
      {name}
    </span>
  );
}

// ── DB outlet row (configured, can be deleted) ───────────────────────────────
function DbOutletRow({
  outlet,
  onDelete,
}: {
  outlet: OutletData;
  onDelete: (id: number, name: string) => void;
}) {
  return (
    <div className="flex items-center justify-between py-2.5 px-3 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 gap-4">
      <div className="min-w-0">
        <p className="font-semibold text-sm text-slate-900 dark:text-slate-100 truncate">
          {outlet.name}
        </p>
        <a
          href={outlet.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-blue-600 dark:text-blue-400 hover:underline truncate block"
        >
          {outlet.url}
        </a>
      </div>
      <button
        onClick={() => onDelete(outlet.id, outlet.name)}
        className="shrink-0 px-3 py-1 text-xs font-medium bg-red-600 hover:bg-red-700 text-white rounded-md transition-colors"
      >
        Remove
      </button>
    </div>
  );
}

// ── Registry card ────────────────────────────────────────────────────────────
function RegistryCard({ entry, isActive }: { entry: OutletRegistryEntry; isActive: boolean }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`rounded-xl border transition-all duration-200 overflow-hidden ${
        isActive
          ? "border-emerald-300 dark:border-emerald-700 bg-emerald-50/50 dark:bg-emerald-900/10"
          : "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/60"
      }`}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3 p-4">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          {/* Active indicator */}
          <div
            className={`w-2 h-2 rounded-full shrink-0 mt-1 ${
              isActive ? "bg-emerald-500 animate-pulse" : "bg-slate-300 dark:bg-slate-600"
            }`}
          />
          <DomainBadge domain={entry.domain} />
          <ClassChip name={entry.scraper_class} />
        </div>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="shrink-0 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors text-xs mt-0.5"
          aria-label="Toggle details"
        >
          {expanded ? "▲ hide" : "▼ details"}
        </button>
      </div>

      {/* Strategy pills */}
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

      {/* Expanded details */}
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

// ── Main component ───────────────────────────────────────────────────────────
export default function OutletManager() {
  const [outlets, setOutlets] = useState<OutletData[]>([]);
  const [registry, setRegistry] = useState<OutletRegistryEntry[]>([]);
  const [isFetching, setIsFetching] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newRssFeeds, setNewRssFeeds] = useState("");
  const [isAdding, setIsAdding] = useState(false);

  const activeDomains = new Set(
    outlets.map((o) => {
      try {
        return new URL(o.url).hostname.replace(/^www\./, "");
      } catch {
        return "";
      }
    })
  );

  const load = async () => {
    setIsFetching(true);
    try {
      const [outletData, registryData] = await Promise.all([
        fetchOutlets(),
        fetchOutletRegistry().catch(() => [] as OutletRegistryEntry[]),
      ]);
      setOutlets(outletData);
      setRegistry(registryData);
    } catch {
      setMessage({ text: "Failed to load outlets.", type: "error" });
    } finally {
      setIsFetching(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleDelete = async (outletId: number, outletName: string) => {
    const confirmed = window.confirm(`Remove outlet "${outletName}" from the DB?\n\nThe specialist scraper will still run if the domain is registered.`);
    if (!confirmed) return;

    setMessage(null);
    try {
      await deleteOutlet(outletId);
      setMessage({ text: `"${outletName}" removed.`, type: "success" });
      await load();
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : "Failed to delete outlet.",
        type: "error",
      });
    }
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim() || !newUrl.trim()) return;

    setIsAdding(true);
    setMessage(null);

    try {
      await createOutlet({
        name: newName.trim(),
        url: newUrl.trim(),
        rss_feeds: newRssFeeds
          ? newRssFeeds.split(",").map((s) => s.trim()).filter(Boolean)
          : [],
      });
      setMessage({ text: `Outlet "${newName}" added successfully.`, type: "success" });
      setNewName("");
      setNewUrl("");
      setNewRssFeeds("");
      await load();
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : "Failed to add outlet.",
        type: "error",
      });
    } finally {
      setIsAdding(false);
    }
  };

  return (
    <section className="space-y-6">

      {/* ── Scraper Registry ── */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden">
        {/* Header */}
        <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">
              Registered Scrapers
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Each outlet has a dedicated specialist scraper. Discovery and extraction are fully customised per domain.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
            <div className="w-2 h-2 rounded-full bg-emerald-500" />
            <span>active in DB</span>
            <div className="w-2 h-2 rounded-full bg-slate-300 dark:bg-slate-600 ml-2" />
            <span>not in DB</span>
          </div>
        </div>

        {/* Registry cards */}
        <div className="p-5 grid grid-cols-1 lg:grid-cols-2 gap-3">
          {registry.length === 0 && isFetching && (
            <p className="col-span-2 text-sm text-slate-400 text-center py-6">Loading registry…</p>
          )}
          {registry.map((entry) => (
            <RegistryCard
              key={entry.domain}
              entry={entry}
              isActive={activeDomains.has(entry.domain)}
            />
          ))}
        </div>
      </div>

      {/* ── DB Outlets ── */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">
              Database Outlets
              <span className="ml-2 text-xs font-normal text-slate-400">
                ({outlets.length} configured)
              </span>
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              Outlets stored in the DB are loaded by the scraper at runtime. Only registered specialist domains are scraped with custom logic.
            </p>
          </div>
          <button
            onClick={load}
            disabled={isFetching}
            className="text-xs px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
          >
            {isFetching ? "Refreshing…" : "↻ Refresh"}
          </button>
        </div>

        <div className="p-5 border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
          <form onSubmit={handleAdd} className="flex flex-col md:flex-row gap-3">
            <div className="flex-1">
              <input
                type="text"
                placeholder="Outlet Name (e.g. Daily Mirror)"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-600 transition-all"
                required
              />
            </div>
            <div className="flex-[2]">
              <input
                type="url"
                placeholder="Base URL (e.g. https://www.dailymirror.lk)"
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-600 transition-all"
                required
              />
            </div>
            <div className="flex-[2]">
              <input
                type="text"
                placeholder="RSS Feeds (Optional, comma-separated)"
                value={newRssFeeds}
                onChange={(e) => setNewRssFeeds(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:focus:ring-indigo-600 transition-all"
              />
            </div>
            <button
              type="submit"
              disabled={isAdding || !newName || !newUrl}
              className="px-4 py-2 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
            >
              {isAdding ? "Adding..." : "Add Outlet"}
            </button>
          </form>
        </div>

        <div className="p-5">
          {message && (
            <p
              className={`text-xs mb-3 px-3 py-2 rounded-lg ${
                message.type === "success"
                  ? "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-400"
                  : "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400"
              }`}
            >
              {message.text}
            </p>
          )}

          {!isFetching && outlets.length === 0 ? (
            <p className="text-sm text-slate-400 dark:text-slate-500 text-center py-6">
              No outlets in DB. Add them via the seed script or Prisma Studio.
            </p>
          ) : (
            <div className="space-y-2">
              {outlets.map((outlet) => (
                <DbOutletRow key={outlet.id} outlet={outlet} onDelete={handleDelete} />
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
