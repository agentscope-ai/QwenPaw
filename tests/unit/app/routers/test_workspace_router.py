# -*- coding: utf-8 -*-
"""Focused unit tests for workspace running-config update ordering."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from qwenpaw.app.routers.workspace import (
    _ConfigRollbackConflict,
    _conditionally_restore_config_changes,
    get_agents_running_config,
    get_running_config_access,
    get_running_config_summary,
    get_agents_running_config_version,
    get_agent_language,
    get_running_config_runtime_status,
    put_agent_language,
    put_agents_running_config,
    retry_running_config_reload,
    _require_workspace_write_access,
    MdFileContent,
    write_working_file,
)
from qwenpaw.config import AgentsRunningConfig
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.access.agent_repository import AgentResourceRole, AgentVisibility


def test_invalid_loop_config_is_rejected_before_persistence_or_reload() -> None:
    from qwenpaw.app.routers import workspace as workspace_router

    app = FastAPI()
    app.include_router(workspace_router.router)
    body = AgentsRunningConfig().model_dump(mode="json")
    body["loop"]["custom_modes"] = [
        {
            "id": "invalid-mode",
            "name": "Invalid mode",
            "description": "Must not be persisted",
            "slash_command": "invalid-mode",
            "enabled": True,
            "gates": [
                {
                    "id": "negative-budget",
                    "type": "token_budget",
                    "enabled": True,
                    "params": {"max_total_tokens": -1},
                },
            ],
        },
    ]

    with (
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
        ) as update_config,
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
        ) as reload_agent,
    ):
        response = TestClient(app).put("/workspace/running-config", json=body)

    assert response.status_code == 422
    update_config.assert_not_called()
    reload_agent.assert_not_called()


@pytest.mark.asyncio
async def test_running_config_get_exposes_current_version_header() -> None:
    workspace = SimpleNamespace(agent_id="bot")
    request = MagicMock()
    response = MagicMock()
    response.headers = {}
    revision = SimpleNamespace(version=7)

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.load_agent_config",
            return_value=AgentProfileConfig(id="bot", name="Bot"),
        ),
        patch(
            "qwenpaw.app.routers.workspace.is_multi_user_enabled",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.routers.workspace.PostgresAgentConfigRepository"
        ) as repository_type,
    ):
        repository_type.return_value.get_current = AsyncMock(
            return_value=revision
        )
        await get_agents_running_config(request, response)

    assert response.headers["ETag"] == '"7"'
    assert response.headers["X-Config-Version"] == "7"


@pytest.mark.asyncio
async def test_user_cannot_read_complete_running_config() -> None:
    workspace = SimpleNamespace(agent_id="bot")
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(role=AgentResourceRole.USER),
        ),
    )

    with patch(
        "qwenpaw.app.routers.workspace.get_agent_for_request",
        AsyncMock(return_value=workspace),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_agents_running_config(request)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_user_can_read_safe_running_config_summary() -> None:
    workspace = SimpleNamespace(agent_id="bot")
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=AgentResourceRole.USER,
                visibility=AgentVisibility.PUBLIC,
                owner_user_id="owner-1",
            ),
        ),
    )
    agent_config = AgentProfileConfig(
        id="bot",
        name="Public bot",
        language="zh",
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.load_agent_config",
            return_value=agent_config,
        ),
        patch(
            "qwenpaw.app.routers.workspace.load_config",
            return_value=SimpleNamespace(user_timezone="Asia/Shanghai"),
        ),
    ):
        summary = await get_running_config_summary(request)

    assert summary.agent_id == "bot"
    assert summary.name == "Public bot"
    assert summary.access_role == AgentResourceRole.USER
    assert summary.can_edit is False
    assert summary.model_switchable is True
    assert summary.timezone == "Asia/Shanghai"
    assert "workspace_dir" not in summary.model_dump()
    assert "api_key" not in str(summary.model_dump())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "can_edit"),
    [
        (AgentResourceRole.OWNER, True),
        (AgentResourceRole.COLLABORATOR, True),
        (AgentResourceRole.USER, False),
    ],
)
async def test_running_config_access_reflects_resource_role(
    role: AgentResourceRole,
    can_edit: bool,
) -> None:
    workspace = SimpleNamespace(agent_id="bot")
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=role,
                visibility=AgentVisibility.PRIVATE,
                owner_user_id="owner-1",
                historical_read_only=False,
            ),
        ),
    )

    with patch(
        "qwenpaw.app.routers.workspace.get_agent_for_request",
        AsyncMock(return_value=workspace),
    ):
        access = await get_running_config_access(request)

    assert access.access_role == role
    assert access.can_edit is can_edit
    assert access.can_edit_project_files is True
    assert access.can_edit_workspace_files is can_edit
    assert access.is_governance is False


@pytest.mark.asyncio
async def test_explicit_admin_governance_is_reported_without_forging_owner() -> None:
    workspace = SimpleNamespace(agent_id="managed-bot")
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_governance=SimpleNamespace(
                agent_key="managed-bot",
                owner_user_id="owner-2",
                visibility=AgentVisibility.PRIVATE,
            ),
        ),
    )

    with patch(
        "qwenpaw.app.routers.workspace.get_running_config_workspace",
        AsyncMock(return_value=workspace),
    ):
        access = await get_running_config_access(request)

    assert access.agent_id == "managed-bot"
    assert access.access_role == "admin_governance"
    assert access.can_edit is True
    assert access.is_governance is True
    assert access.owner_user_id == "owner-2"


@pytest.mark.asyncio
async def test_historical_access_cannot_edit_running_config() -> None:
    workspace = SimpleNamespace(agent_id="bot")
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=AgentResourceRole.OWNER,
                visibility=AgentVisibility.PRIVATE,
                owner_user_id="owner-1",
                historical_read_only=True,
            ),
        ),
    )

    with patch(
        "qwenpaw.app.routers.workspace.get_agent_for_request",
        AsyncMock(return_value=workspace),
    ):
        access = await get_running_config_access(request)

    assert access.can_view is True
    assert access.can_edit is False


def test_use_only_member_cannot_write_agent_workspace() -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=AgentResourceRole.USER,
                historical_read_only=False,
            ),
        ),
    )

    with pytest.raises(HTTPException) as exc:
        _require_workspace_write_access(
            request,
            SimpleNamespace(agent_id="shared-agent"),
        )

    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "role",
    [AgentResourceRole.OWNER, AgentResourceRole.COLLABORATOR],
)
def test_agent_editors_can_write_agent_workspace(role) -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=role,
                historical_read_only=False,
            ),
        ),
    )

    _require_workspace_write_access(
        request,
        SimpleNamespace(agent_id="editable-agent"),
    )


@pytest.mark.asyncio
async def test_profile_write_preserves_forbidden_status() -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(
                role=AgentResourceRole.USER,
                historical_read_only=False,
            ),
        ),
    )
    workspace = SimpleNamespace(agent_id="shared-agent")
    with patch(
        "qwenpaw.app.routers.workspace.get_agent_for_request",
        AsyncMock(return_value=workspace),
    ):
        with pytest.raises(HTTPException) as exc:
            await write_working_file(
                "MEMORY.md",
                MdFileContent(content="blocked"),
                request,
            )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_user_reads_agent_language_from_safe_summary_only() -> None:
    workspace = SimpleNamespace(agent_id="bot")
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(role=AgentResourceRole.USER),
        ),
    )

    with patch(
        "qwenpaw.app.routers.workspace.get_agent_for_request",
        AsyncMock(return_value=workspace),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_agent_language(request)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_user_cannot_update_agent_language() -> None:
    workspace = SimpleNamespace(agent_id="bot")
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(role=AgentResourceRole.USER),
        ),
    )

    with patch(
        "qwenpaw.app.routers.workspace.get_agent_for_request",
        AsyncMock(return_value=workspace),
    ):
        with pytest.raises(HTTPException) as exc:
            await put_agent_language(request, {"language": "zh"})

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_invalid_agent_language_is_rejected_before_any_side_effect() -> None:
    request = SimpleNamespace(state=SimpleNamespace())
    with (
        patch(
            "qwenpaw.app.routers.workspace.get_running_config_workspace",
            AsyncMock(side_effect=AssertionError("workspace resolved")),
        ) as resolve,
        patch("qwenpaw.app.routers.workspace.load_agent_config") as load,
        patch("qwenpaw.app.routers.workspace.save_agent_config") as save,
        patch("qwenpaw.app.routers.workspace.copy_workspace_md_files") as copy,
    ):
        with pytest.raises(HTTPException) as exc:
            await put_agent_language(request, {"language": "invalid-language"})

    assert exc.value.status_code == 400
    resolve.assert_not_awaited()
    load.assert_not_called()
    save.assert_not_called()
    copy.assert_not_called()


def test_invalid_shell_timeout_is_rejected_before_router_side_effects() -> None:
    with pytest.raises(ValidationError):
        AgentsRunningConfig(shell_command_timeout=0.5)


def test_invalid_tool_execution_level_is_rejected_before_router_side_effects() -> None:
    with (
        patch("qwenpaw.app.routers.workspace.update_agent_config_async") as persist,
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
            new_callable=AsyncMock,
        ) as reload,
    ):
        with pytest.raises(ValidationError):
            AgentsRunningConfig(approval_level="ROOT")

    persist.assert_not_called()
    reload.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_running_config_put_is_forbidden_before_side_effects() -> None:
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(
            agent_access=SimpleNamespace(role=AgentResourceRole.USER),
        ),
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(side_effect=AssertionError("workspace lookup too early")),
        ) as get_workspace,
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
        ) as persist,
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
            new_callable=AsyncMock,
        ) as reload,
    ):
        with pytest.raises(HTTPException) as exc:
            await put_agents_running_config(
                AgentsRunningConfig(),
                request,
                MagicMock(),
            )

    assert exc.value.status_code == 403
    get_workspace.assert_not_awaited()
    persist.assert_not_called()
    reload.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_running_config_reload_is_forbidden_before_reload() -> None:
    request = SimpleNamespace(
        state=SimpleNamespace(
            agent_access=SimpleNamespace(role=AgentResourceRole.USER),
        ),
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=SimpleNamespace(agent_id="bot")),
        ),
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
            new_callable=AsyncMock,
        ) as reload,
    ):
        with pytest.raises(HTTPException) as exc:
            await retry_running_config_reload(request)

    assert exc.value.status_code == 403
    reload.assert_not_awaited()


@pytest.mark.asyncio
async def test_running_config_version_endpoint_returns_repository_version() -> None:
    workspace = SimpleNamespace(agent_id="bot")
    revision = SimpleNamespace(version=9)
    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.is_multi_user_enabled",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.routers.workspace.PostgresAgentConfigRepository"
        ) as repository_type,
    ):
        repository_type.return_value.get_current = AsyncMock(
            return_value=revision
        )
        result = await get_agents_running_config_version(MagicMock())

    assert result == {"version": 9}


@pytest.mark.asyncio
async def test_running_config_put_requires_if_match_in_multi_user_mode() -> None:
    request = MagicMock()
    request.headers = {}

    with patch(
        "qwenpaw.app.routers.workspace.is_multi_user_enabled",
        return_value=True,
    ):
        with pytest.raises(HTTPException) as exc:
            await put_agents_running_config(
                AgentsRunningConfig(),
                request,
                MagicMock(),
            )

    assert exc.value.status_code == 428


@pytest.mark.asyncio
async def test_running_config_reload_failure_keeps_saved_config_pending() -> None:
    """热重载异常不能把已持久化配置误报为保存失败。"""
    old_running = AgentsRunningConfig(shell_command_timeout=60)
    new_running = old_running.model_copy(deep=True)
    new_running.shell_command_timeout = 61
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )
    manager = SimpleNamespace(
        agents={"bot": object()},
        reload_agent=AsyncMock(side_effect=RuntimeError("reload failed")),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=manager),
        ),
    )
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=None,
        workspace_dir=".",
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            _config_transaction(agent_config),
        ),
    ):
        response = await put_agents_running_config(new_running, request)

    assert response.shell_command_timeout == 61
    assert agent_config.running.shell_command_timeout == 61
    assert request.app.state.running_config_reload_statuses["bot"] == {
        "state": "pending_reload",
    }


@pytest.mark.asyncio
async def test_running_config_reload_retry_clears_pending_status() -> None:
    manager = SimpleNamespace(reload_agent=AsyncMock(return_value=True))
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                multi_agent_manager=manager,
                running_config_reload_statuses={
                    "bot": {"state": "pending_reload"}
                },
            ),
        ),
    )
    workspace = SimpleNamespace(agent_id="bot")

    with patch(
        "qwenpaw.app.routers.workspace.get_agent_for_request",
        AsyncMock(return_value=workspace),
    ):
        before = await get_running_config_runtime_status(request)
        after = await retry_running_config_reload(request)

    assert before.state == "pending_reload"
    assert after.state == "applied"
    manager.reload_agent.assert_awaited_once_with("bot")
    assert request.app.state.running_config_reload_statuses["bot"] == {
        "state": "applied",
    }


def _embedding_update_configs():
    old_running = AgentsRunningConfig()
    new_running = old_running.model_copy(deep=True)
    old_embedding = old_running.reme_light_memory_config.embedding_model_config
    new_embedding = new_running.reme_light_memory_config.embedding_model_config
    old_embedding.api_key = "old-key"
    old_embedding.model_name = "old-model"
    new_embedding.api_key = "new-key"
    new_embedding.model_name = "new-model"
    return old_running, new_running


def _config_transaction(
    agent_config: AgentProfileConfig,
    *,
    events: list[str] | None = None,
    error: Exception | None = None,
) -> AsyncMock:
    async def update(_agent_id, updater):
        updater(agent_config)
        if error is not None:
            raise error
        if events is not None:
            events.append("save")
        return agent_config

    return AsyncMock(side_effect=update)


@pytest.mark.asyncio
@pytest.mark.parametrize("old_backend", ["none", "adbpg"])
async def test_backend_switch_to_remelight_skips_old_manager_embedding_update(
    old_backend: str,
) -> None:
    old_running, new_running = _embedding_update_configs()
    old_running.memory_manager_backend = old_backend
    new_running.memory_manager_backend = "remelight"
    old_manager = SimpleNamespace()
    workspace = SimpleNamespace(agent_id="bot", memory_manager=old_manager)
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )
    transaction = _config_transaction(agent_config)

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            transaction,
        ),
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
        ) as reload_agent,
    ):
        response = await put_agents_running_config(new_running, MagicMock())

    assert response.memory_manager_backend == "remelight"
    assert agent_config.running == new_running
    assert transaction.await_count == 1
    reload_agent.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("old_backend", "new_backend"),
    [
        ("none", "remelight"),
        ("adbpg", "remelight"),
        ("remelight", "none"),
    ],
)
async def test_backend_only_switch_persists_and_reloads_agent(
    old_backend: str,
    new_backend: str,
) -> None:
    old_running = AgentsRunningConfig(memory_manager_backend=old_backend)
    new_running = old_running.model_copy(deep=True)
    new_running.memory_manager_backend = new_backend
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=SimpleNamespace(),
    )
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            _config_transaction(agent_config),
        ),
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
        ) as reload_agent,
    ):
        response = await put_agents_running_config(new_running, MagicMock())

    assert response.memory_manager_backend == new_backend
    assert agent_config.running.memory_manager_backend == new_backend
    reload_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_remelight_switch_skips_embedding_hot_update() -> None:
    old_running, new_running = _embedding_update_configs()
    new_running.memory_manager_backend = "none"
    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(return_value=True)
    memory_manager.reload_embedding_config = AsyncMock(return_value=True)
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=memory_manager,
    )
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            _config_transaction(agent_config),
        ),
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
        ) as reload_agent,
    ):
        response = await put_agents_running_config(new_running, MagicMock())

    assert response.memory_manager_backend == "none"
    memory_manager.apply_tested_embedding.assert_not_awaited()
    memory_manager.reload_embedding_config.assert_not_awaited()
    reload_agent.assert_awaited_once()


def test_embedding_rollback_preserves_unrelated_concurrent_changes() -> None:
    old_running, new_running = _embedding_update_configs()
    before = AgentProfileConfig(id="bot", name="Bot", running=old_running)
    submitted = before.model_copy(deep=True)
    submitted.running = new_running
    current = submitted.model_copy(deep=True)
    current.language = "zh"

    _conditionally_restore_config_changes(current, before, submitted)

    assert current.language == "zh"
    assert current.running.reme_light_memory_config.embedding_model_config == (
        old_running.reme_light_memory_config.embedding_model_config
    )


def test_embedding_rollback_detects_a_concurrent_same_field_change() -> None:
    old_running, new_running = _embedding_update_configs()
    before = AgentProfileConfig(id="bot", name="Bot", running=old_running)
    submitted = before.model_copy(deep=True)
    submitted.running = new_running
    current = submitted.model_copy(deep=True)
    embedding_config = (
        current.running.reme_light_memory_config.embedding_model_config
    )
    embedding_config.model_name = "third-model"

    with pytest.raises(_ConfigRollbackConflict) as exc_info:
        _conditionally_restore_config_changes(current, before, submitted)

    assert any("model_name" in path for path in exc_info.value.paths)


@pytest.mark.asyncio
async def test_running_config_persists_before_embedding_hot_update() -> None:
    old_running, new_running = _embedding_update_configs()
    new_running.max_iters += 1
    events: list[str] = []

    async def apply_embedding(_config):
        events.append("apply")
        return True

    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(
        side_effect=apply_embedding,
    )
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=memory_manager,
    )
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            _config_transaction(agent_config, events=events),
        ),
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
        ) as reload_agent,
    ):
        response = await put_agents_running_config(
            new_running,
            MagicMock(),
        )

    assert events == ["save", "apply"]
    assert response is new_running
    assert response.reme_light_memory_config.needs_reindex is True
    reload_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_key_change_does_not_require_reindex() -> None:
    old_running = AgentsRunningConfig()
    new_running = old_running.model_copy(deep=True)
    old_running.reme_light_memory_config.embedding_model_config.api_key = "old"
    new_running.reme_light_memory_config.embedding_model_config.api_key = "new"
    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(return_value=True)
    workspace = SimpleNamespace(agent_id="bot", memory_manager=memory_manager)
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            _config_transaction(agent_config),
        ),
        patch("qwenpaw.app.routers.workspace.reload_agent_and_track"),
    ):
        response = await put_agents_running_config(new_running, MagicMock())

    assert response.reme_light_memory_config.needs_reindex is False


@pytest.mark.asyncio
async def test_running_config_save_failure_does_not_touch_runtime() -> None:
    old_running, new_running = _embedding_update_configs()
    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(return_value=True)
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=memory_manager,
    )
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            _config_transaction(
                agent_config,
                error=OSError("disk full"),
            ),
        ),
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
        ) as reload_agent,
    ):
        with pytest.raises(OSError, match="disk full"):
            await put_agents_running_config(new_running, MagicMock())

    memory_manager.apply_tested_embedding.assert_not_awaited()
    reload_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_embedding_hot_update_failure_restarts_reme() -> None:
    old_running, new_running = _embedding_update_configs()
    events: list[str] = []

    async def apply_embedding(_config):
        events.append("apply")
        raise RuntimeError("index rebuild failed")

    async def reload_embedding() -> bool:
        events.append("reme-reload")
        return True

    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(
        side_effect=apply_embedding,
    )
    memory_manager.reload_embedding_config = AsyncMock(
        side_effect=reload_embedding,
    )
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=memory_manager,
    )
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    def reload_agent(_request, _agent_id):
        events.append("reload")

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            _config_transaction(agent_config, events=events),
        ),
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
            side_effect=reload_agent,
        ),
    ):
        response = await put_agents_running_config(
            new_running,
            MagicMock(),
        )

    assert events == ["save", "apply", "reme-reload", "reload"]
    assert response is new_running


@pytest.mark.asyncio
async def test_embedding_update_is_rejected_while_reindexing() -> None:
    old_running, new_running = _embedding_update_configs()
    memory_manager = MagicMock()
    memory_manager.is_reindexing = True
    memory_manager.apply_tested_embedding = AsyncMock()
    workspace = SimpleNamespace(agent_id="bot", memory_manager=memory_manager)
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )
    transaction = _config_transaction(agent_config)

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            transaction,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await put_agents_running_config(new_running, MagicMock())

    assert exc_info.value.status_code == 409
    memory_manager.apply_tested_embedding.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_runtime_update_rolls_back_and_returns_503() -> None:
    old_running, new_running = _embedding_update_configs()
    events: list[str] = []

    async def apply_embedding(_config):
        events.append("apply")
        return False

    reload_results = iter([False, True])

    async def reload_embedding() -> bool:
        events.append("reme-reload")
        return next(reload_results)

    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(
        side_effect=apply_embedding,
    )
    memory_manager.reload_embedding_config = AsyncMock(
        side_effect=reload_embedding,
    )
    workspace = SimpleNamespace(agent_id="bot", memory_manager=memory_manager)
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            _config_transaction(agent_config, events=events),
        ),
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
        ) as reload_agent,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await put_agents_running_config(new_running, MagicMock())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["runtime_restored"] is True
    assert events == [
        "save",
        "apply",
        "reme-reload",
        "save",
        "reme-reload",
    ]
    reload_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_runtime_update_preserves_concurrent_change() -> None:
    old_running, new_running = _embedding_update_configs()
    persisted = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )
    update_count = 0

    async def update_config(_agent_id, updater):
        nonlocal persisted, update_count
        current = persisted.model_copy(deep=True)
        updater(current)
        persisted = current.model_copy(deep=True)
        update_count += 1
        if update_count == 1:
            persisted.language = "zh"
        return current

    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(return_value=False)
    memory_manager.reload_embedding_config = AsyncMock(
        side_effect=[False, True],
    )
    workspace = SimpleNamespace(agent_id="bot", memory_manager=memory_manager)

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            side_effect=update_config,
        ),
        patch("qwenpaw.app.routers.workspace.reload_agent_and_track"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await put_agents_running_config(new_running, MagicMock())

    assert exc_info.value.status_code == 503
    assert persisted.language == "zh"
    assert persisted.running == old_running


@pytest.mark.asyncio
async def test_failed_runtime_update_reports_rollback_conflict() -> None:
    old_running, new_running = _embedding_update_configs()
    persisted = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )
    update_count = 0

    async def update_config(_agent_id, updater):
        nonlocal persisted, update_count
        current = persisted.model_copy(deep=True)
        updater(current)
        persisted = current.model_copy(deep=True)
        update_count += 1
        if update_count == 1:
            memory_config = persisted.running.reme_light_memory_config
            embedding_config = memory_config.embedding_model_config
            embedding_config.model_name = "third-model"
        return current

    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(return_value=False)
    memory_manager.reload_embedding_config = AsyncMock(
        side_effect=[False, True],
    )
    workspace = SimpleNamespace(agent_id="bot", memory_manager=memory_manager)

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            side_effect=update_config,
        ),
        patch("qwenpaw.app.routers.workspace.reload_agent_and_track"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await put_agents_running_config(new_running, MagicMock())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["persisted"] is True
    assert any(
        "model_name" in path for path in exc_info.value.detail["conflicts"]
    )
    embedding_config = (
        persisted.running.reme_light_memory_config.embedding_model_config
    )
    assert embedding_config.model_name == "third-model"


@pytest.mark.asyncio
async def test_failed_runtime_restore_never_continues_to_agent_reload() -> None:
    old_running, new_running = _embedding_update_configs()
    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(return_value=False)
    memory_manager.reload_embedding_config = AsyncMock(return_value=False)
    workspace = SimpleNamespace(agent_id="bot", memory_manager=memory_manager)
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            _config_transaction(agent_config),
        ),
        patch(
            "qwenpaw.app.routers.workspace.reload_agent_and_track",
        ) as reload_agent,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await put_agents_running_config(new_running, MagicMock())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["runtime_restored"] is False
    reload_agent.assert_not_awaited()
