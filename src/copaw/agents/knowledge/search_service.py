# -*- coding: utf-8 -*-
"""Search service for imported knowledge documents."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .models import KnowledgeSearchHit
from .repository import KnowledgeRepository

_SPACE_RE = re.compile(r"\s+")
_LATIN_TERM_RE = re.compile(r"[a-z0-9_]{2,}")
_CJK_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

_LISTING_PATTERNS = (
    "知识库有什么",
    "知识库里有什么",
    "知识库有哪些",
    "知识库内容",
    "what is in",
    "what's in",
    "what do you have",
    "list knowledge",
    "list documents",
    "show documents",
)


class KnowledgeSearchService:
    """Performs lightweight lexical retrieval on imported knowledge chunks."""

    def __init__(self, workspace_dir: Path):
        self.repo = KnowledgeRepository(Path(workspace_dir).expanduser())

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        min_score: float = 0.12,
        per_doc_limit: int = 2,
    ) -> list[KnowledgeSearchHit]:
        """Return ranked knowledge chunk hits for query."""
        normalized_query = _normalize_text(query)
        if not normalized_query:
            return []

        index = self.repo.load_index()
        documents = index.get("documents", {})
        if not isinstance(documents, dict) or not documents:
            return []

        bounded_max = max(1, min(20, int(max_results)))
        bounded_min = max(0.0, min(1.0, float(min_score)))
        bounded_per_doc = max(1, min(5, int(per_doc_limit)))
        query_terms = _extract_query_terms(normalized_query)
        listing_query = _is_listing_query(normalized_query)

        hits: list[KnowledgeSearchHit] = []
        matched_any = False

        for doc_id, meta in documents.items():
            if not isinstance(meta, dict):
                continue

            title = str(meta.get("title") or doc_id)
            title_norm = _normalize_text(title)
            source_file = str(meta.get("source_file") or "")
            source_type = str(meta.get("source_type") or "unknown")
            imported_at = str(meta.get("imported_at") or "")
            chunks = self.repo.load_document_chunks(doc_id, meta=meta)

            for chunk in chunks:
                chunk_text = str(chunk.get("text") or "").strip()
                if not chunk_text:
                    continue

                chunk_norm = _normalize_text(chunk_text)
                lexical_score, hit_count = _score_chunk(
                    query_terms,
                    chunk_norm,
                )
                title_boost = (
                    0.12
                    if hit_count > 0
                    and _score_title_overlap(query_terms, title_norm) > 0
                    else 0.0
                )

                try:
                    chunk_index = int(chunk.get("index", 0))
                except (TypeError, ValueError):
                    chunk_index = 0
                position_boost = 0.08 / (1 + max(0, chunk_index))
                score = lexical_score + title_boost + position_boost

                if hit_count > 0:
                    matched_any = True

                if hit_count == 0 and not listing_query:
                    continue
                if score < bounded_min:
                    continue

                hits.append(
                    KnowledgeSearchHit(
                        doc_id=doc_id,
                        title=title,
                        source_file=source_file,
                        source_type=source_type,
                        imported_at=imported_at,
                        chunk_id=str(
                            chunk.get("chunk_id")
                            or f"chunk-{chunk_index:04d}",
                        ),
                        chunk_index=chunk_index,
                        chunk_text=chunk_text,
                        score=round(score, 6),
                    ),
                )

        if not matched_any and listing_query:
            return self._fallback_listing_hits(
                documents=documents,
                max_results=bounded_max,
                min_score=bounded_min,
            )

        hits.sort(
            key=lambda item: (
                item.score,
                item.imported_at,
                -item.chunk_index,
            ),
            reverse=True,
        )
        return _apply_per_doc_limit(
            hits,
            max_results=bounded_max,
            per_doc_limit=bounded_per_doc,
        )

    def _fallback_listing_hits(
        self,
        *,
        documents: dict[str, Any],
        max_results: int,
        min_score: float,
    ) -> list[KnowledgeSearchHit]:
        fallback_score = 0.2
        if fallback_score < min_score:
            return []

        doc_items = sorted(
            (
                (doc_id, meta)
                for doc_id, meta in documents.items()
                if isinstance(meta, dict)
            ),
            key=lambda item: str(item[1].get("imported_at") or ""),
            reverse=True,
        )
        preview_hits: list[KnowledgeSearchHit] = []
        for doc_id, meta in doc_items:
            chunks = self.repo.load_document_chunks(doc_id, meta=meta)
            first = next(
                (
                    chunk
                    for chunk in chunks
                    if str(chunk.get("text") or "").strip()
                ),
                None,
            )
            if first is None:
                continue
            text = str(first.get("text") or "").strip()
            try:
                index = int(first.get("index", 0))
            except (TypeError, ValueError):
                index = 0
            preview_hits.append(
                KnowledgeSearchHit(
                    doc_id=doc_id,
                    title=str(meta.get("title") or doc_id),
                    source_file=str(meta.get("source_file") or ""),
                    source_type=str(meta.get("source_type") or "unknown"),
                    imported_at=str(meta.get("imported_at") or ""),
                    chunk_id=str(
                        first.get("chunk_id") or f"chunk-{index:04d}",
                    ),
                    chunk_index=index,
                    chunk_text=text,
                    score=fallback_score,
                ),
            )
            if len(preview_hits) >= max_results:
                break

        return preview_hits


def _normalize_text(text: str) -> str:
    lowered = text.lower().strip()
    return _SPACE_RE.sub(" ", lowered)


def _extract_query_terms(normalized_query: str) -> list[str]:
    terms: list[str] = []
    terms.extend(_CJK_TERM_RE.findall(normalized_query))
    terms.extend(_LATIN_TERM_RE.findall(normalized_query))
    if not terms and normalized_query:
        terms.append(normalized_query)
    return _dedupe_terms(terms)


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for term in terms:
        t = term.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        ordered.append(t)
    return ordered


def _is_listing_query(normalized_query: str) -> bool:
    return any(pattern in normalized_query for pattern in _LISTING_PATTERNS)


def _score_chunk(query_terms: list[str], chunk_norm: str) -> tuple[float, int]:
    if not query_terms:
        return 0.0, 0

    total_weight = 0.0
    hit_weight = 0.0
    hit_count = 0
    for term in query_terms:
        weight = _term_weight(term)
        total_weight += weight
        if _contains_term(term, chunk_norm):
            hit_weight += weight
            hit_count += 1

    if total_weight <= 0.0:
        return 0.0, hit_count

    coverage = hit_weight / total_weight
    density = hit_count / len(query_terms)
    return coverage * 0.8 + density * 0.2, hit_count


def _score_title_overlap(query_terms: list[str], title_norm: str) -> float:
    if not query_terms or not title_norm:
        return 0.0
    hit_count = sum(
        1 for term in query_terms if _contains_term(term, title_norm)
    )
    return hit_count / len(query_terms)


def _term_weight(term: str) -> float:
    return max(1.0, min(4.0, 1.0 + len(term) / 8.0))


def _contains_term(term: str, normalized_text: str) -> bool:
    if not term:
        return False
    if _LATIN_TERM_RE.fullmatch(term):
        pattern = rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])"
        return re.search(pattern, normalized_text) is not None
    return term in normalized_text


def _apply_per_doc_limit(
    hits: list[KnowledgeSearchHit],
    *,
    max_results: int,
    per_doc_limit: int,
) -> list[KnowledgeSearchHit]:
    selected: list[KnowledgeSearchHit] = []
    per_doc_count: dict[str, int] = {}
    for hit in hits:
        current = per_doc_count.get(hit.doc_id, 0)
        if current >= per_doc_limit:
            continue
        selected.append(hit)
        per_doc_count[hit.doc_id] = current + 1
        if len(selected) >= max_results:
            break
    return selected


__all__ = ["KnowledgeSearchHit", "KnowledgeSearchService"]
