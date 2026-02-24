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
