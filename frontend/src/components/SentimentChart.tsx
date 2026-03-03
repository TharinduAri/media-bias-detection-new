"use client";

import { useMemo } from "react";
import {
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer,
} from "recharts";
import { SentimentData } from "@/lib/api";
import { useTheme } from "next-themes";

export default function SentimentChart({ data }: { data: SentimentData[] }) {
    const { theme } = useTheme();
    const isDark = theme === "dark";

    const chartData = useMemo(() => {
        const grouped = data.reduce((acc, curr) => {
            const xKey = curr.year_month;
            if (!acc[xKey]) {
                acc[xKey] = { name: xKey };
            }
            acc[xKey][curr.outlet] = curr.avg_sentiment;
            return acc;
        }, {} as Record<string, any>);

        return Object.values(grouped).sort((a, b) => a.name.localeCompare(b.name));
    }, [data]);

    const outlets = useMemo(() => {
        const set = new Set<string>();
        data.forEach((d) => set.add(d.outlet));
        return Array.from(set);
    }, [data]);

    const colors = ["#3b82f6", "#ef4444", "#22c55e", "#eab308", "#a855f7"];
    const gridColor = isDark ? "#374151" : "#e5e7eb";
    const textColor = isDark ? "#9ca3af" : "#6b7280";
    const tooltipBg = isDark ? "#1f2937" : "#ffffff";
    const tooltipBorder = isDark ? "#374151" : "#e5e7eb";

    if (chartData.length === 0) {
        return <div className="p-8 text-center text-gray-500 dark:text-gray-400">No sentiment data available.</div>;
    }

    return (
        <div className="w-full h-96 bg-white dark:bg-gray-800 p-4 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 transition-colors duration-200">
            <h3 className="text-lg font-semibold mb-4 text-gray-900 dark:text-gray-100">Longitudinal Sentiment Trends</h3>
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                    <XAxis dataKey="name" stroke={textColor} tick={{ fill: textColor }} />
                    <YAxis domain={[-1, 1]} stroke={textColor} tick={{ fill: textColor }} />
                    <Tooltip
                        contentStyle={{ backgroundColor: tooltipBg, borderColor: tooltipBorder, borderRadius: "8px" }}
                        labelStyle={{ color: isDark ? "#f9fafb" : "#111827" }}
                        itemStyle={{ color: isDark ? "#d1d5db" : "#374151" }}
                    />
                    <Legend />
                    {outlets.map((outlet, idx) => (
                        <Line
                            key={outlet}
                            type="monotone"
                            dataKey={outlet}
                            stroke={colors[idx % colors.length]}
                            strokeWidth={3}
                            dot={{ r: 4 }}
                            activeDot={{ r: 8 }}
                        />
                    ))}
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
}
