"""Database initialization: create tables and seed default data."""

import sqlite3
import uuid
from datetime import datetime, timezone

from .schema import ALL_TABLES

DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]


def init_database(db_path: str) -> None:
    """Create all tables (idempotent) and seed default data if empty."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        for table_sql in ALL_TABLES:
            conn.execute(table_sql)
        conn.commit()

        # Seed default data if users_profile is empty
        row = conn.execute("SELECT COUNT(*) FROM users_profile").fetchone()
        if row[0] == 0:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
                ("default", 10000.0, now),
            )
            for ticker in DEFAULT_TICKERS:
                conn.execute(
                    "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), "default", ticker, now),
                )
            conn.commit()
    finally:
        conn.close()
