"""Watchlist API endpoints."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.db.connection import get_db
from app.db.repositories import watchlist_repo
from app.models.watchlist import AddTickerRequest, WatchlistEntry

router = APIRouter(prefix="/api", tags=["watchlist"])


@router.get("/watchlist")
async def get_watchlist(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    tickers = watchlist_repo.get_watchlist(conn)
    price_cache = request.app.state.price_cache
    entries = []
    for ticker in tickers:
        update = price_cache.get(ticker)
        entries.append(
            WatchlistEntry(
                ticker=ticker,
                price=update.price if update else None,
                previous_price=update.previous_price if update else None,
                change_pct=update.change_percent if update else None,
                direction=update.direction if update else None,
            )
        )
    return entries


@router.post("/watchlist", status_code=201)
async def add_ticker(
    body: AddTickerRequest,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    ticker = body.ticker.upper().strip()
    added = watchlist_repo.add_ticker(conn, "default", ticker)
    if not added:
        raise HTTPException(status_code=409, detail=f"Ticker {ticker} already in watchlist")
    await request.app.state.market_source.add_ticker(ticker)
    update = request.app.state.price_cache.get(ticker)
    return WatchlistEntry(
        ticker=ticker,
        price=update.price if update else None,
        previous_price=update.previous_price if update else None,
        change_pct=update.change_percent if update else None,
        direction=update.direction if update else None,
    )


@router.delete("/watchlist/{ticker}", status_code=204)
async def remove_ticker(
    ticker: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    ticker = ticker.upper().strip()
    if not watchlist_repo.ticker_in_watchlist(conn, "default", ticker):
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not in watchlist")
    watchlist_repo.remove_ticker(conn, "default", ticker)
    await request.app.state.market_source.remove_ticker(ticker)
    return Response(status_code=204)
