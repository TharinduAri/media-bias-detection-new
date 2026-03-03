"use client";

import { useMemo } from "react";
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer,
} from "recharts";
import { CoverageData } from "@/lib/api";
import { useTheme } from "next-themes";

export default function CoverageChart({ data }: { data: CoverageData[] }) {
    const { theme } = useTheme();
    const isDark = theme === "dark";

    const chartData = useMemo(() => {
        const grouped = data.reduce((acc, curr) => {
            const xKey = curr.entity;
            if (!acc[xKey]) {
                acc[xKey] = { name: xKey };
            }
            acc[xKey][curr.outlet] = (acc[xKey][curr.outlet] || 0) + curr.total_mentions;
            return acc;
        }, {} as Record<string, any>);

        return Object.values(grouped)
            .sort((a, b) => {
                let sumA = 0; let sumB = 0;
                for (let key in a) if (key !== 'name') sumA += a[key];
                for (let key in b) if (key !== 'name') sumB += b[key];
                return sumB - sumA;
            })
            .slice(0, 15);
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
        return <div className="p-8 text-center text-gray-500 dark:text-gray-400">No coverage data available.</div>;
    }

    return (
        <div className="w-full h-96 bg-white dark:bg-gray-800 p-4 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 transition-colors duration-200">
            <h3 className="text-lg font-semibold mb-4 text-gray-900 dark:text-gray-100">Topic Coverage (Top 15 Entities)</h3>
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
                    <XAxis dataKey="name" stroke={textColor} tick={{ fill: textColor }} />
                    <YAxis stroke={textColor} tick={{ fill: textColor }} />
                    <Tooltip
                        cursor={{ fill: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }}
                        contentStyle={{ backgroundColor: tooltipBg, borderColor: tooltipBorder, borderRadius: "8px" }}
                        labelStyle={{ color: isDark ? "#f9fafb" : "#111827" }}
                        itemStyle={{ color: isDark ? "#d1d5db" : "#374151" }}
                    />
                    <Legend />
                    {outlets.map((outlet, idx) => (
                        <Bar
                            key={outlet}
                            dataKey={outlet}
                            fill={colors[idx % colors.length]}
                            radius={[4, 4, 0, 0]}
                        />
                    ))}
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
}
