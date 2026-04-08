# -*- coding: utf-8 -*-
"""Chunking helpers for imported knowledge text."""

from __future__ import annotations

from typing import TypedDict


class KnowledgeChunk(TypedDict):
    """Serializable chunk payload for one document segment."""

    chunk_id: str
    index: int
    text: str
    char_count: int


def chunk_text(
    text: str,
    *,
    chunk_size: int = 1200,
    overlap: int = 120,
) -> list[KnowledgeChunk]:
    """Split normalized text into overlapping character chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    clean_text = text.strip()
    if not clean_text:
        return []

    bounded_overlap = max(0, min(overlap, chunk_size // 2))
    chunks: list[KnowledgeChunk] = []
    start = 0
    text_len = len(clean_text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        if end < text_len:
            boundary = clean_text.rfind("\n", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary

        segment = clean_text[start:end].strip()
        if segment:
            index = len(chunks)
            chunks.append(
                KnowledgeChunk(
                    chunk_id=f"chunk-{index:04d}",
                    index=index,
                    text=segment,
                    char_count=len(segment),
                ),
            )

        if end >= text_len:
            break

        next_start = end - bounded_overlap
        start = end if next_start <= start else next_start

    return chunks
