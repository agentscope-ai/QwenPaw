# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.security.tool_guard.engine import ToolGuardEngine
from qwenpaw.security.tool_guard.guardians.file_guardian import (
    WriteFileOverwriteGuardian,
)


@pytest.fixture(autouse=True)
def _enable_file_guard(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.security.tool_guard.guardians.file_guardian._is_file_guard_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "qwenpaw.security.tool_guard.guardians.file_guardian._is_write_file_overwrite_guard_enabled",
        lambda: True,
    )


def _guard(file_path: str):
    guardian = WriteFileOverwriteGuardian()
    return guardian.guard("write_file", {"file_path": file_path})


def test_write_file_allows_new_file(tmp_path):
    target = tmp_path / "new.txt"

    assert _guard(str(target)) == []


def test_write_file_allows_empty_existing_file(tmp_path):
    target = tmp_path / "empty.txt"
    target.write_text("", encoding="utf-8")

    assert _guard(str(target)) == []


def test_write_file_blocks_non_empty_existing_file(tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("content", encoding="utf-8")

    findings = _guard(str(target))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "WRITE_FILE_OVERWRITE_NON_EMPTY"
    assert finding.tool_name == "write_file"
    assert finding.param_name == "file_path"
    assert finding.metadata["size"] == len("content")


def test_write_file_guard_ignores_other_tools(tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("content", encoding="utf-8")
    guardian = WriteFileOverwriteGuardian()

    assert guardian.guard("edit_file", {"file_path": str(target)}) == []


def test_write_file_guard_respects_overwrite_switch(tmp_path, monkeypatch):
    target = tmp_path / "existing.txt"
    target.write_text("content", encoding="utf-8")
    monkeypatch.setattr(
        "qwenpaw.security.tool_guard.guardians.file_guardian._is_write_file_overwrite_guard_enabled",
        lambda: False,
    )
    guardian = WriteFileOverwriteGuardian()

    assert guardian.guard("write_file", {"file_path": str(target)}) == []


def test_default_engine_registers_write_file_overwrite_guardian():
    engine = ToolGuardEngine(enabled=True)

    assert "write_file_overwrite_guardian" in engine.guardian_names
