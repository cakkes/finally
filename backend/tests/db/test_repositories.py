"""Tests for all repository functions using in-memory SQLite."""

import sqlite3

import pytest

from app.db.schema import ALL_TABLES
from app.db.repositories import portfolio_repo, watchlist_repo, trades_repo, snapshots_repo, chat_repo


@pytest.fixture
def conn():
    """Create an in-memory DB with schema and default user."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    for sql in ALL_TABLES:
        c.execute(sql)
    c.execute(
        "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
        ("default", 10000.0, "2024-01-01T00:00:00"),
    )
    c.commit()
    yield c
    c.close()


# --- Portfolio repo ---

class TestPortfolioRepo:
    def test_get_cash(self, conn):
        assert portfolio_repo.get_cash(conn) == 10000.0

    def test_update_cash(self, conn):
        portfolio_repo.update_cash(conn, 5000.0)
        assert portfolio_repo.get_cash(conn) == 5000.0

    def test_get_positions_empty(self, conn):
        assert portfolio_repo.get_positions(conn) == []

    def test_upsert_position_insert(self, conn):
        portfolio_repo.upsert_position(conn, "default", "AAPL", 10.0, 150.0)
        positions = portfolio_repo.get_positions(conn)
        assert len(positions) == 1
        assert positions[0]["ticker"] == "AAPL"
        assert positions[0]["quantity"] == 10.0
        assert positions[0]["avg_cost"] == 150.0

    def test_upsert_position_update(self, conn):
        portfolio_repo.upsert_position(conn, "default", "AAPL", 10.0, 150.0)
        portfolio_repo.upsert_position(conn, "default", "AAPL", 20.0, 155.0)
        positions = portfolio_repo.get_positions(conn)
        assert len(positions) == 1
        assert positions[0]["quantity"] == 20.0
        assert positions[0]["avg_cost"] == 155.0

    def test_delete_position(self, conn):
        portfolio_repo.upsert_position(conn, "default", "AAPL", 10.0, 150.0)
        portfolio_repo.delete_position(conn, "default", "AAPL")
        assert portfolio_repo.get_positions(conn) == []


# --- Watchlist repo ---

class TestWatchlistRepo:
    def test_empty_watchlist(self, conn):
        assert watchlist_repo.get_watchlist(conn) == []

    def test_add_ticker(self, conn):
        assert watchlist_repo.add_ticker(conn, "default", "AAPL") is True
        assert watchlist_repo.get_watchlist(conn) == ["AAPL"]

    def test_add_duplicate_ticker(self, conn):
        watchlist_repo.add_ticker(conn, "default", "AAPL")
        assert watchlist_repo.add_ticker(conn, "default", "AAPL") is False

    def test_remove_ticker(self, conn):
        watchlist_repo.add_ticker(conn, "default", "AAPL")
        watchlist_repo.remove_ticker(conn, "default", "AAPL")
        assert watchlist_repo.get_watchlist(conn) == []

    def test_ticker_in_watchlist(self, conn):
        assert watchlist_repo.ticker_in_watchlist(conn, "default", "AAPL") is False
        watchlist_repo.add_ticker(conn, "default", "AAPL")
        assert watchlist_repo.ticker_in_watchlist(conn, "default", "AAPL") is True


# --- Trades repo ---

class TestTradesRepo:
    def test_record_and_get_trades(self, conn):
        trades_repo.record_trade(conn, "default", "AAPL", "buy", 10.0, 150.0)
        trades_repo.record_trade(conn, "default", "AAPL", "sell", 5.0, 160.0)
        trades = trades_repo.get_trades(conn)
        assert len(trades) == 2
        assert trades[0]["side"] == "sell"  # DESC order
        assert trades[1]["side"] == "buy"

    def test_empty_trades(self, conn):
        assert trades_repo.get_trades(conn) == []


# --- Snapshots repo ---

class TestSnapshotsRepo:
    def test_record_and_get_snapshots(self, conn):
        snapshots_repo.record_snapshot(conn, "default", 10500.0)
        snapshots_repo.record_snapshot(conn, "default", 10600.0)
        snaps = snapshots_repo.get_snapshots(conn)
        assert len(snaps) == 2

    def test_get_snapshots_limit(self, conn):
        for i in range(10):
            snapshots_repo.record_snapshot(conn, "default", 10000.0 + i)
        snaps = snapshots_repo.get_snapshots(conn, limit=5)
        assert len(snaps) == 5

    def test_empty_snapshots(self, conn):
        assert snapshots_repo.get_snapshots(conn) == []


# --- Chat repo ---

class TestChatRepo:
    def test_save_and_get_messages(self, conn):
        chat_repo.save_message(conn, "default", "user", "Hello")
        chat_repo.save_message(conn, "default", "assistant", "Hi there!", {"trades": []})
        messages = chat_repo.get_recent_messages(conn)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["actions"] is None
        assert messages[1]["role"] == "assistant"
        assert messages[1]["actions"] == {"trades": []}

    def test_get_recent_messages_limit(self, conn):
        for i in range(10):
            chat_repo.save_message(conn, "default", "user", f"Message {i}")
        messages = chat_repo.get_recent_messages(conn, limit=5)
        assert len(messages) == 5

    def test_messages_chronological_order(self, conn):
        chat_repo.save_message(conn, "default", "user", "First")
        chat_repo.save_message(conn, "default", "assistant", "Second")
        messages = chat_repo.get_recent_messages(conn)
        assert messages[0]["content"] == "First"
        assert messages[1]["content"] == "Second"

    def test_empty_messages(self, conn):
        assert chat_repo.get_recent_messages(conn) == []
