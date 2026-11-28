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

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.providers.thinking import ThinkingPreference
from qwenpaw.runtime.commands.control.base import ControlContext
from qwenpaw.runtime.commands.control.model_handler import ModelCommandHandler
from qwenpaw.services.session_thinking import apply_session_thinking


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
    @staticmethod
    def _provider_info(
        name="openai",
        require_api_key=True,
        api_key="k",
        models=("m1",),
        extra_models=(),
    ):
        def _model(mid):
            return SimpleNamespace(
                id=mid,
                model_type="chat",
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
# Session model writes
# ---------------------------------------------------------------------------


class TestSessionModelWrites:
    @pytest.fixture
    def context(self, tmp_path, monkeypatch):
        ctx = _context()
        ctx.session_id = f"feishu:conversation"
        ctx.payload = {f"channel": f"feishu", f"user_id": ctx.user_id}
        ctx.workspace.config = AgentProfileConfig(
            id=f"default",
            name=f"Agent",
            active_model=ModelSlotConfig(
                provider_id=f"demo",
                model=f"agent-default",
            ),
        )
        ctx.workspace.chat_manager = ChatManager(
            repo=JsonChatRepository(tmp_path / f"chats.json"),
        )
        monkeypatch.setattr(
            f"qwenpaw.config.config.update_agent_config_async",
            AsyncMock(side_effect=AssertionError(f"Unexpected agent write")),
        )
        return ctx

    @pytest.mark.parametrize("existing", [False, True])
    async def test_switch_updates_current_session(
        self,
        handler,
        context,
        existing,
    ):
        manager = context.workspace.chat_manager
        other = await manager.get_or_create_chat(
            context.session_id,
            f"another-user",
            f"feishu",
        )
        old_model = {f"provider_id": f"offline", f"model": f"unreachable"}
        if existing:
            chat = await manager.get_or_create_chat(
                context.session_id,
                context.user_id,
                f"feishu",
            )
            await manager.set_session_model(chat.id, old_model)

        with patch.object(
            handler,
            f"_validate_model",
            AsyncMock(return_value=(True, f"")),
        ):
            context.args[f"_raw_args"] = f"demo:replacement"
            result = await handler.handle(context)

        assert f"Model Switched" in result
        assert f"this conversation" in result.lower()
        found = await manager.get_or_create_chat(
            context.session_id,
            context.user_id,
            f"feishu",
        )
        if existing:
            assert found.id == chat.id
        assert found.meta[f"runtime_context"][f"model"] == {
            f"provider_id": f"demo",
            f"model": f"replacement",
        }
        assert (await manager.get_chat(other.id)).meta == {}
        default = context.workspace.config
        assert default.active_model.model == f"agent-default"
        next_turn = await apply_session_thinking(context, default)
        assert next_turn.active_model.model == f"replacement"
        context.args[f"_raw_args"] = f""
        assert f"Model: `replacement`" in await handler.handle(context)

    @pytest.mark.parametrize(
        "default_source",
        [f"agent-specific", f"global default", None],
    )
    async def test_reset_clears_only_session_model_and_thinking(
        self,
        handler,
        context,
        default_source,
    ):
        manager = context.workspace.chat_manager
        chat = await manager.get_or_create_chat(
            context.session_id,
            context.user_id,
            f"feishu",
        )
        await manager.set_session_model(
            chat.id,
            {f"provider_id": f"demo", f"model": f"pinned"},
        )
        await manager.set_session_thinking(
            chat.id,
            ThinkingPreference(level=f"high"),
            f"demo:pinned",
        )
        config = context.workspace.config
        if default_source != f"agent-specific":
            config.active_model = None
        global_model = (
            ModelSlotConfig(provider_id=f"demo", model=f"global-model")
            if default_source == f"global default"
            else None
        )
        providers = SimpleNamespace(get_active_model=lambda: global_model)
        with patch.object(
            ProviderManager,
            f"get_instance",
            return_value=providers,
        ):
            context.args[f"_raw_args"] = f"reset"
            result = await handler.handle(context)

        assert f"Model Reset" in result
        if default_source is None:
            assert f"No default model is configured" in result
        else:
            assert default_source in result
        stored = await manager.get_chat(chat.id)
        assert stored.meta[f"runtime_context"] == {}
        if default_source == f"agent-specific":
            assert config.active_model.model == f"agent-default"

    @pytest.mark.parametrize(
        ("command", "message"),
        [
            (f"", f"agent-default"),
            (f"reset", f"already inherits"),
            (f"demo:missing", f"Switch Failed"),
        ],
    )
    async def test_lookup_reset_and_invalid_switch_do_not_create_chat(
        self,
        handler,
        context,
        command,
        message,
    ):
        with patch.object(
            ProviderManager,
            f"get_instance",
            return_value=SimpleNamespace(get_provider=lambda _: None),
        ):
            context.args[f"_raw_args"] = command
            result = await handler.handle(context)
        assert message in result
        assert await context.workspace.chat_manager.list_chats() == []

    @pytest.mark.parametrize("command", [f"reset", f"demo:replacement"])
    async def test_missing_user_does_not_target_another_chat(
        self,
        handler,
        context,
        command,
    ):
        manager = context.workspace.chat_manager
        other = await manager.get_or_create_chat(
            context.session_id,
            context.user_id,
            f"feishu",
        )
        selected = {f"provider_id": f"demo", f"model": f"pinned"}
        await manager.set_session_model(other.id, selected)
        context.user_id = f""
        context.payload[f"user_id"] = f""
        with patch.object(
            handler,
            f"_validate_model",
            AsyncMock(return_value=(True, f"")),
        ):
            context.args[f"_raw_args"] = command
            result = await handler.handle(context)
        assert f"Failed" in result
        stored = await manager.get_chat(other.id)
        assert stored.meta[f"runtime_context"][f"model"] == selected

    async def test_failed_write_preserves_the_previous_model(
        self,
        handler,
        context,
    ):
        manager = context.workspace.chat_manager
        chat = await manager.get_or_create_chat(
            context.session_id,
            context.user_id,
            f"feishu",
        )
        selected = {f"provider_id": f"demo", f"model": f"pinned"}
        await manager.set_session_model(chat.id, selected)
        context.args[f"_raw_args"] = f"demo:replacement"
        with (
            patch.object(
                handler,
                f"_validate_model",
                AsyncMock(return_value=(True, f"")),
            ),
            patch.object(manager._repo, f"save", side_effect=OSError),
        ):
            result = await handler.handle(context)
        assert f"Switch Failed" in result
        stored = await manager.get_chat(chat.id)
        assert stored.meta[f"runtime_context"][f"model"] == selected


class TestConversationOverrides:
    @pytest.fixture
    def context(self):
        ctx = _context()
        ctx.workspace.config = AgentProfileConfig(
            id="default",
            name="Agent",
            active_model=ModelSlotConfig(
                provider_id="openai",
                model="default",
            ),
        )
        ctx.workspace.chat_manager = SimpleNamespace(
            get_chat_id_by_session=AsyncMock(return_value="chat"),
            get_chat=AsyncMock(
                return_value=SimpleNamespace(
                    meta={
                        "runtime_context": {
                            "model": {
                                "provider_id": "openai",
                                "model": "selected",
                            },
                        },
                    },
                ),
            ),
        )
        return ctx

    async def test_show_and_list_mark_the_session_model(
        self,
        handler,
        context,
    ):
        result = await handler._show_current_model(context)
        assert "session override" in result
        assert "Model: `selected`" in result
        info = TestListModels._provider_info(models=("default", "selected"))
        manager = SimpleNamespace(
            list_provider_info=AsyncMock(return_value=[info]),
        )
        with patch(
            "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
            return_value=manager,
        ):
            listed = await handler._list_models(context)
        assert "`selected` **[ACTIVE]**" in listed
        assert "`default` **[ACTIVE]**" not in listed

    async def test_request_override_wins_in_model_display(
        self,
        handler,
        context,
    ):
        context.payload = {
            "request_context": {
                "model_slot_override": "other:explicit",
            },
        }
        result = await handler._show_current_model(context)
        assert "request override" in result
        assert "`explicit`" in result
        assert "`selected`" not in result
