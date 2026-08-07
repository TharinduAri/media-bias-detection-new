const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000/api/v1";

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
  analysis_type: AnalysisType;
  error: string | null;
  log_lines: string[];
  created_at: string | null;
}

export interface ArticleBiasWithArticleData {
  id: number;
  article_id: number;
  outlet: string;
  analysis_type: AnalysisType;
  title: string;
  date: string;
  url: string;
  topic_key: string;
  topic_label?: string;
  sentiment_label: string;
  sentiment_score: number;
  sentiment_confidence: number;
  entity_sentiments?: EntitySentimentData[] | null;
  sentiment_bias: number;
  group_sentiment_mean: number;
  coverage_majority: boolean;
  coverage_present: boolean;
  emphasis_bias?: number | null;
  dominant_outlet?: boolean;
  emphasis_length_bias?: number | null;
  emphasis_sentence_bias?: number | null;
  emphasis_entity_bias?: number | null;
  political_side_bias?: number | null;
  government_sentiment?: number | null;
  opposition_sentiment?: number | null;
  government_target_count: number;
  opposition_target_count: number;
  political_actor_count: number;
  created_at: string;
}

export interface EntitySentimentData {
  target: string;
  entity_label?: string | null;
  label: "negative" | "neutral" | "positive" | string;
  score: number;
  confidence: number;
  negative: number;
  neutral: number;
  positive: number;
  mentions: number;
  title_mention: boolean;
  canonical_actor?: string | null;
  political_actor_type?: string | null;
  political_side?: "government" | "opposition" | string | null;
  political_side_confidence?: number | null;
  political_party?: string | null;
  political_role?: string | null;
  matched_actor_alias?: string | null;
}

export interface ArticleBiasEvidenceData {
  id: number;
  article_id: number;
  outlet: string;
  analysis_type: AnalysisType;
  topic_key: string;
  topic_label?: string | null;
  target_entity: string;
  entity_label?: string | null;
  sentence: string;
  sentence_index: number;
  is_title: boolean;
  sentiment_label: "negative" | "neutral" | "positive" | string;
  sentiment_score: number;
  sentiment_confidence: number;
  negative_prob: number;
  neutral_prob: number;
  positive_prob: number;
  canonical_actor?: string | null;
  political_actor_type?: string | null;
  political_side?: "government" | "opposition" | string | null;
  political_side_confidence?: number | null;
  created_at: string;
}

export interface OutletBiasProfileData {
  id: number;
  outlet: string;
  analysis_type: AnalysisType;
  sentiment_bias_avg: number;
  sentiment_score_avg: number;
  articles_scored: number;
  topics_covered: number;
  topics_considered: number;
  coverage_missing_majority: number;
  coverage_bias_rate: number;
  missed_topics: string[] | null;
  emphasis_bias_avg?: number | null;
  political_side_bias_avg?: number | null;
  government_sentiment_avg?: number | null;
  opposition_sentiment_avg?: number | null;
  political_actor_count: number;
  bsi_score?: number | null;
  source_trust_score?: number | null;
  misinformation_risk_score?: number | null;
  bsi_confidence_low?: number | null;
  bsi_confidence_high?: number | null;
  article_count_per_topic_avg?: number | null;
  coverage_bias_rate_soft?: number | null;
  updated_at: string;
}

export interface OutletTopicBSIData {
  id: number;
  run_id: number;
  outlet: string;
  analysis_type: AnalysisType;
  topic_key: string;
  topic_label?: string | null;
  sentiment_bias_avg: number;
  emphasis_bias_avg?: number | null;
  political_side_bias_avg?: number | null;
  coverage_present: boolean;
  article_count: number;
  bsi_score: number;
  snapshot_date: string;
}

export interface BiasScoresData {
  last_run_at: string | null;
  scores: OutletTopicBSIData[];
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
  analysis_type: AnalysisType;
  processed_articles: number;
  topics_processed: number;
  profiles_updated: number;
  embeddings_saved: number;
  embedding_provider: "local" | "gemini" | string;
  embedding_model: string;
  cluster_source: "internal" | "external" | string;
  clusters_received?: number | null;
}

export type AnalysisType = "general" | "financial";

export interface ManualArticleBiasInput {
  outlet: string;
  title: string;
  text: string;
  url?: string;
  date?: string;
}

export interface ManualArticlePeerData {
  article_id: number;
  outlet: string;
  title: string;
  url: string;
  similarity: number;
  sentiment_score: number;
  sentiment_label: string;
}

export interface ManualArticleBiasData {
  article: ArticleData;
  sentiment_label: string;
  sentiment_score: number;
  sentiment_confidence: number;
  target_pair_count: number;
  entity_sentiments: EntitySentimentData[];
  sentence_evidence: Array<{
    target: string;
    entity_label?: string | null;
    sentence: string;
    sentence_index: number;
    is_title: boolean;
    label: string;
    score: number;
    confidence: number;
    negative: number;
    neutral: number;
    positive: number;
    canonical_actor?: string | null;
    political_actor_type?: string | null;
    political_side?: "government" | "opposition" | string | null;
    political_side_confidence?: number | null;
  }>;
  relative_sentiment_bias: number | null;
  political_side_bias: number | null;
  government_sentiment: number | null;
  opposition_sentiment: number | null;
  government_target_count: number;
  opposition_target_count: number;
  political_actor_count: number;
  peer_sentiment_mean: number | null;
  peer_count: number;
  peer_outlet_count: number;
  topic_key: string | null;
  topic_label: string | null;
  topic_similarity: number | null;
  emphasis_bias: number | null;
  bias_signal: number;
  bias_label: string;
  saved_article_bias_score: boolean;
  outlet_profile: OutletBiasProfileData | null;
  matched_articles: ManualArticlePeerData[];
  notes: string[];
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

export const FINANCIAL_OUTLETS = ["Economy Next", "LBO"];

export function outletsForAnalysis(outlets: string[], analysisType: AnalysisType): string[] {
  const financial = new Set(FINANCIAL_OUTLETS);
  return analysisType === "financial"
    ? outlets.filter((outlet) => financial.has(outlet))
    : outlets.filter((outlet) => !financial.has(outlet));
}

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

export async function fetchBiasLogs(limit = 10, analysisType?: AnalysisType): Promise<BiasRunLogData[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (analysisType) params.set("analysis_type", analysisType);
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

export interface EmbeddingStatusData {
  count: number;
  last_computed_at: string | null;
}

export async function fetchEmbeddingStatus(): Promise<EmbeddingStatusData> {
  const res = await fetch(`${API_BASE_URL}/bias/embedding-status`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch embedding status");
  return res.json();
}

export async function triggerBiasAnalysisFast(): Promise<BiasRunResponse> {
  const res = await fetch(`${API_BASE_URL}/bias/run-fast`, {
    method: "POST",
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to run fast bias analysis");
  }
  return res.json();
}

export async function triggerFinancialBiasAnalysisFast(): Promise<BiasRunResponse> {
  const res = await fetch(`${API_BASE_URL}/bias/run-financial-fast`, {
    method: "POST",
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to run fast financial analysis");
  }
  return res.json();
}

export async function triggerCleanupKeepEmbeddings(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/bias/cleanup-results`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to clear bias results");
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

export async function triggerFinancialBiasAnalysis(): Promise<BiasRunResponse> {
  const res = await fetch(`${API_BASE_URL}/bias/run-financial`, {
    method: "POST",
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to run financial analysis");
  }

  return res.json();
}

export async function createManualArticleBiasReading(
  input: ManualArticleBiasInput
): Promise<ManualArticleBiasData> {
  const res = await fetch(`${API_BASE_URL}/bias/manual-article`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to analyze article");
  }

  return res.json();
}

export async function fetchBiasProfile(
  outletName: string,
  analysisType: AnalysisType = "general"
): Promise<OutletBiasProfileData> {
  const params = new URLSearchParams({ analysis_type: analysisType });
  const res = await fetch(`${API_BASE_URL}/bias/outlets/${encodeURIComponent(outletName)}?${params}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to fetch outlet bias profile");
  }
  return res.json();
}

export async function compareBiasProfiles(
  outlets: string[],
  analysisType: AnalysisType = "general"
): Promise<OutletBiasProfileData[]> {
  const params = new URLSearchParams({ analysis_type: analysisType });
  const res = await fetch(`${API_BASE_URL}/bias/compare?${params}`, {
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

export async function fetchArticleBiasEvidence(
  articleId: number,
  topicKey?: string,
  analysisType: AnalysisType = "general"
): Promise<ArticleBiasEvidenceData[]> {
  const params = new URLSearchParams({ analysis_type: analysisType });
  if (topicKey) params.set("topic_key", topicKey);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${API_BASE_URL}/bias/articles/${articleId}/evidence${suffix}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to fetch article bias evidence");
  }
  return res.json();
}

export async function fetchBiasArticles(
  limit = 50,
  offset = 0,
  outlet?: string,
  topic_key?: string,
  analysisType: AnalysisType = "general"
): Promise<ArticleBiasWithArticleData[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
    analysis_type: analysisType,
  });
  if (outlet) params.set("outlet", outlet);
  if (topic_key) params.set("topic_key", topic_key);
  const res = await fetch(`${API_BASE_URL}/bias/articles?${params.toString()}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || "Failed to fetch bias articles");
  }
  return res.json();
}

export async function fetchBiasTopics(analysisType: AnalysisType = "general"): Promise<TopicSummaryData[]> {
  const params = new URLSearchParams({ analysis_type: analysisType });
  const res = await fetch(`${API_BASE_URL}/bias/topics?${params}`, { cache: "no-store" });
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

export async function fetchBiasScores(opts?: {
  outlet?: string;
  topic_key?: string;
  run_id?: number;
  analysis_type?: AnalysisType;
}): Promise<BiasScoresData> {
  const params = new URLSearchParams();
  params.set("analysis_type", opts?.analysis_type ?? "general");
  if (opts?.outlet) params.set("outlet", opts.outlet);
  if (opts?.topic_key) params.set("topic_key", opts.topic_key);
  if (opts?.run_id != null) params.set("run_id", String(opts.run_id));
  const res = await fetch(`${API_BASE_URL}/bias/scores?${params}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch bias scores");
  return res.json();
}

export async function fetchAllProfiles(analysisType: AnalysisType = "general"): Promise<AllProfilesData> {
  const params = new URLSearchParams({ analysis_type: analysisType });
  const res = await fetch(`${API_BASE_URL}/bias/profiles?${params}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch all profiles");
  return res.json();
}
