"use client";

import { useEffect, useState } from "react";
import { 
  fetchBiasTopics, 
  fetchBiasArticles, 
  TopicSummaryData, 
  ArticleBiasWithArticleData 
} from "@/lib/api";
import { 
  ChevronDown, 
  AlertCircle, 
  ExternalLink, 
  TrendingUp, 
  TrendingDown, 
  Minus,
  CheckCircle2,
  RefreshCw,
  Search
} from "lucide-react";

export default function TopicValidationPanel() {
  const [topics, setTopics] = useState<TopicSummaryData[]>([]);
  const [selectedTopic, setSelectedTopic] = useState<string>("");
  const [articles, setArticles] = useState<ArticleBiasWithArticleData[]>([]);
  const [loadingTopics, setLoadingTopics] = useState(true);
  const [loadingArticles, setLoadingArticles] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");

  useEffect(() => {
    loadTopics();
  }, []);

  useEffect(() => {
    if (selectedTopic) {
      loadArticles(selectedTopic);
    } else {
      setArticles([]);
    }
  }, [selectedTopic]);

  async function loadTopics() {
    setLoadingTopics(true);
    setError(null);
    try {
      const data = await fetchBiasTopics();
      setTopics(data);
      if (data.length > 0 && !selectedTopic) {
        // Don't auto-select, let the user choose
      }
    } catch (err) {
      setError("Failed to load topic groups.");
      console.error(err);
    } finally {
      setLoadingTopics(false);
    }
  }

  async function loadArticles(topicKey: string) {
    setLoadingArticles(true);
    setError(null);
    try {
      const data = await fetchBiasArticles(100, 0, undefined, topicKey);
      setArticles(data);
    } catch (err) {
      setError("Failed to load articles for this topic.");
      console.error(err);
    } finally {
      setLoadingArticles(false);
    }
  }

  const filteredTopics = topics.filter(t => 
    t.topic_key.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const getSentimentIcon = (score: number) => {
    if (score > 0.2) return <TrendingUp className="w-4 h-4 text-emerald-500" />;
    if (score < -0.2) return <TrendingDown className="w-4 h-4 text-rose-500" />;
    return <Minus className="w-4 h-4 text-slate-400" />;
  };

  const getBiasColor = (bias: number) => {
    const absBias = Math.abs(bias);
    if (absBias > 0.5) return "text-rose-600 dark:text-rose-400 font-bold";
    if (absBias > 0.2) return "text-orange-600 dark:text-orange-400 font-semibold";
    return "text-emerald-600 dark:text-emerald-400";
  };

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 shadow-sm overflow-hidden transition-all duration-300">
      <div className="p-6 border-b border-gray-100 dark:border-gray-800">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
              <CheckCircle2 className="w-6 h-6 text-indigo-500" />
              Topic Validation Case Study
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Sanity check topic groupings by reading the actual articles.
            </p>
          </div>
          <button 
            onClick={loadTopics}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-900/30 rounded-lg hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loadingTopics ? 'animate-spin' : ''}`} />
            Refresh Topics
          </button>
        </div>

        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="relative">
            <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Select Topic Group
            </label>
            <div className="relative">
              <select
                value={selectedTopic}
                onChange={(e) => setSelectedTopic(e.target.value)}
                disabled={loadingTopics}
                className="w-full pl-4 pr-10 py-2.5 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl appearance-none focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all text-sm disabled:opacity-50"
              >
                <option value="">Choose a topic (Sorted by article count)</option>
                {topics.map((topic) => (
                  <option key={topic.topic_key} value={topic.topic_key}>
                    {topic.topic_key} ({topic.article_count} articles)
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            </div>
          </div>

          <div className="relative">
            <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Filter Keys
            </label>
            <div className="relative">
              <input
                type="text"
                placeholder="Search topic key..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all text-sm"
              />
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            </div>
          </div>
        </div>
      </div>

      <div className="min-h-[400px] relative">
        {loadingArticles ? (
          <div className="absolute inset-0 flex items-center justify-center bg-white/50 dark:bg-gray-900/50 backdrop-blur-sm z-10">
            <div className="flex flex-col items-center gap-3">
              <RefreshCw className="w-8 h-8 text-indigo-500 animate-spin" />
              <p className="text-sm font-medium text-gray-600 dark:text-gray-300">Loading articles...</p>
            </div>
          </div>
        ) : null}

        {error ? (
          <div className="p-12 flex flex-col items-center text-center">
            <div className="w-12 h-12 bg-rose-50 dark:bg-rose-900/20 rounded-full flex items-center justify-center mb-4">
              <AlertCircle className="w-6 h-6 text-rose-500" />
            </div>
            <p className="text-gray-900 dark:text-white font-medium">{error}</p>
            <button 
              onClick={() => selectedTopic ? loadArticles(selectedTopic) : loadTopics()}
              className="mt-4 text-indigo-600 dark:text-indigo-400 text-sm font-medium hover:underline"
            >
              Try again
            </button>
          </div>
        ) : !selectedTopic ? (
          <div className="p-20 flex flex-col items-center text-center">
            <div className="w-16 h-16 bg-indigo-50 dark:bg-indigo-900/20 rounded-2xl flex items-center justify-center mb-4 transform rotate-12">
              <Search className="w-8 h-8 text-indigo-500" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">No Topic Selected</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 max-w-xs mt-2">
              Select a topic from the dropdown above to inspect the articles and verify the clustering quality.
            </p>
          </div>
        ) : articles.length === 0 ? (
          <div className="p-20 flex flex-col items-center text-center">
            <p className="text-gray-500 dark:text-gray-400">No articles found for this topic.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-gray-50/50 dark:bg-gray-800/50 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                  <th className="px-6 py-4">Article Title & Outlet</th>
                  <th className="px-6 py-4 text-center">Sentiment</th>
                  <th className="px-6 py-4 text-center">Bias Score</th>
                  <th className="px-6 py-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {articles.map((article) => (
                  <tr key={article.id} className="group hover:bg-slate-50 dark:hover:bg-gray-800/40 transition-colors">
                    <td className="px-6 py-4">
                      <div className="flex flex-col gap-1">
                        <span className="text-sm font-medium text-gray-900 dark:text-white group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors line-clamp-1">
                          {article.title}
                        </span>
                        <span className="text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
                          {article.outlet}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-col items-center gap-1">
                        <div className="flex items-center gap-1.5">
                          {getSentimentIcon(article.sentiment_score)}
                          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                            {article.sentiment_score.toFixed(2)}
                          </span>
                        </div>
                        <span className="text-[10px] text-gray-400 dark:text-gray-500 capitalize">
                          {article.sentiment_label}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-center">
                      <div className="flex flex-col items-center">
                        <span className={`text-sm ${getBiasColor(article.sentiment_bias)}`}>
                          {article.sentiment_bias > 0 ? '+' : ''}{article.sentiment_bias.toFixed(3)}
                        </span>
                        <div className="w-16 h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full mt-1.5 overflow-hidden">
                          <div 
                            className={`h-full rounded-full ${article.sentiment_bias > 0 ? 'bg-emerald-500' : 'bg-rose-500'}`}
                            style={{ 
                              width: `${Math.min(Math.abs(article.sentiment_bias) * 100, 100)}%`,
                              marginLeft: article.sentiment_bias > 0 ? '0' : 'auto'
                            }}
                          />
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <a 
                        href={article.url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 rounded-lg transition-all"
                      >
                        Read
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      
      {selectedTopic && articles.length > 0 && (
        <div className="p-4 bg-gray-50 dark:bg-gray-800/50 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between">
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Showing <strong>{articles.length}</strong> articles for group <strong>{selectedTopic}</strong>
          </p>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-[10px] font-medium text-gray-500 uppercase">Positive Bias</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full bg-rose-500" />
              <span className="text-[10px] font-medium text-gray-500 uppercase">Negative Bias</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
