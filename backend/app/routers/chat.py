"""Chat API router."""

import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.db.connection import get_db
from app.db.repositories import chat_repo, portfolio_repo, trades_repo, watchlist_repo
from app.services.llm_service import LLMResponse, LLMService

router = APIRouter()
llm_service = LLMService()


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    message: str
    trades_executed: list[dict] = []
    watchlist_changes: list[dict] = []
    errors: list[str] = []


def _build_portfolio_context(conn: sqlite3.Connection, price_cache) -> dict:
    cash = portfolio_repo.get_cash(conn)
    positions = portfolio_repo.get_positions(conn)
    watchlist = watchlist_repo.get_watchlist(conn)

    enriched_positions = []
    positions_value = 0.0
    for pos in positions:
        current_price = price_cache.get_price(pos["ticker"]) if price_cache else None
        current = current_price or pos["avg_cost"]
        unrealized_pnl = (current - pos["avg_cost"]) * pos["quantity"]
        market_value = current * pos["quantity"]
        positions_value += market_value
        enriched_positions.append({
            "ticker": pos["ticker"],
            "quantity": pos["quantity"],
            "avg_cost": round(pos["avg_cost"], 2),
            "current_price": round(current, 2),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
        })

    watchlist_prices = {}
    for ticker in watchlist:
        p = price_cache.get_price(ticker) if price_cache else None
        if p is not None:
            watchlist_prices[ticker] = round(p, 2)

    return {
        "cash": round(cash, 2),
        "total_value": round(cash + positions_value, 2),
        "positions": enriched_positions,
        "watchlist": watchlist_prices,
    }


def _execute_trade(
    conn: sqlite3.Connection, price_cache, ticker: str, side: str, quantity: float
) -> dict:
    """Execute a single trade. Returns result dict."""
    current_price = price_cache.get_price(ticker) if price_cache else None
    if current_price is None:
        return {"ticker": ticker, "side": side, "error": f"No price available for {ticker}"}

    cash = portfolio_repo.get_cash(conn)

    if side == "buy":
        cost = current_price * quantity
        if cost > cash:
            return {"ticker": ticker, "side": side, "error": f"Insufficient cash (need ${cost:.2f}, have ${cash:.2f})"}

        # Update cash
        portfolio_repo.update_cash(conn, cash - cost)

        # Update position
        positions = portfolio_repo.get_positions(conn)
        existing = next((p for p in positions if p["ticker"] == ticker), None)
        if existing:
            new_qty = existing["quantity"] + quantity
            new_avg = ((existing["avg_cost"] * existing["quantity"]) + cost) / new_qty
            portfolio_repo.upsert_position(conn, "default", ticker, new_qty, new_avg)
        else:
            portfolio_repo.upsert_position(conn, "default", ticker, quantity, current_price)

        trades_repo.record_trade(conn, "default", ticker, "buy", quantity, current_price)
        return {"ticker": ticker, "side": "buy", "quantity": quantity, "price": round(current_price, 2)}

    elif side == "sell":
        positions = portfolio_repo.get_positions(conn)
        existing = next((p for p in positions if p["ticker"] == ticker), None)
        if not existing or existing["quantity"] < quantity:
            owned = existing["quantity"] if existing else 0
            return {"ticker": ticker, "side": side, "error": f"Insufficient shares (own {owned}, want to sell {quantity})"}

        proceeds = current_price * quantity
        portfolio_repo.update_cash(conn, cash + proceeds)

        new_qty = existing["quantity"] - quantity
        if new_qty <= 0:
            portfolio_repo.delete_position(conn, "default", ticker)
        else:
            portfolio_repo.upsert_position(conn, "default", ticker, new_qty, existing["avg_cost"])

        trades_repo.record_trade(conn, "default", ticker, "sell", quantity, current_price)
        return {"ticker": ticker, "side": "sell", "quantity": quantity, "price": round(current_price, 2)}

    return {"ticker": ticker, "side": side, "error": f"Invalid side: {side}"}


@router.post("/api/chat")
async def chat(request: ChatRequest, req: Request, conn: sqlite3.Connection = Depends(get_db)):
    price_cache = getattr(req.app.state, "price_cache", None)

    # 1. Build portfolio context
    portfolio_context = _build_portfolio_context(conn, price_cache)

    # 2. Get recent chat history
    history = chat_repo.get_recent_messages(conn)

    # 3. Call LLM
    llm_response: LLMResponse = await llm_service.chat(
        request.message, portfolio_context, history
    )

    # 4. Auto-execute trades
    trades_executed = []
    errors = []
    for trade in llm_response.trades:
        result = _execute_trade(
            conn, price_cache, trade.ticker.upper(), trade.side, trade.quantity
        )
        if "error" in result:
            errors.append(result["error"])
        else:
            trades_executed.append(result)

    # 5. Auto-execute watchlist changes
    watchlist_changes = []
    market_source = getattr(req.app.state, "market_source", None)
    for change in llm_response.watchlist_changes:
        ticker = change.ticker.upper()
        if change.action == "add":
            added = watchlist_repo.add_ticker(conn, "default", ticker)
            if added:
                watchlist_changes.append({"ticker": ticker, "action": "add"})
                if market_source:
                    await market_source.add_ticker(ticker)
        elif change.action == "remove":
            watchlist_repo.remove_ticker(conn, "default", ticker)
            watchlist_changes.append({"ticker": ticker, "action": "remove"})
            if market_source:
                await market_source.remove_ticker(ticker)

    # 6. Save messages to DB
    chat_repo.save_message(conn, "default", "user", request.message)

    actions = None
    if trades_executed or watchlist_changes:
        actions = {"trades": trades_executed, "watchlist_changes": watchlist_changes}
    chat_repo.save_message(conn, "default", "assistant", llm_response.message, actions)

    # 7. Return response
    return ChatResponse(
        message=llm_response.message,
        trades_executed=trades_executed,
        watchlist_changes=watchlist_changes,
        errors=errors,
    )
