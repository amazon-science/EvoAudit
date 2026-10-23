# Portions adapted from sethkarten/continual-harness (MIT License,
# Copyright (c) 2026 Seth Karten et al.), modified. See THIRD-PARTY-NOTICES.txt.
"""
Memory store — persistent long-term memory for PokeAgent.

Inherits from BaseStore and adds text search (the only memory-specific op).
Handles migration from legacy ``knowledge_base.json`` and ``category``→``path``.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from continual_harness.stores.base_store import BaseStore

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """A single entry in long-term memory."""
    id: str = ""
    path: str = "uncategorized"
    title: str = ""
    content: str = ""
    location: Optional[str] = None
    coordinates: Optional[tuple] = None
    tags: List[str] = field(default_factory=list)
    created_at: str = None  # type: ignore[assignment]
    updated_at: str = None  # type: ignore[assignment]
    importance: int = 3
    source: str = "orchestrator" # "evolved" | "orchestrator"
    created_in_task: str = ""  # task id this memory was created during (provenance for transfer analysis)
    last_modified_step: Optional[int] = None
    mutation_history: List[dict] = field(default_factory=list)

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            from datetime import datetime
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = self.created_at


# Backward-compat aliases
KnowledgeEntry = MemoryEntry


class Memory(BaseStore[MemoryEntry]):
    """Persistent long-term memory store."""

    file_name = "memory.json"
    id_prefix = "mem_"
    store_label = "LONG-TERM MEMORY"
    empty_message = "No memory entries yet."
    entry_class = MemoryEntry

    def __init__(self, cache_dir: Optional[str] = None):
        super().__init__(cache_dir)
        self._migrate_if_needed()
        self.load()

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def _migrate_if_needed(self) -> None:
        """Auto-migrate from knowledge_base.json -> memory.json,
        and convert legacy ``category`` field to ``path``."""
        legacy_file = os.path.join(self.cache_dir, "knowledge_base.json")
        if not os.path.exists(self.store_file) and os.path.exists(legacy_file):
            try:
                with open(legacy_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for entry_dict in data.get("entries", {}).values():
                    entry_dict.setdefault("source", "orchestrator")
                    entry_dict.setdefault("last_modified_step", None)
                    entry_dict.setdefault("mutation_history", [])
                    self._migrate_category_to_path(entry_dict)
                with open(self.store_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                logger.info(f"Migrated {legacy_file} -> {self.store_file}")
            except Exception as e:
                logger.warning(f"Failed to migrate knowledge_base.json: {e}")

    @staticmethod
    def _migrate_category_to_path(entry_dict: dict) -> None:
        """Convert a legacy ``category`` field to ``path``, removing it."""
        if "category" in entry_dict and "path" not in entry_dict:
            entry_dict["path"] = entry_dict.pop("category")
        elif "category" in entry_dict:
            entry_dict.pop("category")

    # ------------------------------------------------------------------
    # Deserialization override
    # ------------------------------------------------------------------

    def _deserialize_entry(self, entry_dict: dict) -> MemoryEntry:
        if entry_dict.get("coordinates"):
            entry_dict["coordinates"] = tuple(entry_dict["coordinates"])
        entry_dict.setdefault("source", "orchestrator")
        entry_dict.setdefault("last_modified_step", None)
        entry_dict.setdefault("mutation_history", [])
        self._migrate_category_to_path(entry_dict)
        entry_dict.setdefault("path", "uncategorized")
        return MemoryEntry(**entry_dict)

    # ------------------------------------------------------------------
    # Backward-compat add() — translates legacy ``category`` kwarg
    # ------------------------------------------------------------------

    def add(self, **fields) -> str:
        if "category" in fields and "path" not in fields:
            fields["path"] = fields.pop("category")
        elif "category" in fields:
            fields.pop("category")
        return super().add(**fields)

    # ------------------------------------------------------------------
    # Memory-specific: text search
    # ------------------------------------------------------------------

    def search(
        self,
        path: Optional[str] = None,
        location: Optional[str] = None,
        tags: Optional[List[str]] = None,
        query: Optional[str] = None,
        min_importance: int = 1,
        # Legacy kwarg
        category: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """Filter by structured fields and, when ``query`` is given, rank the
        matches by lexical relevance (BM25) instead of importance. Callers that
        don't pass ``query`` get the old importance-sorted behavior.
        """
        effective_path = path or category

        # Structured pre-filters (path / location / tags / importance).
        candidates = []
        for entry in self.entries.values():
            if entry.importance < min_importance:
                continue
            if effective_path and not entry.path.startswith(effective_path):
                continue
            if location and entry.location != location:
                continue
            if tags and not any(tag in entry.tags for tag in tags):
                continue
            candidates.append(entry)

        if query:
            # Relevance ranking: BM25 over title+content; only entries with a
            # positive score (≥1 query term hit) are returned, best first.
            return self._bm25_rank(query, candidates)

        candidates.sort(key=lambda e: (e.importance, e.updated_at or ""), reverse=True)
        return candidates

    def search_ranked(self, query: str, top_n: int = 10,
                      min_importance: int = 1) -> List[MemoryEntry]:
        """Convenience retriever: BM25-ranked entries for ``query``, capped at
        ``top_n``. Used by push-memory mode's auto-injection (the list_memory tool
        returns all entries unranked; this ranked path is for relevance-scored push)."""
        ranked = self.search(query=query, min_importance=min_importance)
        if top_n is not None and top_n > 0:
            return ranked[:top_n]
        return ranked

    # ------------------------------------------------------------------
    # Lexical relevance (dependency-free BM25)
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        import re
        return re.findall(r"\w+", (text or "").lower())

    def _bm25_rank(self, query: str, candidates: List[MemoryEntry],
                   k1: float = 1.5, b: float = 0.75) -> List[MemoryEntry]:
        """Rank ``candidates`` against ``query`` with Okapi BM25 over the
        combined title+content text. Deterministic; entries scoring 0 (no query
        term present) are dropped. Tie-break by importance then recency then id
        so equal scores order reproducibly.
        """
        import math

        q_terms = self._tokenize(query)
        if not q_terms or not candidates:
            return []

        docs = [self._tokenize(f"{e.title} {e.content}") for e in candidates]
        doc_lens = [len(d) for d in docs]
        avgdl = (sum(doc_lens) / len(doc_lens)) if doc_lens else 0.0
        N = len(candidates)

        # Document frequency per unique query term.
        q_unique = set(q_terms)
        df = {t: 0 for t in q_unique}
        doc_term_counts = []
        for d in docs:
            counts: Dict[str, int] = {}
            for tok in d:
                if tok in q_unique:
                    counts[tok] = counts.get(tok, 0) + 1
            doc_term_counts.append(counts)
            for t in counts:
                df[t] += 1

        scored = []
        for entry, counts, dl in zip(candidates, doc_term_counts, doc_lens):
            score = 0.0
            for t in q_terms:
                tf = counts.get(t, 0)
                if tf == 0:
                    continue
                # BM25 idf (with +1 to stay non-negative for common terms).
                idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
                denom = tf + k1 * (1 - b + b * (dl / avgdl if avgdl else 0))
                score += idf * (tf * (k1 + 1)) / denom if denom else 0.0
            if score > 0:
                scored.append((score, entry))

        scored.sort(
            key=lambda se: (se[0], se[1].importance, se[1].updated_at or "", se[1].id),
            reverse=True,
        )
        return [e for _, e in scored]

    def get_all(self, path: Optional[str] = None, category: Optional[str] = None) -> List[MemoryEntry]:
        """Return all entries, optionally filtered by path prefix."""
        effective_path = path or category
        if effective_path:
            return [e for e in self.entries.values() if e.path.startswith(effective_path)]
        return list(self.entries.values())

    def get_summary(self, max_entries: int = 20, min_importance: int = 3) -> str:
        """Legacy summary format — retained for backward compat."""
        important = [e for e in self.entries.values() if e.importance >= min_importance]
        important.sort(key=lambda e: (e.importance, e.updated_at or ""), reverse=True)
        important = important[:max_entries]

        if not important:
            return "No memory entries yet."

        by_path: Dict[str, list] = {}
        for entry in important:
            by_path.setdefault(entry.path, []).append(entry)

        lines = ["=== LONG-TERM MEMORY SUMMARY ==="]
        for path_key in sorted(by_path.keys()):
            lines.append(f"\n[{path_key.upper()}]")
            for entry in by_path[path_key]:
                location_str = f" @ {entry.location}" if entry.location else ""
                coords_str = f" ({entry.coordinates[0]}, {entry.coordinates[1]})" if entry.coordinates else ""
                lines.append(f"  • {entry.title}{location_str}{coords_str}")
                if len(entry.content) <= 100:
                    lines.append(f"    {entry.content}")
                else:
                    lines.append(f"    {entry.content[:97]}...")

        lines.append(f"\nTotal: {len(important)} important entries (showing importance {min_importance}+)")
        return "\n".join(lines)


# Backward-compat aliases
KnowledgeBase = Memory

# Global singleton
_memory_store: Optional[Memory] = None


def get_memory_store() -> Memory:
    """Get or create the global Memory instance (persistent across runs)."""
    global _memory_store
    if _memory_store is None:
        _memory_store = Memory()
    return _memory_store


get_knowledge_base = get_memory_store
