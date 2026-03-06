"""Chat messages repository."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone


def save_message(
    conn: sqlite3.Connection,
    user_id: str,
    role: str,
    content: str,
    actions: dict | list | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    actions_json = json.dumps(actions) if actions is not None else None
    conn.execute(
        "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), user_id, role, content, actions_json, now),
    )
    conn.commit()


def get_recent_messages(
    conn: sqlite3.Connection, user_id: str = "default", limit: int = 20
) -> list[dict]:
    rows = conn.execute(
        "SELECT id, user_id, role, content, actions, created_at FROM chat_messages WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        if d["actions"] is not None:
            d["actions"] = json.loads(d["actions"])
        results.append(d)
    # Return in chronological order
    return list(reversed(results))
