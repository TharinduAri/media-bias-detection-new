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

export default function CoverageChart({ data }: { data: CoverageData[] }) {
    const chartData = useMemo(() => {
        const grouped = data.reduce((acc, curr) => {
            const xKey = curr.entity;
            if (!acc[xKey]) {
                acc[xKey] = { name: xKey };
            }
            // Sum mentions if multiple records exist per entity/outlet combo
            acc[xKey][curr.outlet] = (acc[xKey][curr.outlet] || 0) + curr.total_mentions;
            return acc;
        }, {} as Record<string, any>);

        return Object.values(grouped)
            .sort((a, b) => {
                // Sort by total mentions roughly
                let sumA = 0; let sumB = 0;
                for (let key in a) if (key !== 'name') sumA += a[key];
                for (let key in b) if (key !== 'name') sumB += b[key];
                return sumB - sumA;
            })
            .slice(0, 15); // Top 15 entities
    }, [data]);

    const outlets = useMemo(() => {
        const set = new Set<string>();
        data.forEach((d) => set.add(d.outlet));
        return Array.from(set);
    }, [data]);

    const colors = ["#2563eb", "#dc2626", "#16a34a", "#ca8a04", "#9333ea"];

    if (chartData.length === 0) {
        return <div className="p-8 text-center text-gray-500">No coverage data available.</div>;
    }

    return (
        <div className="w-full h-96 bg-white p-4 rounded-xl shadow-sm border border-gray-100">
            <h3 className="text-lg font-semibold mb-4">Topic Coverage (Top 15 Entities)</h3>
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.5} />
                    <XAxis dataKey="name" />
                    <YAxis />
                    <Tooltip cursor={{ fill: 'transparent' }} />
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
