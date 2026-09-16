# -*- coding: utf-8 -*-
"""运行配置关联接口的目标 Agent 与写前授权测试。"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.agent_context import require_running_config_editor
from qwenpaw.app.routers.coding_mode import (
    CodingModeToggleRequest,
    get_coding_mode,
    post_coding_mode_toggle,
)
from qwenpaw.app.routers.plan import get_plan_config, put_plan_config
from qwenpaw.app.routers.project_directory import (
    SetProjectRequest,
    _workspace_resolution_metadata,
    get_project,
    set_project,
)
from qwenpaw.app.routers.workspace import (
    test_embedding_configuration as run_embedding_test,
)
from qwenpaw.app.routers.agents import _require_agent_role
from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.config.config import EmbeddingModelConfig
from qwenpaw.plan.schemas import PlanConfigResponse


def _request() -> SimpleNamespace:
    return SimpleNamespace()


def test_project_directory_exposes_workspace_resolution_metadata() -> None:
    workspace = SimpleNamespace(
        workspace_kind="user_runtime",
        workspace_key="user_workspaces/user-a/agent-a",
        workspace_read_only=False,
    )

    assert _workspace_resolution_metadata(workspace) == {
        "workspace_kind": "user_runtime",
        "workspace_key": "user_workspaces/user-a/agent-a",
        "workspace_read_only": False,
    }


def test_legacy_workspace_metadata_remains_compatible() -> None:
    workspace = SimpleNamespace(workspace_dir=Path("legacy-agent"))

    assert _workspace_resolution_metadata(workspace) == {
        "workspace_kind": "legacy",
        "workspace_key": "legacy-agent",
        "workspace_read_only": False,
    }


@pytest.mark.parametrize("role", ["user", "viewer"])
def test_read_only_member_cannot_access_complete_runtime_config(
    role: str,
) -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=SimpleNamespace(value=role),
                historical_read_only=False,
            ),
        ),
    )

    with pytest.raises(HTTPException) as error:
        require_running_config_editor(request)

    assert error.value.status_code == 403


@pytest.mark.parametrize("role", ["owner", "collaborator"])
def test_editing_member_can_access_complete_runtime_config(role: str) -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=SimpleNamespace(value=role),
                historical_read_only=False,
            ),
        ),
    )

    require_running_config_editor(request)


def test_admin_governance_can_access_complete_runtime_config() -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_governance=SimpleNamespace(agent_key="managed-agent"),
        ),
    )

    require_running_config_editor(request)


@pytest.mark.asyncio
async def test_project_directory_reads_use_runtime_config_target() -> None:
    request = _request()
    workspace = SimpleNamespace(
        agent_id="governed-agent",
        workspace_dir=SimpleNamespace(),
    )
    with (
        patch(
            "qwenpaw.app.routers.project_directory.get_running_config_workspace",
            AsyncMock(return_value=workspace),
        ) as resolve,
        patch(
            "qwenpaw.app.routers.project_directory.asyncio.to_thread",
            AsyncMock(
                return_value={
                    "path": "/governed",
                    "name": "governed",
                    "is_workspace_default": False,
                },
            ),
        ),
        patch(
            "qwenpaw.app.routers.project_directory.get_files_workspace_access",
            AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "qwenpaw.app.routers.project_directory.get_agent_project_dir",
            return_value=Path("/governed"),
        ),
    ):
        result = await get_project(request)

    assert result["path"] == "/governed"
    resolve.assert_awaited_once_with(
        request,
        action="agent.admin.runtime_config.project_directory.view",
    )


@pytest.mark.asyncio
async def test_project_directory_write_denial_happens_before_save() -> None:
    denied = HTTPException(status_code=403, detail="forbidden")
    with (
        patch(
            "qwenpaw.app.routers.project_directory.get_running_config_workspace",
            AsyncMock(side_effect=denied),
        ),
        patch(
            "qwenpaw.app.routers.project_directory._save_project_dir",
        ) as save,
    ):
        with pytest.raises(HTTPException) as error:
            await set_project(SetProjectRequest(path=None), _request())

    assert error.value.status_code == 403
    save.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_project_directory_is_rejected_before_save() -> None:
    workspace = SimpleNamespace(agent_id="governed-agent")
    with (
        patch(
            "qwenpaw.app.routers.project_directory.get_running_config_workspace",
            AsyncMock(return_value=workspace),
        ),
        patch("pathlib.Path.exists", return_value=False),
        patch(
            "qwenpaw.app.routers.project_directory._save_project_dir",
        ) as save,
    ):
        with pytest.raises(HTTPException) as error:
            await set_project(SetProjectRequest(path="/missing"), _request())

    assert error.value.status_code == 400
    save.assert_not_called()


@pytest.mark.asyncio
async def test_coding_mode_reads_use_runtime_config_target() -> None:
    workspace = SimpleNamespace(agent_id="governed-agent")
    config = SimpleNamespace(
        id="governed-agent",
        coding_mode=SimpleNamespace(enabled=False),
    )
    with (
        patch(
            "qwenpaw.app.routers.coding_mode.get_running_config_workspace",
            AsyncMock(return_value=workspace),
        ) as resolve,
        patch(
            "qwenpaw.config.config.load_agent_config",
            return_value=config,
        ),
    ):
        result = await get_coding_mode(_request())

    assert result == {"enabled": False, "agent_id": "governed-agent"}
    resolve.assert_awaited_once()


@pytest.mark.asyncio
async def test_coding_mode_write_denial_happens_before_save_and_reload() -> None:
    denied = HTTPException(status_code=403, detail="forbidden")
    with (
        patch(
            "qwenpaw.app.routers.coding_mode.get_running_config_workspace",
            AsyncMock(side_effect=denied),
        ),
        patch("qwenpaw.config.config.save_agent_config") as save,
        patch("qwenpaw.app.routers.coding_mode.schedule_agent_reload") as reload,
    ):
        with pytest.raises(HTTPException) as error:
            await post_coding_mode_toggle(
                CodingModeToggleRequest(enabled=True),
                _request(),
            )

    assert error.value.status_code == 403
    save.assert_not_called()
    reload.assert_not_called()


@pytest.mark.asyncio
async def test_plan_config_reads_use_runtime_config_target() -> None:
    plan = SimpleNamespace(
        enabled=False,
        auto_enabled=True,
        auto_execute=False,
        complexity_threshold="medium",
    )
    workspace = SimpleNamespace(
        agent_id="governed-agent",
        config=SimpleNamespace(plan=plan),
    )
    with patch(
        "qwenpaw.app.routers.plan.get_running_config_workspace",
        AsyncMock(return_value=workspace),
    ) as resolve:
        result = await get_plan_config(_request())

    assert result.enabled is False
    resolve.assert_awaited_once()


@pytest.mark.asyncio
async def test_plan_config_write_denial_happens_before_save() -> None:
    denied = HTTPException(status_code=403, detail="forbidden")
    body = PlanConfigResponse(
        enabled=True,
        auto_enabled=True,
        auto_execute=False,
        complexity_threshold="medium",
    )
    with (
        patch(
            "qwenpaw.app.routers.plan.get_running_config_workspace",
            AsyncMock(side_effect=denied),
        ),
        patch("qwenpaw.app.routers.plan.save_agent_config") as save,
    ):
        with pytest.raises(HTTPException) as error:
            await put_plan_config(_request(), body)

    assert error.value.status_code == 403
    save.assert_not_called()


@pytest.mark.asyncio
async def test_embedding_test_uses_explicit_runtime_config_target() -> None:
    request = _request()
    workspace = SimpleNamespace(memory_manager=None)
    result = SimpleNamespace(
        success=True,
        configured_dimensions=1024,
        actual_dimensions=1024,
        latency_ms=12,
        message="ok",
    )
    with (
        patch(
            "qwenpaw.app.routers.workspace.get_governed_running_config_workspace",
            AsyncMock(return_value=workspace),
        ) as resolve,
        patch(
            "qwenpaw.app.routers.workspace.test_embedding_model",
            AsyncMock(return_value=(None, result)),
        ),
    ):
        response = await run_embedding_test(
            EmbeddingModelConfig(model_name="embedding-model"),
            request,
        )

    assert response.success is True
    resolve.assert_awaited_once_with(
        request,
        action="agent.admin.runtime_config.embedding.test",
    )


@pytest.mark.asyncio
async def test_memory_maintenance_accepts_explicit_admin_governance() -> None:
    request = SimpleNamespace(
        headers={"X-Agent-Governance": "runtime-config"},
    )
    workspace = SimpleNamespace(agent_id="governed-agent")
    with (
        patch(
            "qwenpaw.app.routers.agents.is_multi_user_enabled",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.agent_context.get_running_config_workspace",
            AsyncMock(return_value=workspace),
        ) as resolve,
    ):
        await _require_agent_role(
            request=request,
            agent_id="governed-agent",
            allowed_roles={AgentResourceRole.OWNER},
        )

    resolve.assert_awaited_once_with(
        request,
        action="agent.admin.runtime_config.memory",
    )


@pytest.mark.asyncio
async def test_memory_governance_rejects_url_target_mismatch() -> None:
    request = SimpleNamespace(
        headers={"X-Agent-Governance": "runtime-config"},
    )
    workspace = SimpleNamespace(agent_id="other-agent")
    with (
        patch(
            "qwenpaw.app.routers.agents.is_multi_user_enabled",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.agent_context.get_running_config_workspace",
            AsyncMock(return_value=workspace),
        ),
    ):
        with pytest.raises(HTTPException) as error:
            await _require_agent_role(
                request=request,
                agent_id="governed-agent",
                allowed_roles={AgentResourceRole.OWNER},
            )

    assert error.value.status_code == 403
