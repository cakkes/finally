"""Portfolio snapshots repository."""

import sqlite3
import uuid
from datetime import datetime, timezone


def record_snapshot(conn: sqlite3.Connection, user_id: str, total_value: float) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), user_id, total_value, now),
    )
    conn.commit()


def get_snapshots(
    conn: sqlite3.Connection, user_id: str = "default", limit: int = 500
) -> list[dict]:
    rows = conn.execute(
        "SELECT id, user_id, total_value, recorded_at FROM portfolio_snapshots WHERE user_id = ? ORDER BY recorded_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]
