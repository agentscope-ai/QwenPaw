# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument,redefined-outer-name
"""Tests for ``AdvisorMode``: activation, the student-model hook, the
``/advisor`` command, middleware construction and the teacher client."""
from __future__ import annotations

import json

from types import SimpleNamespace

import pytest
from agentscope.message import TextBlock

from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.modes.advisor import AdvisorMiddleware, AdvisorMode
from qwenpaw.modes.advisor import mode as mode_module
from qwenpaw.modes.advisor import teacher as teacher_module
from qwenpaw.modes.advisor.hooks import StudentModelHook
from qwenpaw.modes.advisor.tools import CONSULT_TOOL_NAME
from qwenpaw.modes.base import find_active_explicit_mode
from qwenpaw.modes.advisor.teacher import (
    AdvisorTeacher,
    slot_label,
    slot_to_dict,
)
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


def test_active_follows_config_flag():
    mode = AdvisorMode()
    assert mode.is_active(_ctx(_config(enabled=True))) is True
    assert mode.is_active(_ctx(_config(enabled=False))) is False


def test_inactive_when_config_unavailable(monkeypatch):
    def boom(_agent_id):
        raise RuntimeError("no config")

    monkeypatch.setattr("qwenpaw.config.config.load_agent_config", boom)
    assert AdvisorMode().is_active(_ctx(None)) is False


def test_loads_persisted_config_when_ctx_has_none(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: _config(enabled=True),
    )
    assert AdvisorMode().is_active(_ctx(None)) is True


# ── student model hook ──────────────────────────────────────────────────


def test_hook_is_registered_pre_build():
    mode = AdvisorMode()
    hooks = mode.hooks()
    assert len(hooks) == 1
    hook = hooks[0]
    assert isinstance(hook, StudentModelHook)
    assert hook.phase == Phase.PRE_AGENT_BUILD
    assert hook.owner_mode is mode


async def test_hook_routes_agent_to_subagent_model():
    mode = AdvisorMode()
    ctx = _ctx(_config())
    await mode.hooks()[0].run(ctx)
    assert ctx.request.model_slot_override == {
        "provider_id": "dash",
        "model": "qwen3-8b",
    }
    assert ctx.mode_state["advisor"]["student_model"] == {
        "provider_id": "dash",
        "model": "qwen3-8b",
    }
    assert ctx.mode_state["advisor"]["teacher_model"] == {
        "provider_id": "dash",
        "model": "qwen3-max",
    }


async def test_hook_prefers_the_student_model_override():
    cfg = _config()
    cfg.advisor_mode.student_model = ModelSlotConfig(
        provider_id="small",
        model="s-mini",
    )
    ctx = _ctx(cfg)
    await AdvisorMode().hooks()[0].run(ctx)
    assert ctx.request.model_slot_override == {
        "provider_id": "small",
        "model": "s-mini",
    }


async def test_hook_student_override_works_without_a_subagent_model():
    cfg = _config(sub=None)
    cfg.advisor_mode.student_model = ModelSlotConfig(
        provider_id="small",
        model="s-mini",
    )
    ctx = _ctx(cfg)
    await AdvisorMode().hooks()[0].run(ctx)
    assert ctx.mode_state["advisor"]["student_model"] == {
        "provider_id": "small",
        "model": "s-mini",
    }


async def test_hook_keeps_main_model_without_subagent_model():
    ctx = _ctx(_config(sub=None))
    await AdvisorMode().hooks()[0].run(ctx)
    assert not hasattr(ctx.request, "model_slot_override")
    assert ctx.mode_state["advisor"]["student_model"] is None


async def test_hook_respects_explicit_request_override():
    ctx = _ctx(_config(), request=SimpleNamespace(model_slot_override="p:m"))
    await AdvisorMode().hooks()[0].run(ctx)
    assert ctx.request.model_slot_override == "p:m"
    assert ctx.mode_state["advisor"]["student_model"] is None


async def test_hook_respects_payload_override():
    request = SimpleNamespace(request_context={"model_slot_override": "p:m"})
    ctx = _ctx(_config(), request=request)
    await AdvisorMode().hooks()[0].run(ctx)
    assert not hasattr(ctx.request, "model_slot_override")


async def test_hook_is_a_no_op_when_mode_disabled():
    ctx = _ctx(_config(enabled=False))
    await AdvisorMode().hooks()[0].run(ctx)
    assert not hasattr(ctx.request, "model_slot_override")
    assert "advisor" not in ctx.mode_state


# ── middlewares ─────────────────────────────────────────────────────────


def test_middlewares_only_when_enabled():
    mode = AdvisorMode()
    cfg = _config(enabled=True, followup=False)
    mws = mode.middlewares(_ctx(cfg), cfg)
    assert len(mws) == 1
    mw = mws[0]
    assert isinstance(mw, AdvisorMiddleware)
    assert mw.followup_enabled is False
    assert mw._teacher.label == "dash:qwen3-max"
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


def test_middleware_log_dir_is_per_agent(monkeypatch, tmp_path):
    monkeypatch.setattr("qwenpaw.constant.ADVISOR_DIR", tmp_path)
    cfg = _config()
    mw = AdvisorMode().build_middleware(_ctx(cfg), cfg)
    assert mw._log_dir == tmp_path / "agent-1"


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
    reply = await AdvisorMode()._command_handler(_ctx(), "status")
    text = _text(reply)
    assert reply.role == "system"
    assert "Advisor Mode: on" in text
    assert "dash:qwen3-max" in text and "dash:qwen3-8b" in text


async def test_command_status_without_subagent_model(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: _config(enabled=False, sub=None),
    )
    text = _text(await AdvisorMode()._command_handler(_ctx(), ""))
    assert "Advisor Mode: off" in text
    assert "no sub-agent model configured" in text


@pytest.mark.parametrize("arg,expected", [("on", True), ("OFF", False)])
async def test_command_on_off_switches_this_conversation(
    monkeypatch,
    arg,
    expected,
):
    """/advisor on|off overrides the agent default for the session only;
    agent.json is never written."""
    stored = _config(enabled=not expected)
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: stored,
    )
    mode = AdvisorMode()
    ctx = _ctx(stored)
    reply = await mode._command_handler(ctx, arg)
    assert stored.advisor_mode.enabled is (not expected), "default untouched"
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

    cfg = _config(enabled=False)
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


async def test_session_override_beats_agent_default(monkeypatch):
    cfg = _config(enabled=True)
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: cfg,
    )
    mode = AdvisorMode()
    ctx = _ctx(cfg)
    assert mode.is_active(ctx) is True, "agent default on"
    await mode._command_handler(ctx, "off")
    assert mode.is_active(ctx) is False, "session override wins"
    assert not mode.middlewares(ctx, cfg)
    hook_ctx = _ctx(cfg)
    await mode.hooks()[0].run(hook_ctx)
    assert not hasattr(hook_ctx.request, "model_slot_override")


# ── teacher ─────────────────────────────────────────────────────────────


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


async def test_teacher_builds_model_once_and_sends_msgs(monkeypatch):
    created = []
    seen = {}

    class _Model:
        async def __call__(self, messages, **kwargs):
            seen["messages"] = messages
            return SimpleNamespace(content=[{"type": "text", "text": "PLAN"}])

    async def fake_factory(**kwargs):
        created.append(kwargs)
        return _Model(), None

    # Patched at the source module: ``teacher.py`` imports lazily.
    monkeypatch.setattr(
        "qwenpaw.agents.model_factory.create_model_and_formatter_async",
        fake_factory,
    )
    cfg = _config()
    teacher = AdvisorTeacher(
        agent_id="agent-1",
        agent_config=cfg,
        model_slot=cfg.active_model,
    )
    reply = await teacher.ask(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "plan please"},
        ],
    )
    assert reply == "PLAN"
    assert teacher.label == "dash:qwen3-max"
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

    await teacher.ask([{"role": "user", "content": "again"}])
    assert len(created) == 1, "the model is built once and reused"


def test_mode_module_exports():
    assert mode_module.AdvisorMode is AdvisorMode
    assert teacher_module.AdvisorTeacher is AdvisorTeacher


def test_teacher_override_beats_the_main_model():
    from qwenpaw.modes.advisor.teacher import (
        resolve_student_slot,
        resolve_teacher_slot,
    )

    cfg = _config()
    assert resolve_teacher_slot(cfg) == (cfg.active_model, "main_model")
    assert resolve_student_slot(cfg) == (cfg.subagent_model, "subagent_model")
    cfg.advisor_mode.teacher_model = ModelSlotConfig(
        provider_id="big",
        model="b-max",
    )
    slot, source = resolve_teacher_slot(cfg)
    assert (slot.provider_id, slot.model, source) == (
        "big",
        "b-max",
        "override",
    )
    # An override with an empty model name does not count.
    cfg.advisor_mode.teacher_model = ModelSlotConfig(provider_id="big")
    assert resolve_teacher_slot(cfg)[1] == "main_model"
    assert resolve_student_slot(_config(sub=None)) == (None, "main_model")
    mw = AdvisorMode().middlewares(_ctx(cfg), cfg)[0]
    assert mw._teacher.label == "dash:qwen3-max"


def test_effective_teacher_falls_back_to_global_active_model(monkeypatch):
    from qwenpaw.modes.advisor.teacher import effective_teacher_slot

    cfg = _config()
    assert effective_teacher_slot(cfg) is cfg.active_model

    cfg.active_model = None
    global_slot = ModelSlotConfig(provider_id="glob", model="g-max")
    manager = SimpleNamespace(get_active_model=lambda: global_slot)
    monkeypatch.setattr(
        "qwenpaw.providers.ProviderManager.get_instance",
        lambda: manager,
    )
    assert effective_teacher_slot(cfg) is global_slot
    mw = AdvisorMode().build_middleware(_ctx(cfg), cfg)
    assert mw._teacher.label == "glob:g-max"


# ── consult_advisor tool + session state ────────────────────────────────


class _Teacher:
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


def test_advisor_mode_is_an_exclusive_loop_mode():
    """Listed in the composer's mode menu like /goal; while active it
    counts as the explicit mode of the conversation."""
    mode = AdvisorMode()
    assert mode.exclusive is True
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
    teacher = _Teacher("Switch to the other approach.")
    mw._teacher = teacher
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
    assert "Keep going or switch?" in teacher.calls[0][-1]["content"]


async def test_tool_streams_through_the_agentscope_toolkit(monkeypatch):
    """End to end through ``Toolkit.call_tool``: the chunks reach the
    caller as they are produced and accumulate into one text block."""
    from agentscope.message import ToolCallBlock
    from agentscope.state import AgentState
    from agentscope.tool import FunctionTool, Toolkit, ToolResponse

    mode = AdvisorMode()
    cfg = _config()
    mw = mode.build_middleware(_ctx(cfg), cfg)
    mw._teacher = _Teacher("First half, second half.")
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
    mw._teacher = _Teacher()
    monkeypatch.setattr(
        "qwenpaw.modes.advisor.mode.get_current_session_id",
        lambda: "sess-1",
    )
    assert "switched off" in (await _tool_text(consult, "q"))[0]
    assert mw.consults_used == 0


async def test_session_state_carries_history_and_budget_across_requests():
    mode = AdvisorMode()
    cfg = _config()
    cfg.advisor_mode.max_consults = 2
    first = mode.build_middleware(_ctx(cfg), cfg)
    first._teacher = _Teacher("A1")
    await first.consult("q1")
    assert first.consults_left == 1

    second = mode.build_middleware(_ctx(cfg), cfg)  # next user turn
    assert second.teacher_history is first.teacher_history
    assert second.consults_used == 1 and second.consults_left == 1
    assert mode.current_middleware is not None
    assert mode.session_state("sess-1").middleware is second


async def test_conversation_reset_forgets_the_session():
    mode = AdvisorMode()
    cfg = _config()
    mw = mode.build_middleware(_ctx(cfg), cfg)
    mw.teacher_history.append({"role": "user", "content": "x"})
    await mode.on_conversation_reset(_ctx(cfg))
    fresh = mode.build_middleware(_ctx(cfg), cfg)
    assert fresh.teacher_history == []
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
    assert spec.metadata["loop_name"] == "Advisor"
    assert spec.metadata["name_i18n"]["zh-CN"] == "顾问"
    assert "Advisor" in spec.metadata["description_i18n"]["en"]
    assert "/advisor off" in spec.help_text


def test_consult_tool_is_registered_with_governance():
    """Unregistered tools are denied by policy; the mode registers its
    tool as internal so the agent can call it without approval."""
    from qwenpaw.governance.tool_registry import DEFAULT_REGISTRY
    from qwenpaw.modes.advisor.tools import CONSULT_POLICY_NAME

    AdvisorMode()
    assert (
        DEFAULT_REGISTRY.get_mapped_policy_name(CONSULT_TOOL_NAME)
        == CONSULT_POLICY_NAME
    )
    assert DEFAULT_REGISTRY.get_type(CONSULT_POLICY_NAME) == "internal"
    assert DEFAULT_REGISTRY.get_owner(CONSULT_TOOL_NAME) == "builtin"
    AdvisorMode()  # idempotent: a second mode instance must not conflict
