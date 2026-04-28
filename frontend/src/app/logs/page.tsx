import ScrapeLogsPanel from "@/components/ScrapeLogsPanel";
import { fetchScrapeLogs } from "@/lib/api";

export const metadata = {
  title: "Scrape Logs | Media Bias Control Center",
};

export default async function LogsPage() {
  const scrapeLogs = await fetchScrapeLogs(10).catch(() => []);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 pb-20 transition-colors duration-200">
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 py-8 transition-colors duration-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <h1 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
            Scrape Run Logs
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Review recent scraping runs and their output logs.
          </p>
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-8 space-y-8">
        <ScrapeLogsPanel initialLogs={scrapeLogs} />
      </main>
    </div>
  );
}
