"""Background task for periodic portfolio snapshots."""

import asyncio
import logging
import sqlite3

from app.db.connection import DB_PATH
from app.db.repositories import portfolio_repo, snapshots_repo

logger = logging.getLogger(__name__)

USER_ID = "default"


async def snapshot_loop(app):
    """Record portfolio value snapshot every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                cash = portfolio_repo.get_cash(conn, USER_ID)
                positions = portfolio_repo.get_positions(conn, USER_ID)
                positions_value = 0.0
                for pos in positions:
                    price = app.state.price_cache.get_price(pos["ticker"])
                    if price is not None:
                        positions_value += price * pos["quantity"]
                    else:
                        positions_value += pos["avg_cost"] * pos["quantity"]
                total_value = cash + positions_value
                snapshots_repo.record_snapshot(conn, USER_ID, round(total_value, 2))
            finally:
                conn.close()
        except Exception:
            logger.exception("Error recording portfolio snapshot")
