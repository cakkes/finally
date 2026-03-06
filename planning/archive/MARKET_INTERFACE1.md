# Market Data Interface Design

Unified Python interface for market data in FinAlly. Two concrete implementations — simulator and Massive API — sit behind one abstract interface. All downstream code (SSE streaming, portfolio valuation, trade execution) is source-agnostic.

## Module Location

```
backend/app/market/
  __init__.py          # Public re-exports
  models.py            # PriceUpdate dataclass
  interface.py         # MarketDataSource ABC
  cache.py             # PriceCache
  factory.py           # create_market_data_source()
  massive_client.py    # MassiveDataSource
  simulator.py         # SimulatorDataSource + GBMSimulator
  seed_prices.py       # Seed prices and per-ticker GBM params
  stream.py            # SSE FastAPI router factory
```

## Core Data Model — `PriceUpdate`

```python
# backend/app/market/models.py
from dataclasses import dataclass, field
import time

@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""
    ticker: str
    price: float           # Rounded to 2 decimal places
    previous_price: float  # Price from the preceding update
    timestamp: float       # Unix seconds (default: time.time())

    @property
    def change(self) -> float:
        """Absolute price change (price - previous_price), rounded to 4dp."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous price, rounded to 4dp."""
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

`PriceUpdate` is the **only** data structure that leaves the market data layer. Every consumer — the SSE endpoint, portfolio valuation, trade execution — works exclusively with `PriceUpdate` objects read from `PriceCache`.

## Abstract Interface — `MarketDataSource`

```python
# backend/app/market/interface.py
from abc import ABC, abstractmethod

class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into a shared PriceCache on their
    own schedule. Downstream code never calls the data source directly for
    prices — it always reads from the cache.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        # ... app running ...
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

        Safe to call multiple times. After stop(), no further writes to cache.
        """

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present.

        The next update cycle will include this ticker.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set. No-op if not present.

        Also removes the ticker from the PriceCache.
        """

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""
```

Note: `get_tickers()` is the only synchronous method. All lifecycle methods are `async` because both implementations use asyncio tasks internally.

## Price Cache — `PriceCache`

The shared in-memory store. One writer (the active data source), multiple readers.

```python
# backend/app/market/cache.py
from threading import Lock
from .models import PriceUpdate

class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker.

    Writers: SimulatorDataSource or MassiveDataSource (exactly one at a time).
    Readers: SSE streaming endpoint, portfolio valuation, trade execution.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0  # Increments on every update (for SSE change detection)

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price. Returns the created PriceUpdate.

        previous_price is taken from the prior entry for this ticker.
        On first update for a ticker, previous_price == price (direction='flat').
        """
        ...

    def get(self, ticker: str) -> PriceUpdate | None:
        """Latest PriceUpdate for a ticker, or None if unknown."""
        ...

    def get_price(self, ticker: str) -> float | None:
        """Convenience: get just the price float, or None."""
        ...

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Returns a shallow copy."""
        ...

    def remove(self, ticker: str) -> None:
        """Remove a ticker (called when removed from watchlist)."""
        ...

    @property
    def version(self) -> int:
        """Monotonic counter. Increments on every update."""
        ...
```

### Version-Based Change Detection

The SSE stream uses `PriceCache.version` to avoid sending duplicate events:

```python
last_version = -1
while True:
    current_version = price_cache.version
    if current_version != last_version:
        last_version = current_version
        prices = price_cache.get_all()
        yield f"data: {json.dumps({t: p.to_dict() for t, p in prices.items()})}\n\n"
    await asyncio.sleep(0.5)
```

This means the SSE endpoint sends an event only when something has actually changed — no redundant pushes.

## Factory Function — `create_market_data_source()`

```python
# backend/app/market/factory.py
import os
from .cache import PriceCache
from .interface import MarketDataSource

def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Create the appropriate market data source from environment.

    - MASSIVE_API_KEY set and non-empty  →  MassiveDataSource (real data)
    - Otherwise                          →  SimulatorDataSource (GBM sim)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        from .massive_client import MassiveDataSource
        return MassiveDataSource(api_key=api_key, price_cache=price_cache)
    else:
        from .simulator import SimulatorDataSource
        return SimulatorDataSource(price_cache=price_cache)
```

## Public API — `app.market` Imports

```python
# backend/app/market/__init__.py re-exports:
from app.market import (
    PriceUpdate,          # dataclass
    PriceCache,           # thread-safe price store
    MarketDataSource,     # ABC (for type hints)
    create_market_data_source,  # factory
    create_stream_router, # SSE FastAPI router factory
)
```

## Implementations

### `MassiveDataSource` (real market data)

Lives in `massive_client.py`. Constructor parameters:
- `api_key: str` — Massive/Polygon.io API key
- `price_cache: PriceCache` — shared cache to write into
- `poll_interval: float = 15.0` — seconds between API polls (15s = free tier safe)

Behavior:
- On `start()`: performs one immediate poll to seed the cache, then launches the background poll loop
- On each poll: calls `client.get_snapshot_all()` in a thread (synchronous client + asyncio = `asyncio.to_thread()`), extracts `last_trade.price` and `last_trade.timestamp / 1000.0` from each snapshot
- On `add_ticker()`: appends to the ticker list; the next poll will include it
- On `remove_ticker()`: removes from list and clears from cache immediately
- Poll failures are logged and swallowed — the loop retries on the next interval

### `SimulatorDataSource` (GBM simulation)

Lives in `simulator.py`. Constructor parameters:
- `price_cache: PriceCache` — shared cache to write into
- `update_interval: float = 0.5` — seconds between simulation steps (500ms)
- `event_probability: float = 0.001` — per-tick probability of a random shock event

Behavior:
- On `start()`: creates a `GBMSimulator`, seeds the cache with initial prices immediately, then launches the async step loop
- Every 500ms: calls `GBMSimulator.step()` (returns `dict[str, float]`), writes each price to the cache
- On `add_ticker()`: delegates to `GBMSimulator.add_ticker()` (which assigns a seed price and rebuilds the Cholesky matrix), then seeds the cache immediately
- On `remove_ticker()`: delegates to simulator and removes from cache

See `MARKET_SIMULATOR.md` for the GBM math and `GBMSimulator` internals.

## SSE Streaming — `create_stream_router()`

```python
# backend/app/market/stream.py
from app.market import create_stream_router

# In the FastAPI app setup:
router = create_stream_router(price_cache)
app.include_router(router)
# Registers: GET /api/stream/prices
```

The SSE endpoint (`/api/stream/prices`):
- Returns `text/event-stream` with `Cache-Control: no-cache` and `X-Accel-Buffering: no` (disables nginx buffering if proxied)
- Begins with `retry: 1000\n\n` so the browser reconnects within 1 second on disconnect
- Checks `request.is_disconnected()` every 500ms and exits cleanly when the client leaves
- Payload format per event:

```
data: {"AAPL": {"ticker": "AAPL", "price": 190.25, "previous_price": 190.10, "timestamp": 1704067200.0, "change": 0.15, "change_percent": 0.079, "direction": "up"}, "GOOGL": {...}, ...}

```
(One JSON object per event containing all tracked tickers.)

## Full Application Lifecycle

```python
# On FastAPI startup
cache = PriceCache()
source = create_market_data_source(cache)      # Reads MASSIVE_API_KEY env var
initial_tickers = await db.get_watchlist()     # Load from DB
await source.start(initial_tickers)

# On watchlist add
await source.add_ticker("PYPL")
# (also: INSERT into DB watchlist table)

# On watchlist remove
await source.remove_ticker("NFLX")
# (also: DELETE from DB watchlist table)

# Read current price for trade execution
price_update = cache.get("AAPL")
if price_update is None:
    raise HTTPException(404, "No price data for AAPL")
current_price = price_update.price

# Read all prices for portfolio valuation
all_prices = cache.get_all()  # dict[str, PriceUpdate]
for ticker, update in all_prices.items():
    position_value = quantity * update.price

# On FastAPI shutdown
await source.stop()
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Push-to-cache, not pull | Data source runs independently on its own schedule; consumers read whenever they want without coupling |
| `PriceCache` as single truth | Decouples producers from consumers; easy to swap implementations; thread-safe centralized state |
| `version` counter for SSE | Avoids sending duplicate events; more efficient than timestamp comparison |
| Sync client + `asyncio.to_thread` | Massive's Python client is synchronous; offloading to a thread avoids blocking the FastAPI event loop |
| Immediate seed on `start()` | MassiveDataSource does a first poll before the loop starts so the cache is populated before any SSE client connects |
| `frozen=True` on `PriceUpdate` | Immutability prevents accidental mutation by consumers; safe to pass across threads |
