# -*- coding: utf-8
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "extension"))

from file_baseline.agent_write import try_guarded_agent_file_write
from file_baseline.frozen_store import (
    frozen_approved_path,
    get_frozen_entry,
    restore_workspace_from_frozen,
    sync_frozen_agent_paths,
)
from file_baseline.paths import agent_state_dir, file_baseline_root
from file_baseline.service import FileBaselineService
from file_baseline.trust_root import (
    agent_integrity_write_blocked,
    detect_integrity_state_write_in_text,
)
from file_baseline.os_readonly import temporary_os_writable, write_external_content
from file_baseline.write_context import file_baseline_maintenance_context


def test_agent_blocked_from_baselines_json(tmp_path: Path) -> None:
    baselines = (
        tmp_path
        / "integrity-protection"
        / "file-baseline"
        / "default"
        / "baselines.json"
    )
    baselines.parent.mkdir(parents=True, exist_ok=True)
    baselines.write_text('{"files": {}}\n', encoding="utf-8")

    blocked = agent_integrity_write_blocked(tmp_path, baselines)
    assert blocked is not None
    assert "integrity-protection" in blocked


@pytest.mark.asyncio
async def test_write_file_guard_denies_baselines_json(tmp_path: Path) -> None:
    baselines = (
        tmp_path
        / "integrity-protection"
        / "file-baseline"
        / "default"
        / "baselines.json"
    )
    baselines.parent.mkdir(parents=True, exist_ok=True)
    baselines.write_text('{"files": {}}\n', encoding="utf-8")

    soul = tmp_path / "SOUL.md"
    soul.write_text("baseline\n", encoding="utf-8")
    service = FileBaselineService(tmp_path)
    await service.update_settings(enabled=True)

    outcome = await try_guarded_agent_file_write(
        service,
        absolute_path=str(baselines),
        content='{"tampered": true}\n',
        tool_name="write_file",
    )
    assert outcome.status == "denied"
    assert "integrity-protection" in outcome.message


def test_shell_detects_hidden_integrity_state_write(tmp_path: Path) -> None:
    cmd = (
        "python -c \"open('integrity-protection/file-baseline/default/baselines.json','w').write('x')\""
    )
    hits = detect_integrity_state_write_in_text(tmp_path, cmd, cwd=tmp_path)
    assert hits


def test_shell_detects_low_level_integrity_state_write(tmp_path: Path) -> None:
    cmd = (
        "python -c \"import os; "
        "fd=os.open('integrity-protection/file-baseline/default/baselines.json', "
        "os.O_WRONLY | os.O_TRUNC); os.write(fd, b'x')\""
    )
    hits = detect_integrity_state_write_in_text(tmp_path, cmd, cwd=tmp_path)
    assert hits == ["integrity-protection/file-baseline/default/baselines.json"]


@pytest.mark.asyncio
async def test_frozen_restore_after_poisoned_approved(tmp_path: Path) -> None:
    soul = tmp_path / "SOUL.md"
    soul.write_text("approved soul baseline\n", encoding="utf-8")
    service = FileBaselineService(tmp_path)
    await service.update_settings(enabled=True)

    agent_id = "default"
    state_dir = agent_state_dir(tmp_path, agent_id)
    approved = state_dir / "approved" / "SOUL.md"
    assert approved.is_file()

    with file_baseline_maintenance_context():
        sync_frozen_agent_paths(
            tmp_path,
            agent_id,
            workspace=tmp_path,
            state_dir=state_dir,
            rel_paths=["SOUL.md"],
        )

    entry = get_frozen_entry(tmp_path, agent_id, "SOUL.md")
    assert entry is not None

    write_external_content(approved, "tampered approved copy\n")
    with temporary_os_writable([soul]):
        soul.write_text("tampered workspace\n", encoding="utf-8")

    assert restore_workspace_from_frozen(
        tmp_path,
        agent_id,
        workspace=tmp_path,
        rel_path="SOUL.md",
    )
    assert soul.read_text(encoding="utf-8") == "approved soul baseline\n"
    assert frozen_approved_path(tmp_path, agent_id, "SOUL.md").is_file()
