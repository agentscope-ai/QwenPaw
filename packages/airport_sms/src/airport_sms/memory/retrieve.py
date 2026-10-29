"""检索长期记忆。自动检索与引用都不写案件行。"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from airport_sms.memory.store import MemoryStore, SourceType


class MemoryScope(str, Enum):
    """工作记忆在会话内，长期记忆在本模块。"""

    WORKING = "working"
    LONG_TERM = "long_term"


@dataclass(frozen=True)
class Snippet:
    """一条检索命中。"""

    doc_id: str
    org_id: str
    source_id: str
    source_type: SourceType
    text: str
    score: float

    @property
    def derived(self) -> bool:
        """结案记忆是派生的。"""
        return self.source_type is SourceType.CLOSED_CASE


@dataclass(frozen=True)
class RetrievalResult:
    """带延迟的检索结果。不含案件变更。"""

    snippets: tuple[Snippet, ...]
    latency_ms: float
    scope: MemoryScope = MemoryScope.LONG_TERM


@dataclass(frozen=True)
class CitationProposal:
    """工人引用后的提案。条款 id 只记在这里。"""

    cited_source_ids: tuple[str, ...]
    snippets: tuple[Snippet, ...]


class Retriever:
    """top-k 检索。cite 只生成提案，不写案件。"""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def retrieve(self, org_id: str, query: str, *, k: int = 5) -> RetrievalResult:
        """返回排序片段。不写案件行。"""
        start = time.perf_counter()
        rows = self._store.load(org_id)
        if not rows:
            return RetrievalResult(
                snippets=(),
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        query_vec = self._store.embedder.embed([query])[0]
        scored = [
            Snippet(
                doc_id=doc.doc_id,
                org_id=doc.org_id,
                source_id=doc.source_id,
                source_type=doc.source_type,
                text=doc.text,
                score=_cosine(query_vec, vec),
            )
            for doc, vec in rows
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        return RetrievalResult(
            snippets=tuple(scored[:k]),
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    def cite(self, snippets: Sequence[Snippet]) -> CitationProposal:
        """把命中的 source_id 记到提案上，不写案件。"""
        ids = tuple(dict.fromkeys(item.source_id for item in snippets))
        return CitationProposal(cited_source_ids=ids, snippets=tuple(snippets))


def _cosine(left: list[float], right: list[float]) -> float:
    """余弦相似度。维度必须一致。"""
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_l = sum(a * a for a in left) ** 0.5
    norm_r = sum(b * b for b in right) ** 0.5
    if norm_l == 0 or norm_r == 0:
        return 0.0
    return dot / (norm_l * norm_r)


__all__ = [
    "CitationProposal",
    "MemoryScope",
    "RetrievalResult",
    "Retriever",
    "Snippet",
]
