import BiasAnalysisButton from "@/components/BiasAnalysisButton";
import BiasCleanupButton from "@/components/BiasCleanupButton";
import BiasPageTabs from "@/components/BiasPageTabs";
import { fetchArticleOutlets, fetchBiasTopics } from "@/lib/api";

export const metadata = {
  title: "Bias Results | Media Bias Control Center",
};

export default async function BiasPage() {
  const [topics, outlets] = await Promise.all([
    fetchBiasTopics().catch(() => []),
    fetchArticleOutlets().catch(() => [] as string[]),
  ]);
  const topicCount = topics.length;

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 pb-20 transition-colors duration-200">
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 py-8 transition-colors duration-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-white">
              Bias Results
            </h1>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Calculate bias within topic groups, then inspect outlet profiles.
            </p>
            <div className="mt-4 flex items-center gap-2">
              <div className="px-3 py-1 bg-indigo-50 dark:bg-indigo-900/30 border border-indigo-100 dark:border-indigo-800 rounded-full">
                <span className="text-xs font-semibold text-indigo-700 dark:text-indigo-400">
                  {topicCount} Total Topic Groups
                </span>
              </div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-3">
            <BiasAnalysisButton />
            <BiasCleanupButton />
          </div>
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-8">
        <BiasPageTabs outlets={outlets} initialTopics={topics} />
      </main>
    </div>
  );
}
