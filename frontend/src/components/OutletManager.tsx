"use client";

import { FormEvent, useEffect, useState } from "react";
import { createOutlet, deleteOutlet, fetchOutlets, OutletData } from "@/lib/api";

export default function OutletManager() {
  const [outlets, setOutlets] = useState<OutletData[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isFetching, setIsFetching] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [rssText, setRssText] = useState("");

  const loadOutlets = async () => {
    setIsFetching(true);
    try {
      const data = await fetchOutlets();
      setOutlets(data);
    } catch {
      setMessage({ text: "Failed to load outlets.", type: "error" });
    } finally {
      setIsFetching(false);
    }
  };

  useEffect(() => {
    loadOutlets();
  }, []);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();

    if (!name.trim() || !url.trim()) {
      setMessage({ text: "Name and URL are required.", type: "error" });
      return;
    }

    const rssFeeds = rssText
      .split(/[\n,]/)
      .map((entry) => entry.trim())
      .filter(Boolean);

    setIsLoading(true);
    setMessage(null);

    try {
      await createOutlet({
        name: name.trim(),
        url: url.trim(),
        rss_feeds: rssFeeds,
      });

      setName("");
      setUrl("");
      setRssText("");
      setMessage({ text: "Outlet added successfully.", type: "success" });
      await loadOutlets();
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : "Failed to add outlet.",
        type: "error",
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async (outletId: number, outletName: string) => {
    const confirmed = window.confirm(`Delete outlet "${outletName}"?`);
    if (!confirmed) return;

    setMessage(null);
    try {
      await deleteOutlet(outletId);
      setMessage({ text: "Outlet deleted successfully.", type: "success" });
      await loadOutlets();
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : "Failed to delete outlet.",
        type: "error",
      });
    }
  };

  const inputClass = "border border-gray-300 dark:border-gray-600 rounded-md px-3 py-2 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors";

  return (
    <section className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-4 shadow-sm transition-colors duration-200">
      <div className="mb-3">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">News Outlets</h2>
        <p className="text-sm text-gray-600 dark:text-gray-400">Add outlets to include them in the scraping and bias pipeline.</p>
      </div>

      <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Outlet name"
          className={inputClass}
        />
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com"
          className={inputClass}
        />
        <button
          type="submit"
          disabled={isLoading}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md shadow-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isLoading ? "Adding..." : "Add Outlet"}
        </button>
        <textarea
          value={rssText}
          onChange={(e) => setRssText(e.target.value)}
          placeholder="RSS feed URLs (comma or newline separated)"
          className={`${inputClass} md:col-span-3 min-h-22`}
        />
      </form>

      {message && (
        <p className={`text-sm mb-3 ${message.type === "success" ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
          {message.text}
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="text-left border-b border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400">
              <th className="py-2 pr-3">Name</th>
              <th className="py-2 pr-3">Site URL</th>
              <th className="py-2">RSS Feeds</th>
              <th className="py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {outlets.map((outlet) => (
              <tr key={outlet.id} className="border-b border-gray-100 dark:border-gray-700 align-top">
                <td className="py-2 pr-3 font-medium text-gray-900 dark:text-gray-100">{outlet.name}</td>
                <td className="py-2 pr-3 text-gray-700 dark:text-gray-300 break-all">
                  <a href={outlet.url} target="_blank" rel="noopener noreferrer" className="hover:underline text-blue-600 dark:text-blue-400">
                    {outlet.url}
                  </a>
                </td>
                <td className="py-2 text-gray-700 dark:text-gray-300">
                  {(outlet.rss_feeds || []).length > 0 ? (outlet.rss_feeds || []).join(", ") : "—"}
                </td>
                <td className="py-2 text-right">
                  <button
                    onClick={() => handleDelete(outlet.id, outlet.name)}
                    className="px-3 py-1 bg-red-600 text-white text-xs font-medium rounded-md hover:bg-red-700 transition-colors"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {!isFetching && outlets.length === 0 && (
              <tr>
                <td className="py-3 text-gray-500 dark:text-gray-400" colSpan={4}>No outlets configured yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
