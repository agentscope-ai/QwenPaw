# -*- coding: utf-8 -*-
"""Tests for the built-in slash-command adapters in runtime/builtin_commands.

Covers the adapter closures that the collectors build — daemon,
compound daemon, control and conversation — plus the agent-state
load/save helpers they depend on, and the ReMe approval argument
truncation.  Spec collection itself is covered by
``test_builtin_commands_help_text.py``.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=use-implicit-booleaness-not-comparison
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import Msg, TextBlock
from agentscope.state import AgentState

from qwenpaw.runtime import builtin_commands as bc
from qwenpaw.runtime._state_utils import StateProxy
from qwenpaw.security.tool_guard.approval import ApprovalDecision


def _msg_text(msg: Any) -> str:
    """Join every text block of an agentscope ``Msg`` into one string."""
    if msg is None:
        return ""
    parts = []
    for block in msg.content or []:
        text = (
            block.get("text")
            if isinstance(block, dict)
            else getattr(block, "text", "")
        )
        if text:
            parts.append(str(text))
    return "".join(parts)


def _lcc(
    *,
    strategy: str = "native",
    offload_dialog: bool = False,
) -> SimpleNamespace:
    """Build a light-context-config double."""
    return SimpleNamespace(
        strategy=strategy,
        scroll_config=SimpleNamespace(offload_dialog=offload_dialog),
        dialog_path="dialog.db",
        tool_result_pruning_config=SimpleNamespace(
            tool_results_cache="tool_cache",
        ),
    )


def _cfg(*, name: str = "MyAgent", lcc: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        running=SimpleNamespace(
            light_context_config=lcc if lcc is not None else _lcc(),
        ),
    )


def _session_ctx(
    payload: Optional[dict] = None,
    *,
    workspace_dir: str = "/tmp/ws",
    memory_manager: Any = "mm",
):
    """Build a ``(ctx, saved)`` pair backed by an in-memory session double."""
    saved: dict = {}
    stored = dict(payload or {})

    async def _load(*, session_id, user_id, channel, agent):
        agent.load_state_dict(stored)
        saved["load"] = {
            "session_id": session_id,
            "user_id": user_id,
            "channel": channel,
        }

    async def _save(*, session_id, user_id, channel, agent):
        saved["data"] = agent.state_dict()
        saved["save"] = {
            "session_id": session_id,
            "user_id": user_id,
            "channel": channel,
        }

    session = SimpleNamespace(
        load_session_state=AsyncMock(side_effect=_load),
        save_session_state=AsyncMock(side_effect=_save),
    )
    workspace = SimpleNamespace(
        session=session,
        memory_manager=memory_manager,
        workspace_dir=workspace_dir,
        _manager="mgr",
        channel_manager=None,
    )
    ctx = SimpleNamespace(
        workspace=workspace,
        request=SimpleNamespace(user_id="user-1", channel="console"),
        session_id="session-1",
        agent_id="agent-1",
    )
    return ctx, saved


def _state_payload(**extra: Any) -> dict:
    payload = {"state": AgentState().model_dump(mode="json")}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# _make_daemon_adapter
# ---------------------------------------------------------------------------


class TestDaemonAdapter:
    def test_spec_shape(self):
        spec = bc._make_daemon_adapter("status")
        assert spec.name == "status"
        assert spec.category == "daemon"
        assert spec.aliases == ()

    async def test_forwards_full_query_and_context(self):
        spec = bc._make_daemon_adapter("restart")
        ctx, _ = _session_ctx()
        with (
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(name="MyAgent"),
            ) as load_cfg,
            patch(
                "qwenpaw.runtime.commands.daemon.DaemonCommandHandlerMixin",
            ) as mixin,
        ):
            mixin.return_value.handle_daemon_command = AsyncMock(
                return_value="done",
            )
            result = await spec.handler(ctx, "--force")

        assert result == "done"
        load_cfg.assert_called_once_with("agent-1")
        call = mixin.return_value.handle_daemon_command.await_args
        assert call.args[0] == "/restart --force"
        daemon_ctx = call.args[1]
        assert daemon_ctx.agent_id == "agent-1"
        assert daemon_ctx.agent_name == "MyAgent"
        assert daemon_ctx.session_id == "session-1"
        assert daemon_ctx.memory_manager == "mm"
        assert daemon_ctx.manager == "mgr"

    async def test_blank_args_produce_a_bare_query(self):
        spec = bc._make_daemon_adapter("logs")
        ctx, _ = _session_ctx()
        with (
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
            patch(
                "qwenpaw.runtime.commands.daemon.DaemonCommandHandlerMixin",
            ) as mixin,
        ):
            mixin.return_value.handle_daemon_command = AsyncMock(
                return_value=None,
            )
            assert await spec.handler(ctx, "   ") is None

        assert (
            mixin.return_value.handle_daemon_command.await_args.args[0]
            == "/logs"
        )

    async def test_config_failure_falls_back_to_default_identity(self):
        spec = bc._make_daemon_adapter("version")
        with (
            patch(
                "qwenpaw.config.config.load_agent_config",
                side_effect=RuntimeError("no such agent"),
            ),
            patch(
                "qwenpaw.runtime.commands.daemon.DaemonCommandHandlerMixin",
            ) as mixin,
        ):
            mixin.return_value.handle_daemon_command = AsyncMock(
                return_value="ok",
            )
            # A ctx without any of the optional attributes at all.
            await spec.handler(SimpleNamespace(), "")

        daemon_ctx = mixin.return_value.handle_daemon_command.await_args.args[
            1
        ]
        assert daemon_ctx.agent_id == "default"
        assert daemon_ctx.agent_name == "QwenPaw"
        assert daemon_ctx.session_id == ""
        assert daemon_ctx.memory_manager is None
        assert daemon_ctx.manager is None

    @pytest.mark.parametrize("name", [None, ""])
    async def test_blank_agent_name_falls_back(self, name):
        spec = bc._make_daemon_adapter("status")
        ctx, _ = _session_ctx()
        with (
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(name=name),
            ),
            patch(
                "qwenpaw.runtime.commands.daemon.DaemonCommandHandlerMixin",
            ) as mixin,
        ):
            mixin.return_value.handle_daemon_command = AsyncMock(
                return_value="ok",
            )
            await spec.handler(ctx, "")

        daemon_ctx = mixin.return_value.handle_daemon_command.await_args.args[
            1
        ]
        assert daemon_ctx.agent_name == "QwenPaw"


class TestDaemonSpecCollection:
    def test_reload_config_keeps_an_underscore_alias(self):
        specs = {s.name: s for s in bc._collect_daemon_specs()}
        assert specs["reload-config"].aliases == ("reload_config",)

    def test_every_shortcut_is_advertised(self):
        names = {s.name for s in bc._collect_daemon_specs()}
        assert names == {
            "restart",
            "status",
            "version",
            "logs",
            "reload-config",
            "daemon",
        }
        specs = bc._collect_daemon_specs()
        assert all(s.category == "daemon" for s in specs)


# ---------------------------------------------------------------------------
# _make_daemon_compound_adapter
# ---------------------------------------------------------------------------


class TestDaemonCompoundAdapter:
    async def test_dispatches_a_known_subcommand(self):
        spec = bc._make_daemon_compound_adapter()
        ctx, _ = _session_ctx()
        assert spec.name == "daemon"
        with (
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
            patch(
                "qwenpaw.runtime.commands.daemon.DaemonCommandHandlerMixin",
            ) as mixin,
        ):
            mixin.return_value.handle_daemon_command = AsyncMock(
                return_value="status-text",
            )
            result = await spec.handler(ctx, "status --json")

        assert result == "status-text"
        call = mixin.return_value.handle_daemon_command.await_args
        assert call.args[0] == "/daemon status --json"

    async def test_unknown_subcommand_is_rejected_without_dispatch(self):
        spec = bc._make_daemon_compound_adapter()
        ctx, _ = _session_ctx()
        with patch(
            "qwenpaw.runtime.commands.daemon.DaemonCommandHandlerMixin",
        ) as mixin:
            mixin.return_value.handle_daemon_command = AsyncMock()
            msg = await spec.handler(ctx, "not-a-real-subcommand")

        mixin.return_value.handle_daemon_command.assert_not_awaited()
        assert _msg_text(msg) == "Unknown daemon command."
        assert msg.role == "assistant"

    async def test_bare_daemon_defaults_to_status(self):
        spec = bc._make_daemon_compound_adapter()
        ctx, _ = _session_ctx()
        with (
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
            patch(
                "qwenpaw.runtime.commands.daemon.DaemonCommandHandlerMixin",
            ) as mixin,
        ):
            mixin.return_value.handle_daemon_command = AsyncMock(
                return_value="ok",
            )
            await spec.handler(ctx, "")

        assert (
            mixin.return_value.handle_daemon_command.await_args.args[0]
            == "/daemon"
        )


# ---------------------------------------------------------------------------
# _make_control_adapter
# ---------------------------------------------------------------------------


def _control_handler(**overrides: Any) -> SimpleNamespace:
    handler = SimpleNamespace(
        handle=AsyncMock(return_value="handler text"),
        description="control help",
    )
    for name, value in overrides.items():
        setattr(handler, name, value)
    return handler


class TestControlAdapter:
    def test_spec_shape(self):
        spec = bc._make_control_adapter(
            _control_handler(),
            "stop",
            help_text="control help",
        )
        assert spec.name == "stop"
        assert spec.category == "control"
        assert spec.help_text == "control help"

    async def test_missing_workspace_reports_error(self):
        spec = bc._make_control_adapter(_control_handler(), "stop")
        handler = spec.handler
        msg = await handler(
            SimpleNamespace(workspace=None, request=None),
            "",
        )
        assert "Control command unavailable" in _msg_text(msg)

    async def test_builds_control_context_and_returns_handler_text(self):
        handler = _control_handler()
        spec = bc._make_control_adapter(handler, "stop")
        channel = MagicMock(name="channel")
        manager = SimpleNamespace(
            get_channel=AsyncMock(return_value=channel),
        )
        request = SimpleNamespace(channel="discord", user_id="user-9")
        ctx = SimpleNamespace(
            workspace=SimpleNamespace(channel_manager=manager),
            request=request,
            session_id="session-2",
            agent_id="agent-2",
        )

        msg = await spec.handler(ctx, "session=123")

        assert _msg_text(msg) == "handler text"
        manager.get_channel.assert_awaited_once_with("discord")
        ctrl_ctx = handler.handle.await_args.args[0]
        assert ctrl_ctx.session_id == "session-2"
        assert ctrl_ctx.user_id == "user-9"
        assert ctrl_ctx.agent_id == "agent-2"
        assert ctrl_ctx.channel is channel
        assert ctrl_ctx.payload is request
        assert ctrl_ctx.args["_raw_args"] == "session=123"
        assert ctrl_ctx.args["session"] == "123"

    async def test_empty_args_build_a_bare_query(self):
        handler = _control_handler()
        spec = bc._make_control_adapter(handler, "model")
        ctx = SimpleNamespace(
            workspace=SimpleNamespace(channel_manager=None),
            request=None,
            session_id="s",
            agent_id="a",
        )
        await spec.handler(ctx, "")
        assert handler.handle.await_args.args[0].args == {"_raw_args": ""}

    async def test_channel_lookup_failure_is_tolerated(self):
        handler = _control_handler()
        spec = bc._make_control_adapter(handler, "skills")
        manager = SimpleNamespace(
            get_channel=AsyncMock(side_effect=RuntimeError("no channel")),
        )
        ctx = SimpleNamespace(
            workspace=SimpleNamespace(channel_manager=manager),
            request=None,
            session_id="s",
            agent_id="a",
        )
        msg = await spec.handler(ctx, "list")
        assert _msg_text(msg) == "handler text"
        ctrl_ctx = handler.handle.await_args.args[0]
        assert ctrl_ctx.channel is None
        assert ctrl_ctx.user_id == ""

    async def test_missing_channel_falls_back_to_console(self):
        handler = _control_handler()
        spec = bc._make_control_adapter(handler, "stop")
        manager = SimpleNamespace(get_channel=AsyncMock(return_value=None))
        ctx = SimpleNamespace(
            workspace=SimpleNamespace(channel_manager=manager),
            request=SimpleNamespace(channel=None, user_id="u"),
            session_id="s",
            agent_id="a",
        )
        await spec.handler(ctx, "")
        manager.get_channel.assert_awaited_once_with("console")

    async def test_handler_failure_is_rendered_as_command_failed(self):
        handler = _control_handler(
            handle=AsyncMock(side_effect=RuntimeError("blew up")),
        )
        spec = bc._make_control_adapter(handler, "pause")
        ctx = SimpleNamespace(
            workspace=SimpleNamespace(channel_manager=None),
            request=None,
            session_id="s",
            agent_id="a",
        )
        msg = await spec.handler(ctx, "")
        text = _msg_text(msg)
        assert text.startswith("**Command Failed**")
        assert "blew up" in text


class TestCollectControlSpecs:
    async def test_duplicate_command_names_are_deduplicated(self):
        handler = _control_handler()
        registry = {"/stop": handler, "stop": handler}
        with patch.object(
            bc,
            "_COMMAND_REGISTRY",
            registry,
            create=True,
        ):
            with patch(
                "qwenpaw.runtime.commands.control._COMMAND_REGISTRY",
                registry,
            ):
                specs = bc._collect_control_specs()

        assert [s.name for s in specs] == ["stop"]
        assert specs[0].help_text == "control help"

    def test_real_registry_has_no_leading_slash(self):
        specs = bc._collect_control_specs()
        assert specs
        assert all(not s.name.startswith("/") for s in specs)
        assert all(s.category == "control" for s in specs)


# ---------------------------------------------------------------------------
# _load_agent_state / _save_agent_state
# ---------------------------------------------------------------------------


class TestLoadAgentState:
    async def test_no_workspace_returns_empty(self):
        state, payload = await bc._load_agent_state(
            SimpleNamespace(workspace=None),
        )
        assert state is None
        assert payload == {}

    async def test_no_session_returns_empty(self):
        state, payload = await bc._load_agent_state(
            SimpleNamespace(workspace=SimpleNamespace(session=None)),
        )
        assert state is None
        assert payload == {}

    async def test_empty_payload_yields_a_fresh_state(self):
        ctx, saved = _session_ctx({})
        state, payload = await bc._load_agent_state(ctx)
        assert isinstance(state, AgentState)
        assert payload == {}
        assert saved["load"] == {
            "session_id": "session-1",
            "user_id": "user-1",
            "channel": "console",
        }

    async def test_modern_state_is_restored_with_its_payload(self):
        payload = _state_payload(scroll={"evicted": 3})
        ctx, _ = _session_ctx(payload)
        state, returned = await bc._load_agent_state(ctx)
        assert isinstance(state, AgentState)
        assert returned["scroll"] == {"evicted": 3}

    async def test_legacy_memory_payload_is_parsed(self):
        ctx, _ = _session_ctx({"memory": {"messages": [], "summary": "old"}})
        with patch(
            "qwenpaw.app.chats.utils.parse_legacy_memory_state",
            return_value=(["m1"], "legacy summary"),
        ) as parse:
            state, payload = await bc._load_agent_state(ctx)
        parse.assert_called_once()
        assert state.summary == "legacy summary"
        assert state.context == ["m1"]
        assert payload == {"memory": {"messages": [], "summary": "old"}}

    async def test_legacy_memory_of_wrong_type_is_ignored(self):
        ctx, _ = _session_ctx({"memory": "not-a-dict"})
        state, payload = await bc._load_agent_state(ctx)
        assert isinstance(state, AgentState)
        assert payload == {"memory": "not-a-dict"}

    async def test_unrelated_payload_keys_are_preserved(self):
        ctx, _ = _session_ctx({"mode_state": {"mode": "auto"}})
        state, payload = await bc._load_agent_state(ctx)
        assert isinstance(state, AgentState)
        assert payload == {"mode_state": {"mode": "auto"}}

    async def test_missing_request_falls_back_to_session_id(self):
        ctx, saved = _session_ctx({}, workspace_dir="/tmp/ws")
        ctx.request = None
        await bc._load_agent_state(ctx)
        assert saved["load"]["user_id"] == "session-1"
        assert saved["load"]["channel"] == ""

    async def test_blank_request_fields_fall_back_to_session_id(self):
        ctx, saved = _session_ctx({})
        ctx.request = SimpleNamespace(user_id="", channel="")
        await bc._load_agent_state(ctx)
        assert saved["load"]["user_id"] == "session-1"

    async def test_proxy_protocol_is_what_the_session_receives(self):
        ctx, _saved = _session_ctx({})
        seen = {}

        async def _load(**kwargs):
            seen["agent"] = kwargs["agent"]

        ctx.workspace.session.load_session_state = AsyncMock(side_effect=_load)
        await bc._load_agent_state(ctx)
        assert isinstance(seen["agent"], StateProxy)
        assert seen["agent"].state_dict() == seen["agent"].data


class TestSaveAgentState:
    async def test_writes_state_mode_and_scroll(self):
        ctx, saved = _session_ctx({})
        await bc._save_agent_state(
            ctx,
            AgentState(),
            scroll_block={"evicted": 1},
        )
        assert sorted(saved["data"]) == ["mode_state", "scroll", "state"]
        assert saved["data"]["scroll"] == {"evicted": 1}
        assert saved["save"] == {
            "session_id": "session-1",
            "user_id": "user-1",
            "channel": "console",
        }

    async def test_no_scroll_block_is_written_as_none(self):
        ctx, saved = _session_ctx({})
        await bc._save_agent_state(ctx, AgentState())
        assert "scroll" not in saved["data"]

    async def test_mode_state_comes_from_the_context(self):
        ctx, saved = _session_ctx({})
        ctx.mode_state = {"mode": "plan"}
        await bc._save_agent_state(ctx, AgentState())
        assert saved["data"]["mode_state"] == {"mode": "plan"}

    async def test_missing_mode_state_attribute_defaults_to_empty(self):
        ctx, saved = _session_ctx({})
        await bc._save_agent_state(ctx, AgentState())
        assert saved["data"]["mode_state"] == {}

    async def test_serialised_state_round_trips(self):
        ctx, saved = _session_ctx({})
        state = AgentState()
        state.summary = "kept"
        await bc._save_agent_state(ctx, state)
        restored = AgentState.model_validate(saved["data"]["state"])
        assert restored.summary == "kept"

    async def test_no_workspace_is_a_noop(self):
        ctx, saved = _session_ctx({})
        # Sanity: the recorder is the one sibling tests prove gets written.
        await bc._save_agent_state(ctx, AgentState())
        assert saved

        ctx.workspace = None
        saved.clear()
        assert await bc._save_agent_state(ctx, AgentState()) is None
        assert saved == {}

    async def test_no_session_is_a_noop(self):
        ctx, saved = _session_ctx({})
        await bc._save_agent_state(ctx, AgentState())
        assert saved

        ctx.workspace.session = None
        saved.clear()
        ctx.request = None
        assert await bc._save_agent_state(ctx, AgentState()) is None
        assert saved == {}

    async def test_missing_request_falls_back_to_session_id(self):
        ctx, saved = _session_ctx({})
        ctx.request = None
        await bc._save_agent_state(ctx, AgentState())
        assert saved["save"]["user_id"] == "session-1"
        assert saved["save"]["channel"] == ""


# ---------------------------------------------------------------------------
# _make_conversation_adapter
# ---------------------------------------------------------------------------


def _state_with_context() -> dict:
    """Serialise an AgentState that still holds one turn in its window."""
    state = AgentState()
    state.context.append(
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text="hello")],
        ),
    )
    return state.model_dump(mode="json")


def _patch_command_handler(**kwargs: Any):
    """Patch CommandHandler with a double returning *kwargs* per call."""
    instance = MagicMock(name="CommandHandler")
    instance.handle_command = AsyncMock(
        return_value=kwargs.get("result", "cmd-result"),
    )
    instance.updated_scroll_state = kwargs.get("updated_scroll")
    double = MagicMock(return_value=instance)
    return (
        patch(
            "qwenpaw.agents.command_handler.CommandHandler",
            double,
        ),
        double,
        instance,
    )


class TestConversationAdapter:
    def test_spec_shape(self):
        spec = bc._make_conversation_adapter("compact", help_text="h")
        assert spec.name == "compact"
        assert spec.category == "conversation"
        assert spec.help_text == "h"

    async def test_plan_with_arguments_falls_through_to_the_model(self):
        spec = bc._make_conversation_adapter("plan")
        ctx, saved = _session_ctx(_state_payload())
        assert await spec.handler(ctx, "build a robot") is None
        assert "data" not in saved

    async def test_plan_without_arguments_is_handled(self):
        spec = bc._make_conversation_adapter("plan")
        ctx, _ = _session_ctx(_state_payload())
        patcher, _double, instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
        ):
            result = await spec.handler(ctx, "   ")
        assert result == "cmd-result"
        assert instance.handle_command.await_args.args[0] == "/plan"

    async def test_missing_workspace_is_ignored(self):
        spec = bc._make_conversation_adapter("history")
        assert await spec.handler(SimpleNamespace(workspace=None), "") is None

    async def test_missing_session_is_ignored(self):
        spec = bc._make_conversation_adapter("history")
        ctx = SimpleNamespace(workspace=SimpleNamespace(session=None))
        assert await spec.handler(ctx, "") is None

    async def test_arguments_are_appended_to_the_query(self):
        spec = bc._make_conversation_adapter("compact")
        ctx, _ = _session_ctx(_state_payload())
        patcher, _double, instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
        ):
            await spec.handler(ctx, "--keep 5")
        assert instance.handle_command.await_args.args[0] == (
            "/compact --keep 5"
        )

    async def test_command_handler_receives_state_and_session_wiring(self):
        spec = bc._make_conversation_adapter("history")
        ctx, _ = _session_ctx(
            _state_payload(scroll={"evicted": 2}, mode_state={"mode": "auto"}),
        )
        patcher, double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(name="Named"),
            ),
        ):
            await spec.handler(ctx, "")
        kwargs = double.call_args.kwargs
        assert kwargs["agent_name"] == "Named"
        assert kwargs["agent_id"] == "agent-1"
        assert kwargs["session_id"] == "session-1"
        assert kwargs["memory_manager"] == "mm"
        assert kwargs["workspace_dir"] == "/tmp/ws"
        assert kwargs["scroll_state"] == {"evicted": 2}
        assert kwargs["prompt_context"] is ctx
        assert isinstance(kwargs["state"], AgentState)
        assert callable(kwargs["reme_action_authorizer"])
        # A persisted mode_state is replayed onto the ctx for the handler.
        assert ctx.mode_state == {"mode": "auto"}

    async def test_non_dict_mode_state_is_not_replayed(self):
        spec = bc._make_conversation_adapter("history")
        ctx, _ = _session_ctx(_state_payload(mode_state="broken"))
        patcher, _double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
        ):
            await spec.handler(ctx, "")
        assert not hasattr(ctx, "mode_state")

    async def test_refreshed_scroll_block_is_persisted(self):
        spec = bc._make_conversation_adapter("compact")
        ctx, saved = _session_ctx(_state_payload(scroll={"evicted": 1}))
        patcher, _double, _instance = _patch_command_handler(
            updated_scroll={"evicted": 7},
        )
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
        ):
            await spec.handler(ctx, "")
        assert saved["data"]["scroll"] == {"evicted": 7}

    async def test_untouched_scroll_block_is_preserved(self):
        spec = bc._make_conversation_adapter("history")
        ctx, saved = _session_ctx(
            _state_payload(
                scroll={"evicted": 4},
                state=_state_with_context(),
            ),
        )
        patcher, _double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
        ):
            await spec.handler(ctx, "")
        assert saved["data"]["scroll"] == {"evicted": 4}

    async def test_wiped_context_drops_a_stale_scroll_block(self):
        """The pair of this test and the preserve test pins the branch.

        Both start from a payload holding ``scroll``; only this one has an
        empty context window, so a stale eviction index must not resurface
        turns that ``/clear`` just wiped.
        """
        spec = bc._make_conversation_adapter("clear")
        ctx, saved = _session_ctx(_state_payload(scroll={"evicted": 4}))
        patcher, _double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
        ):
            await spec.handler(ctx, "")
        assert "scroll" not in saved["data"]

    async def test_config_failure_still_runs_the_command(self):
        spec = bc._make_conversation_adapter("history")
        ctx, _ = _session_ctx(_state_payload())
        patcher, double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                side_effect=RuntimeError("config gone"),
            ),
        ):
            result = await spec.handler(ctx, "")
        assert result == "cmd-result"
        assert double.call_args.kwargs["agent_name"] == "QwenPaw"
        assert double.call_args.kwargs["offloader"] is None

    async def test_native_strategy_builds_an_offloader(self):
        spec = bc._make_conversation_adapter("dump_history")
        ctx, _ = _session_ctx(_state_payload(), workspace_dir="/tmp/wsdir")
        patcher, double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(lcc=_lcc(strategy="native")),
            ),
            patch(
                "qwenpaw.agents.offloader.QwenPawOffloader",
            ) as offloader,
        ):
            await spec.handler(ctx, "")
        assert double.call_args.kwargs["offloader"] is offloader.return_value
        assert offloader.call_args.kwargs == {
            "dialog_path": "/tmp/wsdir/dialog.db",
            "tool_results_dir": "/tmp/wsdir/tool_cache",
        }

    async def test_scroll_strategy_skips_the_offloader_by_default(self):
        spec = bc._make_conversation_adapter("history")
        ctx, _ = _session_ctx(_state_payload())
        patcher, double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(lcc=_lcc(strategy="scroll")),
            ),
            patch(
                "qwenpaw.agents.offloader.QwenPawOffloader",
            ) as offloader,
        ):
            await spec.handler(ctx, "")
        assert double.call_args.kwargs["offloader"] is None
        offloader.assert_not_called()

    async def test_scroll_strategy_opted_in_builds_an_offloader(self):
        spec = bc._make_conversation_adapter("history")
        ctx, _ = _session_ctx(_state_payload())
        patcher, double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(
                    lcc=_lcc(strategy="scroll", offload_dialog=True),
                ),
            ),
            patch(
                "qwenpaw.agents.offloader.QwenPawOffloader",
            ) as offloader,
        ):
            await spec.handler(ctx, "")
        assert double.call_args.kwargs["offloader"] is offloader.return_value

    async def test_empty_workspace_dir_skips_the_offloader(self):
        spec = bc._make_conversation_adapter("history")
        ctx, _ = _session_ctx(_state_payload(), workspace_dir="")
        patcher, double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
            patch(
                "qwenpaw.agents.offloader.QwenPawOffloader",
            ) as offloader,
        ):
            await spec.handler(ctx, "")
        assert double.call_args.kwargs["workspace_dir"] is None
        assert double.call_args.kwargs["offloader"] is None
        offloader.assert_not_called()

    async def test_offloader_failure_does_not_break_the_command(self):
        spec = bc._make_conversation_adapter("history")
        ctx, _ = _session_ctx(_state_payload())
        patcher, double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
            patch(
                "qwenpaw.agents.offloader.QwenPawOffloader",
                side_effect=OSError("disk full"),
            ),
        ):
            result = await spec.handler(ctx, "")
        assert result == "cmd-result"
        assert double.call_args.kwargs["offloader"] is None

    async def test_reme_authorizer_delegates_to_the_approval_helper(self):
        spec = bc._make_conversation_adapter("reme")
        ctx, _ = _session_ctx(_state_payload())
        patcher, double, _instance = _patch_command_handler()
        with (
            patcher,
            patch(
                "qwenpaw.config.config.load_agent_config",
                return_value=_cfg(),
            ),
        ):
            await spec.handler(ctx, "")
        authorizer = double.call_args.kwargs["reme_action_authorizer"]
        with patch.object(
            bc,
            "_request_reme_action_approval",
            AsyncMock(return_value=True),
        ) as approval:
            assert await authorizer("daily_paper", {"topics": "x"}) is True
        assert approval.await_args.args == (
            ctx,
            "daily_paper",
            {"topics": "x"},
        )


class TestConversationSpecCollection:
    def test_every_conversation_command_is_collected(self):
        specs = bc._collect_conversation_specs()
        assert {s.name for s in specs} == set(bc._CONVERSATION_COMMANDS)
        assert [s.name for s in specs] == sorted(bc._CONVERSATION_COMMANDS)
        assert all(s.category == "conversation" for s in specs)

    def test_help_text_comes_from_the_curated_descriptions(self):
        from qwenpaw.agents.command_handler import (
            SYSTEM_COMMAND_DESCRIPTIONS,
        )

        specs = {s.name: s for s in bc._collect_conversation_specs()}
        for name, spec in specs.items():
            assert spec.help_text == SYSTEM_COMMAND_DESCRIPTIONS.get(name, "")

    def test_builtin_specs_cover_all_three_categories(self):
        specs = bc.collect_builtin_command_specs()
        categories = {s.category for s in specs}
        assert categories == {"daemon", "control", "conversation"}
        assert len({s.name for s in specs}) == len(specs)


# ---------------------------------------------------------------------------
# _request_reme_action_approval
# ---------------------------------------------------------------------------


def _approval_service(decision: Any = ApprovalDecision.APPROVED):
    return SimpleNamespace(
        create_pending_summary=AsyncMock(
            return_value=SimpleNamespace(request_id="approval-1"),
        ),
        wait_for_approval=AsyncMock(return_value=decision),
    )


class TestRemeApprovalContext:
    async def test_oversized_arguments_are_truncated(self):
        service = _approval_service()
        ctx, _ = _session_ctx({})
        big = {"blob": "x" * 5000}
        with patch(
            "qwenpaw.app.approvals.get_approval_service",
            return_value=service,
        ):
            assert await bc._request_reme_action_approval(ctx, "act", big)
        summary = service.create_pending_summary.await_args.kwargs["summary"]
        arguments = summary.result_summary.split("Arguments:")[1]
        assert "…" in arguments
        assert len(arguments) < 2100
        assert "x" * 2100 not in arguments

    async def test_backticks_are_escaped(self):
        service = _approval_service()
        ctx, _ = _session_ctx({})
        with patch(
            "qwenpaw.app.approvals.get_approval_service",
            return_value=service,
        ):
            await bc._request_reme_action_approval(
                ctx,
                "act",
                {"cmd": "run `rm`"},
            )
        summary = service.create_pending_summary.await_args.kwargs["summary"]
        assert "\\`rm\\`" in summary.result_summary

    async def test_non_console_channel_is_resolved(self):
        service = _approval_service()
        ctx, _ = _session_ctx({})
        channel = MagicMock(name="chan")
        manager = SimpleNamespace(
            get_channel=AsyncMock(return_value=channel),
        )
        ctx.workspace.channel_manager = manager
        ctx.request = SimpleNamespace(
            user_id="u",
            channel="discord",
            metadata=None,
        )
        with patch(
            "qwenpaw.app.approvals.get_approval_service",
            return_value=service,
        ):
            await bc._request_reme_action_approval(ctx, "act", {})
        manager.get_channel.assert_awaited_once_with("discord")
        kwargs = service.create_pending_summary.await_args.kwargs
        assert kwargs["extra"]["_channel_instance"] is channel
        assert kwargs["extra"]["channel_meta"] is None
        assert kwargs["channel"] == "discord"

    async def test_channel_resolution_failure_is_tolerated(self):
        service = _approval_service()
        ctx, _ = _session_ctx({})
        manager = SimpleNamespace(
            get_channel=AsyncMock(side_effect=RuntimeError("gone")),
        )
        ctx.workspace.channel_manager = manager
        ctx.request = SimpleNamespace(user_id="u", channel="discord")
        with patch(
            "qwenpaw.app.approvals.get_approval_service",
            return_value=service,
        ):
            approved = await bc._request_reme_action_approval(ctx, "a", {})
        assert approved is True
        kwargs = service.create_pending_summary.await_args.kwargs
        assert kwargs["extra"]["_channel_instance"] is None

    async def test_console_channel_is_never_resolved(self):
        service = _approval_service()
        ctx, _ = _session_ctx({})
        manager = SimpleNamespace(get_channel=AsyncMock())
        ctx.workspace.channel_manager = manager
        with patch(
            "qwenpaw.app.approvals.get_approval_service",
            return_value=service,
        ):
            await bc._request_reme_action_approval(ctx, "a", {})
        manager.get_channel.assert_not_awaited()

    async def test_channel_meta_falls_back_to_metadata(self):
        service = _approval_service()
        ctx, _ = _session_ctx({})
        ctx.request = SimpleNamespace(
            user_id="u",
            channel="console",
            metadata={"client": "web"},
        )
        with patch(
            "qwenpaw.app.approvals.get_approval_service",
            return_value=service,
        ):
            await bc._request_reme_action_approval(ctx, "a", {})
        kwargs = service.create_pending_summary.await_args.kwargs
        assert kwargs["summary"].source_type == "reme_action"
        assert kwargs["summary"].name == "reme:a"
        assert kwargs["extra"]["channel_meta"] == {"client": "web"}

    async def test_denied_decision_returns_false(self):
        service = _approval_service(ApprovalDecision.DENIED)
        ctx, _ = _session_ctx({})
        with patch(
            "qwenpaw.app.approvals.get_approval_service",
            return_value=service,
        ):
            assert (
                await bc._request_reme_action_approval(ctx, "a", {}) is False
            )

    async def test_missing_identity_fields_fall_back(self):
        service = _approval_service()
        ctx = SimpleNamespace(
            workspace=None,
            request=None,
            session_id="",
            agent_id="",
        )
        with patch(
            "qwenpaw.app.approvals.get_approval_service",
            return_value=service,
        ):
            await bc._request_reme_action_approval(ctx, "a", {})
        kwargs = service.create_pending_summary.await_args.kwargs
        assert kwargs["agent_id"] == "default"
        assert kwargs["user_id"] == ""
        assert kwargs["session_id"] == ""
