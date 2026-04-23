# Media Scraper - System Overview

## Scope
This repository now focuses on one workflow only:
- scrape article URLs and content from configured outlets
- store raw article records in PostgreSQL
- view/manage outlets and raw articles via FastAPI + Next.js

Removed from scope:
- preprocessing, sentiment extraction, aggregation, and explainability pipelines
- analytics API routes and analytics tables

## Current Architecture

### Backend
- Entry point: backend/main.py
- API stack: FastAPI + SQLAlchemy
- Write pipeline: Prisma Python client inside scraper
- Database models in active use: Article, Outlet
- System routes support:
  - clean article table
  - clean and run scraper
  - scraper status polling

### Scraper
- Script: backend/src/collection/scraper.py
- Responsibilities:
  - load outlets from DB
  - discover article URLs (RSS/sitemap/fallback crawling)
  - fetch article payloads concurrently
  - upsert valid records into Article table

### Frontend
- Framework: Next.js App Router
- Main page: frontend/src/app/page.tsx
- Core components:
  - outlet management
  - scraper actions and status modal
  - raw articles browser

## Database Tables
Expected active tables:
- Article
- Outlet
- _prisma_migrations

## Operational Notes
- backend/.env must provide DATABASE_URL
- run backend from backend directory so env loading is consistent
- article browsing depends on /api/v1/articles/* endpoints and SQLAlchemy model/schema compatibility
