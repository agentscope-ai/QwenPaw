# -*- coding: utf-8
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "extension"))

from file_baseline.os_readonly import temporary_os_writable, write_external_content
from file_baseline.post_command_verify import verify_protected_baselines_after_command
from file_baseline.service import FileBaselineService


@pytest.mark.asyncio
async def test_post_command_verify_restores_tampered_soul(tmp_path: Path) -> None:
    soul = tmp_path / "SOUL.md"
    soul.write_text("approved soul baseline\n", encoding="utf-8")
    service = FileBaselineService(tmp_path)
    await service.update_settings(enabled=True)

    write_external_content(soul, "approved soul baseline\n# tampered\n")

    restored = await verify_protected_baselines_after_command(
        service,
        agent_id="default",
    )
    assert restored == ["SOUL.md"]
    assert soul.read_text(encoding="utf-8") == "approved soul baseline\n"
    assert service.drift_store.open_count() >= 1


@pytest.mark.asyncio
async def test_post_command_verify_restores_missing_soul(tmp_path: Path) -> None:
    soul = tmp_path / "SOUL.md"
    soul.write_text("approved soul baseline\n", encoding="utf-8")
    service = FileBaselineService(tmp_path)
    await service.update_settings(enabled=True)

    with temporary_os_writable([soul]):
        soul.unlink()

    restored = await verify_protected_baselines_after_command(
        service,
        agent_id="default",
    )
    assert restored == ["SOUL.md"]
    assert soul.is_file()
    assert soul.read_text(encoding="utf-8") == "approved soul baseline\n"
