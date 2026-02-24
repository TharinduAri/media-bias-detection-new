"use client";

import { OmissionsData } from "@/lib/api";

export default function OmissionsTable({ data }: { data: OmissionsData[] }) {
    if (data.length === 0) {
        return <div className="p-8 text-center text-gray-500">No notable omissions detected.</div>;
    }

    return (
        <div className="w-full bg-white p-4 rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
            <h3 className="text-lg font-semibold mb-4 text-red-600">Potential Coverage Omissions</h3>
            <table className="w-full text-left border-collapse">
                <thead>
                    <tr className="bg-gray-50 border-b border-gray-200">
                        <th className="p-3 text-sm font-semibold text-gray-600">Entity</th>
                        <th className="p-3 text-sm font-semibold text-gray-600">Covered Mostly By</th>
                        <th className="p-3 text-sm font-semibold text-gray-600 text-center">Max Mentions</th>
                        <th className="p-3 text-sm font-semibold text-gray-600">Omitted By</th>
                    </tr>
                </thead>
                <tbody>
                    {data.map((row) => (
                        <tr key={row.id} className="border-b border-gray-100 hover:bg-red-50/30 transition-colors">
                            <td className="p-3 text-sm font-medium">{row.entity}</td>
                            <td className="p-3 text-sm text-gray-700">{row.covered_mostly_by}</td>
                            <td className="p-3 text-sm text-gray-700 text-center font-semibold">{row.max_mentions}</td>
                            <td className="p-3 text-sm text-red-600 font-medium">{row.omitted_by}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
