"""Persistent knowledge store for expert escalation answers."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import KNOWLEDGE_MAX_ENTRIES, KNOWLEDGE_STORE_KEY

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

# Common stop words to exclude from keyword matching
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "for",
    "of", "and", "or", "but", "not", "with", "from", "by", "as",
    "that", "this", "be", "are", "was", "were", "has", "have", "had",
    "do", "does", "did", "will", "would", "can", "could", "should",
    "may", "might", "i", "you", "he", "she", "we", "they", "my",
    "your", "his", "her", "our", "their", "me", "him", "us", "them",
    "what", "which", "who", "how", "when", "where", "why",
    "if", "then", "so", "just", "about", "up", "out", "all", "no",
    "yes", "some", "any", "each", "every", "also", "very", "too",
})

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    """Extract meaningful keywords from text."""
    words = set(_WORD_RE.findall(text.lower()))
    return words - _STOP_WORDS


class KnowledgeStore:
    """Persistent store for expert Q&A pairs with keyword search."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, KNOWLEDGE_STORE_KEY)
        self._entries: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        """Load entries from disk."""
        data = await self._store.async_load()
        if data and isinstance(data.get("entries"), list):
            self._entries = data["entries"]
        _LOGGER.debug("Knowledge store loaded %d entries", len(self._entries))

    async def async_add_entry(
        self, query: str, answer: str, tags: list[str] | None = None
    ) -> None:
        """Add an expert Q&A entry and persist to disk."""
        entry = {
            "query": query,
            "answer": answer,
            "tags": tags or list(_tokenize(query)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._entries.append(entry)

        # FIFO eviction
        while len(self._entries) > KNOWLEDGE_MAX_ENTRIES:
            self._entries.pop(0)

        await self._store.async_save({"entries": self._entries})
        _LOGGER.debug(
            "Knowledge store: added entry (total: %d)", len(self._entries)
        )

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search entries by keyword overlap. Returns top matches."""
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in self._entries:
            entry_tokens = (
                _tokenize(entry.get("query", ""))
                | _tokenize(entry.get("answer", ""))
                | set(entry.get("tags", []))
            )
            overlap = len(query_tokens & entry_tokens)
            if overlap > 0:
                # Normalize by query length so short queries aren't disadvantaged
                score = overlap / len(query_tokens)
                scored.append((score, entry))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _score, entry in scored[:limit]]

    @property
    def entry_count(self) -> int:
        """Return the number of stored entries."""
        return len(self._entries)
