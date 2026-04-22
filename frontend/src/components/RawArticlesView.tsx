"use client";

import { useState, useCallback } from "react";
import { ArticleData, deleteArticle, fetchArticles } from "@/lib/api";

interface Props {
    outlets: string[];
    initialOutlet: string;
    initialArticles: ArticleData[];
}

const PAGE_SIZE = 50;

export default function RawArticlesView({ outlets, initialOutlet, initialArticles }: Props) {
    const [selectedOutlet, setSelectedOutlet] = useState<string>(initialOutlet);
    const [articles, setArticles] = useState<ArticleData[]>(initialArticles);
    const [offset, setOffset] = useState(initialArticles.length);
    const [loading, setLoading] = useState(false);
    const [hasMore, setHasMore] = useState(initialArticles.length === PAGE_SIZE);
    const [search, setSearch] = useState("");
    const [expandedId, setExpandedId] = useState<number | null>(null);
    const [deletingId, setDeletingId] = useState<number | null>(null);
    const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

    const loadArticles = useCallback(async (outlet: string, newOffset: number, replace: boolean) => {
        setLoading(true);
        try {
            const data = await fetchArticles(outlet, PAGE_SIZE, newOffset);
            setArticles(prev => replace ? data : [...prev, ...data]);
            setHasMore(data.length === PAGE_SIZE);
            setOffset(newOffset + data.length);
        } catch {
            // silent fail
        } finally {
            setLoading(false);
        }
    }, []);

    const handleOutletSelect = (outlet: string) => {
        setSelectedOutlet(outlet);
        setSearch("");
        setExpandedId(null);
        setMessage(null);
        setOffset(0);
        loadArticles(outlet, 0, true);
    };

    const handleLoadMore = () => {
        loadArticles(selectedOutlet, offset, false);
    };

    const handleDeleteArticle = async (articleId: number, articleTitle: string) => {
        const confirmed = window.confirm(`Delete article "${articleTitle}"?`);
        if (!confirmed) return;

        setMessage(null);
        setDeletingId(articleId);

        try {
            await deleteArticle(articleId);
            setArticles((prev) => prev.filter((article) => article.id !== articleId));
            setExpandedId((prev) => (prev === articleId ? null : prev));
            setOffset((prev) => Math.max(0, prev - 1));
            setMessage({ text: "Article deleted successfully.", type: "success" });
        } catch (error) {
            setMessage({
                text: error instanceof Error ? error.message : "Failed to delete article.",
                type: "error",
            });
        } finally {
            setDeletingId(null);
        }
    };

    const filtered = articles.filter(a =>
        !search || a.title.toLowerCase().includes(search.toLowerCase())
    );

    return (
        <div className="flex flex-col gap-6">
            {/* Outlet Tabs */}
            <div className="flex flex-wrap gap-2">
                {outlets.map(outlet => (
                    <button
                        key={outlet}
                        onClick={() => handleOutletSelect(outlet)}
                        className={`
              px-4 py-2 rounded-full text-sm font-medium border transition-all duration-200
              ${selectedOutlet === outlet
                                ? "bg-blue-600 border-blue-600 text-white shadow-lg shadow-blue-500/20"
                                : "bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:border-blue-500 hover:text-blue-600 dark:hover:text-white"
                            }
            `}
                    >
                        {outlet}
                    </button>
                ))}
            </div>

            {/* Search */}
            <div className="relative">
                <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 dark:text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input
                    type="text"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    placeholder="Search article titles…"
                    className="w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg pl-10 pr-4 py-2.5 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
                />
                {search && (
                    <button
                        onClick={() => setSearch("")}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300"
                    >
                        ✕
                    </button>
                )}
            </div>

            {/* Count badge */}
            <div className="flex items-center justify-between">
                <p className="text-sm text-gray-500 dark:text-gray-400">
                    {outlets.length === 0
                        ? "No outlets found. Run the scraper first."
                        : (
                            <>
                                Showing <span className="text-gray-900 dark:text-white font-semibold">{filtered.length}</span>
                                {search ? " matching" : ""} articles
                                {selectedOutlet ? <> from <span className="text-blue-600 dark:text-blue-400 font-medium">{selectedOutlet}</span></> : ""}
                            </>
                        )}
                </p>
                {loading && (
                    <span className="text-xs text-gray-400 dark:text-gray-500 animate-pulse">Loading…</span>
                )}
            </div>

            {message && (
                <p className={`text-sm ${message.type === "success" ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
                    {message.text}
                </p>
            )}

            {/* Article list */}
            {filtered.length === 0 && !loading ? (
                <div className="text-center py-16 text-gray-400 dark:text-gray-600">
                    <svg className="mx-auto w-12 h-12 mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <p className="text-sm">{search ? "No articles match your search." : "No articles found for this outlet."}</p>
                </div>
            ) : (
                <div className="space-y-3">
                    {filtered.map(article => (
                        <div
                            key={article.id}
                            className="bg-white dark:bg-gray-800/60 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden hover:border-gray-300 dark:hover:border-gray-500 hover:shadow-sm transition-all duration-200"
                        >
                            {/* Card header */}
                            <div
                                className="flex items-start gap-4 p-4 cursor-pointer"
                                onClick={() => setExpandedId(expandedId === article.id ? null : article.id)}
                            >
                                {/* Date pill */}
                                <div className="shrink-0 text-center">
                                    <div className="bg-gray-100 dark:bg-gray-700 rounded-lg px-2 py-1 min-w-13">
                                        <p className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wide">
                                            {new Date(article.date).toLocaleString("en-GB", { month: "short" })}
                                        </p>
                                        <p className="text-lg font-bold text-gray-900 dark:text-white leading-none">
                                            {new Date(article.date).getDate().toString().padStart(2, "0")}
                                        </p>
                                        <p className="text-[10px] text-gray-500 dark:text-gray-400">
                                            {new Date(article.date).getFullYear()}
                                        </p>
                                    </div>
                                </div>

                                {/* Title + meta */}
                                <div className="flex-1 min-w-0">
                                    <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100 leading-snug line-clamp-2">
                                        {article.title}
                                    </h3>
                                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2">
                                        <span className="text-xs text-blue-600 dark:text-blue-400 font-medium">{article.outlet}</span>
                                        <a
                                            href={article.url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            onClick={e => e.stopPropagation()}
                                            className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 underline underline-offset-2 truncate max-w-xs"
                                        >
                                            {article.url}
                                        </a>
                                    </div>
                                </div>

                                <div className="shrink-0 flex items-center gap-2 mt-1">
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleDeleteArticle(article.id, article.title);
                                        }}
                                        disabled={deletingId === article.id}
                                        className="px-2.5 py-1 rounded-md bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-[11px] font-medium text-red-700 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-900/50 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                                    >
                                        {deletingId === article.id ? "Deleting..." : "Delete"}
                                    </button>
                                    <svg
                                        className={`w-4 h-4 text-gray-400 dark:text-gray-500 transition-transform duration-200 ${expandedId === article.id ? "rotate-180" : ""}`}
                                        fill="none" stroke="currentColor" viewBox="0 0 24 24"
                                    >
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                    </svg>
                                </div>
                            </div>

                            {/* Expanded body */}
                            {expandedId === article.id && (
                                <div className="border-t border-gray-100 dark:border-gray-700 px-4 pb-4 pt-3">
                                    {article.clean_text ? (
                                        <div>
                                            <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">Cleaned Text</p>
                                            <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto pr-1">
                                                {article.clean_text}
                                            </p>
                                        </div>
                                    ) : article.text ? (
                                        <div>
                                            <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">Raw Text</p>
                                            <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto">
                                                {article.text}
                                            </p>
                                        </div>
                                    ) : (
                                        <p className="text-sm text-gray-400 dark:text-gray-600 italic">No text content stored for this article.</p>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {/* Load More */}
            {hasMore && !search && (
                <div className="flex justify-center pt-2">
                    <button
                        onClick={handleLoadMore}
                        disabled={loading}
                        className="px-6 py-2.5 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {loading ? "Loading…" : "Load more articles"}
                    </button>
                </div>
            )}
        </div>
    );
}
