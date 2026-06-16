# -*- coding: utf-8 -*-
"""Regression: Console skill save must use file-baseline operator guard."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.security.file_baseline_bridge import GuardedWriteOutcome
from qwenpaw.app.routers import skills as skills_router


def test_raise_for_operator_guard_denied_maps_to_403():
    outcome = GuardedWriteOutcome(status="denied", message="Operator denied")
    with pytest.raises(HTTPException) as exc_info:
        skills_router._raise_for_operator_guard_outcome(outcome)
    assert exc_info.value.status_code == 403
    assert "denied" in str(exc_info.value.detail).lower()


def test_raise_for_operator_guard_committed_is_ok():
    outcome = GuardedWriteOutcome(status="committed", message="saved")
    skills_router._raise_for_operator_guard_outcome(outcome)


@pytest.mark.asyncio
async def test_save_workspace_skill_skips_disk_write_when_guard_committed(tmp_path):
    workspace_dir = tmp_path / "ws"
    skill_dir = workspace_dir / "skills" / "weather"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# old\n", encoding="utf-8")
    manifest_path = workspace_dir / "skill.json"
    manifest_path.write_text(
        '{"skills":{"weather":{"enabled":true,"channels":["all"]}}}',
        encoding="utf-8",
    )

    request = MagicMock()
    body = skills_router.SaveSkillRequest(name="weather", content="# new\n")

    workspace = MagicMock()
    workspace.workspace_dir = workspace_dir
    workspace.agent_id = "agent-1"

    guard = AsyncMock(return_value="committed")
    save_skill = MagicMock(
        return_value={"success": True, "mode": "edit", "name": "weather"},
    )

    with (
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            new=AsyncMock(return_value=workspace),
        ),
        patch.object(skills_router, "_guard_workspace_skill_md_write", guard),
        patch.object(skills_router.SkillService, "save_skill", save_skill),
        patch.object(skills_router, "schedule_agent_reload"),
    ):
        result = await skills_router.save_workspace_skill(request, body)

    assert result["success"] is True
    guard.assert_awaited_once()
    save_skill.assert_called_once()
    assert save_skill.call_args.kwargs["skip_skill_md_write"] is True


@pytest.mark.asyncio
async def test_save_workspace_skill_propagates_guard_denied(tmp_path):
    request = MagicMock()
    body = skills_router.SaveSkillRequest(name="weather", content="# new\n")
    workspace = MagicMock()
    workspace.workspace_dir = tmp_path
    workspace.agent_id = "agent-1"

    async def _deny(**_kwargs):
        skills_router._raise_for_operator_guard_outcome(
            GuardedWriteOutcome(status="denied", message="denied save"),
        )

    with (
        patch(
            "qwenpaw.app.agent_context.get_agent_for_request",
            new=AsyncMock(return_value=workspace),
        ),
        patch.object(skills_router, "_guard_workspace_skill_md_write", _deny),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await skills_router.save_workspace_skill(request, body)
    assert exc_info.value.status_code == 403


def test_workspace_skill_md_path_resolves_under_skills(tmp_path):
    path = skills_router._workspace_skill_md_path(tmp_path, "weather")
    assert path == tmp_path / "skills" / "weather" / "SKILL.md"
