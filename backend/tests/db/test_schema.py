"""Tests for database schema initialization."""

import sqlite3
import tempfile
import os

from app.db.init_db import init_database


def test_init_database_creates_all_tables():
    """init_database should create all 6 tables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)

        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted([t[0] for t in tables])
        conn.close()

        expected = sorted([
            "chat_messages",
            "portfolio_snapshots",
            "positions",
            "trades",
            "users_profile",
            "watchlist",
        ])
        assert table_names == expected


def test_init_database_seeds_default_data():
    """init_database should seed default user and watchlist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)

        conn = sqlite3.connect(db_path)
        user = conn.execute("SELECT * FROM users_profile WHERE id = 'default'").fetchone()
        assert user is not None
        assert user[1] == 10000.0  # cash_balance

        watchlist = conn.execute("SELECT ticker FROM watchlist WHERE user_id = 'default'").fetchall()
        tickers = sorted([r[0] for r in watchlist])
        assert tickers == sorted(["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"])
        conn.close()


def test_init_database_is_idempotent():
    """Calling init_database twice should not fail or duplicate data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_database(db_path)
        init_database(db_path)

        conn = sqlite3.connect(db_path)
        users = conn.execute("SELECT COUNT(*) FROM users_profile").fetchone()[0]
        assert users == 1

        watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        assert watchlist_count == 10
        conn.close()
