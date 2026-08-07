import Link from "next/link";
import {
  BarChart3,
  BookOpenCheck,
  FileText,
  Layers3,
  Scale,
  Sparkles,
  Target,
} from "lucide-react";
import {
  AnalysisType,
  fetchAllProfiles,
  fetchArticleOutletCounts,
  fetchBiasArticles,
  fetchBiasScores,
  fetchBiasTopics,
  outletsForAnalysis,
} from "@/lib/api";

export const metadata = {
  title: "Demo | Media Bias Control Center",
};

function number(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function percent(value: number | null | undefined): string {
  if (value == null) return "--";
  return `${Math.round(value * 100)}%`;
}

function signed(value: number | null | undefined, digits = 2): string {
  if (value == null) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function biasTone(score: number | null | undefined): string {
  if (score == null) return "text-slate-400";
  if (score >= 0.6) return "text-rose-600 dark:text-rose-400";
  if (score >= 0.3) return "text-amber-600 dark:text-amber-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function politicalLabel(value: number | null | undefined): string {
  if (value == null) return "No signal";
  if (value > 0.15) return "More positive to govt";
  if (value < -0.15) return "More positive to opposition";
  return "Similar portrayal";
}

function politicalTone(value: number | null | undefined): string {
  if (value == null) return "text-slate-400";
  if (value > 0.15) return "text-blue-600 dark:text-blue-400";
  if (value < -0.15) return "text-violet-600 dark:text-violet-400";
  return "text-slate-600 dark:text-slate-300";
}

type DemoPageProps = {
  searchParams: Promise<{
    analysis_type?: string | string[];
  }>;
};

export default async function DemoPage({ searchParams }: DemoPageProps) {
  const params = await searchParams;
  const requestedAnalysisType = Array.isArray(params.analysis_type)
    ? params.analysis_type[0]
    : params.analysis_type;
  const analysisType: AnalysisType =
    requestedAnalysisType === "financial" ? "financial" : "general";
  const isFinancial = analysisType === "financial";

  const [outletCounts, profileResult, topics, scoresResult, articles] = await Promise.all([
    fetchArticleOutletCounts().catch(() => []),
    fetchAllProfiles(analysisType).catch(() => ({ last_run_at: null, profiles: [] })),
    fetchBiasTopics(analysisType).catch(() => []),
    fetchBiasScores({ analysis_type: analysisType }).catch(() => ({
      last_run_at: null,
      scores: [],
    })),
    fetchBiasArticles(8, 0, undefined, undefined, analysisType).catch(() => []),
  ]);

  const profiles = [...profileResult.profiles].sort(
    (a, b) => (a.bsi_score ?? 1) - (b.bsi_score ?? 1)
  );

  const scopedOutletNames = new Set(
    outletsForAnalysis(
      outletCounts.map((outlet) => outlet.outlet),
      analysisType
    )
  );
  const scopedOutletCounts = outletCounts.filter((outlet) =>
    scopedOutletNames.has(outlet.outlet)
  );
  const totalArticles = scopedOutletCounts.reduce(
    (sum, outlet) => sum + outlet.total_articles,
    0
  );
  const scoredArticles = profiles.reduce((sum, profile) => sum + profile.articles_scored, 0);
  const totalCoverageGaps = profiles.reduce(
    (sum, profile) => sum + profile.coverage_missing_majority,
    0
  );
  const averageBsi =
    profiles.length > 0
      ? profiles.reduce((sum, profile) => sum + (profile.bsi_score ?? 0), 0) /
        profiles.length
      : null;
  const topTopic = [...topics].sort((a, b) => b.article_count - a.article_count)[0];
  const strongestArticle = [...articles].sort(
    (a, b) => Math.abs(b.sentiment_bias) - Math.abs(a.sentiment_bias)
  )[0];
  const lastRunAt = profileResult.last_run_at || scoresResult.last_run_at;

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950 dark:bg-gray-950 dark:text-slate-100 pb-16">
      <section className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-gray-900">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
            <div>
              <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-300">
                <Sparkles className="h-3.5 w-3.5" />
                Presentation View
              </div>
              <h1 className="max-w-4xl text-3xl font-bold tracking-tight text-slate-950 dark:text-white sm:text-4xl">
                Media bias, explained through comparable news coverage.
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-300">
                {isFinancial
                  ? "We group financial and economic stories from Sri Lankan business-news outlets, then compare sentiment, coverage, and framing across reports about the same topic."
                  : "We collect articles from multiple Sri Lankan outlets, group stories by the same topic, then compare sentiment, coverage, and political framing across those peer articles."}
              </p>

              <div className="mt-5 inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-950">
                {(["general", "financial"] as AnalysisType[]).map((type) => {
                  const active = analysisType === type;
                  return (
                    <Link
                      key={type}
                      href={`/demo?analysis_type=${type}`}
                      aria-current={active ? "page" : undefined}
                      className={`rounded-md px-4 py-2 text-xs font-semibold transition-colors ${
                        active
                          ? "bg-slate-900 text-white shadow-sm dark:bg-white dark:text-slate-900"
                          : "text-slate-500 hover:bg-white hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
                      }`}
                    >
                      {type === "general" ? "General News" : "Financial News"}
                    </Link>
                  );
                })}
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-gray-950/50">
              <p className="text-xs font-bold uppercase text-slate-400">Demo takeaway</p>
              <p className="mt-2 text-sm leading-6 text-slate-700 dark:text-slate-300">
                {isFinancial
                  ? "Financial framing is measured relative to how other business outlets covered the same economic topic."
                  : "Bias is measured relative to how other outlets covered the same topic, not by judging a single article in isolation."}
              </p>
              <div className="mt-4 flex gap-2">
                <Link
                  href="/bias"
                  className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:opacity-90 dark:bg-white dark:text-slate-900"
                >
                  Full Results
                </Link>
                <Link
                  href="/"
                  className="rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-900"
                >
                  Admin Workspace
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric
            icon={FileText}
            label={isFinancial ? "Financial articles" : "Articles collected"}
            value={number(totalArticles)}
            hint={`${scopedOutletCounts.length} ${isFinancial ? "financial" : "general"} outlets`}
          />
          <Metric
            icon={Layers3}
            label={isFinancial ? "Financial topics" : "Topic groups"}
            value={number(topics.length)}
            hint={topTopic ? `Largest: ${topTopic.article_count} articles` : "Awaiting analysis"}
          />
          <Metric
            icon={Scale}
            label="Articles scored"
            value={number(scoredArticles)}
            hint={`${number(scoresResult.scores.length)} outlet-topic scores`}
          />
          <Metric
            icon={BarChart3}
            label="Average BSI"
            value={averageBsi == null ? "--" : averageBsi.toFixed(2)}
            hint={`Experimental index · ${number(totalCoverageGaps)} major gaps`}
          />
        </div>
      </section>

      <section className="mx-auto grid max-w-7xl gap-6 px-4 sm:px-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)] lg:px-8">
        <div className="rounded-lg border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-gray-900">
          <div className="border-b border-slate-100 px-5 py-4 dark:border-slate-800">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-slate-950 dark:text-white">
                  {isFinancial ? "Financial Outlet BSI Comparison" : "Outlet BSI Comparison"}
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  Lower BSI means less detected relative sentiment, coverage, emphasis, and political-portrayal difference.
                </p>
              </div>
              {lastRunAt && (
                <span className="shrink-0 rounded-md bg-slate-100 px-2.5 py-1 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                  Updated {new Date(lastRunAt).toLocaleDateString("en-GB")}
                </span>
              )}
            </div>
          </div>

          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {profiles.slice(0, 8).map((profile, index) => (
              <div
                key={profile.outlet}
                className="grid gap-3 px-5 py-4 md:grid-cols-[40px_minmax(160px,1fr)_120px_120px_140px]"
              >
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-100 text-sm font-bold text-slate-500 dark:bg-slate-800 dark:text-slate-300">
                  {index + 1}
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-bold text-slate-900 dark:text-slate-100">
                    {profile.outlet}
                  </p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                    {profile.articles_scored} articles across {profile.topics_covered} topics
                  </p>
                </div>
                <ScoreBlock
                  label="Coverage gap"
                  value={percent(profile.coverage_bias_rate_soft ?? profile.coverage_bias_rate)}
                  className={biasTone(profile.coverage_bias_rate_soft ?? profile.coverage_bias_rate)}
                />
                <ScoreBlock
                  label="Bias signal"
                  value={profile.bsi_score == null ? "--" : profile.bsi_score.toFixed(2)}
                  className={biasTone(profile.bsi_score)}
                />
                <ScoreBlock
                  label="Framing"
                  value={politicalLabel(profile.political_side_bias_avg)}
                  subValue={signed(profile.political_side_bias_avg)}
                  className={politicalTone(profile.political_side_bias_avg)}
                />
              </div>
            ))}

            {profiles.length === 0 && (
              <div className="px-5 py-10 text-center text-sm text-slate-400">
                No {analysisType} outlet profiles yet. Run {analysisType} bias analysis
                before the panel demo.
              </div>
            )}
          </div>
        </div>

        <div className="space-y-6">
          <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-gray-900">
            <div className="flex items-center gap-2">
              <Target className="h-5 w-5 text-blue-600 dark:text-blue-400" />
              <h2 className="text-base font-bold text-slate-950 dark:text-white">
                {isFinancial ? "Strongest Financial Example" : "Strongest Example"}
              </h2>
            </div>
            {strongestArticle ? (
              <div className="mt-4 space-y-3">
                <p className="text-sm font-semibold leading-6 text-slate-900 dark:text-slate-100">
                  {strongestArticle.title}
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <MiniStat label="Outlet" value={strongestArticle.outlet} />
                  <MiniStat label="Bias" value={signed(strongestArticle.sentiment_bias, 3)} />
                  <MiniStat label="Sentiment" value={signed(strongestArticle.sentiment_score, 2)} />
                  <MiniStat
                    label="Political"
                    value={politicalLabel(strongestArticle.political_side_bias)}
                  />
                </div>
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-400">
                No scored articles yet.
              </p>
            )}
          </div>

          <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-gray-900">
            <div className="flex items-center gap-2">
              <BookOpenCheck className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
              <h2 className="text-base font-bold text-slate-950 dark:text-white">
                Method In 3 Steps
              </h2>
            </div>
            <div className="mt-4 space-y-3">
              <MethodStep
                step="1"
                title="Collect"
                text={
                  isFinancial
                    ? "Collect reports from specialist financial outlets."
                    : "Scrape articles from registered news outlets."
                }
              />
              <MethodStep
                step="2"
                title="Group"
                text="Cluster articles that discuss the same story."
              />
              <MethodStep
                step="3"
                title="Compare"
                text="Score each outlet against its topic peers."
              />
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 pt-6 sm:px-6 lg:px-8">
        <div className="rounded-lg border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-gray-900">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-amber-600 dark:text-amber-400" />
            <h2 className="text-base font-bold text-slate-950 dark:text-white">
              Panel Script
            </h2>
          </div>
          <div className="mt-4 grid gap-3 text-sm leading-6 text-slate-600 dark:text-slate-300 md:grid-cols-3">
            <p>
              First, this system builds a common article database from multiple{" "}
              {isFinancial ? "financial" : "general-news"} outlets.
            </p>
            <p>
              Then it compares outlets only inside the same topic group, so the
              measurement is fair.
            </p>
            <p>
              Finally, it summarizes the experimental bias signal, coverage gaps,
              and comparable {isFinancial ? "financial framing" : "political portrayal"}{" "}
              at outlet level.
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof FileText;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-gray-900">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-bold uppercase text-slate-400">{label}</p>
        <Icon className="h-4 w-4 text-slate-400" />
      </div>
      <p className="mt-3 text-2xl font-bold text-slate-950 dark:text-white">{value}</p>
      <p className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400">{hint}</p>
    </div>
  );
}

function ScoreBlock({
  label,
  value,
  subValue,
  className,
}: {
  label: string;
  value: string;
  subValue?: string;
  className: string;
}) {
  return (
    <div>
      <p className="text-[10px] font-bold uppercase text-slate-400">{label}</p>
      <p className={`mt-1 truncate text-sm font-bold ${className}`}>{value}</p>
      {subValue && <p className="mt-0.5 text-xs text-slate-400">{subValue}</p>}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-800/70">
      <p className="text-[10px] font-bold uppercase text-slate-400">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
        {value}
      </p>
    </div>
  );
}

function MethodStep({
  step,
  title,
  text,
}: {
  step: string;
  title: string;
  text: string;
}) {
  return (
    <div className="flex gap-3">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-900 text-xs font-bold text-white dark:bg-white dark:text-slate-900">
        {step}
      </div>
      <div>
        <p className="text-sm font-bold text-slate-900 dark:text-slate-100">{title}</p>
        <p className="text-sm leading-6 text-slate-500 dark:text-slate-400">{text}</p>
      </div>
    </div>
  );
}
