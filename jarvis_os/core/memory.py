"""Memory layer with episodic storage, full-text search, and semantic recall."""

import json
import math
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlite_utils


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class Memory:
    """Working + episodic memory backed by SQLite with FTS search."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI runs sync endpoints in a threadpool,
        # so the DB is touched from more than one thread. A lock serializes access.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._fts_conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db = sqlite_utils.Database(self._fts_conn)
        self._init_db()

    def _init_db(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                embedding TEXT,
                source TEXT
            );
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        # Migrate older DBs that predate the embedding/source columns.
        existing = {row[1] for row in self._conn.execute("PRAGMA table_info(episodes)")}
        for col in ("embedding", "source"):
            if col not in existing:
                self._conn.execute(f"ALTER TABLE episodes ADD COLUMN {col} TEXT")
        self._conn.commit()
        # Enable full-text search on episodes content
        if "episodes_fts" not in self._db.table_names():
            self._db["episodes"].enable_fts(["content"], create_triggers=True)

    def add_message(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
        source: str | None = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO episodes (timestamp, role, content, metadata, embedding, source) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    role,
                    content,
                    json.dumps(metadata or {}),
                    json.dumps(embedding) if embedding else None,
                    source,
                ),
            )
            self._conn.commit()
            return cur.lastrowid

    def semantic_search(self, query_vec: list[float], limit: int = 5) -> list[dict[str, Any]]:
        """Rank stored episodes by cosine similarity to query_vec."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT timestamp, role, content, metadata, embedding, source FROM episodes WHERE embedding IS NOT NULL"
            ).fetchall()
        scored = []
        for row in rows:
            try:
                vec = json.loads(row["embedding"])
            except (ValueError, TypeError):
                continue
            scored.append((cosine(query_vec, vec), row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {
                "timestamp": row["timestamp"],
                "role": row["role"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"] or "{}"),
                "source": row["source"],
                "score": round(score, 4),
            }
            for score, row in scored[:limit]
        ]

    def stats(self) -> dict[str, int]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            embedded = self._conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE embedding IS NOT NULL"
            ).fetchone()[0]
        return {"episodes": total, "embedded": embedded}

    def recent_messages(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT timestamp, role, content, metadata FROM episodes ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "timestamp": row["timestamp"],
                "role": row["role"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"] or "{}"),
            }
            for row in reversed(rows)
        ]

    def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search past episodes using full-text search."""
        try:
            with self._lock:
                rows = list(
                    self._db["episodes"].search(query)
                    .order_by("rank")
                    .limit(limit)
                )
        except Exception:  # noqa: BLE001
            # Fallback if FTS is unavailable
            with self._lock:
                rows = self._conn.execute(
                    "SELECT timestamp, role, content, metadata FROM episodes WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
            return [
                {
                    "timestamp": row["timestamp"],
                    "role": row["role"],
                    "content": row["content"],
                    "metadata": json.loads(row["metadata"] or "{}"),
                }
                for row in rows
            ]
        return [
            {
                "timestamp": row["timestamp"],
                "role": row["role"],
                "content": row["content"],
                "metadata": json.loads(row["metadata"] or "{}"),
            }
            for row in rows
        ]

    def set_fact(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO facts (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()

    def get_fact(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
            self._fts_conn.close()
