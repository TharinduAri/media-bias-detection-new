const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface OutletData {
  id: number;
  name: string;
  url: string;
  rss_feeds?: string[];
  created_at: string;
}

export interface CreateOutletPayload {
  name: string;
  url: string;
  rss_feeds?: string[];
}

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
  sentiment_label: string;
  sentiment_score: number;
  sentiment_confidence: number;
  sentiment_bias: number;
  group_sentiment_mean: number;
  coverage_majority: boolean;
  coverage_present: boolean;
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
  sentiment_label: string;
  sentiment_score: number;
  sentiment_confidence: number;
  sentiment_bias: number;
  group_sentiment_mean: number;
  coverage_majority: boolean;
  coverage_present: boolean;
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
  updated_at: string;
}

export interface TopicSummaryData {
  topic_key: string;
  article_count: number;
}

export interface BiasRunResponse {
  status: string;
  message: string;
  processed_articles: number;
  topics_processed: number;
  profiles_updated: number;
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

export async function fetchOutlets(): Promise<OutletData[]> {
  const res = await fetch(`${API_BASE_URL}/outlets/`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch outlets");
  return res.json();
}

export async function fetchOutletRegistry(): Promise<OutletRegistryEntry[]> {
  const res = await fetch(`${API_BASE_URL}/outlets/registry`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch outlet registry");
  return res.json();
}

export async function createOutlet(payload: CreateOutletPayload): Promise<OutletData> {
  const res = await fetch(`${API_BASE_URL}/outlets/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to create outlet");
  }

  return res.json();
}

export async function deleteOutlet(outletId: number): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/outlets/${outletId}`, {
    method: "DELETE",
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to delete outlet");
  }

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
