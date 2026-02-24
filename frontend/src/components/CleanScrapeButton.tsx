"use client";

import { useState } from "react";
import { triggerCleanScrape } from "@/lib/api";

export default function CleanScrapeButton() {
    const [isLoading, setIsLoading] = useState(false);
    const [message, setMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

    const handleCleanAndRescrape = async () => {
        // Confirm before proceeding
        const confirmed = window.confirm(
            "Are you sure you want to completely wipe the database and restart the scraping pipeline? This action cannot be undone."
        );
        if (!confirmed) return;

        setIsLoading(true);
        setMessage(null);

        try {
            const result = await triggerCleanScrape();
            setMessage({ text: result.message, type: "success" });
        } catch (error) {
            console.error(error);
            setMessage({ text: "Failed to clean and rescrape. See console for details.", type: "error" });
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="flex items-center gap-4">
            {message && (
                <span className={`text-sm ${message.type === "success" ? "text-green-600" : "text-red-600"}`}>
                    {message.text}
                </span>
            )}
            <button
                onClick={handleCleanAndRescrape}
                disabled={isLoading}
                className="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-md shadow-sm hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                title="Wipe database and trigger run_pipeline.py"
            >
                {isLoading ? "Processing..." : "Clean & Rescrape"}
            </button>
        </div>
    );
}
