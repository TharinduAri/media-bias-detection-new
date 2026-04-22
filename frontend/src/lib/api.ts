const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface SentimentData {
  id: number;
  outlet: string;
  year_month: string;
  entity: string;
  label: string;
  avg_sentiment: number;
  total_mentions: number;
  article_count: number;
  created_at: string;
}

export interface CoverageData {
  id: number;
  outlet: string;
  entity: string;
  label: string;
  total_mentions: number;
  article_count: number;
  created_at: string;
}

export interface OmissionsData {
  id: number;
  entity: string;
  covered_mostly_by: string;
  max_mentions: number;
  omitted_by: string;
  created_at: string;
}

export interface ExplainabilityData {
  id: number;
  outlet: string;
  year_month: string;
  date: string;
  entity: string;
  label: string;
  sentiment: number;
  mention_count: number;
  article_url: string;
  example_sentence: string;
  example_sentence_score: number;
  abs_sentiment: number;
  created_at: string;
}

export interface OutletData {
  id: number;
  name: string;
  url: string;
  rss_feeds: string[] | null;
  created_at: string;
}

export interface CreateOutletPayload {
  name: string;
  url: string;
  rss_feeds: string[];
}

export async function fetchSentiment(): Promise<SentimentData[]> {
  const res = await fetch(`${API_BASE_URL}/sentiment/`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch sentiment data");
  return res.json();
}

export async function fetchCoverage(): Promise<CoverageData[]> {
  const res = await fetch(`${API_BASE_URL}/coverage/`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch coverage data");
  return res.json();
}

export async function fetchOmissions(): Promise<OmissionsData[]> {
  const res = await fetch(`${API_BASE_URL}/omissions/`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch omissions data");
  return res.json();
}

export async function fetchExplainability(): Promise<ExplainabilityData[]> {
  const res = await fetch(`${API_BASE_URL}/explainability/`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch explainability data");
  return res.json();
}

export async function triggerCleanScrape(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/system/clean-and-rescrape`, {
    method: 'POST',
    cache: 'no-store',
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to trigger clean and rescrape");
  }
  return res.json();
}

export async function triggerCleanDb(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/system/clean-db`, {
    method: 'POST',
    cache: 'no-store',
  });
  if (!res.ok) throw new Error("Failed to clean database");
  return res.json();
}

export async function fetchOutlets(): Promise<OutletData[]> {
  const res = await fetch(`${API_BASE_URL}/outlets/`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch outlets");
  return res.json();
}

export async function createOutlet(payload: CreateOutletPayload): Promise<OutletData> {
  const res = await fetch(`${API_BASE_URL}/outlets/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    cache: 'no-store',
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to create outlet");
  }

  return res.json();
}

export async function deleteOutlet(outletId: number): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/outlets/${outletId}`, {
    method: 'DELETE',
    cache: 'no-store',
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to delete outlet");
  }

  return res.json();
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

export async function fetchArticleOutlets(): Promise<string[]> {
  const res = await fetch(`${API_BASE_URL}/articles/outlets`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch article outlets");
  return res.json();
}

export async function fetchArticles(outlet?: string, limit = 50, offset = 0): Promise<ArticleData[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (outlet) params.set("outlet", outlet);
  const res = await fetch(`${API_BASE_URL}/articles/?${params}`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch articles");
  return res.json();
}

export async function deleteArticle(articleId: number): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/articles/${articleId}`, {
    method: 'DELETE',
    cache: 'no-store',
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to delete article");
  }

  return res.json();
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

export async function fetchPipelineStatus(): Promise<PipelineStatus> {
  const res = await fetch(`${API_BASE_URL}/system/pipeline-status`, { cache: 'no-store' });
  if (!res.ok) throw new Error("Failed to fetch pipeline status");
  return res.json();
}
