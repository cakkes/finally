# Market Simulator Design

Approach and code structure for simulating realistic stock prices when no `MASSIVE_API_KEY` is configured.

## Overview

The simulator uses **Geometric Brownian Motion (GBM)** — the standard model underlying Black-Scholes option pricing — to generate realistic stock price paths. Prices evolve multiplicatively with random noise, can never go negative, and exhibit the lognormal distribution seen in real markets.

Two classes implement this:
- `GBMSimulator` — pure math engine; synchronous; no I/O
- `SimulatorDataSource` — wraps `GBMSimulator` in an async loop; implements the `MarketDataSource` ABC; writes to `PriceCache`

Both live in `backend/app/market/simulator.py`. Seed data (prices, parameters, correlation constants) lives in `backend/app/market/seed_prices.py`.

## GBM Math

At each discrete time step, a stock price evolves as:

```
S(t + dt) = S(t) × exp( (μ - σ²/2) × dt  +  σ × √dt × Z )
```

Where:
- `S(t)` — current price
- `μ` (mu) — annualized drift / expected return (e.g. 0.05 = 5%/year)
- `σ` (sigma) — annualized volatility (e.g. 0.20 = 20%/year)
- `dt` — time step as a fraction of a trading year
- `Z` — standard normal random variable drawn from N(0, 1)

### Time Step Calibration

FinAlly updates at 500ms intervals. The trading year is calibrated as:

```
trading_seconds_per_year = 252 trading days × 6.5 hours/day × 3600 sec/hour
                         = 5,896,800 seconds

dt = 0.5 / 5,896,800 ≈ 8.48 × 10⁻⁸
```

This tiny `dt` produces sub-cent moves per tick. Over a simulated trading day (~47,174 ticks at 2/sec), TSLA with σ=0.50 produces roughly the right intraday price range (~3–5%).

### Why GBM

- Prices are always positive (`exp()` is always > 0)
- Log-returns are normally distributed (matches real equity behavior)
- Analytically tractable — well-understood calibration
- Simple to implement; efficient in NumPy

## Correlated Moves

Real stocks don't move independently — tech stocks tend to co-move. We use **Cholesky decomposition** of a correlation matrix to generate correlated random draws.

### The Math

Given a correlation matrix `C` (positive definite), compute the Cholesky factor `L` such that `C = L × Lᵀ`. Then:

```
Z_correlated = L × Z_independent
```

Where `Z_independent` is a vector of i.i.d. standard normals. The result `Z_correlated` has the covariance structure specified by `C`.

### Correlation Structure

Defined in `seed_prices.py`:

```python
CORRELATION_GROUPS = {
    "tech":    {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

INTRA_TECH_CORR    = 0.6   # Tech stocks move together
INTRA_FINANCE_CORR = 0.5   # Finance stocks move together
CROSS_GROUP_CORR   = 0.3   # Between sectors, or unknown tickers
TSLA_CORR          = 0.3   # TSLA does its own thing despite being in tech
```

Note: TSLA is in `CORRELATION_GROUPS["tech"]` but `_pairwise_correlation()` special-cases it before checking sector membership, giving it the lower cross-group correlation.

### Cholesky Rebuild

The Cholesky matrix is rebuilt (`_rebuild_cholesky()`) whenever tickers are added or removed. With n < 50 tickers this is O(n²) and negligible. With a single ticker, no Cholesky is needed (scalar case).

## Random Events

Each time step, every ticker has a small probability of a random "shock event" — a sudden 2–5% jump or drop to simulate earnings surprises, news, etc.

```python
if random.random() < event_probability:   # default: 0.001 = 0.1%
    shock_magnitude = random.uniform(0.02, 0.05)
    shock_sign = random.choice([-1, 1])
    price *= (1 + shock_magnitude * shock_sign)
```

With the default 0.1% probability per tick per ticker at 2 ticks/sec:
- Any single ticker: one event every ~500 seconds (~8 minutes)
- With 10 tickers: one event somewhere in the watchlist every ~50 seconds
- Enough to keep the dashboard visually interesting

## Seed Prices

Realistic starting prices from `seed_prices.py`:

```python
SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 800.00,
    "META": 500.00,
    "JPM":  195.00,
    "V":    280.00,
    "NFLX": 600.00,
}
```

Tickers dynamically added at runtime that are not in this list start at `random.uniform(50.0, 300.0)`.

## Per-Ticker GBM Parameters

Each ticker has calibrated `sigma` (volatility) and `mu` (drift) to reflect real-world behavior:

```python
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL":  {"sigma": 0.22, "mu": 0.05},  # Mega-cap, moderate vol
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT":  {"sigma": 0.20, "mu": 0.05},  # Lowest vol in tech group
    "AMZN":  {"sigma": 0.28, "mu": 0.05},
    "TSLA":  {"sigma": 0.50, "mu": 0.03},  # High vol, lower drift
    "NVDA":  {"sigma": 0.40, "mu": 0.08},  # High vol, strong upward drift
    "META":  {"sigma": 0.30, "mu": 0.05},
    "JPM":   {"sigma": 0.18, "mu": 0.04},  # Low vol (bank)
    "V":     {"sigma": 0.17, "mu": 0.04},  # Lowest vol overall (payments)
    "NFLX":  {"sigma": 0.35, "mu": 0.05},
}

DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}
```

## GBMSimulator Class

```python
# backend/app/market/simulator.py (simplified)
import math, random
import numpy as np
from .seed_prices import SEED_PRICES, TICKER_PARAMS, DEFAULT_PARAMS, CORRELATION_GROUPS, ...

class GBMSimulator:
    """Geometric Brownian Motion simulator for correlated stock prices.

    Pure math engine — no I/O, no asyncio. Call step() to advance all
    tracked tickers by one time step.
    """

    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR   # ~8.48e-8

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
            self._add_ticker_internal(ticker)   # Batch init without rebuilding
        self._rebuild_cholesky()                # One rebuild after all added

    def step(self) -> dict[str, float]:
        """Advance all tickers by one time step. Returns {ticker: new_price}.

        Hot path — called every 500ms. NumPy operations for the correlated
        normal draws; pure Python loop for the per-ticker GBM step.
        """
        n = len(self._tickers)
        if n == 0:
            return {}

        # Correlated normal draws
        z_independent = np.random.standard_normal(n)
        z = self._cholesky @ z_independent if self._cholesky is not None else z_independent

        result: dict[str, float] = {}
        for i, ticker in enumerate(self._tickers):
            mu, sigma = self._params[ticker]["mu"], self._params[ticker]["sigma"]

            # GBM update
            drift = (mu - 0.5 * sigma**2) * self._dt
            diffusion = sigma * math.sqrt(self._dt) * z[i]
            self._prices[ticker] *= math.exp(drift + diffusion)

            # Random event
            if random.random() < self._event_prob:
                shock = random.uniform(0.02, 0.05) * random.choice([-1, 1])
                self._prices[ticker] *= (1 + shock)

            result[ticker] = round(self._prices[ticker], 2)

        return result

    def add_ticker(self, ticker: str) -> None:
        """Add a ticker. Rebuilds the Cholesky matrix."""
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker. Rebuilds the Cholesky matrix."""
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

    def _add_ticker_internal(self, ticker: str) -> None:
        """Add without rebuilding Cholesky (for batch init)."""
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker, random.uniform(50.0, 300.0))
        self._params[ticker] = TICKER_PARAMS.get(ticker, dict(DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
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
        if t1 in tech    and t2 in tech:    return INTRA_TECH_CORR
        if t1 in finance and t2 in finance: return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR
```

## SimulatorDataSource Class

```python
# backend/app/market/simulator.py (continued)
from .cache import PriceCache
from .interface import MarketDataSource

class SimulatorDataSource(MarketDataSource):
    """Wraps GBMSimulator in an async loop; implements MarketDataSource.

    Every `update_interval` seconds, steps the simulator and writes all
    new prices to the PriceCache.
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
        # Seed cache immediately so SSE has data before the first step
        for ticker in tickers:
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def add_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.add_ticker(ticker)
            # Seed cache immediately so the ticker has a price right away
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        """Core loop: step → write to cache → sleep → repeat."""
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

## Behavioral Properties

| Property | Detail |
|----------|--------|
| Price floor | Prices can never go negative — GBM uses `exp()` which is always > 0 |
| Price drift | With `mu=0.05` and `sigma=0.22` (AAPL), price will drift up very slowly — almost imperceptible over a 1-hour session |
| Volatility feel | TSLA (σ=0.50) moves visibly every few seconds; V (σ=0.17) is much calmer |
| Immediate seeding | Both `start()` and `add_ticker()` write the initial price to the cache before the loop runs — no blank state on first SSE connection |
| Correlation rebuild | O(n²) Cholesky rebuild on ticker add/remove; negligible at n < 50 |
| Event rate | With 10 tickers × 2 steps/sec × 0.001 probability: ~1 event every 50 seconds across the watchlist |
| Price rounding | `round(price, 2)` in `step()` ensures 2 decimal places in the cache |

## File Structure

```
backend/app/market/
  simulator.py      # GBMSimulator + SimulatorDataSource
  seed_prices.py    # SEED_PRICES, TICKER_PARAMS, DEFAULT_PARAMS,
                    # CORRELATION_GROUPS, correlation constants
```

`seed_prices.py` contains only constants. `simulator.py` contains both classes. No other files are needed for the simulation subsystem.

## Extending the Simulator

**Add a new default ticker**: add to `SEED_PRICES` and optionally `TICKER_PARAMS` in `seed_prices.py`. It will be seeded if the DB includes it in the default watchlist.

**Add a new sector correlation group**: add an entry to `CORRELATION_GROUPS` and a new correlation constant, then add a corresponding branch in `_pairwise_correlation()`.

**Adjust event drama**: increase `event_probability` (e.g. 0.005) or widen the shock range (e.g. `random.uniform(0.03, 0.08)`) in `GBMSimulator.__init__` defaults.

**Slow down / speed up**: change `update_interval` in `SimulatorDataSource`. This also changes `dt` implicitly — for correctness, pass a proportional `dt` to `GBMSimulator` (`dt = update_interval / TRADING_SECONDS_PER_YEAR`).
