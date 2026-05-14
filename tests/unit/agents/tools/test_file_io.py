# -*- coding: utf-8 -*-
"""Tests for file_io tool helpers."""

from __future__ import annotations

from qwenpaw.agents.tools.file_io import (
    _line_hash,
    edit_file,
    read_file,
)


def _response_text(response) -> str:
    return response.content[0].get("text", "")


async def test_read_file_can_include_line_hashes(tmp_path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("alpha\nbeta", encoding="utf-8")

    response = await read_file(
        str(target),
        start_line=2,
        end_line=2,
        include_line_hashes=True,
    )

    assert _response_text(response) == f"2:{_line_hash(2, 'beta')}: beta"


async def test_edit_file_uses_line_hash_to_target_duplicate_text(
    tmp_path,
) -> None:
    target = tmp_path / "notes.md"
    target.write_text("task: pending\ntask: pending\n", encoding="utf-8")
    second_hash = _line_hash(2, "task: pending")

    response = await edit_file(
        str(target),
        old_text="pending",
        new_text="done",
        line_hash=second_hash,
    )

    assert _response_text(response) == (
        f"Successfully replaced text in {target}."
    )
    assert target.read_text(encoding="utf-8") == "task: pending\ntask: done\n"


async def test_edit_file_rejects_missing_line_hash(tmp_path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("alpha\n", encoding="utf-8")

    response = await edit_file(
        str(target),
        old_text="alpha",
        new_text="beta",
        line_hash="missing0",
    )

    assert "No line with hash" in _response_text(response)
    assert target.read_text(encoding="utf-8") == "alpha\n"
