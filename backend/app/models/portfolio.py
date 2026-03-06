"""Pydantic models for portfolio endpoints."""

from pydantic import BaseModel, Field


class Position(BaseModel):
    ticker: str
    quantity: float
    avg_cost: float
    current_price: float
    unrealized_pnl: float
    pnl_pct: float


class Portfolio(BaseModel):
    cash_balance: float
    positions: list[Position]
    total_value: float
    total_unrealized_pnl: float


class TradeRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    quantity: float = Field(..., gt=0)
    side: str = Field(..., pattern="^(buy|sell)$")


class TradeResponse(BaseModel):
    success: bool
    trade: dict | None = None
    portfolio: Portfolio | None = None
    error: str | None = None
