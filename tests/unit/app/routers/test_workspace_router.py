# -*- coding: utf-8 -*-
"""Focused unit tests for workspace running-config update ordering."""

# pylint: disable=protected-access

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from qwenpaw.app.routers.workspace import (
    _ConfigRollbackConflict,
    _conditionally_restore_config_changes,
    _mask_memory_backend_secrets,
    _safe_memory_validation_error,
    put_agent_language,
    put_agents_running_config,
)
from qwenpaw.config import AgentsRunningConfig
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.memory import memory_registry


class _RemoteMemoryConfig(BaseModel):
    endpoint: str = ""
    token: str = ""


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
async def test_language_change_schedules_agent_reload(tmp_path):
    request = MagicMock()
    workspace = SimpleNamespace(agent_id="bot", workspace_dir=tmp_path)
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        language="en",
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
        patch("qwenpaw.app.routers.workspace.save_agent_config"),
        patch(
            "qwenpaw.app.routers.workspace.copy_workspace_md_files",
            return_value=["AGENTS.md"],
        ),
        patch(
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
        ) as schedule_reload,
    ):
        response = await put_agent_language(request, {"language": "zh"})

    schedule_reload.assert_called_once_with(request, "bot")
    assert response["language"] == "zh"


def test_memory_backend_secrets_are_masked_without_mutating_source():
    memory_registry.register_backend(
        plugin_id="test-secret-mask",
        backend_id="remote-memory",
        factory=MagicMock,
        label="Remote Memory",
        metadata={"secret_fields": ["token"]},
    )
    try:
        running = AgentsRunningConfig(
            memory_manager_backend="remote-memory",
            memory_backend_configs={
                "remote-memory": {
                    "endpoint": "https://memory.example",
                    "token": "top-secret",
                },
            },
        )

        masked = _mask_memory_backend_secrets(running)

        assert masked.memory_backend_configs["remote-memory"]["token"] == "***"
        assert (
            running.memory_backend_configs["remote-memory"]["token"]
            == "top-secret"
        )
    finally:
        memory_registry.unregister_owner("test-secret-mask")


def test_memory_validation_errors_do_not_echo_secrets():
    detail = _safe_memory_validation_error(
        ValueError("invalid credential top-secret"),
        {"token": "top-secret"},
        ["token"],
    )

    assert detail == "invalid credential ***"


def test_memory_validation_errors_redact_structured_secret_values():
    detail = _safe_memory_validation_error(
        ValueError(
            "invalid token input_value={'credential': 'top-secret'}",
        ),
        {"token": {"credential": "top-secret"}},
        ["token"],
    )

    assert "top-secret" not in detail
    assert "credential" not in detail


def test_unavailable_memory_backend_config_is_not_exposed():
    running = AgentsRunningConfig(
        memory_backend_configs={
            "missing-plugin": {
                "endpoint": "https://memory.example",
                "unknown_secret": "top-secret",
            },
        },
    )

    masked = _mask_memory_backend_secrets(running)

    assert "missing-plugin" not in masked.memory_backend_configs
    assert (
        running.memory_backend_configs["missing-plugin"]["unknown_secret"]
        == "top-secret"
    )


@pytest.mark.asyncio
async def test_save_preserves_unavailable_backend_config_server_side(tmp_path):
    old_running = AgentsRunningConfig(
        memory_backend_configs={
            "missing-plugin": {"unknown_secret": "top-secret"},
        },
    )
    submitted = old_running.model_copy(deep=True)
    submitted.memory_backend_configs["missing-plugin"] = {}
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=SimpleNamespace(),
        workspace_dir=tmp_path,
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
        patch("qwenpaw.app.routers.workspace.schedule_agent_reload"),
    ):
        response = await put_agents_running_config(submitted, MagicMock())

    persisted = agent_config.running.memory_backend_configs["missing-plugin"]
    assert persisted == {"unknown_secret": "top-secret"}
    assert "missing-plugin" not in response.memory_backend_configs


@pytest.mark.asyncio
async def test_save_does_not_create_config_for_core_memory_backend(tmp_path):
    submitted = AgentsRunningConfig(memory_manager_backend="remelight")
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=AgentsRunningConfig(memory_manager_backend="remelight"),
    )
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=SimpleNamespace(),
        workspace_dir=tmp_path,
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
        patch("qwenpaw.app.routers.workspace.schedule_agent_reload"),
    ):
        response = await put_agents_running_config(submitted, MagicMock())

    assert "remelight" not in agent_config.running.memory_backend_configs
    assert "remelight" not in response.memory_backend_configs


@pytest.mark.asyncio
async def test_save_preserves_masked_secret_and_returns_only_mask(tmp_path):
    memory_registry.register_backend(
        plugin_id="test-secret-save",
        backend_id="remote-memory",
        factory=MagicMock,
        label="Remote Memory",
        config_schema=_RemoteMemoryConfig,
        metadata={"secret_fields": ["token"]},
    )
    old_running = AgentsRunningConfig(
        memory_manager_backend="remote-memory",
        memory_backend_configs={
            "remote-memory": {
                "endpoint": "https://old.example",
                "token": "top-secret",
            },
        },
    )
    submitted = old_running.model_copy(deep=True)
    submitted.memory_backend_configs["remote-memory"] = {
        "endpoint": "https://new.example",
        "token": "***",
    }
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )
    workspace = SimpleNamespace(
        agent_id="bot",
        memory_manager=SimpleNamespace(),
        workspace_dir=tmp_path,
    )
    try:
        with (
            patch(
                "qwenpaw.app.routers.workspace.get_agent_for_request",
                AsyncMock(return_value=workspace),
            ),
            patch(
                "qwenpaw.app.routers.workspace.update_agent_config_async",
                _config_transaction(agent_config),
            ),
            patch("qwenpaw.app.routers.workspace.schedule_agent_reload"),
        ):
            response = await put_agents_running_config(submitted, MagicMock())

        persisted = agent_config.running.memory_backend_configs[
            "remote-memory"
        ]
        assert persisted["endpoint"] == "https://new.example"
        assert persisted["token"] == "top-secret"
        assert (
            response.memory_backend_configs["remote-memory"]["token"] == "***"
        )
    finally:
        memory_registry.unregister_owner("test-secret-save")


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
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
        ) as schedule_reload,
    ):
        response = await put_agents_running_config(new_running, MagicMock())

    assert response.memory_manager_backend == "remelight"
    assert agent_config.running == new_running
    assert transaction.await_count == 1
    schedule_reload.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("old_backend", "new_backend"),
    [
        ("none", "remelight"),
        ("adbpg", "remelight"),
        ("remelight", "none"),
    ],
)
async def test_backend_only_switch_persists_and_schedules_reload(
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
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
        ) as schedule_reload,
    ):
        response = await put_agents_running_config(new_running, MagicMock())

    assert response.memory_manager_backend == new_backend
    assert agent_config.running.memory_manager_backend == new_backend
    schedule_reload.assert_called_once()


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
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
        ) as schedule_reload,
    ):
        response = await put_agents_running_config(new_running, MagicMock())

    assert response.memory_manager_backend == "none"
    memory_manager.apply_tested_embedding.assert_not_awaited()
    memory_manager.reload_embedding_config.assert_not_awaited()
    schedule_reload.assert_called_once()


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
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
        ) as schedule_reload,
    ):
        response = await put_agents_running_config(
            new_running,
            MagicMock(),
        )

    assert events == ["save", "apply"]
    assert response == new_running
    assert response.reme_light_memory_config.needs_reindex is True
    previous = (
        response.reme_light_memory_config.pending_reindex_embedding_config
    )
    assert previous is not None
    assert previous.model_name == (
        old_running.reme_light_memory_config.embedding_model_config.model_name
    )
    schedule_reload.assert_called_once()


@pytest.mark.asyncio
async def test_save_cancel_after_persist_completes_runtime() -> None:
    # pylint: disable=protected-access
    old_running, new_running = _embedding_update_configs()
    old_embedding = old_running.reme_light_memory_config.embedding_model_config
    new_embedding = new_running.reme_light_memory_config.embedding_model_config
    live_gate = AsyncMock()

    async def apply_embedding(_config):
        await live_gate()
        return True

    memory_manager = MagicMock()
    memory_manager._active_embedding_config = old_embedding.model_copy(
        deep=True,
    )
    memory_manager._reme = SimpleNamespace(is_started=True)
    memory_manager.apply_tested_embedding = AsyncMock(
        side_effect=apply_embedding,
    )
    workspace = SimpleNamespace(agent_id="bot", memory_manager=memory_manager)
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=old_running,
    )
    caller = asyncio.current_task()
    assert caller is not None
    request = MagicMock()

    async def update_config(_agent_id, updater):
        updater(agent_config)
        caller.cancel()
        return agent_config

    with (
        patch(
            "qwenpaw.app.routers.workspace.get_agent_for_request",
            AsyncMock(return_value=workspace),
        ),
        patch(
            "qwenpaw.app.routers.workspace.update_agent_config_async",
            side_effect=update_config,
        ),
        patch(
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
        ) as schedule_reload,
        pytest.raises(asyncio.CancelledError),
    ):
        await put_agents_running_config(new_running, request)

    assert agent_config.running == new_running
    memory_config = agent_config.running.reme_light_memory_config
    assert memory_config.needs_reindex is True
    assert memory_config.pending_reindex_embedding_config == old_embedding
    # The active config still describes the indexed vector space until the
    # rebuild completes; the live gate prevents reads from that old space.
    assert memory_manager._active_embedding_config == old_embedding
    assert memory_manager._reme.is_started is True
    live_gate.assert_awaited_once_with()
    memory_manager.apply_tested_embedding.assert_awaited_once_with(
        new_embedding,
    )
    schedule_reload.assert_called_once_with(request, "bot")


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
        patch("qwenpaw.app.routers.workspace.schedule_agent_reload"),
    ):
        response = await put_agents_running_config(new_running, MagicMock())

    assert response.reme_light_memory_config.needs_reindex is False


@pytest.mark.asyncio
async def test_restoring_indexed_config_clears_reindex_requirement() -> None:
    old_running, _ = _embedding_update_configs()
    indexed = old_running.reme_light_memory_config.embedding_model_config
    pending_running = old_running.model_copy(deep=True)
    pending_memory = pending_running.reme_light_memory_config
    pending_memory.embedding_model_config.model_name = "pending-model"
    pending_memory.needs_reindex = True
    pending_memory.pending_reindex_embedding_config = indexed.model_copy(
        deep=True,
    )
    restored_running = pending_running.model_copy(deep=True)
    restored_running.reme_light_memory_config.embedding_model_config = (
        indexed.model_copy(deep=True)
    )
    memory_manager = MagicMock()
    memory_manager.apply_tested_embedding = AsyncMock(return_value=True)
    memory_manager.reload_embedding_config = AsyncMock(return_value=True)
    workspace = SimpleNamespace(agent_id="bot", memory_manager=memory_manager)
    agent_config = AgentProfileConfig(
        id="bot",
        name="Bot",
        running=pending_running,
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
        patch("qwenpaw.app.routers.workspace.schedule_agent_reload"),
    ):
        response = await put_agents_running_config(
            restored_running,
            MagicMock(),
        )

    memory_config = response.reme_light_memory_config
    assert memory_config.needs_reindex is False
    assert memory_config.pending_reindex_embedding_config is None
    memory_manager.apply_tested_embedding.assert_not_awaited()
    memory_manager.reload_embedding_config.assert_awaited_once_with()


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
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
        ) as schedule_reload,
    ):
        with pytest.raises(OSError, match="disk full"):
            await put_agents_running_config(new_running, MagicMock())

    memory_manager.apply_tested_embedding.assert_not_awaited()
    schedule_reload.assert_not_called()


@pytest.mark.asyncio
async def test_hot_update_exception_rolls_back_before_reload() -> None:
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

    def schedule_reload(_request, _agent_id):
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
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
            side_effect=schedule_reload,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await put_agents_running_config(
            new_running,
            MagicMock(),
        )

    assert exc_info.value.status_code == 503
    assert events == ["save", "apply", "save", "reme-reload"]
    assert agent_config.running == old_running


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
            "qwenpaw.app.routers.workspace.schedule_agent_reload",
        ) as schedule_reload,
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
    schedule_reload.assert_not_called()


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
        patch("qwenpaw.app.routers.workspace.schedule_agent_reload"),
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
        patch("qwenpaw.app.routers.workspace.schedule_agent_reload"),
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
