"""Watchlist repository."""

import sqlite3
import uuid
from datetime import datetime, timezone


def get_watchlist(conn: sqlite3.Connection, user_id: str = "default") -> list[str]:
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at", (user_id,)
    ).fetchall()
    return [row["ticker"] if isinstance(row, sqlite3.Row) else row[0] for row in rows]


def add_ticker(conn: sqlite3.Connection, user_id: str, ticker: str) -> bool:
    """Add a ticker to the watchlist. Returns True if added, False if already exists."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, ticker, now),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_ticker(conn: sqlite3.Connection, user_id: str, ticker: str) -> None:
    conn.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, ticker)
    )
    conn.commit()


def ticker_in_watchlist(conn: sqlite3.Connection, user_id: str, ticker: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, ticker)
    ).fetchone()
    return row is not None
