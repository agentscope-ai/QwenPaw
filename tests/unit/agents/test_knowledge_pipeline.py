# -*- coding: utf-8 -*-
"""Unit tests for knowledge import text preprocessing."""

from copaw.agents.knowledge.chunker import chunk_text
from copaw.agents.knowledge.normalizer import normalize_document_text


def test_normalize_document_text_removes_noise() -> None:
    raw = "\r\n\r\nLine A  \r\n\r\n\r\nLine B\r\n\x00\r\n"
    normalized = normalize_document_text(raw)
    assert normalized == "Line A\n\nLine B"


def test_chunk_text_splits_and_preserves_order() -> None:
    text = "A" * 900 + "\n" + "B" * 900 + "\n" + "C" * 900
    chunks = chunk_text(text, chunk_size=1000, overlap=100)

    assert len(chunks) >= 3
    assert chunks[0]["index"] == 0
    assert chunks[0]["chunk_id"] == "chunk-0000"
    assert chunks[-1]["text"].endswith("C" * 900)
    assert all(chunk["char_count"] == len(chunk["text"]) for chunk in chunks)
