# -*- coding: utf-8 -*-
"""Tests for the /model control command handler.

Covers handle() dispatch routing, the format-validation guards of
_switch_model and _show_model_info, _show_current_model (agent-specific
vs global fallback vs none), _list_models configured-provider
filtering, and _reset_model, with ProviderManager patched.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.runtime.commands.control.base import ControlContext
from qwenpaw.runtime.commands.control.model_handler import ModelCommandHandler


def _context(active_model=None, raw_args=""):
    config = SimpleNamespace(active_model=active_model, id="default")
    workspace = SimpleNamespace(config=config, agent_id="default")
    return ControlContext(
        workspace=workspace,
        payload={},
        channel=None,
        session_id="console:user1",
        user_id="user1",
        agent_id="default",
        args={"_raw_args": raw_args},
    )


@pytest.fixture
def handler():
    return ModelCommandHandler()


# ---------------------------------------------------------------------------
# handle() dispatch
# ---------------------------------------------------------------------------


class TestHandleDispatch:
    async def test_empty_args_shows_current_model(self, handler):
        async def fake_show(context):
            return "CURRENT"

        with patch.object(handler, "_show_current_model", fake_show):
            result = await handler.handle(_context(raw_args=""))
        assert result == "CURRENT"

    async def test_help_flags(self, handler):
        for flag in ("-h", "--help", "help", "HELP"):
            result = await handler.handle(_context(raw_args=flag))
            assert "Model Management Commands" in result

    async def test_list_dispatches(self, handler):
        async def fake_list(context):
            return "LISTED"

        with patch.object(handler, "_list_models", fake_list):
            result = await handler.handle(_context(raw_args="list"))
        assert result == "LISTED"

    async def test_reset_dispatches(self, handler):
        async def fake_reset(context):
            return "RESET"

        with patch.object(handler, "_reset_model", fake_reset):
            result = await handler.handle(_context(raw_args="reset"))
        assert result == "RESET"

    async def test_info_without_spec_shows_usage(self, handler):
        result = await handler.handle(_context(raw_args="info"))
        assert "Missing Model Specification" in result

    async def test_info_with_spec_dispatches(self, handler):
        async def fake_info(context, spec):
            return f"INFO:{spec}"

        with patch.object(handler, "_show_model_info", fake_info):
            result = await handler.handle(_context(raw_args="info openai:gpt"))
        assert result == "INFO:openai:gpt"

    async def test_other_args_treated_as_switch(self, handler):
        async def fake_switch(context, spec):
            return f"SWITCH:{spec}"

        with patch.object(handler, "_switch_model", fake_switch):
            result = await handler.handle(_context(raw_args="openai:gpt-4o"))
        assert result == "SWITCH:openai:gpt-4o"


# ---------------------------------------------------------------------------
# _switch_model format guards
# ---------------------------------------------------------------------------


class TestSwitchModelFormat:
    async def test_no_colon_rejected(self, handler):
        result = await handler._switch_model(_context(), "openai-gpt")
        assert "Invalid Format" in result
        assert "`/model <provider>:<model>`" in result

    async def test_empty_provider_rejected(self, handler):
        result = await handler._switch_model(_context(), ":gpt-4o")
        assert "Provider and model cannot be empty" in result

    async def test_empty_model_rejected(self, handler):
        result = await handler._switch_model(_context(), "openai:")
        assert "Provider and model cannot be empty" in result

    async def test_whitespace_parts_rejected(self, handler):
        result = await handler._switch_model(_context(), "   :   ")
        assert "Provider and model cannot be empty" in result

    async def test_invalid_model_reports_error(self, handler):
        async def fake_validate(provider_id, model_id):
            return False, "Model not found"

        with patch.object(handler, "_validate_model", fake_validate):
            result = await handler._switch_model(_context(), "openai:ghost")
        assert "Switch Failed" in result
        assert "Model not found" in result


# ---------------------------------------------------------------------------
# _show_model_info guards
# ---------------------------------------------------------------------------


class TestShowModelInfo:
    async def test_no_colon_rejected(self, handler):
        result = await handler._show_model_info(_context(), "badformat")
        assert "Invalid Format" in result

    async def test_unknown_provider_reports(self, handler):
        manager = SimpleNamespace(get_provider=lambda pid: None)
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=manager,
        ):
            result = await handler._show_model_info(_context(), "ghost:model")
        assert "Provider Not Found" in result


# ---------------------------------------------------------------------------
# _show_current_model
# ---------------------------------------------------------------------------


class TestShowCurrentModel:
    async def test_agent_specific_model(self, handler):
        model = SimpleNamespace(provider_id="openai", model="gpt-4o")
        result = await handler._show_current_model(
            _context(active_model=model),
        )
        assert "Current Model" in result
        assert "agent-specific" in result
        assert "openai" in result
        assert "gpt-4o" in result

    async def test_falls_back_to_global(self, handler):
        manager = SimpleNamespace(
            get_active_model=lambda: SimpleNamespace(
                provider_id="anthropic",
                model="claude",
            ),
        )
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=manager,
        ):
            result = await handler._show_current_model(
                _context(active_model=None),
            )
        assert "global default" in result
        assert "anthropic" in result

    async def test_no_model_configured(self, handler):
        manager = SimpleNamespace(get_active_model=lambda: None)
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=manager,
        ):
            result = await handler._show_current_model(
                _context(active_model=None),
            )
        assert "No Active Model" in result

    async def test_agent_model_without_provider_falls_back(self, handler):
        manager = SimpleNamespace(get_active_model=lambda: None)
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=manager,
        ):
            result = await handler._show_current_model(
                _context(
                    active_model=SimpleNamespace(provider_id="", model=""),
                ),
            )
        assert "No Active Model" in result


# ---------------------------------------------------------------------------
# _list_models
# ---------------------------------------------------------------------------


class TestListModels:
    def _provider_info(
        self,
        name="openai",
        require_api_key=True,
        api_key="k",
        models=("m1",),
        extra_models=(),
    ):
        def _model(mid):
            return SimpleNamespace(
                id=mid,
                supports_image=False,
                supports_video=False,
            )

        return SimpleNamespace(
            id=name,
            provider_id=name,
            name=name,
            require_api_key=require_api_key,
            api_key=api_key,
            models=[_model(m) for m in models],
            extra_models=[_model(m) for m in extra_models],
        )

    async def test_no_configured_providers(self, handler):
        manager = SimpleNamespace(
            get_active_model=lambda: None,
            list_provider_info=AsyncMock(return_value=[]),
        )
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=manager,
        ):
            result = await handler._list_models(_context())
        assert "No Providers Configured" in result

    async def test_provider_without_api_key_filtered(self, handler):
        infos = [self._provider_info(require_api_key=True, api_key="")]
        manager = SimpleNamespace(
            get_active_model=lambda: None,
            list_provider_info=AsyncMock(return_value=infos),
        )
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=manager,
        ):
            result = await handler._list_models(_context())
        assert "No Providers Configured" in result

    async def test_provider_without_models_filtered(self, handler):
        infos = [self._provider_info(models=(), extra_models=())]
        manager = SimpleNamespace(
            get_active_model=lambda: None,
            list_provider_info=AsyncMock(return_value=infos),
        )
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=manager,
        ):
            result = await handler._list_models(_context())
        assert "No Providers Configured" in result

    async def test_extra_models_count_for_keep(self, handler):
        infos = [self._provider_info(models=(), extra_models=("x",))]
        manager = SimpleNamespace(
            get_active_model=lambda: None,
            list_provider_info=AsyncMock(return_value=infos),
        )
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=manager,
        ):
            result = await handler._list_models(_context())
        assert "No Providers Configured" not in result
        assert "openai" in result


# ---------------------------------------------------------------------------
# _reset_model
# ---------------------------------------------------------------------------


class TestResetModel:
    async def test_no_global_model_fails(self, handler):
        manager = SimpleNamespace(get_active_model=lambda: None)
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=manager,
        ):
            result = await handler._reset_model(_context())
        assert "Reset Failed" in result

    async def test_reset_clears_agent_model(self, handler):
        global_model = SimpleNamespace(provider_id="openai", model="gpt")
        manager = SimpleNamespace(get_active_model=lambda: global_model)
        ctx = _context(
            active_model=SimpleNamespace(provider_id="x", model="y"),
        )
        applied = {}

        async def fake_update(agent_id, mutator):
            persisted = SimpleNamespace(
                active_model=SimpleNamespace(provider_id="x", model="y"),
            )
            mutator(persisted)
            applied["active_model"] = persisted.active_model
            return persisted

        with (
            patch(
                "qwenpaw.providers.provider_manager"
                ".ProviderManager.get_instance",
                return_value=manager,
            ),
            patch(
                "qwenpaw.config.config.update_agent_config_async",
                fake_update,
            ),
        ):
            await handler._reset_model(ctx)
        assert ctx.workspace.config.active_model is None
        assert applied["active_model"] is None
