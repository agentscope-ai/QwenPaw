# -*- coding: utf-8 -*-
"""Regression tests for Agent model inheritance persistence semantics."""

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.agents import router as agents_router
from qwenpaw.app.routers.providers import router as providers_router
from qwenpaw.app.agent_startup import AgentStartupStatus
from qwenpaw.config.config import AgentProfileConfig, AgentProfileRef, ModelSlotConfig


def _app(manager, provider_manager):
    app = FastAPI()
    app.state.multi_agent_manager = manager
    app.state.provider_manager = provider_manager
    app.include_router(agents_router, prefix="/api")
    app.include_router(providers_router, prefix="/api")
    return app


def _manager():
    manager = MagicMock()
    manager.schedule_agent_startup = MagicMock()
    manager.get_agent_startup_status.return_value = AgentStartupStatus.PENDING
    return manager


class _Provider:
    id = "global"

    def has_model(self, model_id):
        return model_id == "gpt-global"

    def get_context_size(self, model_id):
        assert model_id == "gpt-global"
        return 128_000


class _ProviderManager:
    def __init__(self):
        self.active_model = ModelSlotConfig(
            provider_id="global",
            model="gpt-global",
        )

    def get_active_model(self):
        return self.active_model

    def get_provider(self, provider_id):
        return _Provider() if provider_id == "global" else None

    async def activate_model(self, provider_id, model):
        self.active_model = ModelSlotConfig(provider_id=provider_id, model=model)


def test_create_without_model_persists_inherited_null_snapshot(tmp_path):
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={},
            agent_order=[],
            language="en",
        ),
    )
    saved = {}
    provider_manager = _ProviderManager()

    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch(
            "qwenpaw.app.routers.agents.save_agent_config",
            side_effect=lambda agent_id, value: saved.setdefault(agent_id, value),
        ),
        patch("qwenpaw.app.routers.agents._initialize_agent_workspace"),
        patch("qwenpaw.app.routers.agents.WORKING_DIR", tmp_path),
        patch("qwenpaw.app.routers.agents.is_multi_user_enabled", return_value=False),
        patch(
            "qwenpaw.providers.ProviderManager.get_instance",
            return_value=provider_manager,
        ),
    ):
        response = TestClient(_app(_manager(), provider_manager)).post(
            "/api/agents",
            json={"id": "inherited", "name": "Inherited"},
        )

    assert response.status_code == 201
    assert saved["inherited"].active_model is None


def test_global_model_change_does_not_materialize_inherited_agent(tmp_path):
    provider_manager = _ProviderManager()
    agent_config = AgentProfileConfig(
        id="default",
        name="Default",
        workspace_dir=str(tmp_path),
        active_model=None,
    )
    request = MagicMock()
    request.app.state.multi_agent_manager = _manager()

    with (
        patch("qwenpaw.app.routers.providers.get_agent_for_request", new=AsyncMock(return_value=SimpleNamespace(agent_id="default"))),
        patch("qwenpaw.app.routers.providers.load_agent_config", return_value=agent_config),
        patch("qwenpaw.app.routers.providers.save_agent_config") as save,
        patch("qwenpaw.app.routers.providers.schedule_agent_reload"),
    ):
        from qwenpaw.app.routers.providers import set_active_model
        import asyncio

        result = asyncio.run(
            set_active_model(
                request=request,
                manager=provider_manager,
                body=SimpleNamespace(
                    scope="global",
                    provider_id="global",
                    model="gpt-global",
                    agent_id=None,
                ),
            ),
        )

    assert result.active_llm == ModelSlotConfig(
        provider_id="global",
        model="gpt-global",
    )
    save.assert_not_called()


def test_create_syncs_inherited_model_mode_after_file_save(tmp_path):
    config = SimpleNamespace(
        agents=SimpleNamespace(profiles={}, agent_order=[], language="en"),
    )
    repository = MagicMock()
    repository.register_owner = AsyncMock()
    repository.update_metadata = AsyncMock()
    repository.update_model_mode = AsyncMock()
    provider_manager = _ProviderManager()
    actor = SimpleNamespace(user_id=uuid4())

    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch("qwenpaw.app.routers.agents.save_agent_config"),
        patch("qwenpaw.app.routers.agents._initialize_agent_workspace"),
        patch("qwenpaw.app.routers.agents.WORKING_DIR", tmp_path),
        patch("qwenpaw.app.routers.agents.is_multi_user_enabled", return_value=True),
        patch("qwenpaw.app.routers.agents._request_actor", return_value=actor),
        patch(
            "qwenpaw.app.routers.agents._get_agent_metadata_repository",
            return_value=repository,
        ),
        patch(
            "qwenpaw.providers.ProviderManager.get_instance",
            return_value=provider_manager,
        ),
    ):
        response = TestClient(_app(_manager(), provider_manager)).post(
            "/api/agents",
            json={"id": "inherited-db", "name": "Inherited DB"},
        )

    assert response.status_code == 201
    repository.update_model_mode.assert_awaited_once_with(
        "inherited-db",
        "inherited",
    )


def test_create_with_model_preserves_explicit_mode(tmp_path):
    config = SimpleNamespace(
        agents=SimpleNamespace(profiles={}, agent_order=[], language="en"),
    )
    repository = MagicMock()
    repository.register_owner = AsyncMock()
    repository.update_metadata = AsyncMock()
    repository.update_model_mode = AsyncMock()
    provider_manager = _ProviderManager()
    saved = {}

    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch(
            "qwenpaw.app.routers.agents.save_agent_config",
            side_effect=lambda agent_id, value: saved.setdefault(agent_id, value),
        ),
        patch("qwenpaw.app.routers.agents._initialize_agent_workspace"),
        patch("qwenpaw.app.routers.agents.WORKING_DIR", tmp_path),
        patch("qwenpaw.app.routers.agents.is_multi_user_enabled", return_value=True),
        patch(
            "qwenpaw.app.routers.agents._request_actor",
            return_value=SimpleNamespace(user_id=uuid4()),
        ),
        patch(
            "qwenpaw.app.routers.agents._get_agent_metadata_repository",
            return_value=repository,
        ),
        patch(
            "qwenpaw.providers.ProviderManager.get_instance",
            return_value=provider_manager,
        ),
    ):
        response = TestClient(_app(_manager(), provider_manager)).post(
            "/api/agents",
            json={
                "id": "explicit-db",
                "name": "Explicit DB",
                "active_model": {
                    "provider_id": "global",
                    "model": "gpt-global",
                },
            },
        )

    assert response.status_code == 201
    assert saved["explicit-db"].active_model == ModelSlotConfig(
        provider_id="global",
        model="gpt-global",
    )
    repository.update_model_mode.assert_awaited_once_with(
        "explicit-db",
        "explicit",
    )


def test_create_without_any_effective_model_has_no_residue(tmp_path):
    config = SimpleNamespace(
        agents=SimpleNamespace(profiles={}, agent_order=[], language="en"),
    )
    repository = MagicMock()
    repository.register_owner = AsyncMock()
    provider_manager = _ProviderManager()
    provider_manager.active_model = None

    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch("qwenpaw.app.routers.agents.save_config") as save_root,
        patch("qwenpaw.app.routers.agents.save_agent_config") as save_agent,
        patch("qwenpaw.app.routers.agents._initialize_agent_workspace") as init,
        patch("qwenpaw.app.routers.agents.WORKING_DIR", tmp_path),
        patch("qwenpaw.app.routers.agents.is_multi_user_enabled", return_value=True),
        patch(
            "qwenpaw.app.routers.agents._request_actor",
            return_value=SimpleNamespace(user_id=uuid4()),
        ),
        patch(
            "qwenpaw.app.routers.agents._get_agent_metadata_repository",
            return_value=repository,
        ),
        patch(
            "qwenpaw.providers.ProviderManager.get_instance",
            return_value=provider_manager,
        ),
    ):
        response = TestClient(
            _app(_manager(), provider_manager),
            raise_server_exceptions=False,
        ).post(
            "/api/agents",
            json={"id": "no-model", "name": "No Model"},
        )

    assert response.status_code == 400
    assert "No active model configured" in response.json()["detail"]
    repository.register_owner.assert_not_awaited()
    init.assert_not_called()
    save_root.assert_not_called()
    save_agent.assert_not_called()
    assert not (tmp_path / "workspaces" / "no-model").exists()


def test_update_clear_model_syncs_inherited_mode(tmp_path):
    from qwenpaw.app.routers.agents import _persist_agent_update
    import asyncio

    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "agent-1": AgentProfileRef(
                    id="agent-1",
                    workspace_dir=str(tmp_path),
                ),
            },
        ),
    )
    persisted = AgentProfileConfig(
        id="agent-1",
        name="Agent",
        workspace_dir=str(tmp_path),
        active_model=ModelSlotConfig(
            provider_id="global",
            model="gpt-global",
        ),
    )
    requested = persisted.model_copy(update={"active_model": None})
    repository = MagicMock()
    repository.update_metadata = AsyncMock()
    repository.update_model_mode = AsyncMock()

    async def update_config(_agent_id, mutator):
        mutator(persisted)

    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch(
            "qwenpaw.app.routers.agents.update_agent_config_async",
            side_effect=update_config,
        ),
        patch("qwenpaw.app.routers.agents.load_agent_config", return_value=persisted),
        patch("qwenpaw.app.routers.agents.schedule_agent_reload"),
        patch("qwenpaw.app.routers.agents.is_multi_user_enabled", return_value=True),
        patch(
            "qwenpaw.app.routers.agents._get_agent_metadata_repository",
            return_value=repository,
        ),
    ):
        asyncio.run(
            _persist_agent_update(
                agentId="agent-1",
                agent_config=requested,
                request=MagicMock(),
            ),
        )

    assert persisted.active_model is None
    repository.update_model_mode.assert_awaited_once_with(
        "agent-1",
        "inherited",
    )


def test_update_rejects_unknown_explicit_model_before_persistence(tmp_path):
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "agent-1": AgentProfileRef(
                    id="agent-1",
                    workspace_dir=str(tmp_path),
                ),
            },
        ),
    )
    requested = AgentProfileConfig(
        id="agent-1",
        name="Agent",
        workspace_dir=str(tmp_path),
        active_model=ModelSlotConfig(
            provider_id="global",
            model="missing",
        ),
    )
    persist = AsyncMock()
    provider_manager = _ProviderManager()

    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch("qwenpaw.app.routers.agents.is_multi_user_enabled", return_value=False),
        patch(
            "qwenpaw.app.routers.agents._persist_agent_update",
            persist,
        ),
        patch(
            "qwenpaw.providers.ProviderManager.get_instance",
            return_value=provider_manager,
        ),
    ):
        response = TestClient(
            _app(_manager(), provider_manager),
            raise_server_exceptions=False,
        ).put(
            "/api/agents/agent-1",
            json=requested.model_dump(mode="json"),
        )

    assert response.status_code == 400
    assert "Model 'missing' not found" in response.json()["detail"]
    persist.assert_not_awaited()


def test_copy_inherited_agent_keeps_null_and_syncs_mode(tmp_path):
    source_workspace = tmp_path / "source"
    source_workspace.mkdir()
    target_root = tmp_path / "runtime"
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "source": AgentProfileRef(
                    id="source",
                    workspace_dir=str(source_workspace),
                ),
            },
            agent_order=["source"],
            language="en",
        ),
    )
    source = AgentProfileConfig(
        id="source",
        name="Source",
        workspace_dir=str(source_workspace),
        active_model=None,
    )
    repository = MagicMock()
    repository.register_owner = AsyncMock()
    repository.update_metadata = AsyncMock()
    repository.update_model_mode = AsyncMock()
    provider_manager = _ProviderManager()
    saved = {}

    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch("qwenpaw.app.routers.agents.load_agent_config", return_value=source),
        patch("qwenpaw.app.routers.agents.save_config"),
        patch(
            "qwenpaw.app.routers.agents.save_agent_config",
            side_effect=lambda agent_id, value: saved.setdefault(agent_id, value),
        ),
        patch("qwenpaw.app.routers.agents._initialize_agent_workspace"),
        patch("qwenpaw.app.routers.agents._copy_selected_workspace_files"),
        patch("qwenpaw.app.routers.agents._generate_unique_id", return_value="copy-1"),
        patch("qwenpaw.app.routers.agents.WORKING_DIR", target_root),
        patch("qwenpaw.app.routers.agents.is_multi_user_enabled", return_value=True),
        patch("qwenpaw.app.routers.agents._require_agent_role", new=AsyncMock()),
        patch(
            "qwenpaw.app.routers.agents._request_actor",
            return_value=SimpleNamespace(user_id=uuid4()),
        ),
        patch(
            "qwenpaw.app.routers.agents._get_agent_metadata_repository",
            return_value=repository,
        ),
        patch(
            "qwenpaw.providers.ProviderManager.get_instance",
            return_value=provider_manager,
        ),
    ):
        response = TestClient(_app(_manager(), provider_manager)).post(
            "/api/agents/source/copy",
            json={"name": "Inherited Copy"},
        )

    assert response.status_code == 201
    assert saved["copy-1"].active_model is None
    repository.update_model_mode.assert_awaited_once_with(
        "copy-1",
        "inherited",
    )


def test_copy_invalid_explicit_model_has_no_residue(tmp_path):
    source_workspace = tmp_path / "source-invalid"
    source_workspace.mkdir()
    target_root = tmp_path / "runtime"
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "source": AgentProfileRef(
                    id="source",
                    workspace_dir=str(source_workspace),
                ),
            },
            agent_order=["source"],
            language="en",
        ),
    )
    source = AgentProfileConfig(
        id="source",
        name="Source",
        workspace_dir=str(source_workspace),
        active_model=ModelSlotConfig(
            provider_id="global",
            model="deleted-model",
        ),
    )
    repository = MagicMock()
    repository.register_owner = AsyncMock()
    provider_manager = _ProviderManager()

    with (
        patch("qwenpaw.app.routers.agents.load_config", return_value=config),
        patch("qwenpaw.app.routers.agents.load_agent_config", return_value=source),
        patch("qwenpaw.app.routers.agents.save_config") as save_root,
        patch("qwenpaw.app.routers.agents.save_agent_config") as save_agent,
        patch("qwenpaw.app.routers.agents._initialize_agent_workspace") as init,
        patch("qwenpaw.app.routers.agents._generate_unique_id", return_value="copy-invalid"),
        patch("qwenpaw.app.routers.agents.WORKING_DIR", target_root),
        patch("qwenpaw.app.routers.agents.is_multi_user_enabled", return_value=True),
        patch("qwenpaw.app.routers.agents._require_agent_role", new=AsyncMock()),
        patch(
            "qwenpaw.app.routers.agents._request_actor",
            return_value=SimpleNamespace(user_id=uuid4()),
        ),
        patch(
            "qwenpaw.app.routers.agents._get_agent_metadata_repository",
            return_value=repository,
        ),
        patch(
            "qwenpaw.providers.ProviderManager.get_instance",
            return_value=provider_manager,
        ),
    ):
        response = TestClient(
            _app(_manager(), provider_manager),
            raise_server_exceptions=False,
        ).post("/api/agents/source/copy", json={})

    assert response.status_code == 400
    assert "Model 'deleted-model' not found" in response.json()["detail"]
    repository.register_owner.assert_not_awaited()
    init.assert_not_called()
    save_root.assert_not_called()
    save_agent.assert_not_called()
    assert not (target_root / "workspaces" / "copy-invalid").exists()
