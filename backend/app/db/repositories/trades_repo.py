"""Trades repository."""

import sqlite3
import uuid
from datetime import datetime, timezone


def record_trade(
    conn: sqlite3.Connection,
    user_id: str,
    ticker: str,
    side: str,
    quantity: float,
    price: float,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), user_id, ticker, side, quantity, price, now),
    )
    conn.commit()


def get_trades(conn: sqlite3.Connection, user_id: str = "default") -> list[dict]:
    rows = conn.execute(
        "SELECT id, user_id, ticker, side, quantity, price, executed_at FROM trades WHERE user_id = ? ORDER BY executed_at DESC",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]
