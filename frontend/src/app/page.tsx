import { fetchSentiment, fetchCoverage, fetchOmissions, fetchExplainability } from "@/lib/api";
import SentimentChart from "@/components/SentimentChart";
import CoverageChart from "@/components/CoverageChart";
import OmissionsTable from "@/components/OmissionsTable";
import ExplainabilityCards from "@/components/ExplainabilityCards";
import CleanScrapeButton from "@/components/CleanScrapeButton";
import OutletManager from "@/components/OutletManager";

// Server Component (RSC) to handle data fetching before sending to client
export default async function Home() {
  // Fetch everything in parallel
  const [sentiment, coverage, omissions, explainability] = await Promise.all([
    fetchSentiment().catch(() => []),
    fetchCoverage().catch(() => []),
    fetchOmissions().catch(() => []),
    fetchExplainability().catch(() => []),
  ]);

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 pb-20">

      {/* Header */}
      <header className="bg-white border-b border-gray-200 shadow-sm sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-gray-900">
              Media Bias Control Center
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Analyzing Sentiment, Coverage, and Omissions across Sri Lankan Media
            </p>
          </div>
          <CleanScrapeButton />
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-8 space-y-8">

        <OutletManager />

        {/* Top Row: Longitudinal and Coverage side by side on large screens */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <SentimentChart data={sentiment} />
          <CoverageChart data={coverage} />
        </div>

        {/* Middle Row: Omissions (Full width for table layout) */}
        <div>
          <OmissionsTable data={omissions} />
        </div>

        {/* Bottom Row: Explainability */}
        <div>
          <div className="mb-4">
            <h2 className="text-xl font-bold">Deep Dive</h2>
            <p className="text-sm text-gray-600">See the exact sentences driving the sentiment scores.</p>
          </div>
          <ExplainabilityCards data={explainability} />
        </div>

      </main>
    </div>
  );
}
