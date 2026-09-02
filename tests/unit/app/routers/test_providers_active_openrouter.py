# -*- coding: utf-8 -*-
"""Route tests for provider active-model endpoints and OpenRouter routes.

Covers ``_validate_model_slot``, ``_load_agent_model``,
``_should_auto_discover``, ``list_all_providers``, the three OpenRouter
endpoints (series / discover-extended / models filter), and the
GET/PUT ``/active`` model endpoints with their scope handling.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import providers as providers_mod
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers.openrouter_provider import OpenRouterProvider
from qwenpaw.providers.provider import (
    ExtendedModelInfo,
    ProviderInfo,
)


def _make_manager() -> MagicMock:
    return MagicMock(name="ProviderManager")


def _openrouter_provider() -> OpenRouterProvider:
    return OpenRouterProvider(
        id="openrouter",
        name="OpenRouter",
        api_key="sk-test",
    )


def _extended_model(model_id: str = "openai/gpt-x") -> ExtendedModelInfo:
    return ExtendedModelInfo(
        id=model_id,
        name="GPT X",
        provider="openai",
        supports_multimodal=True,
        supports_image=True,
        supports_video=False,
        probe_source="documentation",
        is_free=False,
        input_modalities=["text", "image"],
        output_modalities=["text"],
        pricing={"prompt": "0.000001", "completion": "0.000002"},
    )


# ---------------------------------------------------------------------------
# _validate_model_slot
# ---------------------------------------------------------------------------


class TestValidateModelSlot:
    def test_provider_missing_raises_404(self) -> None:
        manager = _make_manager()
        manager.get_provider.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            providers_mod._validate_model_slot(manager, "nope", "m")
        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail

    def test_model_missing_raises_400(self) -> None:
        manager = _make_manager()
        provider = MagicMock()
        provider.has_model.return_value = False
        manager.get_provider.return_value = provider
        with pytest.raises(HTTPException) as exc_info:
            providers_mod._validate_model_slot(manager, "p", "m")
        assert exc_info.value.status_code == 400
        assert "not found in provider" in exc_info.value.detail

    def test_unavailable_model_raises_400(self) -> None:
        manager = _make_manager()
        provider = MagicMock()
        provider.has_model.return_value = True
        provider.get_model_info.return_value = SimpleNamespace(
            availability_status="permission_denied",
            availability_message="no access",
        )
        manager.get_provider.return_value = provider
        with pytest.raises(HTTPException) as exc_info:
            providers_mod._validate_model_slot(manager, "p", "m")
        assert exc_info.value.status_code == 400
        assert "cannot be activated" in exc_info.value.detail

    def test_unavailable_model_falls_back_to_status_text(self) -> None:
        manager = _make_manager()
        provider = MagicMock()
        provider.has_model.return_value = True
        provider.get_model_info.return_value = SimpleNamespace(
            availability_status="model_not_found",
            availability_message=None,
        )
        manager.get_provider.return_value = provider
        with pytest.raises(HTTPException) as exc_info:
            providers_mod._validate_model_slot(manager, "p", "m")
        assert "model_not_found" in exc_info.value.detail

    def test_valid_slot_passes(self) -> None:
        manager = _make_manager()
        provider = MagicMock()
        provider.has_model.return_value = True
        provider.get_model_info.return_value = SimpleNamespace(
            availability_status="available",
            availability_message=None,
        )
        manager.get_provider.return_value = provider
        providers_mod._validate_model_slot(manager, "p", "m")

    def test_missing_model_info_passes(self) -> None:
        manager = _make_manager()
        provider = MagicMock()
        provider.has_model.return_value = True
        provider.get_model_info.return_value = None
        manager.get_provider.return_value = provider
        providers_mod._validate_model_slot(manager, "p", "m")


# ---------------------------------------------------------------------------
# _should_auto_discover
# ---------------------------------------------------------------------------


class TestShouldAutoDiscover:
    def test_disabled_flag_returns_false(self) -> None:
        body = SimpleNamespace(auto_discover=False)
        assert providers_mod._should_auto_discover(body, object()) is False

    def test_no_provider_returns_false(self) -> None:
        body = SimpleNamespace(auto_discover=True)
        assert providers_mod._should_auto_discover(body, None) is False

    def test_provider_without_discovery_support_returns_false(self) -> None:
        body = SimpleNamespace(auto_discover=True)
        provider = SimpleNamespace(support_model_discovery=False)
        assert providers_mod._should_auto_discover(body, provider) is False

    def test_requires_key_but_missing_returns_false(self) -> None:
        body = SimpleNamespace(auto_discover=True)
        provider = SimpleNamespace(
            support_model_discovery=True,
            api_key=None,
            require_api_key=True,
        )
        assert providers_mod._should_auto_discover(body, provider) is False

    def test_key_present_returns_true(self) -> None:
        body = SimpleNamespace(auto_discover=True)
        provider = SimpleNamespace(
            support_model_discovery=True,
            api_key="sk-x",
            require_api_key=True,
        )
        assert providers_mod._should_auto_discover(body, provider) is True

    def test_keyless_provider_not_requiring_key_returns_true(self) -> None:
        body = SimpleNamespace(auto_discover=True)
        provider = SimpleNamespace(
            support_model_discovery=True,
            api_key=None,
            require_api_key=False,
        )
        assert providers_mod._should_auto_discover(body, provider) is True


# ---------------------------------------------------------------------------
# list_all_providers / _load_agent_model
# ---------------------------------------------------------------------------


async def test_list_all_providers_returns_manager_listing() -> None:
    manager = _make_manager()
    info = [ProviderInfo(id="openai", name="OpenAI")]
    manager.list_provider_info = AsyncMock(return_value=info)
    result = await providers_mod.list_all_providers(manager=manager)
    assert result == info


async def test_load_agent_model_returns_configured_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = SimpleNamespace(agent_id="agent-1")
    monkeypatch.setattr(
        providers_mod,
        "get_agent_for_request",
        AsyncMock(return_value=workspace),
    )
    slot = ModelSlotConfig(provider_id="p", model="m")
    monkeypatch.setattr(
        providers_mod,
        "load_agent_config",
        MagicMock(return_value=SimpleNamespace(active_model=slot)),
    )
    request = MagicMock()
    result = await providers_mod._load_agent_model(request, "agent-1")
    assert result == slot


# ---------------------------------------------------------------------------
# GET /openrouter/series
# ---------------------------------------------------------------------------


class TestGetOpenrouterSeries:
    async def test_missing_provider_returns_404(self) -> None:
        manager = _make_manager()
        manager.get_provider.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.get_openrouter_series(manager=manager)
        assert exc_info.value.status_code == 404

    async def test_wrong_provider_type_returns_400(self) -> None:
        manager = _make_manager()
        manager.get_provider.return_value = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.get_openrouter_series(manager=manager)
        assert exc_info.value.status_code == 400

    async def test_fetch_error_returns_500(self) -> None:
        manager = _make_manager()
        provider = _openrouter_provider()
        object.__setattr__(
            provider,
            "get_available_providers",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        manager.get_provider.return_value = provider
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.get_openrouter_series(manager=manager)
        assert exc_info.value.status_code == 500
        assert "boom" in exc_info.value.detail

    async def test_success_returns_series(self) -> None:
        manager = _make_manager()
        provider = _openrouter_provider()
        object.__setattr__(
            provider,
            "get_available_providers",
            AsyncMock(return_value=["google", "openai"]),
        )
        manager.get_provider.return_value = provider
        result = await providers_mod.get_openrouter_series(manager=manager)
        assert result.series == ["google", "openai"]


# ---------------------------------------------------------------------------
# POST /openrouter/discover-extended
# ---------------------------------------------------------------------------


class TestDiscoverOpenrouterExtended:
    async def test_missing_provider_returns_404(self) -> None:
        manager = _make_manager()
        manager.get_provider.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.discover_openrouter_extended(
                manager=manager,
                body=None,
            )
        assert exc_info.value.status_code == 404

    async def test_wrong_provider_type_returns_400(self) -> None:
        manager = _make_manager()
        manager.get_provider.return_value = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.discover_openrouter_extended(
                manager=manager,
                body=None,
            )
        assert exc_info.value.status_code == 400

    async def test_success_builds_model_dicts(self) -> None:
        manager = _make_manager()
        provider = _openrouter_provider()
        object.__setattr__(
            provider,
            "fetch_extended_models",
            AsyncMock(return_value=[_extended_model()]),
        )
        object.__setattr__(
            provider,
            "get_available_providers",
            AsyncMock(return_value=["openai"]),
        )
        manager.get_provider.return_value = provider

        result = await providers_mod.discover_openrouter_extended(
            manager=manager,
            body=None,
        )

        assert result.success is True
        assert result.total_count == 1
        assert result.providers == ["openai"]
        entry = result.models[0]
        assert entry["id"] == "openai/gpt-x"
        assert entry["supports_image"] is True
        assert entry["pricing"]["prompt"] == "0.000001"
        assert not manager.update_provider_async.called

    async def test_api_key_in_body_updates_provider(self) -> None:
        manager = _make_manager()
        manager.update_provider_async = AsyncMock()
        provider = _openrouter_provider()
        object.__setattr__(
            provider,
            "fetch_extended_models",
            AsyncMock(return_value=[]),
        )
        object.__setattr__(
            provider,
            "get_available_providers",
            AsyncMock(return_value=[]),
        )
        manager.get_provider.return_value = provider
        body = providers_mod.DiscoverModelsRequest(api_key="sk-new")

        result = await providers_mod.discover_openrouter_extended(
            manager=manager,
            body=body,
        )

        assert result.success is True
        manager.update_provider_async.assert_awaited_once_with(
            "openrouter",
            {"api_key": "sk-new"},
        )

    async def test_fetch_error_returns_failure_response(self) -> None:
        manager = _make_manager()
        provider = _openrouter_provider()
        object.__setattr__(
            provider,
            "fetch_extended_models",
            AsyncMock(side_effect=RuntimeError("down")),
        )
        manager.get_provider.return_value = provider

        result = await providers_mod.discover_openrouter_extended(
            manager=manager,
            body=None,
        )

        assert result.success is False
        assert result.models == []
        assert result.providers == []
        assert result.total_count == 0


# ---------------------------------------------------------------------------
# POST /openrouter/models/filter
# ---------------------------------------------------------------------------


class TestFilterOpenrouterModels:
    async def test_missing_provider_returns_404(self) -> None:
        manager = _make_manager()
        manager.get_provider.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.filter_openrouter_models(
                manager=manager,
                body=providers_mod.FilterModelsRequest(),
            )
        assert exc_info.value.status_code == 404

    async def test_wrong_provider_type_returns_400(self) -> None:
        manager = _make_manager()
        manager.get_provider.return_value = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.filter_openrouter_models(
                manager=manager,
                body=providers_mod.FilterModelsRequest(),
            )
        assert exc_info.value.status_code == 400

    async def test_success_passes_filter_criteria(self) -> None:
        manager = _make_manager()
        provider = _openrouter_provider()
        kept = _extended_model("openai/kept")
        object.__setattr__(
            provider,
            "fetch_extended_models",
            AsyncMock(return_value=[kept, _extended_model("openai/dropped")]),
        )
        object.__setattr__(
            provider,
            "filter_models",
            MagicMock(return_value=[kept]),
        )
        manager.get_provider.return_value = provider
        body = providers_mod.FilterModelsRequest(
            providers=["openai"],
            input_modalities=["image"],
            output_modalities=["text"],
            max_prompt_price=0.001,
            is_free=False,
        )

        result = await providers_mod.filter_openrouter_models(
            manager=manager,
            body=body,
        )

        assert result.success is True
        assert result.total_count == 1
        assert result.models[0]["id"] == "openai/kept"
        provider.filter_models.assert_called_once()
        kwargs = provider.filter_models.call_args.kwargs
        assert kwargs["providers"] == ["openai"]
        assert kwargs["input_modalities"] == ["image"]
        assert kwargs["output_modalities"] == ["text"]
        assert kwargs["max_prompt_price"] == 0.001
        assert kwargs["is_free"] is False

    async def test_empty_criteria_become_none(self) -> None:
        manager = _make_manager()
        provider = _openrouter_provider()
        object.__setattr__(
            provider,
            "fetch_extended_models",
            AsyncMock(return_value=[]),
        )
        object.__setattr__(
            provider,
            "filter_models",
            MagicMock(return_value=[]),
        )
        manager.get_provider.return_value = provider

        result = await providers_mod.filter_openrouter_models(
            manager=manager,
            body=providers_mod.FilterModelsRequest(),
        )

        assert result.success is True
        assert result.total_count == 0
        kwargs = provider.filter_models.call_args.kwargs
        assert kwargs["providers"] is None
        assert kwargs["input_modalities"] is None
        assert kwargs["output_modalities"] is None
        assert kwargs["is_free"] is None

    async def test_fetch_error_returns_500(self) -> None:
        manager = _make_manager()
        provider = _openrouter_provider()
        object.__setattr__(
            provider,
            "fetch_extended_models",
            AsyncMock(side_effect=RuntimeError("nope")),
        )
        manager.get_provider.return_value = provider
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.filter_openrouter_models(
                manager=manager,
                body=providers_mod.FilterModelsRequest(),
            )
        assert exc_info.value.status_code == 500
        assert "nope" in exc_info.value.detail


# ---------------------------------------------------------------------------
# GET /active
# ---------------------------------------------------------------------------


class TestGetActiveModels:
    def _manager_with_global(self, slot: ModelSlotConfig | None) -> MagicMock:
        manager = _make_manager()
        manager.get_active_model.return_value = slot
        provider = MagicMock()
        provider.get_context_size.return_value = 4096
        manager.get_provider.return_value = provider
        return manager

    async def test_global_scope_returns_global_model(self) -> None:
        slot = ModelSlotConfig(provider_id="p", model="m")
        manager = self._manager_with_global(slot)
        result = await providers_mod.get_active_models(
            request=MagicMock(),
            manager=manager,
            scope="global",
            agent_id=None,
        )
        assert result.active_llm == slot
        assert result.effective_max_input_length == 4096

    async def test_global_scope_without_model_resolves_none(self) -> None:
        manager = self._manager_with_global(None)
        result = await providers_mod.get_active_models(
            request=MagicMock(),
            manager=manager,
            scope="global",
            agent_id=None,
        )
        assert result.active_llm is None
        assert result.effective_max_input_length is None

    async def test_agent_scope_requires_agent_id(self) -> None:
        manager = self._manager_with_global(None)
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.get_active_models(
                request=MagicMock(),
                manager=manager,
                scope="agent",
                agent_id=None,
            )
        assert exc_info.value.status_code == 400

    async def test_agent_scope_returns_agent_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        slot = ModelSlotConfig(provider_id="p", model="agent-m")
        manager = self._manager_with_global(None)
        workspace = SimpleNamespace(agent_id="agent-1")
        monkeypatch.setattr(
            providers_mod,
            "get_agent_for_request",
            AsyncMock(return_value=workspace),
        )
        monkeypatch.setattr(
            providers_mod,
            "load_agent_config",
            MagicMock(return_value=SimpleNamespace(active_model=slot)),
        )
        result = await providers_mod.get_active_models(
            request=MagicMock(),
            manager=manager,
            scope="agent",
            agent_id="agent-1",
        )
        assert result.active_llm == slot

    async def test_effective_scope_prefers_agent_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agent_slot = ModelSlotConfig(provider_id="p", model="agent-m")
        global_slot = ModelSlotConfig(provider_id="p", model="global-m")
        manager = self._manager_with_global(global_slot)
        workspace = SimpleNamespace(agent_id="agent-1")
        monkeypatch.setattr(
            providers_mod,
            "get_agent_for_request",
            AsyncMock(return_value=workspace),
        )
        monkeypatch.setattr(
            providers_mod,
            "load_agent_config",
            MagicMock(return_value=SimpleNamespace(active_model=agent_slot)),
        )
        result = await providers_mod.get_active_models(
            request=MagicMock(),
            manager=manager,
            scope="effective",
            agent_id=None,
        )
        assert result.active_llm == agent_slot

    async def test_effective_scope_falls_back_to_global(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        global_slot = ModelSlotConfig(provider_id="p", model="global-m")
        manager = self._manager_with_global(global_slot)
        workspace = SimpleNamespace(agent_id="agent-1")
        monkeypatch.setattr(
            providers_mod,
            "get_agent_for_request",
            AsyncMock(return_value=workspace),
        )
        monkeypatch.setattr(
            providers_mod,
            "load_agent_config",
            MagicMock(return_value=SimpleNamespace(active_model=None)),
        )
        result = await providers_mod.get_active_models(
            request=MagicMock(),
            manager=manager,
            scope="effective",
            agent_id=None,
        )
        assert result.active_llm == global_slot

    async def test_effective_scope_error_falls_back_to_global(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        global_slot = ModelSlotConfig(provider_id="p", model="global-m")
        manager = self._manager_with_global(global_slot)
        workspace = SimpleNamespace(agent_id="agent-1")
        monkeypatch.setattr(
            providers_mod,
            "get_agent_for_request",
            AsyncMock(return_value=workspace),
        )
        monkeypatch.setattr(
            providers_mod,
            "load_agent_config",
            MagicMock(side_effect=ValueError("corrupt config")),
        )
        result = await providers_mod.get_active_models(
            request=MagicMock(),
            manager=manager,
            scope="effective",
            agent_id=None,
        )
        assert result.active_llm == global_slot


# ---------------------------------------------------------------------------
# PUT /active
# ---------------------------------------------------------------------------


class TestSetActiveModel:
    def _manager(self) -> MagicMock:
        manager = _make_manager()
        provider = MagicMock()
        provider.has_model.return_value = True
        provider.get_model_info.return_value = None
        manager.get_provider.return_value = provider
        manager.get_active_model.return_value = ModelSlotConfig(
            provider_id="p",
            model="m",
        )
        return manager

    async def test_global_scope_provider_not_found_maps_to_404(self) -> None:
        manager = self._manager()
        manager.activate_model = AsyncMock(
            side_effect=ValueError("Provider 'x' not found"),
        )
        body = providers_mod.ModelSlotRequest(
            provider_id="x",
            model="m",
            scope="global",
        )
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.set_active_model(
                request=MagicMock(),
                manager=manager,
                body=body,
            )
        assert exc_info.value.status_code == 404

    async def test_global_scope_other_error_maps_to_400(self) -> None:
        manager = self._manager()
        manager.activate_model = AsyncMock(
            side_effect=RuntimeError("bad slot"),
        )
        body = providers_mod.ModelSlotRequest(
            provider_id="p",
            model="m",
            scope="global",
        )
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.set_active_model(
                request=MagicMock(),
                manager=manager,
                body=body,
            )
        assert exc_info.value.status_code == 400

    async def test_global_scope_syncs_unset_agent_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager = self._manager()
        manager.activate_model = AsyncMock()
        workspace = SimpleNamespace(agent_id="agent-1")
        monkeypatch.setattr(
            providers_mod,
            "get_agent_for_request",
            AsyncMock(return_value=workspace),
        )
        reload_calls: list = []
        monkeypatch.setattr(
            providers_mod,
            "schedule_agent_reload",
            lambda request, agent_id: reload_calls.append(agent_id),
        )
        configs: list = []

        async def fake_update(agent_id, mutator):
            cfg = SimpleNamespace(active_model=None)
            mutator(cfg)
            configs.append(cfg)
            return cfg

        monkeypatch.setattr(
            providers_mod,
            "update_agent_config_async",
            fake_update,
        )
        body = providers_mod.ModelSlotRequest(
            provider_id="p",
            model="m",
            scope="global",
        )

        result = await providers_mod.set_active_model(
            request=MagicMock(),
            manager=manager,
            body=body,
        )

        assert result.active_llm == manager.get_active_model()
        assert configs[0].active_model == ModelSlotConfig(
            provider_id="p",
            model="m",
        )
        assert reload_calls == ["agent-1"]

    async def test_global_scope_keeps_existing_agent_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager = self._manager()
        manager.activate_model = AsyncMock()
        workspace = SimpleNamespace(agent_id="agent-1")
        monkeypatch.setattr(
            providers_mod,
            "get_agent_for_request",
            AsyncMock(return_value=workspace),
        )
        reload_calls: list = []
        monkeypatch.setattr(
            providers_mod,
            "schedule_agent_reload",
            lambda request, agent_id: reload_calls.append(agent_id),
        )
        existing = ModelSlotConfig(provider_id="other", model="keep-me")

        async def fake_update(agent_id, mutator):
            cfg = SimpleNamespace(active_model=existing)
            mutator(cfg)
            return cfg

        monkeypatch.setattr(
            providers_mod,
            "update_agent_config_async",
            fake_update,
        )
        body = providers_mod.ModelSlotRequest(
            provider_id="p",
            model="m",
            scope="global",
        )

        await providers_mod.set_active_model(
            request=MagicMock(),
            manager=manager,
            body=body,
        )

        assert reload_calls == []

    async def test_global_scope_ignores_agent_sync_errors(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager = self._manager()
        manager.activate_model = AsyncMock()
        monkeypatch.setattr(
            providers_mod,
            "get_agent_for_request",
            AsyncMock(side_effect=OSError("no workspace")),
        )
        body = providers_mod.ModelSlotRequest(
            provider_id="p",
            model="m",
            scope="global",
        )

        result = await providers_mod.set_active_model(
            request=MagicMock(),
            manager=manager,
            body=body,
        )

        assert result.active_llm == manager.get_active_model()

    async def test_agent_scope_requires_agent_id(self) -> None:
        manager = self._manager()
        body = providers_mod.ModelSlotRequest(
            provider_id="p",
            model="m",
            scope="agent",
        )
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.set_active_model(
                request=MagicMock(),
                manager=manager,
                body=body,
            )
        assert exc_info.value.status_code == 400

    async def test_agent_scope_invalid_slot_raises(self) -> None:
        manager = self._manager()
        manager.get_provider.return_value = None
        body = providers_mod.ModelSlotRequest(
            provider_id="missing",
            model="m",
            scope="agent",
            agent_id="agent-1",
        )
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.set_active_model(
                request=MagicMock(),
                manager=manager,
                body=body,
            )
        assert exc_info.value.status_code == 404

    async def test_agent_scope_saves_and_reloads(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager = self._manager()
        workspace = SimpleNamespace(agent_id="agent-1")
        monkeypatch.setattr(
            providers_mod,
            "get_agent_for_request",
            AsyncMock(return_value=workspace),
        )
        reload_calls: list = []
        monkeypatch.setattr(
            providers_mod,
            "schedule_agent_reload",
            lambda request, agent_id: reload_calls.append(agent_id),
        )
        configs: list = []

        async def fake_update(agent_id, mutator):
            cfg = SimpleNamespace(active_model=None)
            mutator(cfg)
            configs.append(cfg)
            return cfg

        monkeypatch.setattr(
            providers_mod,
            "update_agent_config_async",
            fake_update,
        )
        body = providers_mod.ModelSlotRequest(
            provider_id="p",
            model="agent-m",
            scope="agent",
            agent_id="agent-1",
        )

        result = await providers_mod.set_active_model(
            request=MagicMock(),
            manager=manager,
            body=body,
        )

        assert configs[0].active_model == ModelSlotConfig(
            provider_id="p",
            model="agent-m",
        )
        assert reload_calls == ["agent-1"]
        manager.maybe_probe_multimodal.assert_called_once_with(
            "p",
            "agent-m",
        )
        assert result.active_llm == ModelSlotConfig(
            provider_id="p",
            model="agent-m",
        )

    async def test_agent_scope_save_failure_maps_to_500(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager = self._manager()
        monkeypatch.setattr(
            providers_mod,
            "get_agent_for_request",
            AsyncMock(side_effect=OSError("workspace gone")),
        )
        body = providers_mod.ModelSlotRequest(
            provider_id="p",
            model="m",
            scope="agent",
            agent_id="agent-1",
        )
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.set_active_model(
                request=MagicMock(),
                manager=manager,
                body=body,
            )
        assert exc_info.value.status_code == 500
        assert "Failed to save" in exc_info.value.detail


# ---------------------------------------------------------------------------
# POST /{provider_id}/test (connection endpoint)
# ---------------------------------------------------------------------------


class TestProviderConnectionEndpoint:
    async def test_missing_provider_returns_404(self) -> None:
        manager = _make_manager()
        manager.get_provider.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            await providers_mod.test_provider(
                manager=manager,
                provider_id="ghost",
                body=None,
            )
        assert exc_info.value.status_code == 404

    async def test_successful_connection(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager = _make_manager()
        provider = _openrouter_provider()
        manager.get_provider.return_value = provider
        monkeypatch.setattr(
            OpenRouterProvider,
            "check_connection",
            AsyncMock(return_value=(True, "")),
        )
        result = await providers_mod.test_provider(
            manager=manager,
            provider_id="openrouter",
            body=None,
        )
        assert result.success is True
        assert result.message == "Connection successful"

    async def test_failed_connection_reports_reason(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager = _make_manager()
        provider = _openrouter_provider()
        manager.get_provider.return_value = provider
        monkeypatch.setattr(
            OpenRouterProvider,
            "check_connection",
            AsyncMock(return_value=(False, "timeout")),
        )
        result = await providers_mod.test_provider(
            manager=manager,
            provider_id="openrouter",
            body=None,
        )
        assert result.success is False
        assert "timeout" in result.message

    async def test_body_overrides_are_applied(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        manager = _make_manager()
        provider = _openrouter_provider()
        manager.get_provider.return_value = provider
        seen: list = []

        async def fake_check(self_provider):
            seen.append(self_provider.api_key)
            return True, ""

        monkeypatch.setattr(
            OpenRouterProvider,
            "check_connection",
            fake_check,
        )
        body = providers_mod.TestProviderRequest(api_key="sk-override")
        result = await providers_mod.test_provider(
            manager=manager,
            provider_id="openrouter",
            body=body,
        )
        assert result.success is True
        assert seen == ["sk-override"]
        # The original provider keeps its key; only the copy changed.
        assert provider.api_key == "sk-test"
