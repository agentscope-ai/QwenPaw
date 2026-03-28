# -*- coding: utf-8 -*-
"""Unit tests for knowledge import text preprocessing."""

from copaw.agents.knowledge.chunker import chunk_text
from copaw.agents.knowledge.normalizer import normalize_document_text


def test_normalize_document_text_removes_noise() -> None:
    raw = "\r\n\r\nLine A  \r\n\r\n\r\nLine B\r\n\x00\r\n"
    normalized = normalize_document_text(raw)
    assert normalized == "Line A\n\nLine B"


def test_normalize_document_text_strips_surrogates() -> None:
    # Lone surrogate points cannot be encoded as UTF-8 during persistence.
    raw = "Hello" + chr(0xD83D) + "World"
    normalized = normalize_document_text(raw)
    assert normalized == "HelloWorld"


def test_chunk_text_splits_and_preserves_order() -> None:
    text = "A" * 900 + "\n" + "B" * 900 + "\n" + "C" * 900
    chunks = chunk_text(text, chunk_size=1000, overlap=100)

    assert len(chunks) >= 3
    assert chunks[0]["index"] == 0
    assert chunks[0]["chunk_id"] == "chunk-0000"
    # Overlap strategy may produce a short tail chunk; assert C content
    # is present and ordering metadata stays consistent.
    assert any(("C" * 200) in chunk["text"] for chunk in chunks)
    assert chunks[-1]["text"].endswith("C" * 50)
    assert all(chunk["char_count"] == len(chunk["text"]) for chunk in chunks)
