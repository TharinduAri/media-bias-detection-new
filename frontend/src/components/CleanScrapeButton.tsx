"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
    triggerCleanDb,
    triggerCleanScrape,
    fetchPipelineStatus,
    PipelineStatus,
} from "@/lib/api";

const POLL_MS = 1500;
const STAGE_ICONS = ["🔍"];

// ─── Confirm Dialog ────────────────────────────────────────────────────────────
function ConfirmDialog({
    title,
    message,
    danger,
    onConfirm,
    onCancel,
}: {
    title: string;
    message: string;
    danger?: boolean;
    onConfirm: () => void;
    onCancel: () => void;
}) {
    return (
        <div className="fixed inset-0 z-100 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onCancel} />
            <div className="relative w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 p-6">
                <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-2">{title}</h2>
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-6 leading-relaxed">{message}</p>
                <div className="flex gap-3 justify-end">
                    <button
                        onClick={onCancel}
                        className="px-4 py-2 rounded-lg text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        id="confirm-action-btn"
                        onClick={onConfirm}
                        className={`px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors ${danger ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"
                            }`}
                    >
                        Confirm
                    </button>
                </div>
            </div>
        </div>
    );
}

// ─── Progress Modal ─────────────────────────────────────────────────────────────
function ProgressModal({
    status,
    onClose,
}: {
    status: PipelineStatus;
    onClose: () => void;
}) {
    const logRef = useRef<HTMLDivElement>(null);
    const totalStages = status.stages.length;
    const completedStages =
        status.status === "done"
            ? totalStages
            : Math.max(0, status.current_stage_index);
    const progressPct =
        status.status === "done"
            ? 100
            : Math.round((completedStages / totalStages) * 100);

    useEffect(() => {
        if (logRef.current) {
            logRef.current.scrollTop = logRef.current.scrollHeight;
        }
    }, [status.logs]);

    const isDone = status.status === "done";
    const isError = status.status === "error";
    const isRunning = status.status === "running";

    return (
        <div className="fixed inset-0 z-100 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />

            <div className="relative w-full max-w-2xl bg-white dark:bg-gray-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
                {/* Header */}
                <div
                    className={`px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between ${isDone
                            ? "bg-green-50 dark:bg-green-900/20"
                            : isError
                                ? "bg-red-50 dark:bg-red-900/20"
                                : "bg-gray-50 dark:bg-gray-800"
                        }`}
                >
                    <div className="flex items-center gap-3">
                        {isRunning && (
                            <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin shrink-0" />
                        )}
                        {isDone && <span className="text-2xl">✅</span>}
                        {isError && <span className="text-2xl">❌</span>}
                        <div>
                            <h2 className="font-bold text-gray-900 dark:text-white text-base">
                                {isDone
                                    ? "Scraper Complete!"
                                    : isError
                                        ? "Scraper Error"
                                        : "Running Scraper..."}
                            </h2>
                            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                                {isDone
                                    ? "Scrape finished successfully."
                                    : isError
                                        ? (status.error ?? "An error occurred.")
                                        : `Stage ${Math.min(status.current_stage_index + 1, totalStages)} of ${totalStages}`}
                            </p>
                        </div>
                    </div>
                    {(isDone || isError) && (
                        <button
                            onClick={onClose}
                            className="text-gray-400 hover:text-gray-700 dark:hover:text-white transition-colors text-xl leading-none ml-4"
                        >
                            ✕
                        </button>
                    )}
                </div>

                {/* Progress bar */}
                <div className="px-6 pt-5">
                    <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mb-1.5">
                        <span>Progress</span>
                        <span>{progressPct}%</span>
                    </div>
                    <div className="w-full h-2.5 bg-gray-100 dark:bg-gray-700 rounded-full overflow-hidden">
                        <div
                            className={`h-full rounded-full transition-all duration-700 ease-out ${isError
                                    ? "bg-red-500"
                                    : isDone
                                        ? "bg-green-500"
                                        : "bg-linear-to-r from-blue-500 to-violet-500"
                                }`}
                            style={{ width: `${progressPct}%` }}
                        />
                    </div>
                </div>

                {/* Stage steps */}
                <div className="px-6 pt-4 pb-2">
                    <div className="flex gap-1 justify-between">
                        {status.stages.map((stage, idx) => {
                            const isDoneStage = isDone || idx < status.current_stage_index;
                            const isActive = !isDone && idx === status.current_stage_index;
                            const isFailedStage = isError && idx === status.current_stage_index;

                            return (
                                <div key={stage.key} className="flex-1 flex flex-col items-center gap-1">
                                    <div
                                        className={`w-8 h-8 rounded-full flex items-center justify-center text-sm border-2 transition-all duration-300 ${isDoneStage
                                                ? "bg-green-500 border-green-500 text-white"
                                                : isActive
                                                    ? "bg-blue-500 border-blue-500 text-white animate-pulse"
                                                    : isFailedStage
                                                        ? "bg-red-500 border-red-500 text-white"
                                                        : "bg-gray-100 dark:bg-gray-700 border-gray-200 dark:border-gray-600 text-gray-400"
                                            }`}
                                    >
                                        {isDoneStage ? "✓" : isFailedStage ? "✗" : STAGE_ICONS[idx]}
                                    </div>
                                    <span
                                        className={`text-[9px] text-center leading-tight ${isActive
                                                ? "text-blue-600 dark:text-blue-400 font-semibold"
                                                : isDoneStage
                                                    ? "text-green-600 dark:text-green-400"
                                                    : isFailedStage
                                                        ? "text-red-500"
                                                        : "text-gray-400 dark:text-gray-500"
                                            }`}
                                    >
                                        {stage.label}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Live log */}
                <div className="px-6 pb-6 pt-3">
                    <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">
                        Live Output
                    </p>
                    <div
                        ref={logRef}
                        className="h-44 overflow-y-auto rounded-lg bg-gray-950 dark:bg-black border border-gray-800 p-3 font-mono text-xs text-gray-300 space-y-0.5"
                    >
                        {status.logs.length === 0 ? (
                            <span className="text-gray-600">Waiting for output…</span>
                        ) : (
                            status.logs.map((line, i) => (
                                <div
                                    key={i}
                                    className={`whitespace-pre-wrap leading-relaxed ${line.startsWith("✓")
                                            ? "text-green-400"
                                            : line.startsWith("✗") || line.toLowerCase().includes("error") || line.toLowerCase().includes("failed")
                                                ? "text-red-400"
                                                : line.startsWith("▶")
                                                    ? "text-blue-400 font-semibold"
                                                    : line.startsWith("🎉")
                                                        ? "text-yellow-300 font-semibold"
                                                        : line.startsWith("Pipeline")
                                                            ? "text-gray-300"
                                                            : "text-gray-500"
                                        }`}
                                >
                                    {line}
                                </div>
                            ))
                        )}
                        {isRunning && (
                            <div className="flex items-center gap-1.5 text-gray-600 mt-1">
                                <div className="flex gap-0.5">
                                    {[0, 1, 2].map((i) => (
                                        <span
                                            key={i}
                                            className="w-1 h-1 rounded-full bg-gray-500 animate-bounce"
                                            style={{ animationDelay: `${i * 0.15}s` }}
                                        />
                                    ))}
                                </div>
                                <span>Processing…</span>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

// ─── Main Component ────────────────────────────────────────────────────────────
export default function CleanScrapeButton() {
    const [isLoadingCleanDb, setIsLoadingCleanDb] = useState(false);
    const [cleanDbMessage, setCleanDbMessage] = useState<{
        text: string;
        type: "success" | "error";
    } | null>(null);

    // Confirmation dialog state
    const [confirmAction, setConfirmAction] = useState<"scrape" | "cleandb" | null>(null);

    // Progress modal state
    const [showModal, setShowModal] = useState(false);
    const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const stopPolling = useCallback(() => {
        if (pollRef.current !== null) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
    }, []);

    const startPolling = useCallback(() => {
        stopPolling();
        pollRef.current = setInterval(async () => {
            try {
                const s = await fetchPipelineStatus();
                setPipelineStatus(s);
                if (s.status === "done" || s.status === "error") {
                    stopPolling();
                }
            } catch {
                /* ignore transient failures */
            }
        }, POLL_MS);
    }, [stopPolling]);

    useEffect(() => () => stopPolling(), [stopPolling]);

    // ── Scrape flow ──────────────────────────────────────────────────────────────
    const confirmScrape = async () => {
        setConfirmAction(null);
        try {
            await triggerCleanScrape();
        } catch (err) {
            alert(err instanceof Error ? err.message : "Failed to start scraper.");
            return;
        }
                const initial = await fetchPipelineStatus().catch(() => null);
        setPipelineStatus(initial);
        setShowModal(true);
        startPolling();
    };

    // ── Clean DB flow ────────────────────────────────────────────────────────────
    const confirmCleanDb = async () => {
        setConfirmAction(null);
        setIsLoadingCleanDb(true);
        setCleanDbMessage(null);
        try {
            const result = await triggerCleanDb();
            setCleanDbMessage({ text: result.message, type: "success" });
        } catch (error) {
            setCleanDbMessage({
                text: error instanceof Error ? error.message : "Failed to clean database.",
                type: "error",
            });
        } finally {
            setIsLoadingCleanDb(false);
        }
    };

    return (
        <>
            <div className="flex items-center gap-4">
                {cleanDbMessage && (
                    <span
                        className={`text-sm ${cleanDbMessage.type === "success"
                                ? "text-green-600 dark:text-green-400"
                                : "text-red-600 dark:text-red-400"
                            }`}
                    >
                        {cleanDbMessage.text}
                    </span>
                )}
                <button
                    onClick={() => setConfirmAction("cleandb")}
                    disabled={isLoadingCleanDb}
                    className="px-4 py-2 bg-gray-700 dark:bg-gray-600 text-white text-sm font-medium rounded-md shadow-sm hover:bg-gray-800 dark:hover:bg-gray-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                    {isLoadingCleanDb ? "Cleaning..." : "Clean DB"}
                </button>
                <button
                    id="clean-rescrape-btn"
                    onClick={() => setConfirmAction("scrape")}
                    className="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-md shadow-sm hover:bg-red-700 transition-colors"
                >
                    Clean &amp; Scrape
                </button>
            </div>

            {/* Custom confirm dialog */}
            {confirmAction === "scrape" && (
                <ConfirmDialog
                    title="Clean &amp; Scrape"
                    message="This will wipe stored raw articles and restart scraping. This action cannot be undone. Continue?"
                    danger
                    onConfirm={confirmScrape}
                    onCancel={() => setConfirmAction(null)}
                />
            )}
            {confirmAction === "cleandb" && (
                <ConfirmDialog
                    title="Clean Database"
                    message="This will delete stored raw articles without triggering a new scrape. This action cannot be undone. Continue?"
                    danger
                    onConfirm={confirmCleanDb}
                    onCancel={() => setConfirmAction(null)}
                />
            )}

            {/* Progress modal */}
            {showModal && pipelineStatus && (
                <ProgressModal
                    status={pipelineStatus}
                    onClose={() => {
                        stopPolling();
                        setShowModal(false);
                    }}
                />
            )}
        </>
    );
}
