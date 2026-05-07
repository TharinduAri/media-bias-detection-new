"""Add emphasis_bias columns to ArticleBiasScore and OutletBiasProfile.

Run once against the Neon PostgreSQL DB:
    python backend/scratch/migrate_emphasis_bias.py
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
    ('ALTER TABLE "ArticleBiasScore" ADD COLUMN IF NOT EXISTS emphasis_bias FLOAT', "ArticleBiasScore.emphasis_bias"),
    ('ALTER TABLE "OutletBiasProfile" ADD COLUMN IF NOT EXISTS emphasis_bias_avg FLOAT', "OutletBiasProfile.emphasis_bias_avg"),
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
