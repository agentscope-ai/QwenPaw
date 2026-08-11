# -*- coding: utf-8 -*-
"""Focused unit tests for workspace running-config update ordering."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers.workspace import (
    _ConfigRollbackConflict,
    _conditionally_restore_config_changes,
    put_agents_running_config,
)
from qwenpaw.config import AgentsRunningConfig
from qwenpaw.config.config import AgentProfileConfig


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
    assert response is new_running
    assert response.reme_light_memory_config.needs_reindex is True
    schedule_reload.assert_called_once()


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
