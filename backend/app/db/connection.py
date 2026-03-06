"""Database connection management for FastAPI."""

import os
import sqlite3
from typing import Generator


DB_PATH = os.environ.get("DB_PATH", "/app/db/finally.db")


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI dependency that yields a sqlite3.Connection with WAL mode and Row factory."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
