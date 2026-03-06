# Massive API Reference (formerly Polygon.io)

Reference documentation for the Massive (formerly Polygon.io) REST API as used in FinAlly.

## Overview

- **Base URL**: `https://api.polygon.io` (legacy URL; the `massive` Python package handles this)
- **Python package**: `massive` (install via `uv add massive`)
- **Auth**: API key via `MASSIVE_API_KEY` env var or passed explicitly to `RESTClient`
- **Auth header**: `Authorization: Bearer <API_KEY>` (the client handles this automatically)

The `massive` package is a thin wrapper around the Polygon.io REST API, providing typed Python objects for all responses.

## Rate Limits

| Tier | Limit | Recommended Poll Interval |
|------|-------|--------------------------|
| Free | 5 requests/minute | Every 15 seconds |
| Starter | Unlimited | Every 5–10 seconds |
| Developer+ | Unlimited | Every 2–5 seconds |

FinAlly defaults to 15 seconds (`poll_interval=15.0`) to stay safely within the free tier.

## Client Initialization

```python
from massive import RESTClient

# Reads MASSIVE_API_KEY from environment automatically
client = RESTClient()

# Or pass the key explicitly
client = RESTClient(api_key="your_key_here")
```

The client is synchronous. In an async context (FastAPI), wrap calls with `asyncio.to_thread()`.

## Endpoints Used in FinAlly

### 1. Snapshot — All Tickers (Primary Endpoint)

Gets the current market snapshot for multiple tickers in **one API call**. This is the only endpoint FinAlly uses for live price polling.

**REST**: `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,GOOGL,MSFT`

**Python client**:
```python
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

client = RESTClient()

snapshots = client.get_snapshot_all(
    market_type=SnapshotMarketType.STOCKS,
    tickers=["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"],
)

for snap in snapshots:
    price = snap.last_trade.price
    # Timestamps are Unix milliseconds — convert to seconds
    timestamp_sec = snap.last_trade.timestamp / 1000.0
    print(f"{snap.ticker}: ${price:.2f} at {timestamp_sec}")
```

**Response structure** (per ticker, as Python object fields):
```
snap.ticker                     # "AAPL"
snap.last_trade.price           # 190.25   — current price (use this for trading)
snap.last_trade.size            # 100       — shares in last trade
snap.last_trade.timestamp       # 1675190399000  — Unix milliseconds
snap.last_quote.bid_price       # 190.24
snap.last_quote.ask_price       # 190.26
snap.last_quote.bid_size        # 500
snap.last_quote.ask_size        # 300
snap.day.open                   # 188.00
snap.day.high                   # 191.50
snap.day.low                    # 187.50
snap.day.close                  # 190.25   — latest close (same as last_trade during session)
snap.day.volume                 # 45230100
snap.day.volume_weighted_average_price  # 189.87
snap.day.change                 # +2.25    — change from previous close
snap.day.change_percent         # +1.20    — percent change from previous close
snap.prev_daily_bar.close       # 188.00   — previous day's closing price
```

**Key fields FinAlly extracts**:
- `snap.last_trade.price` — the live price written to the `PriceCache`
- `snap.last_trade.timestamp / 1000.0` — converted to Unix seconds for the `PriceUpdate`

**What FinAlly ignores** (for simplicity): bid/ask spread, volume, day OHLC, previous close. These could be surfaced in a richer UI in the future.

### 2. Single Ticker Snapshot

For detailed data on one ticker. Not used in the current polling loop but available if a future endpoint needs individual ticker data.

```python
snapshot = client.get_snapshot_ticker(
    market_type=SnapshotMarketType.STOCKS,
    ticker="AAPL",
)
print(f"Price: ${snapshot.last_trade.price}")
print(f"Bid/Ask: ${snapshot.last_quote.bid_price} / ${snapshot.last_quote.ask_price}")
print(f"Day range: ${snapshot.day.low} - ${snapshot.day.high}")
```

### 3. Previous Close

Previous trading day's OHLCV. Useful for seeding realistic starting prices if a real-data mode needs historical anchoring.

**REST**: `GET /v2/aggs/ticker/{ticker}/prev`

```python
prev_bars = client.get_previous_close_agg(ticker="AAPL")
for bar in prev_bars:
    print(f"Prev close: ${bar.close}")
    print(f"OHLC: O={bar.open} H={bar.high} L={bar.low} C={bar.close}")
    print(f"Volume: {bar.volume}")
    # bar.timestamp is Unix milliseconds
```

### 4. Aggregate Bars (Historical OHLCV)

Historical bars over a date range. Not used in the current implementation but the natural next step for adding historical charts to the main chart area.

**REST**: `GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`

```python
# Fetch daily bars for January 2024
bars = []
for bar in client.list_aggs(
    ticker="AAPL",
    multiplier=1,
    timespan="day",       # "minute", "hour", "day", "week", "month"
    from_="2024-01-01",
    to="2024-01-31",
    limit=50000,
):
    bars.append(bar)

for bar in bars:
    # bar.timestamp is Unix milliseconds
    date_sec = bar.timestamp / 1000.0
    print(f"O={bar.open} H={bar.high} L={bar.low} C={bar.close} V={bar.volume}")
```

### 5. Last Trade / Last Quote (Individual Endpoints)

Fine-grained endpoints for the most recent trade or NBBO quote on a single ticker. Slower than the batch snapshot but available:

```python
# Most recent trade
trade = client.get_last_trade(ticker="AAPL")
print(f"Last trade: ${trade.price} x {trade.size} shares")

# Most recent NBBO quote
quote = client.get_last_quote(ticker="AAPL")
print(f"Bid: ${quote.bid} x {quote.bid_size}")
print(f"Ask: ${quote.ask} x {quote.ask_size}")
```

## How FinAlly Polls the API

The `MassiveDataSource` (in `backend/app/market/massive_client.py`) runs as a background asyncio task:

1. On `start()`, creates `RESTClient` and performs an **immediate first poll** so the cache has data before the first SSE client connects
2. Launches `_poll_loop()` as an asyncio background task
3. Every `poll_interval` seconds, calls `_poll_once()`:
   - Offloads the synchronous `RESTClient.get_snapshot_all()` to a thread via `asyncio.to_thread()` so it doesn't block the event loop
   - Iterates the snapshot list; extracts `last_trade.price` and `last_trade.timestamp`
   - Writes each price to `PriceCache.update(ticker, price, timestamp)`
   - Logs a debug summary of how many tickers were updated
4. If a poll fails (network error, rate limit, bad key), logs the error and continues — the loop will retry on the next interval

```python
# Simplified version of _poll_once() from massive_client.py
async def _poll_once(self) -> None:
    if not self._tickers or not self._client:
        return
    try:
        snapshots = await asyncio.to_thread(
            self._client.get_snapshot_all,
            market_type=SnapshotMarketType.STOCKS,
            tickers=self._tickers,
        )
        for snap in snapshots:
            price = snap.last_trade.price
            timestamp = snap.last_trade.timestamp / 1000.0  # ms → seconds
            self._cache.update(ticker=snap.ticker, price=price, timestamp=timestamp)
    except Exception as e:
        logger.error("Massive poll failed: %s", e)
        # Loop continues — retries on next interval
```

## Error Handling

The client raises standard Python exceptions for HTTP errors:

| Situation | Exception | Behavior in FinAlly |
|-----------|-----------|---------------------|
| Invalid API key | `401` HTTP error | Logged as error; loop retries (will keep failing) |
| Plan doesn't cover endpoint | `403` HTTP error | Logged as error; loop retries |
| Rate limit exceeded | `429` HTTP error | Logged as error; back off by increasing `poll_interval` |
| Server error | `5xx` HTTP error | Client retries 3x by default before raising |
| Network timeout | `requests.Timeout` | Logged as error; loop retries on next interval |
| Ticker not found | Ticker absent from response | No cache update for that ticker; others unaffected |
| Snapshot field missing | `AttributeError` | Per-snapshot `try/except`; logs warning and skips that ticker |

The per-ticker `try/except AttributeError` in `_poll_once()` means one bad ticker (e.g., a delisted stock with no recent trade) never blocks updates for others.

## Market Hours Behavior

- **During regular session (9:30–16:00 ET)**: `last_trade.price` reflects real-time trades
- **Pre-market / after-hours**: `last_trade.price` is the most recent trade, which may be from extended hours trading
- **Weekends / market closed**: `last_trade.price` is the last traded price (Friday close or most recent after-hours)
- **`day` object**: resets at market open each day; during pre-market it reflects the previous session

Since FinAlly is primarily a demo platform, market-hours edge cases are acceptable — the cache simply holds the last known price.

## Timestamp Notes

- All Massive API timestamps are **Unix milliseconds** (integer)
- `PriceCache.update()` expects **Unix seconds** (float)
- Always divide by 1000.0: `timestamp_sec = snap.last_trade.timestamp / 1000.0`

## Package Installation

```toml
# backend/pyproject.toml
[project]
dependencies = [
    "massive",
    ...
]
```

```bash
cd backend
uv add massive
# or: uv sync  (if already in pyproject.toml)
```
