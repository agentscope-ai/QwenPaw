# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "extension"))

from persona_baseline.service import PersonaBaselineService
from persona_baseline.shell_preflight import (
    detect_python_protected_write_targets,
    detect_shell_protected_write_targets,
)


@pytest.fixture
def persona_service(tmp_path: Path) -> PersonaBaselineService:
    (tmp_path / "SOUL.md").write_text("baseline\n", encoding="utf-8")
    service = PersonaBaselineService(tmp_path)
    return service


@pytest.mark.asyncio
async def test_shell_detects_redirect_to_soul(persona_service: PersonaBaselineService) -> None:
    await persona_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        persona_service,
        agent_id="default",
        command='echo tamper >> SOUL.md',
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_ignores_read_only(persona_service: PersonaBaselineService) -> None:
    await persona_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        persona_service,
        agent_id="default",
        command="type SOUL.md",
    )
    assert targets == []


@pytest.mark.asyncio
async def test_shell_detects_powershell_command_wrapper(
    persona_service: PersonaBaselineService,
) -> None:
    await persona_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        persona_service,
        agent_id="default",
        command='powershell -Command "Set-Content -Path SOUL.md -Value hello"',
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_powershell_no_profile_wrapper(
    persona_service: PersonaBaselineService,
) -> None:
    await persona_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        persona_service,
        agent_id="default",
        command='powershell.exe -NoProfile -Command "Set-Content SOUL.md -Value x"',
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_write_all_text_replace_chain(
    persona_service: PersonaBaselineService,
) -> None:
    await persona_service.update_settings(enabled=True)
    cmd = (
        "$c=[IO.File]::ReadAllText('SOUL.md'); "
        "$c=$c -replace 'old','new'; "
        "[IO.File]::WriteAllText('SOUL.md',$c)"
    )
    targets = detect_shell_protected_write_targets(
        persona_service,
        agent_id="default",
        command=cmd,
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_detects_append_all_text(persona_service: PersonaBaselineService) -> None:
    await persona_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        persona_service,
        agent_id="default",
        command="[System.IO.File]::AppendAllText('SOUL.md', 'tamper')",
    )
    assert targets == ["SOUL.md"]


@pytest.mark.asyncio
async def test_shell_ignores_read_only_get_content(
    persona_service: PersonaBaselineService,
) -> None:
    await persona_service.update_settings(enabled=True)
    targets = detect_shell_protected_write_targets(
        persona_service,
        agent_id="default",
        command="Get-Content SOUL.md",
    )
    assert targets == []


@pytest.mark.asyncio
async def test_python_detects_open_write(persona_service: PersonaBaselineService) -> None:
    await persona_service.update_settings(enabled=True)
    targets = detect_python_protected_write_targets(
        persona_service,
        agent_id="default",
        code="open('SOUL.md', 'w').write('x')",
    )
    assert targets == ["SOUL.md"]
