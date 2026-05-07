"""Add BSI score, OutletBiasSnapshot, and OutletTopicBSI for v2 features.

Run once against the Neon PostgreSQL DB:
    python backend/scratch/migrate_v2_features.py
"""
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in .env", file=sys.stderr)
    sys.exit(1)

MIGRATIONS = [
    # 1. Extend OutletBiasProfile with BSI score
    (
        'ALTER TABLE "OutletBiasProfile" ADD COLUMN IF NOT EXISTS bsi_score FLOAT',
        "OutletBiasProfile.bsi_score",
    ),
    # 2. Create OutletBiasSnapshot table
    (
        """
        CREATE TABLE IF NOT EXISTS "OutletBiasSnapshot" (
            id SERIAL PRIMARY KEY,
            outlet VARCHAR NOT NULL,
            run_id INTEGER NOT NULL,
            snapshot_date TIMESTAMP NOT NULL,
            sentiment_bias_avg FLOAT NOT NULL,
            sentiment_score_avg FLOAT NOT NULL,
            articles_scored INTEGER NOT NULL,
            topics_covered INTEGER NOT NULL,
            topics_considered INTEGER NOT NULL,
            coverage_missing_majority INTEGER NOT NULL,
            coverage_bias_rate FLOAT NOT NULL,
            missed_topics JSONB,
            emphasis_bias_avg FLOAT,
            bsi_score FLOAT,
            omission_score FLOAT,
            systematic_omission BOOLEAN,
            baseline_used_runs INTEGER
        )
        """,
        "CREATE OutletBiasSnapshot",
    ),
    # 3. Indexes on OutletBiasSnapshot
    (
        'CREATE INDEX IF NOT EXISTS ix_outlet_bias_snapshot_outlet ON "OutletBiasSnapshot" (outlet)',
        "ix_OutletBiasSnapshot.outlet",
    ),
    (
        'CREATE INDEX IF NOT EXISTS ix_outlet_bias_snapshot_run_id ON "OutletBiasSnapshot" (run_id)',
        "ix_OutletBiasSnapshot.run_id",
    ),
    (
        'CREATE INDEX IF NOT EXISTS ix_outlet_bias_snapshot_date ON "OutletBiasSnapshot" (snapshot_date)',
        "ix_OutletBiasSnapshot.snapshot_date",
    ),
    # 4. Create OutletTopicBSI table
    (
        """
        CREATE TABLE IF NOT EXISTS "OutletTopicBSI" (
            id SERIAL PRIMARY KEY,
            run_id INTEGER NOT NULL,
            outlet VARCHAR NOT NULL,
            topic_key VARCHAR NOT NULL,
            topic_label VARCHAR,
            sentiment_bias_avg FLOAT NOT NULL,
            emphasis_bias_avg FLOAT,
            coverage_present BOOLEAN NOT NULL DEFAULT TRUE,
            article_count INTEGER NOT NULL,
            bsi_score FLOAT NOT NULL,
            snapshot_date TIMESTAMP NOT NULL,
            CONSTRAINT uq_outlet_topic_bsi_run_outlet_topic
                UNIQUE (run_id, outlet, topic_key)
        )
        """,
        "CREATE OutletTopicBSI",
    ),
    # 5. Indexes on OutletTopicBSI
    (
        'CREATE INDEX IF NOT EXISTS ix_outlet_topic_bsi_run_id ON "OutletTopicBSI" (run_id)',
        "ix_OutletTopicBSI.run_id",
    ),
    (
        'CREATE INDEX IF NOT EXISTS ix_outlet_topic_bsi_outlet ON "OutletTopicBSI" (outlet)',
        "ix_OutletTopicBSI.outlet",
    ),
]

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

for sql, description in MIGRATIONS:
    try:
        cur.execute(sql)
        print(f"OK  {description}")
    except Exception as exc:
        print(f"ERR {description}: {exc}", file=sys.stderr)

cur.close()
conn.close()
print("Migration complete.")
