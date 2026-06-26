# -*- coding: utf-8 -*-
"""Unit tests for migration._ensure_workspace_json_files."""
from __future__ import annotations

import json
from pathlib import Path

from qwenpaw.app.migration import _ensure_workspace_json_files


def test_creates_missing_json_files(tmp_path: Path):
    _ensure_workspace_json_files(tmp_path, label="test")

    json_files = list(tmp_path.glob("*.json"))
    assert len(json_files) > 0


def test_does_not_overwrite_existing(tmp_path: Path):
    chats_path = tmp_path / "chats.json"
    chats_path.write_text(
        '{"version":1,"chats":[{"id":"keep-me"}]}',
        encoding="utf-8",
    )

    _ensure_workspace_json_files(tmp_path, label="test")

    data = json.loads(chats_path.read_text(encoding="utf-8"))
    assert data["chats"][0]["id"] == "keep-me"


def test_created_files_are_valid_json(tmp_path: Path):
    _ensure_workspace_json_files(tmp_path, label="test")

    for fp in tmp_path.glob("*.json"):
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
