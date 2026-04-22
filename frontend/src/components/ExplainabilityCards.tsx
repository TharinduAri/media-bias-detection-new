"use client";

import { useState, useMemo } from "react";
import { ExplainabilityData } from "@/lib/api";
import { ChevronDown, ExternalLink } from "lucide-react";

export default function ExplainabilityCards({ data }: { data: ExplainabilityData[] }) {
    const [selectedEntity, setSelectedEntity] = useState<string | null>(null);

    const entities = useMemo(() => {
        const set = new Set<string>();
        data.forEach((d) => set.add(d.entity));
        return Array.from(set).sort();
    }, [data]);

    const filteredData = useMemo(() => {
        if (!selectedEntity) return [];
        return data.filter((d) => d.entity === selectedEntity);
    }, [data, selectedEntity]);

    if (data.length === 0) {
        return <div className="p-8 text-center text-gray-500 dark:text-gray-400">No explainability data available.</div>;
    }

    // Auto-select first entity if none selected
    if (!selectedEntity && entities.length > 0) {
        setSelectedEntity(entities[0]);
    }

    return (
        <div className="w-full bg-white dark:bg-gray-800 p-4 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 transition-colors duration-200">
            <div className="flex flex-col md:flex-row md:items-center justify-between mb-6">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Sentiment Explainability</h3>

                <div className="mt-4 md:mt-0 relative">
                    <select
                        value={selectedEntity || ''}
                        onChange={(e) => setSelectedEntity(e.target.value)}
                        className="appearance-none bg-gray-50 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 text-gray-900 dark:text-gray-100 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5 pr-8 transition-colors"
                    >
                        {entities.map(ent => (
                            <option key={ent} value={ent}>{ent}</option>
                        ))}
                    </select>
                    <ChevronDown className="absolute right-2 top-3 w-4 h-4 text-gray-500 dark:text-gray-400 pointer-events-none" />
                </div>
            </div>

            <div className="space-y-4 max-h-[600px] overflow-y-auto pr-2">
                {filteredData.map((item) => (
                    <div key={item.id} className="p-4 border border-gray-200 dark:border-gray-600 rounded-lg hover:shadow-md dark:hover:shadow-gray-900/50 transition-shadow bg-white dark:bg-gray-750">
                        <div className="flex justify-between items-start mb-2">
                            <div>
                                <span className="inline-block px-2 py-1 text-xs font-semibold rounded bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 mr-2">
                                    {item.outlet}
                                </span>
                                <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
                                    Date: {new Date(item.date).toLocaleDateString()}
                                </span>
                            </div>
                            <div className={`px-2 py-1 text-xs font-bold rounded ${item.sentiment > 0.05
                                    ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-400'
                                    : item.sentiment < -0.05
                                        ? 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-400'
                                        : 'bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-300'
                                }`}>
                                Score: {item.sentiment.toFixed(2)}
                            </div>
                        </div>

                        <blockquote className="border-l-4 border-blue-500 pl-4 py-2 italic text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-700/40 my-3 rounded-r">
                            &ldquo;{item.example_sentence}&rdquo;
                        </blockquote>

                        <a href={item.article_url} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center text-sm font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300">
                            Read Source Article <ExternalLink className="w-3 h-3 ml-1" />
                        </a>
                    </div>
                ))}
                {filteredData.length === 0 && selectedEntity && (
                    <div className="text-center text-gray-500 dark:text-gray-400 py-4">No sentences found for {selectedEntity}</div>
                )}
            </div>
        </div>
    );
}
