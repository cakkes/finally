"""FinAlly backend — FastAPI application."""

import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.background.snapshots import snapshot_loop
from app.db import init_database, DB_PATH
from app.db.connection import get_db
from app.db.repositories import watchlist_repo
from app.market import PriceCache, create_market_data_source, create_stream_router
from app.routers import chat, health, portfolio, watchlist

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "out")
STATIC_DIR = os.path.normpath(STATIC_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    init_database(DB_PATH)

    # Create price cache and market data source
    price_cache = PriceCache()
    market_source = create_market_data_source(price_cache)

    # Get watchlist tickers from DB (direct connection, not the generator dependency)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    try:
        tickers = watchlist_repo.get_watchlist(conn)
    finally:
        conn.close()

    # Start market data source
    await market_source.start(tickers)

    # Store in app.state for access by routes
    app.state.price_cache = price_cache
    app.state.market_source = market_source

    # Include the SSE stream router (needs price_cache)
    stream_router = create_stream_router(price_cache)
    app.include_router(stream_router)

    # Mount SPA fallback AFTER all API/stream routes are registered
    if os.path.isdir(STATIC_DIR):
        @app.get("/{path:path}", include_in_schema=False)
        async def spa_fallback(path: str):
            file_path = os.path.join(STATIC_DIR, path)
            if os.path.isfile(file_path):
                return FileResponse(file_path)
            index = os.path.join(STATIC_DIR, "index.html")
            if os.path.isfile(index):
                return FileResponse(index)

        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Start background snapshot task
    snapshot_task = asyncio.create_task(snapshot_loop(app))

    logger.info("FinAlly backend started with %d tickers", len(tickers))

    yield

    # Shutdown
    snapshot_task.cancel()
    try:
        await snapshot_task
    except asyncio.CancelledError:
        pass
    await market_source.stop()
    logger.info("FinAlly backend stopped")


app = FastAPI(title="FinAlly", lifespan=lifespan)

# Include API routers
app.include_router(health.router)
app.include_router(watchlist.router)
app.include_router(portfolio.router)
app.include_router(chat.router)

# SPA fallback is deferred to lifespan so it's registered after the SSE stream router.
# See _mount_spa_fallback() call in lifespan.
