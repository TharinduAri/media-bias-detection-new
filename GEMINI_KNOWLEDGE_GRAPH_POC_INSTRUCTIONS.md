# Build Brief: Concurrent Gemini Knowledge-Graph News Analysis POC

## 1. Objective

Create a new, standalone proof-of-concept repository for continuously ingesting news articles, expanding a persistent knowledge graph, associating articles with events, and producing versioned cross-outlet bias-analysis snapshots.

The system must:

- Run independently of any existing project.
- Accept articles periodically from an external scraper/API through both push and polling adapters.
- Continue ingesting while extraction, graph expansion, event association, and scoring run concurrently.
- Use no locally hosted ML models.
- Use Gemini for embeddings and language understanding.
- Use deterministic code for matching thresholds, aggregation, coverage, and final scores.
- Preserve complete provenance from every graph fact and score back to an article version and evidence passage.
- Serve only complete published snapshots, never partially updated results.
- Classify eligible political articles as `government_favouring`, `opposition_favouring`, `balanced_or_mixed`, `neutral`, or `insufficient_evidence` using an explicit, versioned rubric.
- Build time-aware, event-balanced outlet profiles from article evidence without claiming to know an outlet's political intent or factual trustworthiness.

This is a working POC, not a design-only exercise. Build it, run its migrations, run its automated tests, and document how to execute a live Gemini smoke test.

## 2. Non-goals

Do not build:

- A production frontend.
- A custom-trained or locally hosted model.
- A crawler. Provide an ingestion API, polling adapter, and mock external feed instead.
- A system that asks Gemini to directly invent the final outlet bias score.
- Binary political labels forced onto articles that contain insufficient evidence.
- Claims that an outlet intentionally supports a political side; report observable treatment and coverage patterns instead.
- A dedicated graph database for the first version.
- Kubernetes or cloud-specific deployment manifests.

## 3. Required technology

Use:

- Python 3.12 or newer.
- FastAPI.
- Pydantic v2.
- SQLAlchemy 2.x using the async API.
- Alembic migrations.
- PostgreSQL 16 with the pgvector extension.
- The official `google-genai` Python SDK.
- `httpx` for the external polling adapter.
- `pytest`, `pytest-asyncio`, and `respx` or equivalent for tests.
- Ruff for formatting and linting.
- Docker Compose for the database, API, worker, and scheduler/poller.

Do not install or import:

- PyTorch
- TensorFlow
- Transformers
- sentence-transformers
- spaCy model packages
- KeyBERT
- Any other local inference framework or model checkpoint

A deterministic mock AI provider is required for automated tests. It is a test double, not a local model.

## 4. Repository structure

Use a structure similar to:

```text
news-knowledge-graph-poc/
  app/
    api/
      routes/
    core/
      config.py
      logging.py
    db/
      models/
      session.py
    domain/
      schemas/
      scoring/
      matching/
    providers/
      ai/
        base.py
        gemini.py
        mock.py
      external_feed/
        base.py
        http.py
        mock.py
    repositories/
    services/
      ingestion.py
      extraction.py
      graph.py
      event_matching.py
      scoring.py
      snapshots.py
    workers/
      runner.py
      handlers/
    scheduler/
      poller.py
    main.py
  alembic/
  tests/
    unit/
    integration/
    fixtures/
  scripts/
  .env.example
  compose.yaml
  Dockerfile
  pyproject.toml
  README.md
  ARCHITECTURE.md
```

Keep route handlers thin. Business logic belongs in services, and Gemini-specific code belongs behind an AI provider interface.

## 5. Configuration

Provide `.env.example` containing placeholders only:

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/news_graph
AI_PROVIDER=mock
GEMINI_API_KEY=
GEMINI_EMBEDDING_MODEL=gemini-embedding-2
GEMINI_EXTRACTION_MODEL=gemini-3.5-flash-lite
GEMINI_REASONING_MODEL=gemini-3.6-flash
GEMINI_EXTRACTION_THINKING_LEVEL=low
GEMINI_REASONING_THINKING_LEVEL=medium
EXTERNAL_FEED_URL=
EXTERNAL_FEED_API_KEY=
INGESTION_API_KEY=change-me
POLL_INTERVAL_SECONDS=300
WORKER_CONCURRENCY=4
GEMINI_MAX_CONCURRENCY=4
JOB_MAX_ATTEMPTS=5
EVENT_QUIET_PERIOD_MINUTES=30
EVENT_FINALIZATION_HOURS=24
POLITICAL_LEANING_THRESHOLD=0.20
POLITICAL_MIN_EVIDENCE_ITEMS=2
OUTLET_PROFILE_MIN_ARTICLES=20
OUTLET_PROFILE_MIN_EVENTS=10
```

All model IDs must be configurable. Never hard-code or log credentials.

## 6. Data model

Create proper SQLAlchemy models and Alembic migrations for the following concepts. Use UUID primary keys internally unless there is a strong reason not to.

### Source and article storage

`Source`

- `id`
- `key`, unique
- `display_name`
- `created_at`

`SourceArticle`

- `id`
- `source_id`
- `external_id`
- `canonical_url`
- `current_version_id`, nullable during initial insertion
- `first_seen_at`
- `last_seen_at`
- Unique constraint on `(source_id, external_id)`

`ArticleVersion`

- `id`
- `source_article_id`
- `content_hash`
- `title`
- `body`
- `published_at`
- `received_at`
- `raw_payload` JSONB
- `superseded_at`, nullable
- Unique constraint on `(source_article_id, content_hash)`

Never overwrite historical article content. Identical content must not create a new version or new processing jobs.

### Durable processing queue

`ProcessingJob`

- `id`
- `job_type`
- `entity_type`
- `entity_id`
- `input_version`
- `status`: `pending`, `running`, `retry`, `completed`, `dead`
- `priority`
- `attempts`
- `available_at`
- `locked_at`
- `locked_by`
- `last_error`
- `created_at`
- `completed_at`
- Unique idempotency constraint on `(job_type, entity_type, entity_id, input_version)`

Workers must claim jobs using a short transaction and `FOR UPDATE SKIP LOCKED`. Never keep a database transaction open while calling Gemini or the external API.

`OutboxEvent`

- Store transactional events such as `article_version_created`.
- Insert the article version and outbox row in the same transaction.
- A dispatcher turns outbox rows into idempotent processing jobs.

### AI artifacts

`ArticleEmbedding`

- `article_version_id`
- `provider`
- `model`
- `dimensions`
- pgvector `embedding`
- `content_hash`
- token usage
- timestamps
- Unique constraint on `(article_version_id, provider, model)`

`ArticleExtraction`

- `article_version_id`
- `provider`
- `model`
- `prompt_version`
- `schema_version`
- `status`
- `raw_response` JSONB
- `validated_response` JSONB
- input, output, and thinking token counts
- `validation_errors` JSONB
- timestamps
- Unique constraint on `(article_version_id, model, prompt_version, schema_version)`

### Knowledge graph

`GraphEntity`

- `id`
- `canonical_name`
- `entity_type`: `PERSON`, `ORGANIZATION`, `LOCATION`, `POLITICAL_GROUP`, `OTHER`
- optional `political_side`
- timestamps

Do not treat `political_side` as a timeless property. It may be used only as a current display hint. Historical analysis must resolve political roles through time-bounded assignments.

`EntityAlias`

- `entity_id`
- normalized alias
- source/provenance
- Unique normalized alias where safe; ambiguous aliases must be representable.

`PoliticalRoleAssignment`

- `id`
- `entity_id`
- `jurisdiction`
- optional party or coalition entity ID
- `role`: `government`, `opposition`, `independent`, `non_aligned`, `unknown`
- `valid_from`
- `valid_to`, nullable
- provenance and verification status
- timestamps

Political role lookup must use the article publication timestamp. The same actor may have different roles across different periods. Gemini may suggest a role, but only a verified temporal assignment may be used in published political-leaning calculations.

`GraphClaim`

- `id`
- `subject_entity_id`, nullable
- normalized `predicate`
- normalized `object_text`
- optional `object_entity_id`
- `claim_fingerprint`
- timestamps

`GraphEvent`

- `id`
- `label`
- `summary`
- `status`: `open`, `quiet`, `finalized`, `reopened`
- `revision`
- `first_article_at`
- `last_article_at`
- timestamps

`ArticleEntityEdge`, `ArticleClaimEdge`, `ArticleEventEdge`, and `ArticleFrameEdge`

Every edge must include:

- `article_version_id`
- target node ID or normalized frame
- relationship type
- evidence text
- character offsets where available
- rubric score or confidence if applicable
- extraction ID
- timestamps

Article-to-entity treatment edges must additionally support:

- target-treatment label and bounded score
- evidence type: `reporter_voice`, `attributed_quote`, or `unclear`
- speaker entity where available
- prominence: `headline`, `lead`, or `body`
- mention count
- whether the target's political role was resolved for the publication date

`ExternalClusterObservation`

- source
- external cluster ID
- graph event ID
- observed label
- observed article membership
- observed timestamp

An external cluster ID is evidence about an event, not the permanent internal event identity.

### Analysis and publication

`ArticlePoliticalAssessment`

- article version
- analysis run or rubric execution ID
- rubric version
- government affinity score
- opposition affinity score
- normalized leaning score
- classification: `government_favouring`, `opposition_favouring`, `balanced_or_mixed`, `neutral`, or `insufficient_evidence`
- component scores for target treatment, prominence, framing, quotation/source balance, and loaded language
- government and opposition evidence counts
- evidence-sufficiency score
- reliability flags
- evidence edge IDs or evidence summary JSONB
- timestamps

`AnalysisRun`

- `id`
- fixed `cutoff_at`
- graph revision/watermark
- model and rubric versions
- status
- started and finished timestamps
- error metadata

`EventOutletScore`

- analysis run
- event
- outlet/source
- coverage status
- target-treatment score
- framing score
- emphasis score
- government affinity score
- opposition affinity score
- political leaning score and classification
- government/opposition source and target counts
- evidence sufficiency
- evidence summary JSONB

`OutletSnapshot`

- analysis run
- outlet/source
- deterministic aggregate metrics
- final composite score
- government-favouring, opposition-favouring, balanced, neutral, and insufficient-evidence article rates
- event-balanced government and opposition treatment averages
- event-balanced political leaning score
- government and opposition source shares
- political events and articles analysed
- profile sufficiency status and reliability interval

`PublishedSnapshot`

- singleton or publication-channel row pointing to the active completed analysis run

API reads must use only the active published run.

## 7. Ingestion contracts

Implement:

```http
POST /api/v1/ingestion/articles
```

Protect it with an API key header for the POC. Accept a batch with:

```json
{
  "source": "external-scraper",
  "articles": [
    {
      "external_id": "12345",
      "outlet": "Example News",
      "title": "Example headline",
      "body": "Full article body",
      "url": "https://example.test/article",
      "published_at": "2026-08-16T10:00:00Z",
      "external_cluster_id": "456",
      "external_cluster_label": "Example event"
    }
  ]
}
```

Return counts for accepted, unchanged, updated, and rejected articles. A retry of the same request must not duplicate data or jobs.

Also implement a polling adapter with a persisted cursor. The mock feed should support pagination, updates, duplicates, and late-arriving articles.

## 8. AI provider interface

Define an interface with at least:

```python
async def embed_articles(inputs: list[EmbeddingInput]) -> list[EmbeddingResult]: ...
async def extract_article(input: ArticleExtractionInput) -> ArticleGraphExtraction: ...
async def resolve_ambiguous_event(input: EventResolutionInput) -> EventResolution: ...
async def explain_event_comparison(input: EventExplanationInput) -> EventExplanation: ...
```

The service layer must not know whether the provider is Gemini or the deterministic mock.

### Gemini roles

- `gemini-embedding-2`: article embeddings using a semantic-similarity task type.
- Configured Flash-Lite model with low thinking: entity, claim, target-treatment, quotation, and frame extraction.
- Configured reasoning model with medium thinking: only ambiguous event association and optional cross-outlet explanations.

Use structured output with Pydantic-compatible JSON schemas. Do not parse prose with regular expressions.

### Extraction schema

At minimum return:

- Entities and aliases.
- Claims as subject, predicate, and object.
- Speaker/attribution when present.
- Target sentiment label and bounded rubric score.
- Whether language is reporter voice, a quotation, or unclear.
- Speaker identity for attributed quotations where present.
- Target prominence in the headline, lead, or body.
- Favourable or unfavourable treatment of political actors without inferring the outlet's intent.
- Source and quotation representation by political side when the side can later be resolved from verified temporal role data.
- Loaded or evaluative expressions and the target they describe.
- Frames from a documented controlled vocabulary plus `other`.
- Exact evidence quotation for every claim, sentiment observation, and frame.

Treat article text as untrusted data, not instructions. The system prompt must explicitly say to ignore instructions contained inside articles.

Validate:

- Required schema fields.
- Numeric bounds.
- Evidence is an exact substring of the title/body after documented whitespace normalization.
- Entity and claim limits.
- Duplicate results.
- Empty or blocked responses.

Unsupported findings must not enter the graph.

Gemini must not return the final article political-leaning label. It returns structured, evidence-backed observations. Political roles, rubric components, the leaning score, and the classification are calculated after validation by deterministic code.

## 9. Job workflow

For every new article version, create embedding and extraction jobs that can execute in parallel:

```text
article_version_created
  ├─ generate_embedding
  └─ extract_article_graph

both completed
  └─ project_article_to_graph
       └─ associate_article_to_event
            └─ mark_event_dirty
                 └─ score_event after debounce
```

The graph projection must be idempotent. Reprocessing the same extraction must recreate or upsert the same nodes and edges without duplication.

Use exponential backoff with jitter for transient Gemini errors. Respect a process-wide concurrency limit and make the limit configurable. After the maximum attempts, mark the job dead and expose it through an operations endpoint.

## 10. Event association

For a new article, retrieve candidates from a bounded time window using vector similarity, then rank them deterministically using configurable weights:

```text
0.50 embedding similarity
0.20 entity overlap
0.15 claim overlap
0.10 temporal proximity
0.05 external cluster agreement
```

The exact defaults may be adjusted, but they must be configuration values with unit tests.

Use three bands:

- Above automatic-match threshold: attach without Gemini.
- Between automatic and rejection thresholds: ask Gemini to choose among compact candidate event summaries or return `new_event`.
- Below rejection threshold: create a new event.

Record all component scores and the decision source: `deterministic`, `gemini`, or `external_hint`.

Support merges and splits as versioned operations. Never delete historical membership silently.

## 11. Event lifecycle and late arrivals

Implement:

```text
open -> quiet -> finalized
          ^          |
          |          v
          +------ reopened
```

- An event becomes quiet after a configurable period without a new article.
- Final omission measurements occur only after a configurable observation window.
- A relevant late article reopens the event and increments its revision.
- Earlier analysis runs remain immutable.
- Provisional results must be labelled provisional.

This is required to prevent concurrent scraping delays from being interpreted as outlet omission.

## 12. Deterministic scoring

Create a documented scoring module. Gemini supplies evidence and bounded rubric observations, but Python calculates all aggregates.

The POC must calculate at least:

- Event coverage by outlet.
- Missing-event/omission status after finalization.
- Target-treatment difference against the balanced mean of peer outlets.
- Government-versus-opposition treatment difference when classifications exist.
- Article emphasis relative to event peers using text length and article count.
- Claim and actor selection differences.
- A composite demonstration score with weights defined in configuration.
- Article-level government/opposition affinity and leaning classification.
- Event-balanced outlet political-treatment profiles.

Do not call the score factuality, trustworthiness, misinformation, or political truth. It measures observable differences in coverage and treatment.

Use one mean per outlet per event before calculating peer references so outlets publishing many articles cannot dominate the reference mean.

### Article political-leaning rubric

Implement the first rubric as configurable, versioned code. Its default dimensions are:

```text
40% target treatment
20% headline and lead prominence
15% claim and framing treatment
15% quotation/source representation
10% loaded or evaluative language
```

Calculate two intermediate measures:

```text
government affinity = favourable government treatment + unfavourable opposition treatment
opposition affinity = favourable opposition treatment + unfavourable government treatment
leaning score = normalized government affinity - normalized opposition affinity
```

Normalize the result to `[-1, 1]`, where positive means government-favouring treatment and negative means opposition-favouring treatment. Preserve every component so the result can be explained and recalculated.

Do not assume that merely mentioning, quoting, or criticizing a side proves political favour. The rubric must distinguish:

- reporter narration from attributed quotations
- positive treatment from neutral factual description
- article prominence from repeated boilerplate mentions
- an article containing both favourable and unfavourable evidence
- absent evidence from neutral treatment

Use configurable classification thresholds. Reasonable uncalibrated POC defaults may be `>= 0.20` for government-favouring and `<= -0.20` for opposition-favouring, but document that these thresholds require evaluation before production use.

Classification rules must include:

- `government_favouring`: sufficient evidence and score above the positive threshold
- `opposition_favouring`: sufficient evidence and score below the negative threshold
- `balanced_or_mixed`: sufficient evidence concerning both sides without a strong net direction, including genuinely mixed evidence
- `neutral`: relevant political targets are present but treatment is predominantly factual and non-evaluative
- `insufficient_evidence`: too few resolved political targets or too little validated evidence

Never convert `insufficient_evidence` into neutral. Publish the evidence count, rubric version, and component breakdown with the label.

### Outlet political profile

Construct outlet profiles in two stages:

1. Calculate one aggregate per outlet per eligible event.
2. Aggregate those event-level values across the requested time window.

This prevents one outlet from dominating its profile by publishing many articles about one event. Profiles must report:

- event-balanced political leaning score
- separate government and opposition treatment averages
- article-label distribution
- source and quotation representation
- event coverage and finalized omission patterns
- number of eligible political events and articles
- evidence-sufficiency status
- a reliability or bootstrap interval where sample size permits

Require configurable minimum article and event counts before assigning a directional outlet label. Below those minimums, publish measurements but set the profile conclusion to `inconclusive`.

Describe results as observable treatment, for example, "government-favouring treatment was detected across the eligible sample." Do not describe the result as proof that the outlet supports a party, spreads misinformation, or has a particular intention.

## 13. Snapshot execution

Implement an endpoint or scheduled job that starts a snapshot with a fixed cutoff timestamp and graph watermark.

The snapshot worker must:

1. Create a new analysis run.
2. Select only eligible data at or before the cutoff.
3. Calculate event and outlet rows under the new run ID.
4. Validate row counts and invariants.
5. Mark the run complete.
6. Atomically update the published snapshot pointer.

New ingestion must continue throughout this process. Readers continue seeing the previous completed snapshot until publication.

Never delete current results before replacements are complete.

## 14. API endpoints

Implement at least:

```text
GET  /health
GET  /ready
POST /api/v1/ingestion/articles
GET  /api/v1/articles/{article_id}
GET  /api/v1/articles/{article_id}/political-assessment
GET  /api/v1/events
GET  /api/v1/events/{event_id}
GET  /api/v1/events/{event_id}/graph
GET  /api/v1/entities/{entity_id}
POST /api/v1/analysis/snapshots
GET  /api/v1/analysis/runs/{run_id}
GET  /api/v1/analysis/published/outlets
GET  /api/v1/analysis/published/outlets/{outlet}/political-profile
GET  /api/v1/analysis/published/outlets/{outlet}/political-evidence
GET  /api/v1/operations/jobs
POST /api/v1/operations/jobs/{job_id}/retry
```

The event graph endpoint should return nodes, edges, evidence, provenance, and version identifiers suitable for later visualization.

## 15. Observability

Use structured JSON logs with:

- request ID
- job ID
- article version ID
- event ID
- analysis run ID
- provider/model
- duration
- retry count
- token counts
- outcome

Expose counters or a simple operations response for:

- queue depth by status and job type
- oldest pending job age
- Gemini calls and failures
- validation rejection rate
- dead jobs
- ingestion lag
- graph projection lag
- dirty events
- last published snapshot

Never log full article bodies, Gemini keys, or external API credentials.

## 16. Required tests

Automated tests must not require a real Gemini key.

### Unit tests

- Content hashing and article-version idempotency.
- Evidence substring validation.
- Entity alias normalization.
- Claim fingerprinting.
- Event-match component calculations.
- Event threshold decisions.
- Balanced peer scoring.
- Political-role resolution using the article publication date.
- Government/opposition affinity component calculations.
- All five article political classifications, including insufficient evidence.
- Reporter-voice and attributed-quotation weighting.
- Event-balanced outlet aggregation so article volume cannot dominate a profile.
- Minimum-evidence and inconclusive-profile behavior.
- Event lifecycle transitions.
- Retry/backoff state transitions.

### Integration tests

- Duplicate ingestion produces no duplicate version or jobs.
- Updated article creates one new version and supersedes the old one.
- Multiple workers cannot claim the same job concurrently.
- A worker crash leaves a job recoverable after lock expiry.
- Embedding and extraction jobs can complete in either order.
- Graph projection is idempotent.
- A late article reopens a finalized event.
- Ingestion continues during snapshot creation.
- Readers see the old snapshot until the new snapshot is atomically published.
- Gemini timeout/429/5xx simulation retries correctly.
- Invalid or hallucinated evidence is rejected.
- Political leaning cannot be published when actor roles are unresolved or evidence is below the configured minimum.
- An actor who changes political role is classified according to the article date.
- Quoted criticism is not automatically treated as the outlet's own position.
- Outlet profiles are calculated from one aggregate per event, not directly from all articles.
- A dead job does not block unrelated articles.

### End-to-end test

Use a fixture containing at least:

- Three outlets.
- Two events.
- Duplicate deliveries.
- One edited article.
- One late-arriving article.
- One ambiguous event association handled by the mock reasoning provider.
- Government and opposition actors with verified time-bounded roles.
- One actor whose role changes across fixture dates.
- Government-favouring, opposition-favouring, balanced, neutral, and insufficient-evidence article examples.

Demonstrate ingestion through publication and verify the final graph and outlet snapshots.

## 17. Docker and developer experience

`docker compose up --build` must start:

- PostgreSQL/pgvector
- API
- worker
- scheduler/poller

Provide commands for:

- Running migrations.
- Seeding the mock external feed.
- Ingesting fixture data.
- Starting an analysis snapshot.
- Viewing an event graph.
- Running tests and linting.
- Running one optional live Gemini smoke test.

The default compose configuration must use `AI_PROVIDER=mock` so the project is runnable without credentials. Live Gemini operation is enabled only through environment configuration.

## 18. Documentation deliverables

`README.md` must include:

- Quick start.
- Architecture overview.
- Required environment variables.
- Mock and Gemini modes.
- Example API requests.
- Test commands.
- Known POC limitations.

`ARCHITECTURE.md` must include:

- Component diagram.
- Ingestion and job sequence diagram.
- Schema overview.
- Idempotency strategy.
- Concurrency strategy.
- Event lifecycle.
- Political-role history, article leaning rubric, and outlet-profile aggregation.
- Snapshot publication design.
- Gemini responsibility boundaries.
- Data privacy and prompt-injection considerations.

## 19. Implementation order

Work in this order and keep the project runnable after every stage:

1. Scaffold repository, configuration, Compose, database, and migrations.
2. Implement immutable ingestion and outbox creation.
3. Implement database-backed jobs and concurrent worker claiming.
4. Implement mock AI provider and extraction validation.
5. Implement Gemini provider behind the same interface.
6. Implement graph projection.
7. Implement embeddings and event association.
8. Implement event lifecycle and incremental dirty-event processing.
9. Implement deterministic scoring and immutable snapshots.
10. Implement API queries, observability, end-to-end tests, and documentation.

Do not postpone concurrency and idempotency until the end; they are core functional requirements.

## 20. Definition of done

The POC is complete only when all of the following are true:

- The repository starts in a clean environment with Docker Compose.
- No local ML libraries or model checkpoints are present.
- Automated tests run without Gemini credentials.
- A documented optional live Gemini smoke test works when a key is supplied.
- Duplicate and updated article deliveries behave correctly.
- At least two workers process jobs concurrently without duplicate effects.
- Ingestion remains available during graph updates and snapshots.
- Every graph observation includes article evidence and extraction provenance.
- Invalid evidence cannot enter the graph.
- Event association is incremental and uses Gemini only for ambiguous cases.
- Omission is not finalized until the event observation window closes.
- Article political assessments expose the five required labels, component scores, evidence counts, and rubric version.
- Political roles are resolved using valid-from and valid-to dates rather than a timeless actor label.
- Outlet political profiles are event-balanced and become directional only after configurable minimum evidence requirements are met.
- Every directional article or outlet result can be traced to validated evidence and deterministic rubric components.
- Published API responses come from a complete immutable snapshot.
- A failed Gemini request cannot corrupt or partially publish analysis results.
- The full fixture demonstration and all tests pass.

## 21. Final handoff format

At completion, report:

- What was built.
- Repository structure.
- Architectural decisions and tradeoffs.
- Commands executed.
- Migration, lint, unit-test, integration-test, and end-to-end-test results.
- Whether the live Gemini smoke test was run; if not, state that it requires a user-provided key.
- Remaining limitations and the safest next production-hardening steps.

Do not claim completion if tests or migrations are failing. Do not place real secrets in source files, fixtures, logs, or documentation.
