import { fetchArticleOutlets, fetchArticleOutletCounts, fetchArticles, fetchScrapeLogs } from "@/lib/api";
import CleanScrapeButton from "@/components/CleanScrapeButton";
import BiasAnalysisButton from "@/components/BiasAnalysisButton";
import OutletManager from "@/components/OutletManager";
import RawArticlesView from "@/components/RawArticlesView";

export const metadata = {
  title: "Scraping Workspace | Media Bias Control Center",
};

export default async function Home() {
  const outlets = await fetchArticleOutlets().catch(() => [] as string[]);
  const outletCounts = await fetchArticleOutletCounts().catch(() => []);
  const firstOutlet = outlets[0] ?? "";
  const initialArticles = firstOutlet
    ? await fetchArticles(firstOutlet, 50, 0).catch(() => [])
    : [];

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 pb-20 transition-colors duration-200">

      {/* Page Sub-header */}
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 py-8 transition-colors duration-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
              Scraping Workspace
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Manage outlets, trigger scraping, and browse stored raw articles.
            </p>
          </div>
          <div className="flex flex-col items-end gap-3">
            <BiasAnalysisButton />
            <CleanScrapeButton />
          </div>
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-8 space-y-8">
        <OutletManager />
        <RawArticlesView
          outlets={outlets}
          outletCounts={outletCounts}
          initialOutlet={firstOutlet}
          initialArticles={initialArticles}
        />
      </main>
    </div>
  );
}
