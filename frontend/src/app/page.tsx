import { fetchSentiment, fetchCoverage, fetchOmissions, fetchExplainability } from "@/lib/api";
import SentimentChart from "@/components/SentimentChart";
import CoverageChart from "@/components/CoverageChart";
import OmissionsTable from "@/components/OmissionsTable";
import ExplainabilityCards from "@/components/ExplainabilityCards";
import CleanScrapeButton from "@/components/CleanScrapeButton";
import OutletManager from "@/components/OutletManager";

export const metadata = {
  title: "Dashboard | Media Bias Control Center",
};

export default async function Home() {
  const [sentiment, coverage, omissions, explainability] = await Promise.all([
    fetchSentiment().catch(() => []),
    fetchCoverage().catch(() => []),
    fetchOmissions().catch(() => []),
    fetchExplainability().catch(() => []),
  ]);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 pb-20 transition-colors duration-200">

      {/* Page Sub-header */}
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 py-8 transition-colors duration-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
              Dashboard
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Sentiment, Coverage &amp; Omissions across Sri Lankan Media
            </p>
          </div>
          <CleanScrapeButton />
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-8 space-y-8">

        <OutletManager />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <SentimentChart data={sentiment} />
          <CoverageChart data={coverage} />
        </div>

        <div>
          <OmissionsTable data={omissions} />
        </div>

        <div>
          <div className="mb-4">
            <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Deep Dive</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">See the exact sentences driving the sentiment scores.</p>
          </div>
          <ExplainabilityCards data={explainability} />
        </div>

      </main>
    </div>
  );
}
