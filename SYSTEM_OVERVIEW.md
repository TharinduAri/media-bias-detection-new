# Media Bias Detection MVP - System Overview

This document provides a comprehensive overview of the media bias detection backend and data pipeline. It is designed to be fed to an LLM to quickly understand the architecture, data flow, and database schema of the system.

## 1. High-Level Architecture
The system is a Python-based data pipeline that collects news articles, processes them using NLP (Natural Language Processing), extracts sentiment and bias signals, aggregates statistics, and serves them via a Streamlit dashboard. 

The entire state of the system is stored in a **NeonDB PostgreSQL Database** and is accessed and mutated using the **Prisma ORM** (Python Client).

### Pipeline Stages
1. **Collection (`scraper.py`)**: Fetches raw articles from news outlets.
2. **Preprocessing (`preprocessor.py`)**: Cleans text, segments sentences, and extracts named entities.
3. **Extraction (`bias_extractor.py`)**: Evaluates sentiment of entities based on context.
4. **Aggregation (`aggregator.py`)**: Computes longitudinal and comparative statistics.
5. **Explainability (`explainer.py`)**: Prepares human-readable evidence of bias.
6. **Dashboard (`app.py`)**: Streamlit UI for data visualization.

Everything is orchestrated by `run_pipeline.py`.

---

## 2. Database Schema (`schema.prisma`)
The system relies on five relational models to store data across the pipeline stages.

1. **`Article`**: The core table. 
   - Stores raw scraped data (`title`, `url`, `outlet`, `date`, `text`).
   - Stores pipeline-processed data as JSON or Text (`clean_text`, `sentences`, `entities`, `entity_sentiments`).
2. **`AggregatedSentiment`**: Longitudinal data for line charts. Stores average sentiment toward an entity over time per outlet.
3. **`AggregatedCoverage`**: Comparative data for bar charts. Stores how often an outlet mentions an entity.
4. **`PotentialOmission`**: Bias by omission data. Tracks entities heavily covered by one outlet but ignored by another.
5. **`UIExplainData`**: Contains the specific, most polarizing sentences driving an entity's sentiment score, used for UI transparency.

---

## 3. Component Breakdown

### Orchestrator (`run_pipeline.py`)
- Executes the pipeline stages sequentially.
- Ensures stages run in order using `subprocess`.
- Supports `--dry-run` and `--continue-on-error` flags.

### Stage 1: Scraper (`src/collection/scraper.py`)
- **Sources**: Target outlets are defined in the script (e.g., NewsFirst, AdaDerana).
- **Process**: Primarily uses RSS feeds (via `feedparser`) for reliability and recent articles. If RSS fails or returns nothing, it falls back to site scraping using `newspaper3k`.
- **Output**: Uses Prisma `upsert` to insert new articles into the `Article` table or update existing ones based on URL.

### Stage 2: Preprocessor (`src/processing/preprocessor.py`)
- **Input**: Fetches `Article` records from Prisma where `clean_text` is `None`.
- **Process**: Uses the `SpaCy` NLP library (`en_core_web_sm`).
  - Cleans boilerplate HTML and whitespace.
  - Segments the article into discrete sentences.
  - Performs Named Entity Recognition (NER) focusing on `PERSON`, `ORG`, `GPE`, and `NORP`. Filters out duplicate entities per article to prevent over-counting.
- **Output**: Updates the `Article` record, saving `clean_text`, `sentences` (JSON array), and `entities` (JSON array).

### Stage 3: Bias Extractor (`src/extraction/bias_extractor.py`)
- **Input**: Fetches `Article` records where `entities` exist but `entity_sentiments` is `None`.
- **Process**: Uses `vaderSentiment` for rule-based sentiment analysis.
  - For each extracted entity, it finds the specific sentences in the article that mention that entity.
  - It scores the sentiment of those specific sentences.
  - Averages the sentiment scores to determine the baseline contextual sentiment of how the *article treats the entity*.
  - Identifies the single most polarizing sentence (highest absolute sentiment) as an "example sentence" for explainability.
- **Output**: Updates the `Article` record with `entity_sentiments` (JSON array containing sentiment stats and example sentences per entity).

### Stage 4: Aggregator (`src/aggregation/aggregator.py`)
- **Input**: Fetches all `Article` records that have `entity_sentiments`.
- **Process**: Flattens the nested JSON entity data into an entity-mention level dataset. Uses `pandas` to group and aggregate:
  - **Sentiment**: Groups by `[outlet, year_month, entity, label]` to find the `avg_sentiment`.
  - **Coverage**: Groups by `[outlet, entity, label]` to find the total mentions (`total_mentions`).
  - **Omissions**: Pivots the coverage data to find cases where `Outlet A` has `> 2` mentions but `Outlet B` has `0` mentions.
- **Output**: Clears old analytical tables and bulk inserts the new calculations into `AggregatedSentiment`, `AggregatedCoverage`, and `PotentialOmission` models.

### Stage 5: Explainer (`src/explainability/explainer.py`)
- **Input**: Fetches all `Article` records containing `entity_sentiments`.
- **Process**: Flattens data and filters out entities with no context or zero sentiment. Sorts by absolute sentiment (most opinionated first) and extracts the Top 5 most polarizing sentences per entity per outlet.
- **Output**: Clears old data and bulk inserts into the `UIExplainData` Prisma model.

## 4. API Layer (FastAPI)
The backend now exposes a RESTful API via **FastAPI**, creating a clean detachment between the data aggregation and frontend display systems.

- **Routing Model**: Routes are modularized inside `backend/api/routers/` (`sentiment`, `coverage`, `omissions`, `explainability`).
- **Read-Only**: The API provides strictly `GET` endpoints fetching JSON-serialized analytics.
- **ORM Distinction**: 
  - **Prisma** is strictly reserved for the Python data pipeline's background **writes**.
  - **SQLAlchemy** is used exclusively by the FastAPI service for ultra-fast, strictly typed **reads**. The SQLAlchemy models exactly mirror the Prisma-generated tables.

### Endpoints Available
- `GET /api/v1/sentiment/`
- `GET /api/v1/coverage/`
- `GET /api/v1/omissions/`
- `GET /api/v1/explainability/`

Swagger/OpenAPI documentation is auto-generated and hosted locally at `http://localhost:8000/docs`.

---

## 5. Next.js Frontend Integration Context
If building a Next.js frontend:
- The Next.js frontend can connect directly to the FastAPI endpoints (`http://localhost:8000/api/v1/*`) to retrieve cleanly formatted JSON arrays using standard `fetch` or a tool like `React Query` or `SWR`.
- Bypassing direct DB connection from the frontend is safer and allows the Python API to scale independently.
- The Streamlit app (`backend/app.py`) serves as a reference implementation of this, proving that charts can be fully re-rendered exclusively from the API responses.
