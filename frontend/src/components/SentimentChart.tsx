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

export default function SentimentChart({ data }: { data: SentimentData[] }) {
    // Transform data: group by year_month, then create keys for each outlet's avg_sentiment
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

    const colors = ["#2563eb", "#dc2626", "#16a34a", "#ca8a04", "#9333ea"];

    if (chartData.length === 0) {
        return <div className="p-8 text-center text-gray-500">No sentiment data available.</div>;
    }

    return (
        <div className="w-full h-96 bg-white p-4 rounded-xl shadow-sm border border-gray-100">
            <h3 className="text-lg font-semibold mb-4">Longitudinal Sentiment Trends</h3>
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.5} />
                    <XAxis dataKey="name" />
                    <YAxis domain={[-1, 1]} />
                    <Tooltip />
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
