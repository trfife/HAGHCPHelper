"""SQLite analytics store for conversation request logging."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

ANALYTICS_DB = "ghcp_conversation_analytics.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS request_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    user_prompt TEXT NOT NULL,
    route TEXT NOT NULL,
    model TEXT,
    latency_ms INTEGER,
    tokens_in INTEGER,
    tokens_out INTEGER,
    success INTEGER NOT NULL DEFAULT 1,
    error_msg TEXT
)
"""

_CREATE_KNOWLEDGE_TABLE = """
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    answer TEXT NOT NULL,
    tags TEXT,
    timestamp TEXT NOT NULL,
    source TEXT DEFAULT 'expert',
    hit_count INTEGER NOT NULL DEFAULT 0,
    promoted INTEGER NOT NULL DEFAULT 0
)
"""

_INSERT_LOG = """
INSERT INTO request_log
    (timestamp, user_prompt, route, model, latency_ms, tokens_in, tokens_out, success, error_msg)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_KNOWLEDGE = """
INSERT INTO knowledge (query, answer, tags, timestamp, source)
VALUES (?, ?, ?, ?, ?)
"""


@dataclass
class RequestMetrics:
    """Tracks timing and token usage for a single request."""

    start_time: float = field(default_factory=time.monotonic)
    route: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    success: bool = True
    error_msg: str = ""

    @property
    def latency_ms(self) -> int:
        """Elapsed time in milliseconds since start."""
        return int((time.monotonic() - self.start_time) * 1000)


class AnalyticsStore:
    """SQLite-backed analytics and knowledge store."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._db_path = Path(hass.config.path(".storage")) / ANALYTICS_DB
        self._db: aiosqlite.Connection | None = None

    async def async_setup(self) -> None:
        """Open database and create tables."""
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_KNOWLEDGE_TABLE)
        await self._db.commit()
        _LOGGER.debug("Analytics DB ready at %s", self._db_path)

    async def async_close(self) -> None:
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ── Request logging ──────────────────────────────────────────────────

    async def async_log(
        self, prompt: str, metrics: RequestMetrics
    ) -> None:
        """Log a conversation request with its metrics."""
        if not self._db:
            return
        try:
            await self._db.execute(
                _INSERT_LOG,
                (
                    datetime.now(timezone.utc).isoformat(),
                    prompt[:500],  # cap stored prompt length
                    metrics.route,
                    metrics.model,
                    metrics.latency_ms,
                    metrics.tokens_in,
                    metrics.tokens_out,
                    1 if metrics.success else 0,
                    metrics.error_msg[:500] if metrics.error_msg else None,
                ),
            )
            await self._db.commit()
        except Exception:
            _LOGGER.exception("Failed to log analytics")

    async def async_get_stats(
        self, hours: int = 24
    ) -> dict[str, Any]:
        """Get aggregate statistics for the last N hours."""
        if not self._db:
            return {}
        try:
            cutoff = datetime.now(timezone.utc).isoformat()
            cursor = await self._db.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successes,
                    AVG(latency_ms) as avg_latency,
                    MIN(latency_ms) as min_latency,
                    MAX(latency_ms) as max_latency,
                    SUM(tokens_in) as total_tokens_in,
                    SUM(tokens_out) as total_tokens_out
                FROM request_log
                WHERE timestamp >= datetime(?, '-' || ? || ' hours')
                """,
                (cutoff, hours),
            )
            row = await cursor.fetchone()
            if not row:
                return {}

            # Route breakdown
            cursor2 = await self._db.execute(
                """
                SELECT route, COUNT(*) as cnt, AVG(latency_ms) as avg_lat
                FROM request_log
                WHERE timestamp >= datetime(?, '-' || ? || ' hours')
                GROUP BY route
                """,
                (cutoff, hours),
            )
            routes = {
                r[0]: {"count": r[1], "avg_latency_ms": round(r[2] or 0)}
                for r in await cursor2.fetchall()
            }

            return {
                "total_requests": row[0],
                "successes": row[1],
                "avg_latency_ms": round(row[2] or 0),
                "min_latency_ms": row[3],
                "max_latency_ms": row[4],
                "total_tokens_in": row[5] or 0,
                "total_tokens_out": row[6] or 0,
                "by_route": routes,
            }
        except Exception:
            _LOGGER.exception("Failed to get analytics stats")
            return {}

    # ── Knowledge (SQLite-backed) ────────────────────────────────────────

    async def async_add_knowledge(
        self, query: str, answer: str, tags: list[str] | None = None,
        source: str = "expert",
    ) -> None:
        """Store a knowledge entry."""
        if not self._db:
            return
        tag_str = ",".join(tags) if tags else ""
        try:
            await self._db.execute(
                _INSERT_KNOWLEDGE,
                (
                    query,
                    answer,
                    tag_str,
                    datetime.now(timezone.utc).isoformat(),
                    source,
                ),
            )
            await self._db.commit()
        except Exception:
            _LOGGER.exception("Failed to add knowledge entry")

    async def async_search_knowledge(
        self, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search knowledge by keyword overlap and bump hit_count."""
        if not self._db:
            return []

        # Tokenize query for keyword matching
        from .knowledge import _tokenize
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        try:
            cursor = await self._db.execute(
                "SELECT id, query, answer, tags FROM knowledge"
            )
            rows = await cursor.fetchall()
        except Exception:
            _LOGGER.exception("Failed to search knowledge")
            return []

        scored: list[tuple[float, int, dict[str, Any]]] = []
        for row in rows:
            entry_tokens = (
                _tokenize(row[1])
                | _tokenize(row[2])
                | set(row[3].split(",")) if row[3] else set()
            )
            overlap = len(query_tokens & entry_tokens)
            if overlap > 0:
                score = overlap / len(query_tokens)
                scored.append((score, row[0], {"query": row[1], "answer": row[2]}))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = scored[:limit]

        # Bump hit_count for matched entries
        if results:
            ids = [r[1] for r in results]
            placeholders = ",".join("?" * len(ids))
            try:
                await self._db.execute(
                    f"UPDATE knowledge SET hit_count = hit_count + 1 WHERE id IN ({placeholders})",
                    ids,
                )
                await self._db.commit()
            except Exception:
                _LOGGER.debug("Failed to bump hit_count")

        return [r[2] for r in results]

    async def async_get_promotion_candidates(
        self, min_hits: int = 5
    ) -> list[dict[str, Any]]:
        """Return high-hit knowledge entries that could be promoted to fast rules."""
        if not self._db:
            return []
        try:
            cursor = await self._db.execute(
                """
                SELECT query, answer, hit_count, timestamp
                FROM knowledge
                WHERE hit_count >= ? AND promoted = 0
                ORDER BY hit_count DESC
                LIMIT 20
                """,
                (min_hits,),
            )
            return [
                {"query": r[0], "answer": r[1], "hit_count": r[2], "timestamp": r[3]}
                for r in await cursor.fetchall()
            ]
        except Exception:
            _LOGGER.exception("Failed to get promotion candidates")
            return []

    async def async_migrate_from_json(
        self, entries: list[dict[str, Any]]
    ) -> int:
        """Import entries from the legacy JSON knowledge store."""
        if not self._db or not entries:
            return 0
        count = 0
        for entry in entries:
            try:
                await self._db.execute(
                    _INSERT_KNOWLEDGE,
                    (
                        entry.get("query", ""),
                        entry.get("answer", ""),
                        ",".join(entry.get("tags", [])),
                        entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
                        "migrated",
                    ),
                )
                count += 1
            except Exception:
                continue
        await self._db.commit()
        _LOGGER.info("Migrated %d entries from JSON knowledge store", count)
        return count
