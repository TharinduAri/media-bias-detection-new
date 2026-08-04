"use client";

import { useState, useCallback } from "react";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

type ParamDef = {
  name: string;
  in: "query" | "path";
  type: "string" | "number";
  description: string;
  default?: string;
  placeholder?: string;
};

type Endpoint = {
  id: string;
  method: "GET" | "POST" | "DELETE";
  path: string;
  description: string;
  params?: ParamDef[];
};

type Group = {
  name: string;
  tag: string;
  endpoints: Endpoint[];
};

const GROUPS: Group[] = [
  {
    name: "System",
    tag: "system",
    endpoints: [
      {
        id: "pipeline-status",
        method: "GET",
        path: "/system/pipeline-status",
        description: "Get current scraper pipeline status",
      },
      {
        id: "scrape-logs",
        method: "GET",
        path: "/system/scrape-logs",
        description: "List scrape run logs",
        params: [
          { name: "limit", in: "query", type: "number", description: "Max results", default: "10" },
        ],
      },
      {
        id: "scrape-logs-latest",
        method: "GET",
        path: "/system/scrape-logs/latest",
        description: "Get the latest scrape log entry",
      },
      {
        id: "scrape",
        method: "POST",
        path: "/system/scrape",
        description: "Trigger scrape for one or more outlets",
      },
      {
        id: "clean-rescrape",
        method: "POST",
        path: "/system/clean-and-rescrape",
        description: "Delete all articles and trigger a full rescrape",
      },
      {
        id: "clean-db",
        method: "POST",
        path: "/system/clean-db",
        description: "Delete all articles without rescraping",
      },
    ],
  },
  {
    name: "Articles",
    tag: "articles",
    endpoints: [
      {
        id: "articles-outlets",
        method: "GET",
        path: "/articles/outlets",
        description: "List distinct outlet names that have articles",
      },
      {
        id: "articles-outlet-counts",
        method: "GET",
        path: "/articles/outlet-counts",
        description: "Article count grouped by outlet",
      },
      {
        id: "articles-list",
        method: "GET",
        path: "/articles",
        description: "List articles with optional filters",
        params: [
          { name: "outlet", in: "query", type: "string", description: "Filter by outlet" },
          { name: "source", in: "query", type: "string", description: "Filter by source" },
          { name: "from", in: "query", type: "string", description: "From date", placeholder: "2024-01-01" },
          { name: "to", in: "query", type: "string", description: "To date", placeholder: "2024-12-31" },
          { name: "limit", in: "query", type: "number", description: "Max results", default: "20" },
          { name: "offset", in: "query", type: "number", description: "Offset", default: "0" },
        ],
      },
      {
        id: "delete-outlet-articles",
        method: "DELETE",
        path: "/articles/outlet/{outlet_name}",
        description: "Delete all articles for a given outlet",
        params: [{ name: "outlet_name", in: "path", type: "string", description: "Outlet name" }],
      },
      {
        id: "delete-article",
        method: "DELETE",
        path: "/articles/{article_id}",
        description: "Delete a single article by ID",
        params: [{ name: "article_id", in: "path", type: "string", description: "Article ID" }],
      },
    ],
  },
  {
    name: "Outlets",
    tag: "outlets",
    endpoints: [
      {
        id: "outlets-registry",
        method: "GET",
        path: "/outlets/registry",
        description: "Get outlet scraper registry metadata",
      },
    ],
  },
  {
    name: "Bias",
    tag: "bias",
    endpoints: [
      { id: "bias-health", method: "GET", path: "/bias/health", description: "Bias service health check" },
      { id: "bias-run-status", method: "GET", path: "/bias/run-status", description: "Get bias analysis run status" },
      {
        id: "bias-embedding-status",
        method: "GET",
        path: "/bias/embedding-status",
        description: "Get embedding count and last update timestamp",
      },
      {
        id: "bias-articles",
        method: "GET",
        path: "/bias/articles",
        description: "List bias-scored articles",
        params: [
          { name: "outlet", in: "query", type: "string", description: "Filter by outlet" },
          { name: "topic_key", in: "query", type: "string", description: "Filter by topic key" },
          { name: "limit", in: "query", type: "number", description: "Max results", default: "20" },
          { name: "offset", in: "query", type: "number", description: "Offset", default: "0" },
        ],
      },
      {
        id: "bias-article-by-id",
        method: "GET",
        path: "/bias/articles/{article_id}",
        description: "Get bias scores for a single article",
        params: [{ name: "article_id", in: "path", type: "string", description: "Article ID" }],
      },
      { id: "bias-topics", method: "GET", path: "/bias/topics", description: "List all topics in the bias analysis" },
      {
        id: "bias-logs",
        method: "GET",
        path: "/bias/logs",
        description: "List bias analysis run logs",
        params: [{ name: "limit", in: "query", type: "number", description: "Max results", default: "10" }],
      },
      { id: "bias-profiles", method: "GET", path: "/bias/profiles", description: "Get all outlet bias profiles" },
      {
        id: "bias-outlet-profile",
        method: "GET",
        path: "/bias/outlets/{outlet_name}",
        description: "Get bias profile for a specific outlet",
        params: [{ name: "outlet_name", in: "path", type: "string", description: "Outlet name" }],
      },
      {
        id: "bias-outlet-trend",
        method: "GET",
        path: "/bias/outlets/{outlet_name}/trend",
        description: "Get bias trend over time for an outlet",
        params: [
          { name: "outlet_name", in: "path", type: "string", description: "Outlet name" },
          { name: "days_back", in: "query", type: "number", description: "Days back", default: "30" },
        ],
      },
      {
        id: "bias-trends",
        method: "GET",
        path: "/bias/trends",
        description: "Get bias trends for all outlets",
        params: [{ name: "days_back", in: "query", type: "number", description: "Days back", default: "30" }],
      },
      {
        id: "bias-scores",
        method: "GET",
        path: "/bias/scores",
        description: "Get raw bias scores with optional filters",
        params: [
          { name: "outlet", in: "query", type: "string", description: "Filter by outlet" },
          { name: "topic_key", in: "query", type: "string", description: "Filter by topic key" },
          { name: "run_id", in: "query", type: "string", description: "Filter by run ID" },
        ],
      },
      {
        id: "bias-omitted-topics",
        method: "GET",
        path: "/bias/omitted-topics",
        description: "Get topics with missing coverage across outlets",
      },
      {
        id: "bias-omissions",
        method: "GET",
        path: "/bias/omissions",
        description: "Get omission bias scores per outlet",
      },
      { id: "bias-run", method: "POST", path: "/bias/run", description: "Trigger a full bias analysis run" },
      { id: "bias-run-fast", method: "POST", path: "/bias/run-fast", description: "Trigger a fast bias analysis run" },
      {
        id: "bias-run-clusters",
        method: "POST",
        path: "/bias/run-with-clusters",
        description: "Trigger bias analysis with externally supplied clusters",
      },
      {
        id: "bias-compare",
        method: "POST",
        path: "/bias/compare",
        description: "Compare bias profiles across selected outlets",
      },
      {
        id: "bias-cleanup",
        method: "DELETE",
        path: "/bias/cleanup",
        description: "Delete all bias results and embeddings",
      },
      {
        id: "bias-cleanup-results",
        method: "DELETE",
        path: "/bias/cleanup-results",
        description: "Delete bias results but keep embeddings",
      },
    ],
  },
];

const METHOD_BADGE: Record<string, string> = {
  GET: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  POST: "bg-blue-500/15 text-blue-400 border border-blue-500/30",
  DELETE: "bg-rose-500/15 text-rose-400 border border-rose-500/30",
};

const GROUP_TEXT: Record<string, string> = {
  System: "text-blue-400",
  Articles: "text-emerald-400",
  Outlets: "text-violet-400",
  Bias: "text-amber-400",
};

function syntaxHighlightJson(jsonStr: string): string {
  const safe = jsonStr
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  return safe.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          return `<span style="color:#7dd3fc">${match}</span>`;
        }
        return `<span style="color:#86efac">${match}</span>`;
      }
      if (/true|false/.test(match)) return `<span style="color:#c084fc">${match}</span>`;
      if (/null/.test(match)) return `<span style="color:#94a3b8">${match}</span>`;
      return `<span style="color:#fcd34d">${match}</span>`;
    }
  );
}

export default function ApiExplorerPage() {
  const [selected, setSelected] = useState<Endpoint | null>(null);
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [response, setResponse] = useState<{ data: unknown; status: number; time: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    new Set(GROUPS.map((g) => g.name))
  );

  const selectEndpoint = useCallback((ep: Endpoint) => {
    setSelected(ep);
    const defaults: Record<string, string> = {};
    ep.params?.forEach((p) => {
      if (p.default) defaults[p.name] = p.default;
    });
    setParamValues(defaults);
    setResponse(null);
    setFetchError(null);
  }, []);

  const buildUrl = useCallback(
    (ep: Endpoint, values: Record<string, string>) => {
      let path = ep.path;
      ep.params
        ?.filter((p) => p.in === "path")
        .forEach((p) => {
          if (values[p.name]) path = path.replace(`{${p.name}}`, encodeURIComponent(values[p.name]));
        });
      const qs = ep.params
        ?.filter((p) => p.in === "query" && values[p.name])
        .map((p) => `${p.name}=${encodeURIComponent(values[p.name])}`)
        .join("&");
      return `${BASE_URL}${path}${qs ? `?${qs}` : ""}`;
    },
    []
  );

  const handleFetch = async () => {
    if (!selected || selected.method !== "GET") return;
    setLoading(true);
    setFetchError(null);
    setResponse(null);
    const url = buildUrl(selected, paramValues);
    const t0 = Date.now();
    try {
      const res = await fetch(url, { cache: "no-store" });
      const data = await res.json().catch(() => null);
      setResponse({ data, status: res.status, time: Date.now() - t0 });
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  const copyJson = () => {
    if (!response) return;
    navigator.clipboard.writeText(JSON.stringify(response.data, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const toggleGroup = (name: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  const totalEndpoints = GROUPS.reduce((n, g) => n + g.endpoints.length, 0);
  const getCount = GROUPS.reduce((n, g) => n + g.endpoints.filter((e) => e.method === "GET").length, 0);

  const url = selected ? buildUrl(selected, paramValues) : "";
  const jsonStr = response ? JSON.stringify(response.data, null, 2) : null;

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 pb-20 transition-colors duration-200">
      {/* Page header */}
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 py-8 transition-colors duration-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-blue-600 flex items-center justify-center shadow">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l-3 3 3 3M16 9l3 3-3 3M12 5l-2 14" />
                </svg>
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
                  Exposed API
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  Base URL:{" "}
                  <code className="text-xs bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded font-mono text-indigo-600 dark:text-indigo-400">
                    {BASE_URL}
                  </code>
                </p>
              </div>
            </div>
            <div className="hidden sm:flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400">
              <span>
                <span className="font-semibold text-gray-700 dark:text-gray-200">{totalEndpoints}</span> endpoints
              </span>
              <span>
                <span className="font-semibold text-emerald-500">{getCount}</span> fetchable
              </span>
            </div>
          </div>
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-6">
        <div className="flex gap-5 items-start">
          {/* Left: endpoint list */}
          <div className="w-64 shrink-0 space-y-2 sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto pr-1">
            {GROUPS.map((group) => {
              const isExpanded = expandedGroups.has(group.name);
              return (
                <div
                  key={group.name}
                  className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden"
                >
                  <button
                    onClick={() => toggleGroup(group.name)}
                    className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <span className={`text-[11px] font-bold uppercase tracking-widest ${GROUP_TEXT[group.name]}`}>
                        {group.name}
                      </span>
                      <span className="text-[10px] text-gray-400 font-mono">/{group.tag}</span>
                    </div>
                    <svg
                      className={`w-3.5 h-3.5 text-gray-400 transition-transform shrink-0 ${isExpanded ? "rotate-180" : ""}`}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>

                  {isExpanded && (
                    <div className="border-t border-gray-100 dark:border-gray-800 divide-y divide-gray-100 dark:divide-gray-800/50">
                      {group.endpoints.map((ep) => {
                        const isActive = selected?.id === ep.id;
                        return (
                          <button
                            key={ep.id}
                            onClick={() => selectEndpoint(ep)}
                            className={`w-full text-left px-3 py-2 flex items-start gap-2 transition-colors ${
                              isActive
                                ? "bg-indigo-50 dark:bg-indigo-950/50"
                                : "hover:bg-gray-50 dark:hover:bg-gray-800/30"
                            }`}
                          >
                            <span
                              className={`mt-0.5 shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded font-mono leading-tight ${METHOD_BADGE[ep.method]}`}
                            >
                              {ep.method}
                            </span>
                            <span
                              className={`text-[11px] font-mono leading-relaxed break-all ${
                                isActive
                                  ? "text-indigo-600 dark:text-indigo-300"
                                  : "text-gray-500 dark:text-gray-400"
                              }`}
                            >
                              {ep.path}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Right: detail + response */}
          <div className="flex-1 min-w-0">
            {!selected ? (
              <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 flex flex-col items-center justify-center py-32 text-center gap-3">
                <svg
                  className="w-10 h-10 text-gray-200 dark:text-gray-800"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 9l-3 3 3 3M16 9l3 3-3 3M12 5l-2 14" />
                </svg>
                <p className="text-sm text-gray-400 dark:text-gray-600">Select an endpoint to get started</p>
              </div>
            ) : (
              <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden">
                {/* Endpoint header */}
                <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800 flex items-start gap-3">
                  <span
                    className={`mt-0.5 shrink-0 text-xs font-bold px-2 py-1 rounded font-mono ${METHOD_BADGE[selected.method]}`}
                  >
                    {selected.method}
                  </span>
                  <div>
                    <code className="text-sm font-mono text-gray-900 dark:text-white">{selected.path}</code>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{selected.description}</p>
                  </div>
                </div>

                {/* Parameters */}
                {selected.params && selected.params.length > 0 && (
                  <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800">
                    <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-3">
                      Parameters
                    </p>
                    <div className="space-y-3">
                      {selected.params.map((p) => (
                        <div key={p.name} className="flex items-center gap-3">
                          <div className="w-40 shrink-0">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="text-xs font-mono font-medium text-gray-700 dark:text-gray-300">
                                {p.name}
                              </span>
                              <span
                                className={`text-[10px] px-1 rounded border ${
                                  p.in === "path"
                                    ? "text-rose-400 border-rose-400/30 bg-rose-400/10"
                                    : "text-sky-400 border-sky-400/30 bg-sky-400/10"
                                }`}
                              >
                                {p.in}
                              </span>
                            </div>
                            <p className="text-[11px] text-gray-400 mt-0.5">{p.description}</p>
                          </div>
                          <input
                            type={p.type === "number" ? "number" : "text"}
                            value={paramValues[p.name] ?? ""}
                            placeholder={p.placeholder ?? p.default ?? ""}
                            onChange={(e) =>
                              setParamValues((prev) => ({ ...prev, [p.name]: e.target.value }))
                            }
                            className="flex-1 px-3 py-1.5 text-sm font-mono rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* URL preview + fetch button */}
                <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800">
                  <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">
                    Request URL
                  </p>
                  <div className="flex items-center gap-3">
                    <code className="flex-1 min-w-0 text-xs font-mono bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2 text-gray-700 dark:text-gray-300 break-all">
                      {url}
                    </code>
                    {selected.method === "GET" ? (
                      <button
                        onClick={handleFetch}
                        disabled={loading}
                        className="shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
                      >
                        {loading ? (
                          <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                          </svg>
                        ) : (
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                        )}
                        {loading ? "Fetching…" : "Fetch"}
                      </button>
                    ) : (
                      <span className="shrink-0 text-xs text-gray-400 dark:text-gray-500 italic whitespace-nowrap">
                        {selected.method} — read-only explorer
                      </span>
                    )}
                  </div>
                </div>

                {/* Response */}
                {(response !== null || fetchError) && (
                  <div className="px-5 py-4">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-3">
                        <p className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                          Response
                        </p>
                        {response && (
                          <>
                            <span
                              className={`text-xs font-bold px-2 py-0.5 rounded ${
                                response.status >= 200 && response.status < 300
                                  ? "bg-emerald-500/15 text-emerald-400"
                                  : "bg-rose-500/15 text-rose-400"
                              }`}
                            >
                              {response.status}
                            </span>
                            <span className="text-xs text-gray-400">{response.time}ms</span>
                          </>
                        )}
                      </div>
                      {jsonStr && (
                        <button
                          onClick={copyJson}
                          className="text-xs text-gray-400 hover:text-gray-200 transition-colors flex items-center gap-1.5"
                        >
                          {copied ? (
                            <>
                              <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                              </svg>
                              <span className="text-emerald-400">Copied</span>
                            </>
                          ) : (
                            <>
                              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                  d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                              </svg>
                              <span>Copy JSON</span>
                            </>
                          )}
                        </button>
                      )}
                    </div>

                    {fetchError ? (
                      <div className="rounded-lg bg-rose-500/10 border border-rose-500/20 px-4 py-3 text-sm text-rose-400 font-mono">
                        {fetchError}
                      </div>
                    ) : jsonStr ? (
                      <pre
                        className="rounded-lg bg-gray-950 border border-gray-800 p-4 text-xs font-mono overflow-auto max-h-[520px] leading-relaxed"
                        dangerouslySetInnerHTML={{ __html: syntaxHighlightJson(jsonStr) }}
                      />
                    ) : null}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
