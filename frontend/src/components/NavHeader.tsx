"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

const navLinks = [
    { href: "/", label: "Scraping Workspace" },
    { href: "/bias", label: "Bias Results" },
    { href: "/logs", label: "Scrape Logs" },
    { href: "/api-explorer", label: "Exposed API" },
];

function ThemeToggle() {
    const { theme, setTheme } = useTheme();
    const [mounted, setMounted] = useState(false);

    useEffect(() => setMounted(true), []);

    if (!mounted) {
        return <div className="w-9 h-9" />;
    }

    const isDark = theme === "dark";

    return (
        <button
            onClick={() => setTheme(isDark ? "light" : "dark")}
            aria-label="Toggle theme"
            className="w-9 h-9 flex items-center justify-center rounded-lg transition-colors duration-200 text-gray-400 hover:text-white hover:bg-white/10"
        >
            {isDark ? (
                /* Sun icon for light mode */
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343 17.657l-.707.707M17.657 17.657l-.707-.707M6.343 6.343l-.707-.707M12 8a4 4 0 100 8 4 4 0 000-8z" />
                </svg>
            ) : (
                /* Moon icon for dark mode */
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
            )}
        </button>
    );
}

export default function NavHeader() {
    const pathname = usePathname();

    return (
        <header className="bg-gray-900 dark:bg-gray-900 border-b border-gray-700 dark:border-gray-700 sticky top-0 z-50 shadow-lg">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div className="flex items-center justify-between h-16">
                    {/* Brand */}
                    <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-linear-to-br from-blue-500 to-violet-600 flex items-center justify-center shadow-inner">
                            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                            </svg>
                        </div>
                        <div>
                            <span className="text-white font-bold text-base leading-none tracking-tight">
                                Media Bias
                            </span>
                            <span className="block text-gray-400 text-[10px] leading-none mt-0.5 tracking-widest uppercase">
                                Control Center
                            </span>
                        </div>
                    </div>

                    {/* Nav links + theme toggle */}
                    <div className="flex items-center gap-1">
                        <nav className="flex items-center gap-1">
                            {navLinks.map(({ href, label }) => {
                                const isActive = pathname === href;
                                return (
                                    <Link
                                        key={href}
                                        href={href}
                                        className={`
                      relative px-4 py-2 rounded-md text-sm font-medium transition-all duration-200
                      ${isActive
                                                ? "text-white bg-white/10"
                                                : "text-gray-400 hover:text-white hover:bg-white/5"
                                            }
                    `}
                                    >
                                        {isActive && (
                                            <span className="absolute inset-x-3 bottom-0.5 h-0.5 rounded-full bg-linear-to-r from-blue-400 to-violet-500" />
                                        )}
                                        {label}
                                    </Link>
                                );
                            })}
                        </nav>

                        <div className="ml-2 pl-2 border-l border-gray-700">
                            <ThemeToggle />
                        </div>
                    </div>
                </div>
            </div>
        </header>
    );
}
