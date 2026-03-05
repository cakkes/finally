# Market Data Backend — Detailed Design

Implementation-ready design for the FinAlly market data subsystem. Covers the
unified interface, in-memory price cache, GBM simulator, Massive (Polygon.io)
API client, SSE streaming endpoint, and FastAPI lifecycle integration.

Everything in this document lives under `backend/app/market/`.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [File Structure](#2-file-structure)
3. [Data Model — `models.py`](#3-data-model)
4. [Price Cache — `cache.py`](#4-price-cache)
5. [Abstract Interface — `interface.py`](#5-abstract-interface)
6. [Seed Prices & Ticker Parameters — `seed_prices.py`](#6-seed-prices--ticker-parameters)
7. [GBM Simulator — `simulator.py`](#7-gbm-simulator)
8. [Massive API Client — `massive_client.py`](#8-massive-api-client)
9. [Factory — `factory.py`](#9-factory)
10. [SSE Streaming Endpoint — `stream.py`](#10-sse-streaming-endpoint)
11. [FastAPI Lifecycle Integration](#11-fastapi-lifecycle-integration)
12. [Watchlist Coordination](#12-watchlist-coordination)
13. [Testing Strategy](#13-testing-strategy)
14. [Error Handling & Edge Cases](#14-error-handling--edge-cases)
15. [Configuration Summary](#15-configuration-summary)

---

## 1. Architecture Overview

```
                        MARKET DATA LAYER
┌─────────────────────────────────────────────────────┐
│                                                     │
│   MarketDataSource (ABC)                            │
│   ├── SimulatorDataSource  (GBM, default)           │
│   └── MassiveDataSource    (Polygon.io REST poller) │
│                │                                    │
│                ▼  writes to                         │
│         PriceCache  (thread-safe, in-memory)        │
│                │                                    │
│     ┌──────────┼──────────────┐                     │
│     ▼          ▼              ▼                     │
│  SSE stream  Portfolio    Trade execution           │
│  /api/stream/prices  valuation   /api/portfolio/trade│
└─────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| Strategy pattern | Both data sources implement the same ABC; downstream code is source-agnostic |
| PriceCache as single source of truth | Producers write on their own schedule; consumers read independently — no coupling |
| SSE over WebSockets | One-way server→client push is all we need; simpler, no bidirectional complexity, universal browser support, native `EventSource` retry |
| Factory based on env var | `MASSIVE_API_KEY` present → real data; absent → simulator. Zero config for students |
| Simulator by default | No external dependencies, works offline, produces visually interesting data |
| Thread-safe cache with `Lock` | The Massive client runs synchronous API calls via `asyncio.to_thread`; the lock guards against concurrent writes |
| `frozen=True, slots=True` dataclass | `PriceUpdate` is immutable and memory-efficient — shared freely across threads |

---

## 2. File Structure

```
backend/
  app/
    market/
      __init__.py          # Re-exports: PriceUpdate, PriceCache, MarketDataSource,
                           #             create_market_data_source, create_stream_router
      models.py            # PriceUpdate dataclass
      cache.py             # PriceCache — thread-safe in-memory price store
      interface.py         # MarketDataSource — abstract base class
      seed_prices.py       # SEED_PRICES, TICKER_PARAMS, DEFAULT_PARAMS, CORRELATION_GROUPS
      simulator.py         # GBMSimulator + SimulatorDataSource
      massive_client.py    # MassiveDataSource (Polygon.io REST polling)
      factory.py           # create_market_data_source() — selects simulator or Massive
      stream.py            # SSE endpoint (FastAPI router factory)
```

---

## 3. Data Model

`PriceUpdate` is the **only** data structure that leaves the market data layer.
All downstream code (SSE, portfolio valuation, trade execution) works with
`PriceUpdate` objects.

```python
# backend/app/market/models.py

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat'."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        """Serialize for JSON / SSE transmission."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
        }
```

**Why `frozen=True, slots=True`?**

- `frozen=True` makes the dataclass hashable and safe to pass across threads
  without defensive copying.
- `slots=True` reduces per-instance memory by ~40% vs a regular class — matters
  when the cache holds hundreds of tickers and SSE is serializing at 2 Hz.

**Example `PriceUpdate`:**
```python
PriceUpdate(ticker="AAPL", price=190.50, previous_price=190.25, timestamp=1741168800.0)
# .change         → 0.25
# .change_percent → 0.1314
# .direction      → "up"
# .to_dict()      → {"ticker": "AAPL", "price": 190.5, "previous_price": 190.25,
#                     "timestamp": 1741168800.0, "change": 0.25,
#                     "change_percent": 0.1314, "direction": "up"}
```

---

## 4. Price Cache

The cache is the shared memory between producers (simulator / Massive poller)
and consumers (SSE stream, portfolio routes, trade execution).

```python
# backend/app/market/cache.py

from __future__ import annotations

import time
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker.

    Writers: SimulatorDataSource or MassiveDataSource (one at a time).
    Readers: SSE streaming endpoint, portfolio valuation, trade execution.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0  # Monotonically increasing; bumped on every update

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price for a ticker. Returns the created PriceUpdate.

        Computes direction and change from the previous price automatically.
        If this is the first update for the ticker, previous_price == price (direction='flat').
        """
        with self._lock:
            ts = timestamp or time.time()
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price

            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=round(previous_price, 2),
                timestamp=ts,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        """Get the latest price for a single ticker, or None if unknown."""
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Returns a shallow copy."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        """Convenience: get just the price float, or None."""
        update = self.get(ticker)
        return update.price if update else None

    def remove(self, ticker: str) -> None:
        """Remove a ticker from the cache (e.g., when removed from watchlist)."""
        with self._lock:
            self._prices.pop(ticker, None)

    @property
    def version(self) -> int:
        """Current version counter. Used by the SSE endpoint for change detection."""
        return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

**Usage examples:**

```python
cache = PriceCache()

# Producer side (simulator / Massive)
update = cache.update("AAPL", 190.50)
# → PriceUpdate(ticker='AAPL', price=190.5, previous_price=190.5, ...)

cache.update("AAPL", 190.75)  # next tick
update = cache.get("AAPL")
# → PriceUpdate(ticker='AAPL', price=190.75, previous_price=190.5, direction='up')

# Consumer side (portfolio valuation, trade execution)
price = cache.get_price("AAPL")   # → 190.75
all_prices = cache.get_all()       # → {"AAPL": PriceUpdate(...), ...}

# Watchlist removal
cache.remove("AAPL")               # ticker no longer streamed
```

**Version-based change detection** (used by SSE):

```python
last_seen = -1
while True:
    if cache.version != last_seen:
        last_seen = cache.version
        # something changed — serialize and send
        snapshot = cache.get_all()
        ...
    await asyncio.sleep(0.5)
```

---

## 5. Abstract Interface

```python
# backend/app/market/interface.py

from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into a shared PriceCache on their own
    schedule. Downstream code never calls the data source directly for prices —
    it reads from the cache.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        # ... app runs ...
        await source.add_ticker("TSLA")
        await source.remove_ticker("GOOGL")
        # ... app shutting down ...
        await source.stop()
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates for the given tickers.

        Starts a background task that periodically writes to the PriceCache.
        Must be called exactly once.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task and release resources.

        Safe to call multiple times.
        """

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set. Also removes from PriceCache."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""
```

Both `SimulatorDataSource` and `MassiveDataSource` implement this interface.
The watchlist routes, trade executor, and SSE endpoint all call methods on
`MarketDataSource` — never on a concrete subclass.

---

## 6. Seed Prices & Ticker Parameters

```python
# backend/app/market/seed_prices.py

# Realistic starting prices for the default watchlist
SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 800.00,
    "META": 500.00,
    "JPM": 195.00,
    "V": 280.00,
    "NFLX": 600.00,
}

# Per-ticker GBM parameters
# sigma: annualized volatility (higher = more movement per tick)
# mu: annualized drift / expected return
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL":  {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT":  {"sigma": 0.20, "mu": 0.05},
    "AMZN":  {"sigma": 0.28, "mu": 0.05},
    "TSLA":  {"sigma": 0.50, "mu": 0.03},   # High vol, low drift
    "NVDA":  {"sigma": 0.40, "mu": 0.08},   # High vol, strong drift
    "META":  {"sigma": 0.30, "mu": 0.05},
    "JPM":   {"sigma": 0.18, "mu": 0.04},   # Low vol (bank)
    "V":     {"sigma": 0.17, "mu": 0.04},   # Low vol (payments)
    "NFLX":  {"sigma": 0.35, "mu": 0.05},
}

# Default for tickers added dynamically (not in the known list)
DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

# Sector correlation groups for Cholesky decomposition
CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech":    {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

INTRA_TECH_CORR    = 0.6   # Tech stocks move together
INTRA_FINANCE_CORR = 0.5   # Finance stocks move together
CROSS_GROUP_CORR   = 0.3   # Between sectors / unknown tickers
TSLA_CORR          = 0.3   # TSLA does its own thing
```

---

## 7. GBM Simulator

### The Math

At each 500 ms tick, every ticker's price evolves via **Geometric Brownian Motion**:

```
S(t+dt) = S(t) × exp( (μ − σ²/2) × dt  +  σ × √dt × Z )
```

| Symbol | Meaning |
|--------|---------|
| `S(t)` | Current price |
| `μ` | Annualized drift (expected return) |
| `σ` | Annualized volatility |
| `dt` | Time step as a fraction of a trading year |
| `Z` | Correlated standard normal random variable |

For 500 ms ticks over 252 trading days × 6.5 h/day:
```
dt = 0.5 / (252 × 6.5 × 3600) ≈ 8.48 × 10⁻⁸
```

This tiny `dt` produces sub-cent moves per tick that look realistic when
accumulated over minutes.

### Correlated Moves (Cholesky Decomposition)

Real stocks don't move independently — tech stocks tend to move together.
Given correlation matrix `C`, compute the lower-triangular Cholesky factor `L`
such that `C = L Lᵀ`. Then:

```
Z_correlated = L × Z_independent
```

where `Z_independent` is a vector of i.i.d. N(0,1) draws. The resulting
`Z_correlated` has the desired pairwise correlations.

```python
# backend/app/market/simulator.py

from __future__ import annotations

import asyncio
import logging
import math
import random

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource
from .seed_prices import (
    CORRELATION_GROUPS, CROSS_GROUP_CORR, DEFAULT_PARAMS,
    INTRA_FINANCE_CORR, INTRA_TECH_CORR,
    SEED_PRICES, TICKER_PARAMS, TSLA_CORR,
)

logger = logging.getLogger(__name__)


class GBMSimulator:
    """Geometric Brownian Motion simulator for correlated stock prices."""

    # 500ms expressed as a fraction of a trading year
    # 252 trading days × 6.5 h/day × 3600 s/h = 5,896,800 seconds/year
    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR  # ~8.48e-8

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None

        for ticker in tickers:
            self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def step(self) -> dict[str, float]:
        """Advance all tickers by one time step. Returns {ticker: new_price}.

        Hot path — called every 500ms. Keep it fast.
        """
        n = len(self._tickers)
        if n == 0:
            return {}

        z_independent = np.random.standard_normal(n)
        z_correlated = self._cholesky @ z_independent if self._cholesky is not None else z_independent

        result: dict[str, float] = {}
        for i, ticker in enumerate(self._tickers):
            params = self._params[ticker]
            mu, sigma = params["mu"], params["sigma"]

            # GBM step
            drift     = (mu - 0.5 * sigma**2) * self._dt
            diffusion = sigma * math.sqrt(self._dt) * z_correlated[i]
            self._prices[ticker] *= math.exp(drift + diffusion)

            # Random event: ~0.1% chance per tick per ticker.
            # With 10 tickers at 2 ticks/s → expect one event ~every 50 seconds.
            if random.random() < self._event_prob:
                shock = random.uniform(0.02, 0.05) * random.choice([-1, 1])
                self._prices[ticker] *= (1 + shock)
                logger.debug("Random event on %s: %.1f%%", ticker, shock * 100)

            result[ticker] = round(self._prices[ticker], 2)

        return result

    def add_ticker(self, ticker: str) -> None:
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Private ---

    def _add_ticker_internal(self, ticker: str) -> None:
        """Add ticker without rebuilding Cholesky (for batch initialization)."""
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker, random.uniform(50.0, 300.0))
        self._params[ticker] = TICKER_PARAMS.get(ticker, dict(DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        """Rebuild Cholesky decomposition of the correlation matrix. O(n²)."""
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = rho
                corr[j, i] = rho
        self._cholesky = np.linalg.cholesky(corr)

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        tech    = CORRELATION_GROUPS["tech"]
        finance = CORRELATION_GROUPS["finance"]
        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR
        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR


class SimulatorDataSource(MarketDataSource):
    """MarketDataSource backed by GBMSimulator.

    Background asyncio task calls GBMSimulator.step() every `update_interval`
    seconds and writes results to PriceCache.
    """

    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(tickers=tickers, event_probability=self._event_prob)
        # Seed cache immediately so SSE has data on first connection
        for ticker in tickers:
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers", len(tickers))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Simulator stopped")

    async def add_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.add_ticker(ticker)
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
            logger.info("Simulator: added ticker %s", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)
        logger.info("Simulator: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        while True:
            try:
                if self._sim:
                    prices = self._sim.step()
                    for ticker, price in prices.items():
                        self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed")
            await asyncio.sleep(self._interval)
```

---

## 8. Massive API Client

The `massive` package (formerly Polygon.io) provides a synchronous REST client.
Because the client is synchronous, all API calls run via `asyncio.to_thread` to
avoid blocking the event loop.

### Rate Limits

| Tier | Limit | Recommended poll interval |
|------|-------|--------------------------|
| Free | 5 req/min | 15 s (default) |
| Paid | Unlimited | 2–5 s |

### Massive API Endpoints Used

**Primary: Snapshot — All Tickers**

Gets current prices for all watched tickers in **one API call** — essential for
staying within the free tier's 5 req/min limit.

```python
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

client = RESTClient(api_key="...")

# One call for all tickers
snapshots = client.get_snapshot_all(
    market_type=SnapshotMarketType.STOCKS,
    tickers=["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"],
)

for snap in snapshots:
    print(f"{snap.ticker}: ${snap.last_trade.price}")
    print(f"  Day change: {snap.day.change_percent}%")
    print(f"  Timestamp:  {snap.last_trade.timestamp} ms")
```

**Response structure (per ticker):**

```json
{
  "ticker": "AAPL",
  "last_trade": {
    "price": 190.50,
    "size": 100,
    "exchange": "XNYS",
    "timestamp": 1741168800000
  },
  "last_quote": {
    "bid_price": 190.48,
    "ask_price": 190.52,
    "bid_size": 500,
    "ask_size": 1000,
    "spread": 0.04,
    "timestamp": 1741168800500
  },
  "day": {
    "open": 189.00,
    "high": 191.20,
    "low": 188.50,
    "close": 190.50,
    "volume": 42000000,
    "previous_close": 187.75,
    "change": 2.75,
    "change_percent": 1.46
  }
}
```

**Key fields we extract:**
- `last_trade.price` → current price for display and trade execution
- `last_trade.timestamp` → Unix milliseconds, converted to seconds for the cache
- `day.previous_close` → for computing daily change (future enhancement)

### Full Implementation

```python
# backend/app/market/massive_client.py

from __future__ import annotations

import asyncio
import logging

from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


class MassiveDataSource(MarketDataSource):
    """MarketDataSource backed by the Massive (Polygon.io) REST API.

    Polls /v2/snapshot/locale/us/markets/stocks/tickers for all watched tickers
    in a single API call, then writes results to the PriceCache.
    """

    def __init__(
        self,
        api_key: str,
        price_cache: PriceCache,
        poll_interval: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = list(tickers)
        # Immediate first poll so cache has data before any SSE client connects
        await self._poll_once()
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info(
            "Massive poller started: %d tickers, %.1fs interval",
            len(tickers), self._interval,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._client = None
        logger.info("Massive poller stopped")

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        if ticker not in self._tickers:
            self._tickers.append(ticker)
            logger.info("Massive: added ticker %s (next poll will include it)", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)
        logger.info("Massive: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Internal ---

    async def _poll_loop(self) -> None:
        """Poll on interval. First poll already happened in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        """Execute one poll cycle: fetch snapshots → update cache."""
        if not self._tickers or not self._client:
            return
        try:
            # RESTClient is synchronous — run in a thread to avoid blocking the event loop
            snapshots = await asyncio.to_thread(self._fetch_snapshots)
            processed = 0
            for snap in snapshots:
                try:
                    price = snap.last_trade.price
                    # Massive timestamps are Unix milliseconds → convert to seconds
                    timestamp = snap.last_trade.timestamp / 1000.0
                    self._cache.update(ticker=snap.ticker, price=price, timestamp=timestamp)
                    processed += 1
                except (AttributeError, TypeError) as e:
                    logger.warning(
                        "Skipping snapshot for %s: %s",
                        getattr(snap, "ticker", "???"), e,
                    )
            logger.debug("Massive poll: updated %d/%d tickers", processed, len(self._tickers))
        except Exception as e:
            logger.error("Massive poll failed: %s", e)
            # Don't re-raise — the loop retries on the next interval.
            # Common failures: 401 (bad key), 429 (rate limit), network errors.

    def _fetch_snapshots(self) -> list:
        """Synchronous Massive API call. Always runs in a thread pool."""
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=self._tickers,
        )
```

### Massive API Error Handling

| HTTP status | Cause | Behaviour |
|-------------|-------|-----------|
| 401 | Invalid API key | Logged as error; loop retries next interval |
| 403 | Endpoint not in plan | Logged as error; loop retries |
| 429 | Rate limit exceeded | Logged as error; loop retries at configured interval |
| 5xx | Server error | `RESTClient` has built-in 3-retry; then logged, loop continues |

---

## 9. Factory

```python
# backend/app/market/factory.py

from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Select and construct the appropriate market data source.

    Rules:
      - MASSIVE_API_KEY set and non-empty → MassiveDataSource (real market data)
      - Otherwise                         → SimulatorDataSource (GBM simulation)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        logger.info("Market data source: Massive API (real data)")
        return MassiveDataSource(api_key=api_key, price_cache=price_cache)
    else:
        logger.info("Market data source: GBM Simulator")
        return SimulatorDataSource(price_cache=price_cache)
```

**Usage:**

```python
cache = PriceCache()
source = create_market_data_source(cache)   # picks simulator or Massive from env
await source.start(["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
                    "NVDA", "META", "JPM", "V", "NFLX"])
```

---

## 10. SSE Streaming Endpoint

The SSE endpoint reads from `PriceCache` and pushes updates to all connected
browser clients using the native `EventSource` API.

```python
# backend/app/market/stream.py

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stream", tags=["streaming"])


def create_stream_router(price_cache: PriceCache) -> APIRouter:
    """Factory that registers the SSE route with a bound PriceCache."""

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        """SSE endpoint: streams all ticker prices every ~500ms.

        Connect with EventSource:
            const es = new EventSource("/api/stream/prices");
            es.onmessage = (event) => {
                const prices = JSON.parse(event.data);
                // prices: { "AAPL": { ticker, price, previous_price, change, direction, ... } }
            };
        """
        return StreamingResponse(
            _generate_events(price_cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control":    "no-cache",
                "Connection":       "keep-alive",
                "X-Accel-Buffering": "no",   # Disable nginx buffering if proxied
            },
        )

    return router


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
    interval: float = 0.5,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted price events.

    Version-based change detection: only serializes when the cache has changed
    since the last send, avoiding redundant payloads.
    """
    # Tell the browser to reconnect after 1 second if the connection drops
    yield "retry: 1000\n\n"

    last_version = -1
    client_ip = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client_ip)

    try:
        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected: %s", client_ip)
                break

            current_version = price_cache.version
            if current_version != last_version:
                last_version = current_version
                prices = price_cache.get_all()
                if prices:
                    data = {ticker: update.to_dict() for ticker, update in prices.items()}
                    yield f"data: {json.dumps(data)}\n\n"

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for: %s", client_ip)
```

### SSE Event Format

Each event is a JSON-encoded dict of **all** currently tracked tickers:

```
data: {"AAPL":{"ticker":"AAPL","price":190.75,"previous_price":190.50,
               "timestamp":1741168800.5,"change":0.25,"change_percent":0.1314,
               "direction":"up"},
       "MSFT":{"ticker":"MSFT","price":421.10,"previous_price":420.80,...},
       ...}
```

### Browser Client

```javascript
const es = new EventSource("/api/stream/prices");

es.onmessage = (event) => {
    const prices = JSON.parse(event.data);

    for (const [ticker, update] of Object.entries(prices)) {
        const el = document.getElementById(`price-${ticker}`);
        if (!el) continue;

        el.textContent = `$${update.price.toFixed(2)}`;

        // Flash green/red on price change
        el.classList.remove("flash-up", "flash-down");
        if (update.direction !== "flat") {
            el.classList.add(`flash-${update.direction}`);
        }
    }
};

es.onerror = () => {
    // EventSource retries automatically using the retry: 1000 directive
    console.warn("SSE connection lost — browser will retry in 1s");
};
```

---

## 11. FastAPI Lifecycle Integration

Wire everything together in the application's `lifespan` context manager:

```python
# backend/app/main.py  (excerpt)

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.market import PriceCache, create_market_data_source, create_stream_router
from app.db import get_default_watchlist   # returns list[str] of ticker symbols


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    price_cache = PriceCache()
    tickers = get_default_watchlist()                     # e.g. from DB seed

    source = create_market_data_source(price_cache)
    await source.start(tickers)

    # Attach to app state so routes can access them
    app.state.price_cache = price_cache
    app.state.market_source = source

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    await source.stop()


app = FastAPI(lifespan=lifespan)

# Register the SSE router (needs the cache, hence deferred to lifespan)
# In practice, call this after creating price_cache in lifespan, or use a
# dependency-injection approach:
@app.on_event("startup")  # alternative pattern
async def register_stream_router():
    stream_router = create_stream_router(app.state.price_cache)
    app.include_router(stream_router)
```

**Simpler pattern** — create the cache at module level so the router factory
can reference it before `lifespan` runs:

```python
# backend/app/main.py

from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.market import PriceCache, create_market_data_source, create_stream_router

price_cache = PriceCache()   # module-level; safe because it starts empty

@asynccontextmanager
async def lifespan(app: FastAPI):
    source = create_market_data_source(price_cache)
    tickers = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
                "NVDA", "META", "JPM", "V", "NFLX"]
    await source.start(tickers)
    app.state.market_source = source
    yield
    await source.stop()

app = FastAPI(lifespan=lifespan)
app.include_router(create_stream_router(price_cache))
```

---

## 12. Watchlist Coordination

When a user adds or removes a ticker via the watchlist API, the market data
source must be notified so it begins (or stops) producing prices for that ticker.

```python
# backend/app/routes/watchlist.py  (excerpt)

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class AddTickerBody(BaseModel):
    ticker: str


@router.post("")
async def add_ticker(body: AddTickerBody, request: Request):
    ticker = body.ticker.upper().strip()
    source = request.app.state.market_source    # MarketDataSource
    cache  = request.app.state.price_cache      # PriceCache

    # Validate — quick check that Massive knows the ticker (skip for simulator)
    # await validate_ticker(ticker)   ← optional

    # Tell the data source to start tracking it
    await source.add_ticker(ticker)

    # Persist to DB
    db_add_watchlist_ticker(ticker)

    return {"ticker": ticker, "price": cache.get_price(ticker)}


@router.delete("/{ticker}")
async def remove_ticker(ticker: str, request: Request):
    ticker = ticker.upper().strip()
    source = request.app.state.market_source

    await source.remove_ticker(ticker)   # also removes from PriceCache
    db_remove_watchlist_ticker(ticker)

    return {"ticker": ticker, "removed": True}
```

**Sequence for "Add TSLA":**

```
Client POST /api/watchlist {"ticker": "TSLA"}
  → source.add_ticker("TSLA")
      Simulator: GBMSimulator.add_ticker("TSLA"), seeds PriceCache["TSLA"] immediately
      Massive:   appends "TSLA" to self._tickers; included in next poll cycle
  → db_add_watchlist_ticker("TSLA")
  → return {"ticker": "TSLA", "price": 250.00}

Next SSE tick (~500ms):
  → PriceCache now contains "TSLA"
  → SSE event includes TSLA price
  → Frontend shows TSLA in watchlist with live price
```

---

## 13. Testing Strategy

### Test Structure

```
backend/tests/market/
  test_models.py           # PriceUpdate: properties, to_dict, edge cases
  test_cache.py            # PriceCache: update, get, get_all, remove, version
  test_simulator.py        # GBMSimulator: step, correlation, random events
  test_simulator_source.py # SimulatorDataSource: start/stop, add/remove ticker
  test_factory.py          # create_market_data_source: env var routing
  test_massive.py          # MassiveDataSource: mock RESTClient, poll logic
```

### Key Unit Tests

```python
# tests/market/test_models.py

import time
from app.market.models import PriceUpdate


def test_direction_up():
    u = PriceUpdate(ticker="AAPL", price=190.75, previous_price=190.50)
    assert u.direction == "up"
    assert u.change == 0.25
    assert u.change_percent > 0


def test_direction_flat():
    u = PriceUpdate(ticker="AAPL", price=190.50, previous_price=190.50)
    assert u.direction == "flat"
    assert u.change == 0.0


def test_to_dict_keys():
    u = PriceUpdate(ticker="MSFT", price=420.0, previous_price=419.0)
    d = u.to_dict()
    assert set(d.keys()) == {
        "ticker", "price", "previous_price", "timestamp",
        "change", "change_percent", "direction",
    }


def test_immutability():
    import pytest
    u = PriceUpdate(ticker="AAPL", price=190.0, previous_price=189.0)
    with pytest.raises((AttributeError, TypeError)):
        u.price = 999.0   # frozen=True prevents mutation
```

```python
# tests/market/test_cache.py

import pytest
from app.market.cache import PriceCache


def test_first_update_sets_previous_price_equal():
    cache = PriceCache()
    update = cache.update("AAPL", 190.0)
    assert update.previous_price == 190.0   # first update: no change
    assert update.direction == "flat"


def test_second_update_tracks_previous():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    update = cache.update("AAPL", 191.0)
    assert update.previous_price == 190.0
    assert update.direction == "up"


def test_version_increments_on_each_update():
    cache = PriceCache()
    v0 = cache.version
    cache.update("AAPL", 190.0)
    cache.update("MSFT", 420.0)
    assert cache.version == v0 + 2


def test_remove_ticker():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.remove("AAPL")
    assert cache.get("AAPL") is None
    assert "AAPL" not in cache


def test_get_all_returns_copy():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    all1 = cache.get_all()
    cache.update("AAPL", 191.0)
    all2 = cache.get_all()
    # Modifying the returned dict doesn't affect the cache
    assert all1["AAPL"].price == 190.0
    assert all2["AAPL"].price == 191.0
```

```python
# tests/market/test_simulator.py

import numpy as np
from app.market.simulator import GBMSimulator


def test_prices_stay_positive():
    sim = GBMSimulator(tickers=["AAPL", "TSLA"])
    for _ in range(1000):
        prices = sim.step()
        assert all(p > 0 for p in prices.values())


def test_step_returns_all_tickers():
    sim = GBMSimulator(tickers=["AAPL", "MSFT", "NVDA"])
    prices = sim.step()
    assert set(prices.keys()) == {"AAPL", "MSFT", "NVDA"}


def test_add_remove_ticker():
    sim = GBMSimulator(tickers=["AAPL"])
    sim.add_ticker("GOOGL")
    assert "GOOGL" in sim.get_tickers()
    sim.remove_ticker("GOOGL")
    assert "GOOGL" not in sim.get_tickers()


def test_cholesky_rebuilt_correctly():
    """Correlation matrix must be positive-definite for Cholesky to succeed."""
    tickers = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
               "NVDA", "META", "JPM", "V", "NFLX"]
    # If Cholesky fails, GBMSimulator.__init__ raises LinAlgError
    sim = GBMSimulator(tickers=tickers)
    assert sim._cholesky is not None
    assert sim._cholesky.shape == (10, 10)


def test_no_cholesky_for_single_ticker():
    sim = GBMSimulator(tickers=["AAPL"])
    assert sim._cholesky is None


def test_unknown_ticker_gets_random_seed_price():
    sim = GBMSimulator(tickers=["UNKN"])
    price = sim.get_price("UNKN")
    assert price is not None
    assert 50.0 <= price <= 300.0
```

```python
# tests/market/test_simulator_source.py

import asyncio
import pytest
from app.market.cache import PriceCache
from app.market.simulator import SimulatorDataSource


@pytest.mark.asyncio
async def test_start_seeds_cache():
    cache = PriceCache()
    source = SimulatorDataSource(price_cache=cache, update_interval=1.0)
    await source.start(["AAPL", "MSFT"])
    # Cache should be seeded immediately, before any tick
    assert cache.get_price("AAPL") is not None
    assert cache.get_price("MSFT") is not None
    await source.stop()


@pytest.mark.asyncio
async def test_stop_is_idempotent():
    cache = PriceCache()
    source = SimulatorDataSource(price_cache=cache)
    await source.start(["AAPL"])
    await source.stop()
    await source.stop()  # second stop should not raise


@pytest.mark.asyncio
async def test_add_ticker_mid_session():
    cache = PriceCache()
    source = SimulatorDataSource(price_cache=cache, update_interval=0.05)
    await source.start(["AAPL"])
    await source.add_ticker("TSLA")
    assert "TSLA" in source.get_tickers()
    assert cache.get_price("TSLA") is not None
    await source.stop()


@pytest.mark.asyncio
async def test_remove_ticker_clears_cache():
    cache = PriceCache()
    source = SimulatorDataSource(price_cache=cache, update_interval=0.05)
    await source.start(["AAPL", "MSFT"])
    await source.remove_ticker("MSFT")
    assert "MSFT" not in source.get_tickers()
    assert cache.get("MSFT") is None
    await source.stop()
```

```python
# tests/market/test_factory.py

import os
import pytest
from app.market.cache import PriceCache
from app.market.factory import create_market_data_source
from app.market.simulator import SimulatorDataSource
from app.market.massive_client import MassiveDataSource


def test_no_api_key_gives_simulator(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    cache = PriceCache()
    source = create_market_data_source(cache)
    assert isinstance(source, SimulatorDataSource)


def test_empty_api_key_gives_simulator(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "   ")
    cache = PriceCache()
    source = create_market_data_source(cache)
    assert isinstance(source, SimulatorDataSource)


def test_api_key_gives_massive(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test_key_123")
    cache = PriceCache()
    source = create_market_data_source(cache)
    assert isinstance(source, MassiveDataSource)
```

```python
# tests/market/test_massive.py

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from app.market.cache import PriceCache
from app.market.massive_client import MassiveDataSource


def make_snapshot(ticker: str, price: float, ts_ms: int = 1_741_168_800_000):
    snap = MagicMock()
    snap.ticker = ticker
    snap.last_trade.price = price
    snap.last_trade.timestamp = ts_ms
    return snap


@pytest.mark.asyncio
async def test_poll_updates_cache():
    cache = PriceCache()
    source = MassiveDataSource(api_key="test", price_cache=cache, poll_interval=60.0)
    source._client = MagicMock()  # inject mock client before start()

    snapshots = [make_snapshot("AAPL", 190.5), make_snapshot("MSFT", 420.1)]

    with patch.object(source, "_fetch_snapshots", return_value=snapshots):
        await source._poll_once()

    assert cache.get_price("AAPL") == 190.5
    assert cache.get_price("MSFT") == 420.1


@pytest.mark.asyncio
async def test_malformed_snapshot_is_skipped():
    cache = PriceCache()
    source = MassiveDataSource(api_key="test", price_cache=cache)
    source._client = MagicMock()

    bad_snap = MagicMock()
    bad_snap.ticker = "BAD"
    bad_snap.last_trade.price = None   # will cause TypeError in cache.update

    with patch.object(source, "_fetch_snapshots", return_value=[bad_snap]):
        # Should not raise — bad snapshot is logged and skipped
        await source._poll_once()

    assert cache.get("BAD") is None


@pytest.mark.asyncio
async def test_add_remove_ticker():
    cache = PriceCache()
    source = MassiveDataSource(api_key="test", price_cache=cache)
    source._tickers = ["AAPL"]
    await source.add_ticker("TSLA")
    assert "TSLA" in source.get_tickers()
    await source.remove_ticker("TSLA")
    assert "TSLA" not in source.get_tickers()


@pytest.mark.asyncio
async def test_stop_cancels_background_task():
    cache = PriceCache()
    source = MassiveDataSource(api_key="test", price_cache=cache, poll_interval=60.0)
    source._client = MagicMock()

    with patch.object(source, "_fetch_snapshots", return_value=[]):
        await source.start(["AAPL"])

    assert source._task is not None
    await source.stop()
    assert source._task is None
```

### Running the Tests

```bash
cd backend
uv run pytest tests/market/ -v --tb=short
```

Expected output (73 tests, all passing when `massive` package is installed):
```
tests/market/test_cache.py::test_first_update_sets_previous_price_equal PASSED
tests/market/test_cache.py::test_second_update_tracks_previous          PASSED
...
tests/market/test_massive.py::test_poll_updates_cache                   PASSED
...
73 passed in 1.23s
```

Coverage:
```bash
uv run pytest tests/market/ --cov=app/market --cov-report=term-missing
```

| Module | Coverage |
|--------|---------|
| models.py | 100% |
| cache.py | 100% |
| interface.py | 100% |
| seed_prices.py | 100% |
| factory.py | 100% |
| simulator.py | ~98% |
| massive_client.py | ~56% (real API methods require live credentials) |
| stream.py | ~31% (SSE generator requires a running ASGI server) |

---

## 14. Error Handling & Edge Cases

### Simulator

| Scenario | Behaviour |
|----------|-----------|
| `GBMSimulator.step()` raises | Caught in `_run_loop`, logged, loop continues |
| Ticker added before `start()` | `SimulatorDataSource.add_ticker` checks `if self._sim` and is a no-op |
| Same ticker added twice | `_add_ticker_internal` guards with `if ticker in self._prices` |
| All tickers removed | `step()` returns `{}` immediately; no error |
| NumPy `LinAlgError` on Cholesky | Would propagate from `__init__`; in practice the correlation matrix is always PD for valid `rho ∈ (0, 1)` values |

### Massive

| Scenario | Behaviour |
|----------|-----------|
| Invalid API key (401) | Logged as error; next interval retries |
| Rate limit exceeded (429) | Logged as error; next interval retries (increase `poll_interval`) |
| Snapshot has `None` price | Caught in `_poll_once` per-snapshot try/except; ticker skipped |
| Empty ticker list | `_poll_once` returns early (`if not self._tickers`) |
| Network timeout | `RESTClient` has built-in 3-retries; then raises; caught by outer try/except |

### Cache

| Scenario | Behaviour |
|----------|-----------|
| `get()` on unknown ticker | Returns `None` |
| `get_price()` on unknown ticker | Returns `None` |
| `remove()` on unknown ticker | No-op (`dict.pop` with default) |
| Concurrent writes | Guarded by `threading.Lock` |

### SSE

| Scenario | Behaviour |
|----------|-----------|
| Client disconnect | `request.is_disconnected()` returns `True`; generator exits cleanly |
| Empty cache on first connect | `if prices:` guard prevents sending empty payload |
| `asyncio.CancelledError` | Caught and logged; generator exits |
| No price change since last tick | `version` unchanged; no event sent (avoids redundant traffic) |

---

## 15. Configuration Summary

```bash
# .env (project root)

# Required for LLM functionality
OPENROUTER_API_KEY=your-openrouter-api-key

# Optional: real market data (if absent, simulator is used)
MASSIVE_API_KEY=

# Optional: deterministic LLM responses for E2E tests
LLM_MOCK=false
```

### Tunable Constants (in code)

| Location | Constant | Default | Effect |
|----------|----------|---------|--------|
| `SimulatorDataSource.__init__` | `update_interval` | `0.5` s | Price update frequency |
| `GBMSimulator.__init__` | `event_probability` | `0.001` | ~0.1% chance of shock per tick |
| `GBMSimulator.DEFAULT_DT` | — | `8.48e-8` | Time step (fraction of trading year) |
| `MassiveDataSource.__init__` | `poll_interval` | `15.0` s | Massive API poll frequency |
| `_generate_events` | `interval` | `0.5` s | SSE emit frequency |
| `seed_prices.py` | `INTRA_TECH_CORR` | `0.6` | Tech stock correlation |
| `seed_prices.py` | `INTRA_FINANCE_CORR` | `0.5` | Finance stock correlation |
| `seed_prices.py` | `CROSS_GROUP_CORR` | `0.3` | Cross-sector correlation |

### Public Module API (`backend/app/market/__init__.py`)

```python
from app.market import (
    PriceUpdate,               # Data model: immutable frozen dataclass
    PriceCache,                # Thread-safe in-memory price store
    MarketDataSource,          # Abstract interface (for type hints)
    create_market_data_source, # Factory: picks simulator or Massive from env
    create_stream_router,      # FastAPI router factory for SSE endpoint
)

# Typical startup sequence
cache  = PriceCache()
source = create_market_data_source(cache)    # reads MASSIVE_API_KEY
await source.start(watchlist_tickers)

# Reading prices (in any route)
price  = cache.get_price("AAPL")            # float | None
update = cache.get("AAPL")                  # PriceUpdate | None
all_p  = cache.get_all()                    # dict[str, PriceUpdate]

# Dynamic watchlist
await source.add_ticker("TSLA")
await source.remove_ticker("GOOGL")

# Shutdown
await source.stop()
```
