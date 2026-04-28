# Frontend - Media Scraper Workspace

## Purpose
This frontend provides a single workspace for:
- managing outlets
- triggering scraper runs
- viewing and deleting raw stored articles

## Stack
- Next.js App Router
- React
- TypeScript

## Key Views and Components
- src/app/page.tsx: main scraping workspace page
- src/components/OutletManager.tsx: create/delete outlet records
- src/components/CleanScrapeButton.tsx: clean and scrape controls with status polling
- src/components/RawArticlesView.tsx: outlet tabs, article list, search, and delete actions
- src/lib/api.ts: API client for backend endpoints

## Backend Dependency
Set frontend environment variable:
- NEXT_PUBLIC_API_URL (default: http://localhost:8000/api/v1)

## Run
From frontend directory:

```bash
npm install
npm run dev
```

Open http://localhost:3000
