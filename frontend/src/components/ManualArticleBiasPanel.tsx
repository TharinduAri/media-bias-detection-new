"use client";

import { FormEvent, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  FileText,
  Gauge,
  Loader2,
  Scale,
  Users,
} from "lucide-react";
import {
  createManualArticleBiasReading,
  ManualArticleBiasData,
} from "@/lib/api";

interface Props {
  outlets: string[];
}

function signed(value: number | null | undefined, digits = 3): string {
  if (value == null) return "n/a";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function percent(value: number | null | undefined): string {
  if (value == null) return "n/a";
  return `${Math.round(value * 100)}%`;
}

function sentimentTone(value: number | null | undefined): string {
  if (value == null) return "text-slate-500 dark:text-slate-400";
  if (value > 0.15) return "text-emerald-600 dark:text-emerald-400";
  if (value < -0.15) return "text-rose-600 dark:text-rose-400";
  return "text-slate-600 dark:text-slate-300";
}

function signalTone(value: number): string {
  if (value >= 0.7) return "text-rose-600 dark:text-rose-400";
  if (value >= 0.4) return "text-amber-600 dark:text-amber-400";
  if (value >= 0.2) return "text-blue-600 dark:text-blue-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function todayInputValue() {
  return new Date().toISOString().slice(0, 10);
}

export default function ManualArticleBiasPanel({ outlets }: Props) {
  const [outlet, setOutlet] = useState(outlets[0] ?? "");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [date, setDate] = useState(todayInputValue());
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ManualArticleBiasData | null>(null);

  const textLength = text.trim().length;
  const canSubmit = Boolean(outlet && title.trim().length >= 5 && textLength >= 100 && !loading);

  const relativeAvailable = result?.relative_sentiment_bias != null;
  const strongestTargets = useMemo(
    () => (result?.entity_sentiments ?? []).slice(0, 6),
    [result]
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;

    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payloadDate = date ? `${date}T12:00:00` : undefined;
      setResult(
        await createManualArticleBiasReading({
          outlet,
          title: title.trim(),
          text: text.trim(),
          url: url.trim() || undefined,
          date: payloadDate,
        })
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Article analysis failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-slate-100 dark:border-slate-800 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-base font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <FileText className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            Single Article Reading
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Paste one article, assign its outlet, and get target sentiment plus peer-relative bias when matches exist.
          </p>
        </div>
        {result && (
          <div className="inline-flex items-center gap-2 rounded-lg border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/30 px-3 py-2 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="h-4 w-4" />
            Article #{result.article.id} saved
          </div>
        )}
      </div>

      <div className="p-5 grid grid-cols-1 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)] gap-5">
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="space-y-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300">
              Outlet
              <select
                value={outlet}
                onChange={(e) => setOutlet(e.target.value)}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm font-normal text-slate-900 dark:text-slate-100"
              >
                {outlets.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300">
              Date
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm font-normal text-slate-900 dark:text-slate-100"
              />
            </label>
          </div>

          <label className="space-y-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 block">
            Title
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Article headline"
              className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm font-normal text-slate-900 dark:text-slate-100 placeholder:text-slate-400"
            />
          </label>

          <label className="space-y-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 block">
            Source URL
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://..."
              className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm font-normal text-slate-900 dark:text-slate-100 placeholder:text-slate-400"
            />
          </label>

          <label className="space-y-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300 block">
            Article Text
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Paste the article body here"
              rows={12}
              className="w-full resize-y rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-sm font-normal leading-6 text-slate-900 dark:text-slate-100 placeholder:text-slate-400"
            />
          </label>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span className={`text-xs ${textLength >= 100 ? "text-slate-400" : "text-amber-600 dark:text-amber-400"}`}>
              {textLength} characters
            </span>
            <button
              type="submit"
              disabled={!canSubmit}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-900 dark:bg-white px-4 py-2 text-sm font-semibold text-white dark:text-slate-900 hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Gauge className="h-4 w-4" />}
              {loading ? "Analyzing" : "Analyze Article"}
            </button>
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/30 px-3 py-2 text-xs text-rose-700 dark:text-rose-300">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </form>

        <div className="min-h-[360px] rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-4">
          {!result ? (
            <div className="h-full min-h-[320px] flex items-center justify-center text-center text-sm text-slate-400 dark:text-slate-500">
              Article readings will appear here.
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-3">
                  <p className="text-[10px] uppercase font-bold text-slate-400 flex items-center gap-1.5">
                    <Gauge className="h-3.5 w-3.5" />
                    Bias Signal
                  </p>
                  <p className={`mt-1 text-2xl font-bold ${signalTone(result.bias_signal)}`}>
                    {result.bias_signal.toFixed(3)}
                  </p>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">{result.bias_label}</p>
                </div>
                <div className="rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-3">
                  <p className="text-[10px] uppercase font-bold text-slate-400 flex items-center gap-1.5">
                    <Scale className="h-3.5 w-3.5" />
                    Relative Bias
                  </p>
                  <p className={`mt-1 text-2xl font-bold ${sentimentTone(result.relative_sentiment_bias)}`}>
                    {signed(result.relative_sentiment_bias)}
                  </p>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    {relativeAvailable ? "vs. matched peers" : "sentiment-only"}
                  </p>
                </div>
                <div className="rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-3">
                  <p className="text-[10px] uppercase font-bold text-slate-400 flex items-center gap-1.5">
                    <Users className="h-3.5 w-3.5" />
                    Peer Evidence
                  </p>
                  <p className="mt-1 text-2xl font-bold text-slate-900 dark:text-slate-100">
                    {result.peer_count}
                  </p>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    {result.peer_outlet_count} outlets
                  </p>
                </div>
              </div>

              <div className="rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[10px] uppercase font-bold text-slate-400">Article Sentiment</p>
                    <p className={`mt-1 text-lg font-bold ${sentimentTone(result.sentiment_score)}`}>
                      {signed(result.sentiment_score)}
                      <span className="ml-2 text-xs font-semibold capitalize text-slate-500 dark:text-slate-400">
                        {result.sentiment_label}
                      </span>
                    </p>
                  </div>
                  <div className="text-right text-[11px] text-slate-500 dark:text-slate-400">
                    <p>{percent(result.sentiment_confidence)} confidence</p>
                    <p>{result.target_pair_count} target pairs</p>
                  </div>
                </div>
                {result.topic_label && (
                  <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                    Topic: <span className="font-semibold text-slate-700 dark:text-slate-200">{result.topic_label}</span>
                    {result.topic_similarity != null && (
                      <span className="ml-2">match {percent(result.topic_similarity)}</span>
                    )}
                  </p>
                )}
              </div>

              {strongestTargets.length > 0 && (
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-400 mb-2">Targets</p>
                  <div className="flex flex-wrap gap-2">
                    {strongestTargets.map((target) => (
                      <span
                        key={`${target.target}-${target.score}`}
                        className="max-w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-2.5 py-1 text-xs text-slate-700 dark:text-slate-300"
                      >
                        <span className="font-semibold">{target.target}</span>{" "}
                        <span className={sentimentTone(target.score)}>{signed(target.score, 2)}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {result.notes.length > 0 && (
                <div className="space-y-1">
                  {result.notes.map((note) => (
                    <p key={note} className="text-xs text-slate-500 dark:text-slate-400">
                      {note}
                    </p>
                  ))}
                </div>
              )}

              {result.matched_articles.length > 0 && (
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-400 mb-2">Matched Articles</p>
                  <div className="max-h-48 overflow-y-auto divide-y divide-slate-200 dark:divide-slate-700 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
                    {result.matched_articles.slice(0, 6).map((peer) => (
                      <div key={peer.article_id} className="p-3 text-xs">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="font-semibold text-slate-800 dark:text-slate-100 line-clamp-2">
                              {peer.title}
                            </p>
                            <p className="mt-1 text-slate-500 dark:text-slate-400">
                              {peer.outlet} - match {percent(peer.similarity)}
                            </p>
                          </div>
                          <span className={`shrink-0 font-bold ${sentimentTone(peer.sentiment_score)}`}>
                            {signed(peer.sentiment_score, 2)}
                          </span>
                        </div>
                        {peer.url && !peer.url.startsWith("manual://") && (
                          <a
                            href={peer.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-2 inline-flex items-center gap-1 text-[11px] font-semibold text-blue-600 dark:text-blue-400 hover:underline"
                          >
                            Source
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
