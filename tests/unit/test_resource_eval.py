# -*- coding: utf-8 -*-
"""Unit tests for embedding resource hints."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# pylint: disable-next=wrong-import-position
from copaw.embedding.resource_eval import embedding_resource_hint  # noqa: E402


def test_embedding_resource_hint_shape():
    h = embedding_resource_hint()
    assert h["platform"]
    assert "cpu_count" in h
    assert "ram_total_gb" in h
    assert "gpus" in h
    assert isinstance(h["gpus"], list)
    assert "recommendation" in h
    assert "model_tiers" in h
    assert "text_small" in h["model_tiers"]
    assert "note" in h
