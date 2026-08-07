import type { Metadata } from "next";
import "./globals.css";
import NavHeader from "@/components/NavHeader";
import Providers from "./providers";

export const metadata: Metadata = {
  title: "Media Bias Control Center",
  description: "Scrape outlets and manage stored raw articles.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased">
        <Providers>
          <NavHeader />
          {children}
        </Providers>
      </body>
    </html>
  );
}
