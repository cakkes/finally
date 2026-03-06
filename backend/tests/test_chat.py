"""Tests for LLM chat service and chat router."""

import json
import os
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.schema import ALL_TABLES
from app.routers.chat import ChatRequest, ChatResponse, _build_portfolio_context, _execute_trade, router
from app.services.llm_service import LLMResponse, LLMService, TradeAction, WatchlistChange


# --- LLMResponse parsing tests ---


class TestLLMResponseParsing:
    def test_basic_message(self):
        resp = LLMResponse(message="Hello")
        assert resp.message == "Hello"
        assert resp.trades == []
        assert resp.watchlist_changes == []

    def test_with_trades(self):
        resp = LLMResponse(
            message="Buying AAPL",
            trades=[TradeAction(ticker="AAPL", side="buy", quantity=10)],
        )
        assert len(resp.trades) == 1
        assert resp.trades[0].ticker == "AAPL"
        assert resp.trades[0].side == "buy"
        assert resp.trades[0].quantity == 10

    def test_with_watchlist_changes(self):
        resp = LLMResponse(
            message="Adding PYPL",
            watchlist_changes=[WatchlistChange(ticker="PYPL", action="add")],
        )
        assert len(resp.watchlist_changes) == 1
        assert resp.watchlist_changes[0].ticker == "PYPL"

    def test_parse_from_json(self):
        raw = '{"message": "Done", "trades": [{"ticker": "MSFT", "side": "sell", "quantity": 5}], "watchlist_changes": []}'
        resp = LLMResponse.model_validate_json(raw)
        assert resp.message == "Done"
        assert resp.trades[0].ticker == "MSFT"

    def test_parse_minimal_json(self):
        raw = '{"message": "Hi"}'
        resp = LLMResponse.model_validate_json(raw)
        assert resp.trades == []
        assert resp.watchlist_changes == []


# --- LLMService tests ---


class TestLLMService:
    async def test_mock_mode(self):
        with patch.dict(os.environ, {"LLM_MOCK": "true"}):
            service = LLMService()
            result = await service.chat("hello", {}, [])
            assert result.message != ""
            assert result.trades == []
            assert result.watchlist_changes == []

    async def test_mock_mode_case_insensitive(self):
        with patch.dict(os.environ, {"LLM_MOCK": "True"}):
            service = LLMService()
            assert service.mock_mode is True

    async def test_error_handling(self):
        with patch.dict(os.environ, {"LLM_MOCK": "false", "OPENROUTER_API_KEY": "fake"}):
            service = LLMService()
            with patch("app.services.llm_service.litellm.acompletion", side_effect=Exception("API error")):
                result = await service.chat("hello", {}, [])
                assert "error" in result.message.lower()
                assert result.trades == []


# --- Database fixtures ---


@pytest.fixture
def db_conn():
    """In-memory SQLite database with schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for table_sql in ALL_TABLES:
        conn.execute(table_sql)
    # Seed default user
    from datetime import datetime, timezone
    conn.execute(
        "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
        ("default", 10000.0, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    yield conn
    conn.close()


class MockPriceCache:
    def __init__(self, prices: dict[str, float]):
        self._prices = prices

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)

    def get(self, ticker: str):
        price = self._prices.get(ticker)
        if price is None:
            return None
        return type("PriceUpdate", (), {"price": price})()


# --- Trade execution tests ---


class TestExecuteTrade:
    def test_buy_success(self, db_conn):
        cache = MockPriceCache({"AAPL": 150.0})
        result = _execute_trade(db_conn, cache, "AAPL", "buy", 10)
        assert "error" not in result
        assert result["quantity"] == 10
        assert result["price"] == 150.0
        # Cash should decrease
        from app.db.repositories import portfolio_repo
        assert portfolio_repo.get_cash(db_conn) == 10000.0 - 1500.0

    def test_buy_insufficient_cash(self, db_conn):
        cache = MockPriceCache({"AAPL": 150.0})
        result = _execute_trade(db_conn, cache, "AAPL", "buy", 1000)
        assert "error" in result
        assert "Insufficient cash" in result["error"]

    def test_sell_no_position(self, db_conn):
        cache = MockPriceCache({"AAPL": 150.0})
        result = _execute_trade(db_conn, cache, "AAPL", "sell", 10)
        assert "error" in result
        assert "Insufficient shares" in result["error"]

    def test_sell_success(self, db_conn):
        cache = MockPriceCache({"AAPL": 150.0})
        # First buy
        _execute_trade(db_conn, cache, "AAPL", "buy", 10)
        # Then sell
        cache._prices["AAPL"] = 160.0
        result = _execute_trade(db_conn, cache, "AAPL", "sell", 5)
        assert "error" not in result
        assert result["quantity"] == 5

    def test_no_price_available(self, db_conn):
        cache = MockPriceCache({})
        result = _execute_trade(db_conn, cache, "AAPL", "buy", 10)
        assert "error" in result
        assert "No price" in result["error"]


# --- Portfolio context tests ---


class TestBuildPortfolioContext:
    def test_empty_portfolio(self, db_conn):
        cache = MockPriceCache({})
        ctx = _build_portfolio_context(db_conn, cache)
        assert ctx["cash"] == 10000.0
        assert ctx["total_value"] == 10000.0
        assert ctx["positions"] == []

    def test_with_positions(self, db_conn):
        from app.db.repositories import portfolio_repo
        portfolio_repo.upsert_position(db_conn, "default", "AAPL", 10, 150.0)
        cache = MockPriceCache({"AAPL": 160.0})
        ctx = _build_portfolio_context(db_conn, cache)
        assert len(ctx["positions"]) == 1
        assert ctx["positions"][0]["unrealized_pnl"] == 100.0


# --- Router integration tests ---


class TestChatRouter:
    @pytest.fixture
    def app(self, db_conn):
        app = FastAPI()
        app.include_router(router)
        app.state.price_cache = MockPriceCache({"AAPL": 150.0, "GOOGL": 175.0})
        app.state.market_source = None

        # Override DB dependency
        def override_get_db():
            yield db_conn

        from app.db.connection import get_db
        app.dependency_overrides[get_db] = override_get_db
        return app

    async def test_chat_mock_mode(self, app):
        with patch.dict(os.environ, {"LLM_MOCK": "true"}):
            # Re-init the service for mock mode
            from app.routers import chat as chat_module
            chat_module.llm_service = LLMService()

            client = TestClient(app)
            resp = client.post("/api/chat", json={"message": "hello"})
            assert resp.status_code == 200
            data = resp.json()
            assert "message" in data
            assert data["trades_executed"] == []

    async def test_chat_with_trade_execution(self, app):
        mock_llm_response = LLMResponse(
            message="Buying 5 shares of AAPL for you!",
            trades=[TradeAction(ticker="AAPL", side="buy", quantity=5)],
        )

        from app.routers import chat as chat_module
        original_service = chat_module.llm_service
        mock_service = LLMService()
        mock_service.chat = AsyncMock(return_value=mock_llm_response)
        chat_module.llm_service = mock_service

        try:
            client = TestClient(app)
            resp = client.post("/api/chat", json={"message": "buy 5 AAPL"})
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["trades_executed"]) == 1
            assert data["trades_executed"][0]["ticker"] == "AAPL"
            assert data["trades_executed"][0]["quantity"] == 5
        finally:
            chat_module.llm_service = original_service
