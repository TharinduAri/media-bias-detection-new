"""Verify that the configured PostgreSQL database is reachable.

Run from the repository root with::

    python backend/connect_database.py

The script reads ``backend/.env.local`` first, then ``backend/.env``. An
existing ``DATABASE_URL`` environment variable takes precedence over both.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parent


def load_database_environment() -> None:
    """Load local configuration without overriding process environment."""
    load_dotenv(BACKEND_DIR / ".env.local")
    load_dotenv(BACKEND_DIR / ".env")


def main() -> int:
    load_database_environment()

    # Import after loading the environment because DatabaseManager is created
    # when this module is imported.
    from api.database import db_manager

    try:
        db_manager.connect()
    except Exception as exc:
        print(
            f"Database connection failed ({type(exc).__name__}). "
            "Check DATABASE_URL and network access.",
            file=sys.stderr,
        )
        return 1
    finally:
        db_manager.disconnect()

    print("Database connection successful.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
