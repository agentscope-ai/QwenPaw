# -*- coding: utf-8 -*-
"""Integration tests for Context & Scroll module internals.

Covers src/qwenpaw/agents/context/* (visual_compression budget +
precision, scroll sync) — 1,783 uncovered lines.
"""

from __future__ import annotations

import pytest


# ------------------------------------------------------------------ #
# budget
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_count_text_tokens() -> None:
    """count_text_tokens estimates tokens from characters."""
    from qwenpaw.agents.context.visual_compression.pipeline.budget import (
        count_text_tokens,
    )

    assert count_text_tokens("") == 0
    assert count_text_tokens("a" * 400) == 100


@pytest.mark.integration
@pytest.mark.p1
def test_estimate_image_tokens_empty() -> None:
    """estimate_image_tokens returns 0 for no pages."""
    from qwenpaw.agents.context.visual_compression.pipeline.budget import (
        estimate_image_tokens,
    )

    assert estimate_image_tokens([]) == 0


# ------------------------------------------------------------------ #
# precision / factsheet
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_trim_context_whitespace() -> None:
    """_trim_context_whitespace strips surrounding whitespace."""
    from qwenpaw.agents.context.visual_compression.pipeline.precision import (
        _trim_context_whitespace,
    )

    assert _trim_context_whitespace("  x  ") == "x"


@pytest.mark.integration
@pytest.mark.p1
def test_extract_fact_entries_urls() -> None:
    """extract_fact_entries pulls exact tokens (urls) from text."""
    from qwenpaw.agents.context.visual_compression.pipeline.precision import (
        extract_fact_entries,
    )

    entries = extract_fact_entries(
        "see https://example.com/a for details",
    )
    assert isinstance(entries, list)
    assert len(entries) >= 1


@pytest.mark.integration
@pytest.mark.p1
def test_factsheet_text_empty() -> None:
    """factsheet_text returns empty string when no facts found."""
    from qwenpaw.agents.context.visual_compression.pipeline.precision import (
        factsheet_text,
    )

    assert factsheet_text("plain words only") == ""


# ------------------------------------------------------------------ #
# scroll sync
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_sha256(tmp_path) -> None:
    """_sha256 hashes a file deterministically."""
    from qwenpaw.agents.context.scroll.sync import _sha256

    f = tmp_path / "x.txt"
    f.write_text("hello")
    h1 = _sha256(f)
    h2 = _sha256(f)
    assert h1 == h2
    assert len(h1) == 64


@pytest.mark.integration
@pytest.mark.p1
def test_load_save_manifest_roundtrip(tmp_path) -> None:
    """_load_manifest/_save_manifest round-trip a manifest."""
    from qwenpaw.agents.context.scroll.sync import (
        _load_manifest,
        _save_manifest,
    )

    manifest_path = tmp_path / "manifest.json"
    _save_manifest(manifest_path, {"version": 2, "files": {"a": 1}})
    loaded = _load_manifest(manifest_path)
    assert loaded.get("files") == {"a": 1}


@pytest.mark.integration
@pytest.mark.p1
def test_load_manifest_missing(tmp_path) -> None:
    """_load_manifest returns a versioned empty manifest when missing."""
    from qwenpaw.agents.context.scroll.sync import _load_manifest

    loaded = _load_manifest(tmp_path / "missing.json")
    assert loaded.get("files") == {}
    assert "version" in loaded
