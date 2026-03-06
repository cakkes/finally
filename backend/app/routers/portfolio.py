"""Portfolio API endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from app.db.connection import get_db
from app.db.repositories import portfolio_repo, snapshots_repo, trades_repo
from app.models.portfolio import Portfolio, Position, TradeRequest, TradeResponse

router = APIRouter(prefix="/api", tags=["portfolio"])

USER_ID = "default"


def _build_portfolio(conn: sqlite3.Connection, price_cache) -> Portfolio:
    cash = portfolio_repo.get_cash(conn, USER_ID)
    db_positions = portfolio_repo.get_positions(conn, USER_ID)
    positions = []
    total_unrealized_pnl = 0.0
    positions_value = 0.0

    for pos in db_positions:
        current_price = price_cache.get_price(pos["ticker"]) or pos["avg_cost"]
        unrealized_pnl = (current_price - pos["avg_cost"]) * pos["quantity"]
        pnl_pct = (
            ((current_price - pos["avg_cost"]) / pos["avg_cost"] * 100)
            if pos["avg_cost"] > 0
            else 0.0
        )
        positions.append(
            Position(
                ticker=pos["ticker"],
                quantity=pos["quantity"],
                avg_cost=round(pos["avg_cost"], 2),
                current_price=round(current_price, 2),
                unrealized_pnl=round(unrealized_pnl, 2),
                pnl_pct=round(pnl_pct, 2),
            )
        )
        total_unrealized_pnl += unrealized_pnl
        positions_value += current_price * pos["quantity"]

    return Portfolio(
        cash_balance=round(cash, 2),
        positions=positions,
        total_value=round(cash + positions_value, 2),
        total_unrealized_pnl=round(total_unrealized_pnl, 2),
    )


@router.get("/portfolio")
async def get_portfolio(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return _build_portfolio(conn, request.app.state.price_cache)


@router.post("/portfolio/trade")
async def execute_trade(
    body: TradeRequest,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    ticker = body.ticker.upper().strip()
    quantity = body.quantity
    side = body.side
    price_cache = request.app.state.price_cache

    current_price = price_cache.get_price(ticker)
    if current_price is None:
        raise HTTPException(status_code=400, detail=f"No price available for {ticker}")

    cash = portfolio_repo.get_cash(conn, USER_ID)
    db_positions = portfolio_repo.get_positions(conn, USER_ID)
    existing = next((p for p in db_positions if p["ticker"] == ticker), None)

    if side == "buy":
        total_cost = current_price * quantity
        if total_cost > cash:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient cash. Need ${total_cost:.2f}, have ${cash:.2f}",
            )
        new_cash = cash - total_cost
        portfolio_repo.update_cash(conn, new_cash, USER_ID)

        if existing:
            old_qty = existing["quantity"]
            old_cost = existing["avg_cost"]
            new_qty = old_qty + quantity
            new_avg_cost = (old_qty * old_cost + quantity * current_price) / new_qty
            portfolio_repo.upsert_position(conn, USER_ID, ticker, new_qty, new_avg_cost)
        else:
            portfolio_repo.upsert_position(conn, USER_ID, ticker, quantity, current_price)

    elif side == "sell":
        if not existing or existing["quantity"] < quantity:
            available = existing["quantity"] if existing else 0
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient shares. Have {available}, trying to sell {quantity}",
            )
        new_qty = existing["quantity"] - quantity
        proceeds = current_price * quantity
        new_cash = cash + proceeds
        portfolio_repo.update_cash(conn, new_cash, USER_ID)

        if new_qty > 0:
            portfolio_repo.upsert_position(conn, USER_ID, ticker, new_qty, existing["avg_cost"])
        else:
            portfolio_repo.delete_position(conn, USER_ID, ticker)

    trades_repo.record_trade(conn, USER_ID, ticker, side, quantity, current_price)

    portfolio = _build_portfolio(conn, price_cache)
    snapshots_repo.record_snapshot(conn, USER_ID, portfolio.total_value)

    return TradeResponse(
        success=True,
        trade={
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "price": current_price,
        },
        portfolio=portfolio,
    )


@router.get("/portfolio/history")
async def get_portfolio_history(conn: sqlite3.Connection = Depends(get_db)):
    snapshots = snapshots_repo.get_snapshots(conn, USER_ID)
    return [
        {"total_value": s["total_value"], "recorded_at": s["recorded_at"]} for s in snapshots
    ]
