"""Tests for FastAPI REST API endpoints."""

import os
import sqlite3
import tempfile
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import get_db
from app.db.init_db import init_database
from app.market import PriceCache
from app.routers import health, portfolio, watchlist


class MockMarketSource:
    async def add_ticker(self, ticker: str):
        pass

    async def remove_ticker(self, ticker: str):
        pass


@pytest.fixture()
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    init_database(path)
    yield path
    os.unlink(path)


@pytest.fixture()
def price_cache():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("GOOGL", 175.0)
    cache.update("MSFT", 420.0)
    cache.update("AMZN", 185.0)
    cache.update("TSLA", 250.0)
    cache.update("NVDA", 880.0)
    cache.update("META", 500.0)
    cache.update("JPM", 195.0)
    cache.update("V", 280.0)
    cache.update("NFLX", 620.0)
    return cache


def _make_db_dependency(db_path: str):
    def get_test_db():
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    return get_test_db


@pytest.fixture()
def client(db_path, price_cache):
    test_app = FastAPI()
    test_app.include_router(health.router)
    test_app.include_router(watchlist.router)
    test_app.include_router(portfolio.router)

    test_app.dependency_overrides[get_db] = _make_db_dependency(db_path)
    test_app.state.price_cache = price_cache
    test_app.state.market_source = MockMarketSource()

    with TestClient(test_app, raise_server_exceptions=False) as c:
        yield c


class TestHealth:
    def test_health_check(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "timestamp" in data


class TestWatchlist:
    def test_get_watchlist(self, client):
        resp = client.get("/api/watchlist")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 10
        tickers = [e["ticker"] for e in data]
        assert "AAPL" in tickers
        assert "GOOGL" in tickers

    def test_get_watchlist_has_prices(self, client):
        resp = client.get("/api/watchlist")
        data = resp.json()
        aapl = next(e for e in data if e["ticker"] == "AAPL")
        assert aapl["price"] == 190.0

    def test_add_ticker(self, client):
        resp = client.post("/api/watchlist", json={"ticker": "PYPL"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["ticker"] == "PYPL"

    def test_add_duplicate_ticker(self, client):
        resp = client.post("/api/watchlist", json={"ticker": "AAPL"})
        assert resp.status_code == 409

    def test_remove_ticker(self, client):
        resp = client.delete("/api/watchlist/AAPL")
        assert resp.status_code == 204
        resp = client.get("/api/watchlist")
        tickers = [e["ticker"] for e in resp.json()]
        assert "AAPL" not in tickers

    def test_remove_nonexistent_ticker(self, client):
        resp = client.delete("/api/watchlist/ZZZZ")
        assert resp.status_code == 404


class TestPortfolio:
    def test_get_portfolio_initial(self, client):
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cash_balance"] == 10000.0
        assert data["positions"] == []
        assert data["total_value"] == 10000.0
        assert data["total_unrealized_pnl"] == 0.0

    def test_buy_shares(self, client):
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 10, "side": "buy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["trade"]["ticker"] == "AAPL"
        assert data["trade"]["side"] == "buy"
        assert data["trade"]["quantity"] == 10
        assert data["trade"]["price"] == 190.0
        portfolio = data["portfolio"]
        assert portfolio["cash_balance"] == 10000.0 - 190.0 * 10
        assert len(portfolio["positions"]) == 1
        assert portfolio["positions"][0]["ticker"] == "AAPL"
        assert portfolio["positions"][0]["quantity"] == 10

    def test_sell_shares(self, client):
        client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 10, "side": "buy"},
        )
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 5, "side": "sell"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["trade"]["side"] == "sell"
        assert data["trade"]["quantity"] == 5
        portfolio = data["portfolio"]
        assert portfolio["positions"][0]["quantity"] == 5

    def test_sell_all_shares_removes_position(self, client):
        client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 10, "side": "buy"},
        )
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 10, "side": "sell"},
        )
        assert resp.status_code == 200
        portfolio = resp.json()["portfolio"]
        assert len(portfolio["positions"]) == 0
        assert portfolio["cash_balance"] == 10000.0

    def test_buy_insufficient_cash(self, client):
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 1000, "side": "buy"},
        )
        assert resp.status_code == 400
        assert "Insufficient cash" in resp.json()["detail"]

    def test_sell_insufficient_shares(self, client):
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 10, "side": "sell"},
        )
        assert resp.status_code == 400
        assert "Insufficient shares" in resp.json()["detail"]

    def test_buy_no_price_available(self, client):
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "ZZZZ", "quantity": 1, "side": "buy"},
        )
        assert resp.status_code == 400
        assert "No price available" in resp.json()["detail"]

    def test_buy_updates_avg_cost(self, client):
        client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 10, "side": "buy"},
        )
        client.app.state.price_cache.update("AAPL", 200.0)
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 10, "side": "buy"},
        )
        portfolio = resp.json()["portfolio"]
        pos = portfolio["positions"][0]
        assert pos["quantity"] == 20
        assert pos["avg_cost"] == 195.0

    def test_portfolio_pnl_calculation(self, client):
        client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 10, "side": "buy"},
        )
        client.app.state.price_cache.update("AAPL", 200.0)
        resp = client.get("/api/portfolio")
        data = resp.json()
        pos = data["positions"][0]
        assert pos["unrealized_pnl"] == 100.0
        assert pos["pnl_pct"] == pytest.approx(5.26, abs=0.01)

    def test_portfolio_history(self, client):
        resp = client.get("/api/portfolio/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_trade_records_snapshot(self, client):
        client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 10, "side": "buy"},
        )
        resp = client.get("/api/portfolio/history")
        data = resp.json()
        assert len(data) >= 1

    def test_invalid_side(self, client):
        resp = client.post(
            "/api/portfolio/trade",
            json={"ticker": "AAPL", "quantity": 10, "side": "short"},
        )
        assert resp.status_code == 422
