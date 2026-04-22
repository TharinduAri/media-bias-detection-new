import os
from threading import Lock
from typing import Generator, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

load_dotenv()

Base = declarative_base()


def _resolve_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url


class DatabaseManager:
    _instance: Optional["DatabaseManager"] = None
    _lock = Lock()

    def __new__(cls) -> "DatabaseManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        database_url = _resolve_database_url()
        # Keep a single process-wide engine and session factory.
        self._engine = create_engine(database_url, pool_pre_ping=True)
        self._session_factory = sessionmaker(autocommit=False, autoflush=False, bind=self._engine)
        self._initialized = True

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        return self._session_factory

    def connect(self) -> None:
        # Fail fast on startup if the configured database is unreachable.
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def disconnect(self) -> None:
        self._engine.dispose()


db_manager = DatabaseManager()

# Backward-compatible exports used by existing imports.
engine = db_manager.engine
SessionLocal = db_manager.session_factory


def get_db() -> Generator[Session, None, None]:
    db = db_manager.session_factory()
    try:
        yield db
    finally:
        db.close()
