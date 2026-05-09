const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface OutletRegistryEntry {
  domain: string;
  scraper_class: string;
  discovery: string;
  extraction: string;
  notes: string;
}

export interface ArticleData {
  id: number;
  outlet: string;
  date: string;
  title: string;
  url: string;
  text: string | null;
  clean_text: string | null;
  created_at: string;
}

export interface ArticleOutletCountData {
  outlet: string;
  total_articles: number;
}

export interface PipelineStage {
  key: string;
  label: string;
}

export interface PipelineStatus {
  running: boolean;
  status: "idle" | "running" | "done" | "error";
  current_stage_index: number;
  stages: PipelineStage[];
  logs: string[];
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface ScrapeRunLogData {
  id: number;
  started_at: string;
  finished_at: string;
  status: "done" | "error" | string;
  error: string | null;
  log_lines: string[];
  created_at: string | null;
}

export interface BiasRunLogData {
  id: number;
  started_at: string;
  finished_at: string;
  status: "done" | "error" | string;
  error: string | null;
  log_lines: string[];
  created_at: string | null;
}

export interface ArticleBiasScoreData {
  id: number;
  article_id: number;
  outlet: string;
  topic_key: string;
  topic_label?: string;
  sentiment_label: string;
  sentiment_score: number;
  sentiment_confidence: number;
  sentiment_bias: number;
  group_sentiment_mean: number;
  coverage_majority: boolean;
  coverage_present: boolean;
  emphasis_bias?: number | null;
  created_at: string;
}

export interface ArticleBiasWithArticleData {
  id: number;
  article_id: number;
  outlet: string;
  title: string;
  date: string;
  url: string;
  topic_key: string;
  topic_label?: string;
  sentiment_label: string;
  sentiment_score: number;
  sentiment_confidence: number;
  sentiment_bias: number;
  group_sentiment_mean: number;
  coverage_majority: boolean;
  coverage_present: boolean;
  emphasis_bias?: number | null;
  created_at: string;
}

export interface OutletBiasProfileData {
  id: number;
  outlet: string;
  sentiment_bias_avg: number;
  sentiment_score_avg: number;
  articles_scored: number;
  topics_covered: number;
  topics_considered: number;
  coverage_missing_majority: number;
  coverage_bias_rate: number;
  missed_topics: string[] | null;
  emphasis_bias_avg?: number | null;
  bsi_score?: number | null;
  updated_at: string;
}

export interface OutletBiasSnapshotData {
  id: number;
  outlet: string;
  run_id: number;
  snapshot_date: string;
  sentiment_bias_avg: number;
  sentiment_score_avg: number;
  articles_scored: number;
  topics_covered: number;
  topics_considered: number;
  coverage_missing_majority: number;
  coverage_bias_rate: number;
  missed_topics: string[] | null;
  emphasis_bias_avg?: number | null;
  bsi_score?: number | null;
  omission_score?: number | null;
  systematic_omission?: boolean | null;
  baseline_used_runs?: number | null;
}

export interface OutletTrendData {
  outlet: string;
  snapshots: OutletBiasSnapshotData[];
}

export interface AllTrendsData {
  last_run_at: string | null;
  trends: OutletTrendData[];
}

export interface OutletTopicBSIData {
  id: number;
  run_id: number;
  outlet: string;
  topic_key: string;
  topic_label?: string | null;
  sentiment_bias_avg: number;
  emphasis_bias_avg?: number | null;
  coverage_present: boolean;
  article_count: number;
  bsi_score: number;
  snapshot_date: string;
}

export interface BiasScoresData {
  last_run_at: string | null;
  scores: OutletTopicBSIData[];
}

export interface OutletOmissionData {
  outlet: string;
  current_coverage_bias_rate: number;
  current_bsi_score?: number | null;
  omission_score?: number | null;
  systematic_omission?: boolean | null;
  baseline_used_runs?: number | null;
  last_run_at?: string | null;
}

export interface AllOmissionsData {
  last_run_at: string | null;
  omissions: OutletOmissionData[];
}

export interface AllProfilesData {
  last_run_at: string | null;
  profiles: OutletBiasProfileData[];
}

export interface TopicSummaryData {
  topic_key: string;
  topic_label?: string;
  article_count: number;
}

export interface BiasRunResponse {
  status: string;
  message: string;
  processed_articles: number;
  topics_processed: number;
  profiles_updated: number;
  embeddings_saved: number;
  embedding_provider: "local" | "gemini" | string;
  embedding_model: string;
  cluster_source: "internal" | "external" | string;
  clusters_received?: number | null;
}

export interface BiasTopicClusterInput {
  topic_key: string;
  topic_label?: string;
  article_ids: number[];
}

export const OUTLET_NAMES: string[] = [
  "Ada Derana",
  "Ceylon Today",
  "Daily FT",
  "Economy Next",
  "LBO",
  "Newsfirst",
  "Daily Mirror",
  "The Morning",
  "Daily News",
  "The Island",
  "Sunday Observer",
  "Colombo Gazette",
  "News LK",
];

export async function triggerScrape(
  outlets?: string[]
): Promise<{ status: string; message: string; outlets: string[] }> {
  const res = await fetch(`${API_BASE_URL}/system/scrape`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outlets: outlets ?? [] }),
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to start scraper");
  }
  return res.json();
}

export async function triggerCleanScrape(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/system/clean-and-rescrape`, {
    method: "POST",
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to trigger clean and scrape");
  }
  return res.json();
}

export async function triggerCleanDb(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/system/clean-db`, {
    method: "POST",
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to clean article table");
  }
  return res.json();
}

export async function fetchPipelineStatus(): Promise<PipelineStatus> {
  const res = await fetch(`${API_BASE_URL}/system/pipeline-status`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch scraper status");
  return res.json();
}

export async function fetchScrapeLogs(limit = 10): Promise<ScrapeRunLogData[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${API_BASE_URL}/system/scrape-logs?${params}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch scrape logs");
  return res.json();
}

export async function fetchBiasLogs(limit = 10): Promise<BiasRunLogData[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${API_BASE_URL}/bias/logs?${params}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch bias logs");
  return res.json();
}

export async function fetchOutletRegistry(): Promise<OutletRegistryEntry[]> {
  const res = await fetch(`${API_BASE_URL}/outlets/registry`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch outlet registry");
  return res.json();
}

export async function fetchArticleOutlets(): Promise<string[]> {
  const res = await fetch(`${API_BASE_URL}/articles/outlets`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch article outlets");
  return res.json();
}

export async function fetchArticleOutletCounts(): Promise<ArticleOutletCountData[]> {
  const res = await fetch(`${API_BASE_URL}/articles/outlet-counts`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch article outlet counts");
  return res.json();
}

export async function fetchArticles(outlet?: string, limit = 50, offset = 0): Promise<ArticleData[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (outlet) params.set("outlet", outlet);
  const res = await fetch(`${API_BASE_URL}/articles/?${params}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch articles");
  return res.json();
}

export async function deleteOutletArticles(outlet: string): Promise<{ status: string; message: string; deleted: number }> {
  const res = await fetch(`${API_BASE_URL}/articles/outlet/${encodeURIComponent(outlet)}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to delete outlet articles");
  }
  return res.json();
}

export async function deleteArticle(articleId: number): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/articles/${articleId}`, {
    method: "DELETE",
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to delete article");
  }

  return res.json();
}

export interface BiasRunStatus {
  running: boolean;
  logs: string[];
  status: "idle" | "running" | "done" | "error";
}

export async function fetchBiasRunStatus(): Promise<BiasRunStatus> {
  const res = await fetch(`${API_BASE_URL}/bias/run-status`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch run status");
  return res.json();
}

export async function triggerBiasAnalysis(): Promise<BiasRunResponse> {
  const res = await fetch(`${API_BASE_URL}/bias/run`, {
    method: "POST",
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to run bias analysis");
  }

  return res.json();
}

export async function triggerBiasAnalysisWithClusters(
  clusters: BiasTopicClusterInput[]
): Promise<BiasRunResponse> {
  const res = await fetch(`${API_BASE_URL}/bias/run-with-clusters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ clusters }),
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to run bias analysis with external clusters");
  }

  return res.json();
}

export async function fetchBiasProfile(outletName: string): Promise<OutletBiasProfileData> {
  const res = await fetch(`${API_BASE_URL}/bias/outlets/${encodeURIComponent(outletName)}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to fetch outlet bias profile");
  }
  return res.json();
}

export async function compareBiasProfiles(outlets: string[]): Promise<OutletBiasProfileData[]> {
  const res = await fetch(`${API_BASE_URL}/bias/compare`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ outlets }),
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to compare bias profiles");
  }
  return res.json();
}

export async function fetchArticleBiasScore(articleId: number): Promise<ArticleBiasScoreData> {
  const res = await fetch(`${API_BASE_URL}/bias/articles/${articleId}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to fetch article bias score");
  }
  return res.json();
}

export async function fetchBiasArticles(
  limit = 50,
  offset = 0,
  outlet?: string,
  topic_key?: string
): Promise<ArticleBiasWithArticleData[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (outlet) params.set("outlet", outlet);
  if (topic_key) params.set("topic_key", topic_key);
  const res = await fetch(`${API_BASE_URL}/bias/articles?${params.toString()}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to fetch bias articles");
  }
  return res.json();
}

export async function fetchBiasTopics(): Promise<TopicSummaryData[]> {
  const res = await fetch(`${API_BASE_URL}/bias/topics`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch bias topics");
  return res.json();
}

export async function triggerBiasCleanup(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/bias/cleanup`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to clear bias analysis data");
  }
  return res.json();
}

export async function fetchOutletTrend(
  outletName: string,
  daysBack = 90
): Promise<OutletBiasSnapshotData[]> {
  const params = new URLSearchParams({ days_back: String(daysBack) });
  const res = await fetch(
    `${API_BASE_URL}/bias/outlets/${encodeURIComponent(outletName)}/trend?${params}`,
    { cache: "no-store" }
  );
  if (!res.ok) throw new Error("Failed to fetch outlet trend");
  return res.json();
}

export async function fetchAllTrends(daysBack = 90): Promise<AllTrendsData> {
  const params = new URLSearchParams({ days_back: String(daysBack) });
  const res = await fetch(`${API_BASE_URL}/bias/trends?${params}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch all trends");
  return res.json();
}

export async function fetchBiasScores(opts?: {
  outlet?: string;
  topic_key?: string;
  run_id?: number;
}): Promise<BiasScoresData> {
  const params = new URLSearchParams();
  if (opts?.outlet) params.set("outlet", opts.outlet);
  if (opts?.topic_key) params.set("topic_key", opts.topic_key);
  if (opts?.run_id != null) params.set("run_id", String(opts.run_id));
  const res = await fetch(`${API_BASE_URL}/bias/scores?${params}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch bias scores");
  return res.json();
}

export async function fetchOmissions(): Promise<AllOmissionsData> {
  const res = await fetch(`${API_BASE_URL}/bias/omissions`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch omissions");
  return res.json();
}

export async function fetchAllProfiles(): Promise<AllProfilesData> {
  const res = await fetch(`${API_BASE_URL}/bias/profiles`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch all profiles");
  return res.json();
}
