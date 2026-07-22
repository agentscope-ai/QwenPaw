# -*- coding: utf-8 -*-
"""Tests for cross-platform atomic file writes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.utils.atomic_io import write_json_atomic, write_text_atomic


def test_write_json_atomic_replaces_complete_document(tmp_path: Path) -> None:
    """JSON writes replace the destination with one complete document."""
    path = tmp_path / "state.json"
    path.write_text("old", encoding="utf-8")

    write_json_atomic(path, {"value": "new"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": "new"}
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_write_text_atomic_preserves_destination_on_replace_error(
    tmp_path: Path,
) -> None:
    """A failed Windows-style replace leaves the previous file intact."""
    path = tmp_path / "state.txt"
    path.write_text("old", encoding="utf-8")

    with (
        patch(
            "qwenpaw.utils.atomic_io.os.replace",
            side_effect=PermissionError("locked"),
        ),
        pytest.raises(PermissionError, match="locked"),
    ):
        write_text_atomic(path, "new")

    assert path.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".state.txt.*.tmp"))
