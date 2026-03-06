"""Portfolio repository: cash balance and positions."""

import sqlite3
import uuid
from datetime import datetime, timezone


def get_cash(conn: sqlite3.Connection, user_id: str = "default") -> float:
    row = conn.execute(
        "SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None:
        return 0.0
    return row["cash_balance"] if isinstance(row, sqlite3.Row) else row[0]


def update_cash(conn: sqlite3.Connection, amount: float, user_id: str = "default") -> None:
    conn.execute(
        "UPDATE users_profile SET cash_balance = ? WHERE id = ?", (amount, user_id)
    )
    conn.commit()


def get_positions(conn: sqlite3.Connection, user_id: str = "default") -> list[dict]:
    rows = conn.execute(
        "SELECT id, user_id, ticker, quantity, avg_cost, updated_at FROM positions WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def upsert_position(
    conn: sqlite3.Connection, user_id: str, ticker: str, quantity: float, avg_cost: float
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id FROM positions WHERE user_id = ? AND ticker = ?", (user_id, ticker)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE positions SET quantity = ?, avg_cost = ?, updated_at = ? WHERE user_id = ? AND ticker = ?",
            (quantity, avg_cost, now, user_id, ticker),
        )
    else:
        conn.execute(
            "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, ticker, quantity, avg_cost, now),
        )
    conn.commit()


def delete_position(conn: sqlite3.Connection, user_id: str, ticker: str) -> None:
    conn.execute(
        "DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, ticker)
    )
    conn.commit()
