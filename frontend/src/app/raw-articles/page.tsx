import { fetchArticleOutlets, fetchArticles } from "@/lib/api";
import RawArticlesView from "@/components/RawArticlesView";

export const metadata = {
    title: "Raw Articles | Media Bias Control Center",
    description: "Browse all raw scraped articles separated by news outlet.",
};

export default async function RawArticlesPage() {
    const outlets = await fetchArticleOutlets().catch(() => [] as string[]);
    const firstOutlet = outlets[0] ?? "";
    const initialArticles = firstOutlet
        ? await fetchArticles(firstOutlet, 50, 0).catch(() => [])
        : [];

    return (
        <div className="min-h-screen bg-slate-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 pb-20 transition-colors duration-200">

            {/* Page Hero */}
            <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 py-10 transition-colors duration-200">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="flex items-start gap-4">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center shadow-lg mt-0.5">
                            <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
                            </svg>
                        </div>
                        <div>
                            <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-white">Raw Articles</h1>
                            <p className="text-gray-500 dark:text-gray-400 mt-1 text-sm max-w-xl">
                                Browse all scraped articles from each outlet. Click any article to expand its full text content.
                            </p>
                            <div className="flex gap-4 mt-3 text-sm text-gray-500 dark:text-gray-500">
                                <span className="flex items-center gap-1.5">
                                    <span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />
                                    {outlets.length} outlet{outlets.length !== 1 ? "s" : ""} tracked
                                </span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Main content */}
            <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-8">
                <RawArticlesView
                    outlets={outlets}
                    initialOutlet={firstOutlet}
                    initialArticles={initialArticles}
                />
            </main>
        </div>
    );
}
