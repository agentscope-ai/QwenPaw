# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument,redefined-outer-name
"""Tests for ``AdvisorMode``: activation, the worker-model hook, the
``/advisor`` command, middleware construction and the advisor client."""
from __future__ import annotations

import json

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from agentscope.message import TextBlock

from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.modes.advisor import AdvisorMiddleware, AdvisorMode
from qwenpaw.modes.advisor import mode as mode_module
from qwenpaw.modes.advisor import models as models_module
from qwenpaw.modes.advisor.hooks import WorkerModelHook
from qwenpaw.modes.advisor.tools import CONSULT_TOOL_NAME
from qwenpaw.modes.base import find_active_explicit_mode
from qwenpaw.modes.advisor.models import (
    AdvisorClient,
    slot_label,
    slot_to_dict,
)
from qwenpaw.modes.advisor.trigger import TriggerConfig
from qwenpaw.runtime.phases import Phase


def _config(
    *,
    enabled=True,
    followup=True,
    main=("dash", "qwen3-max"),
    sub=("dash", "qwen3-8b"),
):
    cfg = AgentProfileConfig(id="agent-1", name="Agent")
    cfg.advisor_mode.enabled = enabled
    cfg.advisor_mode.followup_enabled = followup
    cfg.active_model = ModelSlotConfig(provider_id=main[0], model=main[1])
    cfg.subagent_model = (
        ModelSlotConfig(provider_id=sub[0], model=sub[1]) if sub else None
    )
    return cfg


def _picked() -> AdvisorMode:
    """A mode that was picked for the test conversation (``/advisor``)."""
    mode = AdvisorMode()
    mode.session_state("sess-1").override = True
    return mode


def _ctx(cfg=None, request=None, workspace_dir=None):
    return SimpleNamespace(
        agent_id="agent-1",
        session_id="sess-1",
        workspace_dir=workspace_dir,
        agent_config=cfg,
        request=request if request is not None else SimpleNamespace(),
        mode_state={},
    )


# ── activation ──────────────────────────────────────────────────────────


def test_conversations_start_in_the_default_loop():
    """``enabled`` makes the mode available; a conversation is in Advisor
    Mode only after it was picked (``/advisor``)."""
    mode = AdvisorMode()
    assert mode.is_available(_config(enabled=True)) is True
    assert mode.is_available(_config(enabled=False)) is False
    assert mode.is_active(_ctx(_config(enabled=True))) is False
    mode.session_state("sess-1").override = True
    assert mode.is_active(_ctx(_config(enabled=True))) is True
    # Switching the agent off wins over a conversation that picked it.
    assert mode.is_active(_ctx(_config(enabled=False))) is False


def test_inactive_when_config_unavailable(monkeypatch):
    def boom(_agent_id):
        raise RuntimeError("no config")

    monkeypatch.setattr("qwenpaw.config.config.load_agent_config", boom)
    mode = AdvisorMode()
    mode.session_state("sess-1").override = True
    assert mode.is_active(_ctx(None)) is False


def test_is_active_reads_no_config_until_the_conversation_picked_it(
    monkeypatch,
):
    """``is_active`` runs on every gated hook; the cheap session check
    comes first so unrelated conversations never load agent config."""
    loads = []
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda agent_id: loads.append(agent_id) or _config(enabled=True),
    )
    mode = AdvisorMode()
    assert mode.is_active(_ctx(None)) is False
    assert not loads
    mode.session_state("sess-1").override = True
    assert mode.is_active(_ctx(None)) is True
    assert loads == ["agent-1"]


def test_loads_persisted_config_when_ctx_has_none(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: _config(enabled=True),
    )
    mode = AdvisorMode()
    mode.session_state("sess-1").override = True
    assert mode.is_active(_ctx(None)) is True


# ── worker model hook ──────────────────────────────────────────────────


def test_hook_is_registered_pre_build():
    mode = AdvisorMode()
    hooks = mode.hooks()
    assert len(hooks) == 1
    hook = hooks[0]
    assert isinstance(hook, WorkerModelHook)
    assert hook.phase == Phase.PRE_AGENT_BUILD
    assert hook.owner_mode is mode


async def test_hook_routes_agent_to_subagent_model():
    mode = _picked()
    ctx = _ctx(_config())
    await mode.hooks()[0].run(ctx)
    assert ctx.request.model_slot_override == {
        "provider_id": "dash",
        "model": "qwen3-8b",
    }


async def test_hook_prefers_the_worker_model_override():
    cfg = _config()
    cfg.advisor_mode.worker_model = ModelSlotConfig(
        provider_id="small",
        model="s-mini",
    )
    ctx = _ctx(cfg)
    await _picked().hooks()[0].run(ctx)
    assert ctx.request.model_slot_override == {
        "provider_id": "small",
        "model": "s-mini",
    }


async def test_hook_worker_override_works_without_a_subagent_model():
    cfg = _config(sub=None)
    cfg.advisor_mode.worker_model = ModelSlotConfig(
        provider_id="small",
        model="s-mini",
    )
    ctx = _ctx(cfg)
    await _picked().hooks()[0].run(ctx)
    assert ctx.request.model_slot_override == {
        "provider_id": "small",
        "model": "s-mini",
    }


async def test_hook_keeps_main_model_without_subagent_model():
    ctx = _ctx(_config(sub=None))
    await _picked().hooks()[0].run(ctx)
    assert not hasattr(ctx.request, "model_slot_override")


async def test_hook_respects_explicit_request_override():
    ctx = _ctx(_config(), request=SimpleNamespace(model_slot_override="p:m"))
    await _picked().hooks()[0].run(ctx)
    assert ctx.request.model_slot_override == "p:m"


async def test_hook_respects_payload_override():
    request = SimpleNamespace(request_context={"model_slot_override": "p:m"})
    ctx = _ctx(_config(), request=request)
    await _picked().hooks()[0].run(ctx)
    assert not hasattr(ctx.request, "model_slot_override")


async def test_hook_is_a_no_op_when_mode_disabled():
    ctx = _ctx(_config(enabled=False))
    await _picked().hooks()[0].run(ctx)  # picked, but switched off
    assert not hasattr(ctx.request, "model_slot_override")


# ── middlewares ─────────────────────────────────────────────────────────


def test_middlewares_only_when_enabled():
    mode = _picked()
    cfg = _config(enabled=True, followup=False)
    mws = mode.middlewares(_ctx(cfg), cfg)
    assert len(mws) == 1
    mw = mws[0]
    assert isinstance(mw, AdvisorMiddleware)
    assert mw.followup_enabled is False
    assert mw._advisor.label == "dash:qwen3-max"
    assert mw._session_id == "sess-1"

    off = _config(enabled=False)
    assert not mode.middlewares(_ctx(off), off)


def test_middleware_env_root_prefers_project_dir(tmp_path):
    cfg = _config()
    cfg.project_dir = str(tmp_path)
    mw = AdvisorMode().build_middleware(_ctx(cfg, workspace_dir="/ws"), cfg)
    assert mw._env_context_root == str(tmp_path)
    cfg.project_dir = None
    mw = AdvisorMode().build_middleware(_ctx(cfg, workspace_dir="/ws"), cfg)
    assert mw._env_context_root == "/ws"


# ── /advisor command ────────────────────────────────────────────────────


def _text(msg):
    return "".join(
        block.text for block in msg.content if isinstance(block, TextBlock)
    )


def test_command_is_registered():
    specs = AdvisorMode().commands()
    assert [spec.name for spec in specs] == ["advisor"]
    assert specs[0].category == "builtin"


async def test_command_status_reports_models(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: _config(enabled=True),
    )
    mode = AdvisorMode()
    text = _text(await mode._command_handler(_ctx(), "status"))
    assert "Advisor Mode: off (not selected for this conversation" in text
    mode.session_state("sess-1").override = True
    reply = await mode._command_handler(_ctx(), "status")
    text = _text(reply)
    assert reply.role == "system"
    assert "Advisor Mode: on (this conversation)" in text
    assert "dash:qwen3-max" in text and "dash:qwen3-8b" in text


async def test_command_status_without_subagent_model(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: _config(enabled=False, sub=None),
    )
    text = _text(await AdvisorMode()._command_handler(_ctx(), ""))
    assert "Advisor Mode: off (switched off for this agent" in text
    assert "no sub-agent model configured" in text


async def test_command_refuses_to_start_when_switched_off(monkeypatch):
    """With the agent switch off, ``/advisor on`` and ``/advisor <task>``
    explain where to turn it on instead of starting the mode."""
    from agentscope.message import UserMsg

    cfg = _config(enabled=False)
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: cfg,
    )
    mode = AdvisorMode()
    ctx = _ctx(cfg)
    ctx.input_msgs = [UserMsg(name="user", content="/advisor build it")]
    for args in ("on", "build it"):
        reply = await mode._command_handler(ctx, args)
        assert "switched off for this agent" in _text(reply)
    assert mode.is_active(ctx) is False
    assert mode._override("sess-1") is None
    assert ctx.input_msgs[-1].content[0].text == "/advisor build it"
    # ``off`` always works, so a stale override can be cleared.
    assert "disabled for this conversation" in _text(
        await mode._command_handler(ctx, "off"),
    )


async def test_command_refuses_while_another_mode_is_active(monkeypatch):
    """Like ``/goal``, ``/advisor`` does not start on top of another
    explicit mode; Advisor itself being active is not a conflict."""
    cfg = _config()
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: cfg,
    )
    mode = AdvisorMode()
    goal = SimpleNamespace(name="goal", is_active=lambda _ctx: True)
    ctx = _ctx(cfg)
    ctx.workspace = SimpleNamespace(plugins=SimpleNamespace(modes=[goal]))
    for args in ("on", "build it"):
        reply = await mode._command_handler(ctx, args)
        assert _text(reply) == (
            "End the active goal mode before starting /advisor."
        )
    assert mode._override("sess-1") is None

    ctx.workspace.plugins.modes = [mode]
    mode.session_state("sess-1").override = True
    assert "enabled for this conversation" in _text(
        await mode._command_handler(ctx, "on"),
    )


@pytest.mark.parametrize("arg,expected", [("on", True), ("OFF", False)])
async def test_command_on_off_switches_this_conversation(
    monkeypatch,
    arg,
    expected,
):
    """/advisor on|off switches the session only; agent.json is never
    written."""
    stored = _config(enabled=True)
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: stored,
    )
    mode = AdvisorMode()
    ctx = _ctx(stored)
    reply = await mode._command_handler(ctx, arg)
    assert stored.advisor_mode.enabled is True, "config untouched"
    assert mode.is_active(ctx) is expected
    assert mode.session_state("sess-1").override is expected
    text = _text(reply)
    assert ("enabled" if expected else "disabled") in text
    assert "this conversation" in text


async def test_command_with_a_task_starts_the_mode_and_runs_it(
    monkeypatch,
):
    """What the composer sends when Advisor is picked from its menu:
    ``/advisor <task>``. The mode switches on for the session and the
    agent sees the bare task."""
    from agentscope.message import UserMsg

    cfg = _config(enabled=True)
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: cfg,
    )
    mode = AdvisorMode()
    ctx = _ctx(cfg)
    ctx.input_msgs = [UserMsg(name="user", content="/advisor build the CLI")]
    reply = await mode._command_handler(ctx, "build the CLI")
    assert reply is None, "the agent must run"
    assert ctx.input_msgs[-1].content[0].text == "build the CLI"
    assert mode.is_active(ctx) is True
    # Later messages of the conversation stay in Advisor Mode ...
    assert mode.middlewares(ctx, cfg)
    # ... until the conversation is reset.
    await mode.on_conversation_reset(ctx)
    assert mode.is_active(ctx) is False


async def test_leaving_the_mode_switches_everything_off(monkeypatch):
    cfg = _config(enabled=True)
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: cfg,
    )
    mode = _picked()
    ctx = _ctx(cfg)
    assert mode.is_active(ctx) is True, "picked for the conversation"
    await mode._command_handler(ctx, "off")
    assert mode.is_active(ctx) is False
    assert not mode.middlewares(ctx, cfg)
    hook_ctx = _ctx(cfg)
    await mode.hooks()[0].run(hook_ctx)
    assert not hasattr(hook_ctx.request, "model_slot_override")


# ── advisor ─────────────────────────────────────────────────────────────


def test_slot_helpers():
    slot = ModelSlotConfig(provider_id="p", model="m")
    assert slot_to_dict(slot) == {"provider_id": "p", "model": "m"}
    assert slot_to_dict({"provider_id": "p", "model": "m"}) == {
        "provider_id": "p",
        "model": "m",
    }
    assert slot_to_dict(None) is None
    assert slot_to_dict(ModelSlotConfig()) is None
    assert slot_label(slot) == "p:m"
    assert slot_label(None) == "active model"


async def test_advisor_builds_model_once_and_sends_msgs(monkeypatch):
    created = []
    seen = {}

    class _Model:
        async def __call__(self, messages, **kwargs):
            seen["messages"] = messages
            return SimpleNamespace(content=[{"type": "text", "text": "PLAN"}])

    async def fake_factory(**kwargs):
        created.append(kwargs)
        return _Model(), None

    # Patched at the source module: ``advisor.py`` imports lazily.
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        fake_factory,
    )
    cfg = _config()
    advisor = AdvisorClient(
        agent_id="agent-1",
        agent_config=cfg,
        model_slot=cfg.active_model,
    )
    reply = await advisor.ask(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "plan please"},
        ],
    )
    assert reply == "PLAN"
    assert advisor.label == "dash:qwen3-max"
    assert created == [
        {
            "agent_id": "agent-1",
            "model_slot_override": cfg.active_model,
            "agent_config": cfg,
        },
    ]
    msgs = seen["messages"]
    assert [m.role for m in msgs] == ["system", "user"]
    assert msgs[1].content[0].text == "plan please"

    await advisor.ask([{"role": "user", "content": "again"}])
    assert len(created) == 1, "the model is built once and reused"


def test_mode_module_exports():
    assert mode_module.AdvisorMode is AdvisorMode
    assert models_module.AdvisorClient is AdvisorClient


def test_advisor_override_beats_the_main_model():
    from qwenpaw.modes.advisor.models import (
        resolve_worker_slot,
        resolve_advisor_slot,
    )

    cfg = _config()
    assert resolve_advisor_slot(cfg) == (cfg.active_model, "main_model")
    assert resolve_worker_slot(cfg) == (cfg.subagent_model, "subagent_model")
    cfg.advisor_mode.advisor_model = ModelSlotConfig(
        provider_id="big",
        model="b-max",
    )
    slot, source = resolve_advisor_slot(cfg)
    assert (slot.provider_id, slot.model, source) == (
        "big",
        "b-max",
        "override",
    )
    # An override with an empty model name does not count.
    cfg.advisor_mode.advisor_model = ModelSlotConfig(provider_id="big")
    assert resolve_advisor_slot(cfg)[1] == "main_model"
    assert resolve_worker_slot(_config(sub=None)) == (None, "main_model")
    mw = _picked().middlewares(_ctx(cfg), cfg)[0]
    assert mw._advisor.label == "dash:qwen3-max"


def test_effective_advisor_falls_back_to_global_active_model(monkeypatch):
    from qwenpaw.modes.advisor.models import effective_advisor_slot

    cfg = _config()
    assert effective_advisor_slot(cfg) is cfg.active_model

    cfg.active_model = None
    global_slot = ModelSlotConfig(provider_id="glob", model="g-max")
    manager = SimpleNamespace(get_active_model=lambda: global_slot)
    monkeypatch.setattr(
        "qwenpaw.providers.ProviderManager.get_instance",
        lambda: manager,
    )
    assert effective_advisor_slot(cfg) is global_slot
    mw = AdvisorMode().build_middleware(_ctx(cfg), cfg)
    assert mw._advisor.label == "glob:g-max"


# ── consult_advisor tool + session state ────────────────────────────────


class _Advisor:
    label = "stub"

    def __init__(self, reply="ADVICE"):
        self.reply = reply
        self.calls = []

    async def ask(self, messages, *, on_text=None):
        self.calls.append(messages)
        if on_text is not None:
            on_text(self.reply[: len(self.reply) // 2])
            on_text(self.reply)
        return self.reply


async def _tool_text(consult, question):
    """Run the streaming ``consult_advisor`` tool and join its chunks."""
    chunks = [chunk async for chunk in consult(question)]
    assert all(len(c.content) == 1 for c in chunks)
    return "".join(c.content[0].text for c in chunks), chunks


def test_tool_is_registered_and_mode_gated():
    mode = AdvisorMode()
    descs = mode.tools()
    assert [d.name for d in descs] == [CONSULT_TOOL_NAME]
    assert descs[0].requires_modes == ("advisor",)
    assert "advisor" in descs[0].description.lower()


def test_advisor_mode_counts_as_the_explicit_loop_mode():
    """Listed in the composer's mode menu like /goal; while active it
    counts as the explicit mode of the conversation."""
    mode = _picked()
    ctx = _ctx(_config(enabled=True))
    ctx.workspace = SimpleNamespace(plugins=SimpleNamespace(modes=[mode]))
    assert find_active_explicit_mode(ctx) == "advisor"
    off = _ctx(_config(enabled=False))
    off.workspace = ctx.workspace
    assert find_active_explicit_mode(off) is None


async def test_tool_consults_the_middleware_of_the_current_session(
    monkeypatch,
):
    mode = AdvisorMode()
    cfg = _config()
    mw = mode.build_middleware(_ctx(cfg), cfg)
    advisor = _Advisor("Switch to the other approach.")
    mw._advisor = advisor
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.mode.get_current_session_id",
        lambda: "sess-1",
    )
    consult = mode.tools()[0].func
    reply, chunks = await _tool_text(consult, "Keep going or switch?")
    assert reply == "Switch to the other approach."
    assert len(chunks) >= 2, "the answer streams in pieces"
    assert len({c.content[0].id for c in chunks}) == 1, "one text block"
    assert mw.consults_used == 1
    assert "Keep going or switch?" in advisor.calls[0][-1]["content"]


async def test_tool_streams_through_the_agentscope_toolkit(monkeypatch):
    """End to end through ``Toolkit.call_tool``: the chunks reach the
    caller as they are produced and accumulate into one text block."""
    from agentscope.message import ToolCallBlock
    from agentscope.state import AgentState
    from agentscope.tool import FunctionTool, Toolkit, ToolResponse

    mode = AdvisorMode()
    cfg = _config()
    mw = mode.build_middleware(_ctx(cfg), cfg)
    mw._advisor = _Advisor("First half, second half.")
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.mode.get_current_session_id",
        lambda: "sess-1",
    )
    toolkit = Toolkit(tools=[FunctionTool(mode.tools()[0].func)])
    call = ToolCallBlock(
        id="tc-1",
        name=CONSULT_TOOL_NAME,
        input=json.dumps({"question": "which half?"}),
    )
    seen = [item async for item in toolkit.call_tool(call, AgentState())]
    final = seen[-1]
    assert isinstance(final, ToolResponse)
    assert len(seen) >= 3, "at least two chunks before the response"
    assert len(final.content) == 1, "chunks merged into one text block"
    assert final.content[0].text == "First half, second half."


async def test_tool_without_session_or_when_disabled(monkeypatch):
    mode = AdvisorMode()
    consult = mode.tools()[0].func
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.mode.get_current_session_id",
        lambda: None,
    )
    assert "not available" in (await _tool_text(consult, "q"))[0]

    cfg = _config()
    cfg.advisor_mode.on_demand_enabled = False
    mw = mode.build_middleware(_ctx(cfg), cfg)
    mw._advisor = _Advisor()
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.mode.get_current_session_id",
        lambda: "sess-1",
    )
    assert "switched off" in (await _tool_text(consult, "q"))[0]
    assert mw.consults_used == 0


async def test_session_state_carries_history_and_budget_across_requests(
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.mode.get_current_session_id",
        lambda: "sess-1",
    )
    mode = AdvisorMode()
    cfg = _config()
    cfg.advisor_mode.max_consults = 2
    first = mode.build_middleware(_ctx(cfg), cfg)
    first._advisor = _Advisor("A1")
    await first.consult("q1")
    assert first.consults_left == 1

    second = mode.build_middleware(_ctx(cfg), cfg)  # next user turn
    assert second.advisor_history is first.advisor_history
    assert second.consults_used == 1 and second.consults_left == 1
    assert mode.current_middleware() is second


async def test_plan_is_written_once_per_conversation():
    """The second user turn of a conversation gets no new opening plan;
    it relies on the mid-run intervention and on-demand questions."""
    from agentscope.message import UserMsg

    async def next_handler(**kwargs):
        return kwargs

    def agent(text):
        return SimpleNamespace(
            name="a",
            state=SimpleNamespace(
                context=[UserMsg(name="user", content=text)],
            ),
        )

    mode = AdvisorMode()
    cfg = _config()
    first = mode.build_middleware(_ctx(cfg), cfg)
    first._advisor = _Advisor("THE PLAN")
    assert first.plan_injected is False
    await first.on_model_call(
        agent("task one"),
        {"messages": []},
        next_handler,
    )
    assert first.plan_injected is True
    assert len(first._advisor.calls) == 1

    second = mode.build_middleware(_ctx(cfg), cfg)  # next user turn
    second._advisor = _Advisor("ANOTHER PLAN")
    assert second.plan_injected is True, "carried over from the first turn"
    a2 = agent("task two")
    await second.on_model_call(a2, {"messages": []}, next_handler)
    assert second._advisor.calls == [], "no plan request on a later turn"
    assert len(a2.state.context) == 1, "nothing injected"
    assert second._task == "task two", "follow-ups still name the new task"

    await mode.on_conversation_reset(_ctx(cfg))
    fresh = mode.build_middleware(_ctx(cfg), cfg)
    assert fresh.plan_injected is False, "/new starts the advisor over"


def test_intervention_thresholds_come_from_the_config():
    cfg = _config()
    cfg.advisor_mode.intervention.consecutive_failures = 2
    cfg.advisor_mode.intervention.max_interventions = 1
    mw = AdvisorMode().build_middleware(_ctx(cfg), cfg)
    trigger = mw._trigger.config
    assert trigger.consecutive_failures == 2
    assert trigger.max_interventions == 1
    assert trigger.window_size == 10, "defaults for the rest"
    # Configs without the section (older agent.json) get the defaults.
    bare = _config()
    bare.advisor_mode = SimpleNamespace(
        enabled=True,
        plan_enabled=True,
        followup_enabled=True,
        on_demand_enabled=True,
        max_consults=3,
    )
    assert (
        AdvisorMode().build_middleware(_ctx(bare), bare)._trigger.config
        == TriggerConfig()
    )


def test_transcripts_stay_out_of_the_real_working_dir(isolated_advisor_dir):
    from qwenpaw.modes.advisor.middleware import default_log_dir

    assert default_log_dir("agent-1") == isolated_advisor_dir / "agent-1"
    mw = AdvisorMode().build_middleware(_ctx(_config()), _config())
    assert str(mw._log_dir).startswith(str(isolated_advisor_dir))


async def test_a_failed_plan_is_retried_on_the_next_turn():
    mode = AdvisorMode()
    cfg = _config()
    first = mode.build_middleware(_ctx(cfg), cfg)
    first._plan_injected = False  # the plan never landed (advisor down)
    second = mode.build_middleware(_ctx(cfg), cfg)
    assert second.plan_injected is False


async def test_conversation_reset_forgets_the_session():
    mode = AdvisorMode()
    cfg = _config()
    mw = mode.build_middleware(_ctx(cfg), cfg)
    mw.advisor_history.append({"role": "user", "content": "x"})
    await mode.on_conversation_reset(_ctx(cfg))
    fresh = mode.build_middleware(_ctx(cfg), cfg)
    assert fresh.advisor_history == []
    assert fresh.consults_used == 0


def test_session_registry_is_bounded():
    mode = AdvisorMode()
    for i in range(80):
        mode.session_state(f"s{i}")
    assert len(mode._sessions) == 64
    assert "s0" not in mode._sessions and "s79" in mode._sessions


async def test_status_mentions_the_consult_tool(monkeypatch):
    cfg = _config()
    cfg.advisor_mode.on_demand_enabled = False
    cfg.advisor_mode.max_consults = 5
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: cfg,
    )
    text = _text(await AdvisorMode()._command_handler(_ctx(), "status"))
    assert "consult_advisor tool: off (max 5 per conversation)" in text


def test_command_metadata_exposes_the_loop_mode_entry():
    spec = AdvisorMode().commands()[0]
    assert spec.metadata == {"loop_name": "Advisor"}
    assert "plans" in spec.help_text and "/advisor off" in spec.help_text


def test_consult_tool_is_registered_with_governance():
    """Unregistered tools are denied by policy; the mode registers its
    tool as internal so the agent can call it without approval."""
    from qwenpaw.governance.tool_registry import DEFAULT_REGISTRY
    from qwenpaw.modes.advisor.tools import CONSULT_POLICY_NAME

    AdvisorMode().setup(MagicMock())
    assert (
        DEFAULT_REGISTRY.get_mapped_policy_name(CONSULT_TOOL_NAME)
        == CONSULT_POLICY_NAME
    )
    assert DEFAULT_REGISTRY.get_type(CONSULT_POLICY_NAME) == "internal"
    assert DEFAULT_REGISTRY.get_owner(CONSULT_TOOL_NAME) == "builtin"
    AdvisorMode().setup(MagicMock())  # idempotent across workspaces


async def test_advisor_thinking_level_reaches_the_model_factory(monkeypatch):
    seen = {}

    async def fake_create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(), None

    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        fake_create,
    )
    cfg = _config()
    cfg.thinking_level = "high"
    cfg.advisor_mode.advisor_thinking = "off"
    mw = AdvisorMode().build_middleware(_ctx(cfg), cfg)
    await mw._advisor._get_model()
    assert seen["agent_config"].thinking_level == "off"
    assert cfg.thinking_level == "high", "the agent's own level is untouched"

    seen.clear()
    cfg.advisor_mode.advisor_thinking = "inherit"
    mw = AdvisorMode().build_middleware(_ctx(cfg), cfg)
    await mw._advisor._get_model()
    assert seen["agent_config"] is cfg
