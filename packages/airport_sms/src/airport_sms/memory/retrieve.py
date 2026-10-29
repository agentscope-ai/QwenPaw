"""检索长期记忆。自动检索不改写案件。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from enum import Enum

from airport_sms.domain.case import Case
from airport_sms.memory.embedder import Embedder
from airport_sms.memory.store import MemoryStore, SourceType


class MemoryScope(str, Enum):
    """工作记忆在会话内，长期记忆在本模块。"""

    WORKING = "working"
    LONG_TERM = "long_term"


@dataclass(frozen=True)
class Snippet:
    """一条检索命中。"""

    doc_id: str
    source_id: str
    source_type: SourceType
    text: str
    score: float
    derived: bool


@dataclass(frozen=True)
class RetrievalResult:
    """带延迟的检索结果。不包含案件变更。"""

    snippets: tuple[Snippet, ...]
    latency_ms: float
    scope: MemoryScope = MemoryScope.LONG_TERM


class Retriever:
    """top-k 检索。cite 才会把条款写回案件副本。"""

    def __init__(self, store: MemoryStore, embedder: Embedder) -> None:
        self._store = store
        self._embedder = embedder

    def retrieve(
        self, org_id: str, query: str, *, k: int = 5
    ) -> RetrievalResult:
        """返回排序片段。不写案件。"""
        start = time.perf_counter()
        rows = self._store.rows(org_id)
        if not rows:
            return RetrievalResult(
                snippets=(),
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        query_vec = self._embedder.embed([query])[0]
        scored: list[Snippet] = []
        for row in rows:
            vec = json.loads(row["embedding"])
            snippet = Snippet(
                doc_id=row["doc_id"],
                source_id=row["source_id"],
                source_type=SourceType(row["source_type"]),
                text=row["text"],
                score=_cosine(query_vec, vec),
                derived=bool(row["derived"]),
            )
            scored.append(snippet)
        scored.sort(key=lambda item: item.score, reverse=True)
        return RetrievalResult(
            snippets=tuple(scored[:k]),
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    def cite(self, case: Case, snippets: tuple[Snippet, ...]) -> Case:
        """工人引用片段后，把 source_id 写入案件 cited_clauses。"""
        ids = tuple(
            dict.fromkeys(
                (*case.cited_clauses, *(item.source_id for item in snippets))
            )
        )
        return replace(case, cited_clauses=ids, version=case.version + 1)


def _cosine(left: list[float], right: list[float]) -> float:
    """余弦相似度。"""
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm_l = sum(a * a for a in left) ** 0.5
    norm_r = sum(b * b for b in right) ** 0.5
    if norm_l == 0 or norm_r == 0:
        return 0.0
    return dot / (norm_l * norm_r)


__all__ = [
    "MemoryScope",
    "RetrievalResult",
    "Retriever",
    "Snippet",
]
