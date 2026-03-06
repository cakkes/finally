"""Pydantic models for watchlist endpoints."""

from pydantic import BaseModel, Field


class AddTickerRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)


class WatchlistEntry(BaseModel):
    ticker: str
    price: float | None = None
    previous_price: float | None = None
    change_pct: float | None = None
    direction: str | None = None
