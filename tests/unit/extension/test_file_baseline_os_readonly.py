# -*- coding: utf-8
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "extension"))

from file_baseline.os_readonly import (
    apply_os_readonly_for_paths,
    clear_os_readonly_for_paths,
    is_os_readonly,
    temporary_os_writable,
)
from file_baseline.service import FileBaselineService


def test_os_readonly_blocks_direct_write(tmp_path: Path) -> None:
    soul = tmp_path / "SOUL.md"
    soul.write_text("baseline\n", encoding="utf-8")
    apply_os_readonly_for_paths(tmp_path, ["SOUL.md"])
    assert is_os_readonly(soul)
    with pytest.raises(PermissionError):
        soul.write_text("tamper\n", encoding="utf-8")
    clear_os_readonly_for_paths(tmp_path, ["SOUL.md"])
    assert not is_os_readonly(soul)
    soul.write_text("tamper\n", encoding="utf-8")


def test_temporary_os_writable_allows_commit_style_write(tmp_path: Path) -> None:
    soul = tmp_path / "SOUL.md"
    soul.write_text("baseline\n", encoding="utf-8")
    apply_os_readonly_for_paths(tmp_path, ["SOUL.md"])
    with temporary_os_writable([soul]):
        soul.write_text("approved\n", encoding="utf-8")
    assert soul.read_text(encoding="utf-8") == "approved\n"
    assert is_os_readonly(soul)


@pytest.mark.asyncio
async def test_enable_applies_os_readonly(tmp_path: Path) -> None:
    soul = tmp_path / "SOUL.md"
    soul.write_text("baseline\n", encoding="utf-8")
    service = FileBaselineService(tmp_path)
    await service.update_settings(enabled=True)
    assert is_os_readonly(soul)


@pytest.mark.asyncio
async def test_disable_clears_os_readonly(tmp_path: Path) -> None:
    soul = tmp_path / "SOUL.md"
    soul.write_text("baseline\n", encoding="utf-8")
    service = FileBaselineService(tmp_path)
    await service.update_settings(enabled=True)
    assert is_os_readonly(soul)
    await service.update_settings(enabled=False)
    assert not is_os_readonly(soul)
