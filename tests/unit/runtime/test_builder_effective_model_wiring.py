# -*- coding: utf-8 -*-
"""AgentBuilder publishes the serving model before tools are built.

Driver tools copy the request context at construction time, so the
``effective_model`` entry must exist before tool collection starts
(issue #8378).
"""

# pylint: disable=protected-access

from types import SimpleNamespace

import pytest

from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.runtime import builder as builder_mod
from qwenpaw.runtime.builder import AgentBuilder

SESSION_SLOT = ModelSlotConfig(provider_id="p", model="vision-pro")


@pytest.mark.asyncio
async def test_effective_model_is_visible_to_driver_tools(monkeypatch):
    config = AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=SESSION_SLOT,
    )

    async def identity_session(_ctx, agent_config):
        return agent_config

    monkeypatch.setattr(
        builder_mod, "apply_session_thinking", identity_session
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: config,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.ensure_skills_initialized",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.resolve_effective_skills",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        AgentBuilder,
        "_build_request_context",
        staticmethod(lambda _ctx: {"channel": "console"}),
    )
    monkeypatch.setattr(
        AgentBuilder,
        "_apply_request_project",
        staticmethod(lambda agent_config, _request_context: agent_config),
    )
    monkeypatch.setattr(
        AgentBuilder,
        "_init_governor",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        AgentBuilder,
        "_get_local_workspace",
        staticmethod(lambda _ctx: None),
    )
    monkeypatch.setattr(
        AgentBuilder,
        "_collect_coding_mode_tools",
        staticmethod(lambda *_args, **_kwargs: []),
    )
    monkeypatch.setattr(
        AgentBuilder,
        "_collect_context_recall_tools",
        staticmethod(lambda *_args, **_kwargs: []),
    )

    seen: dict[str, object] = {}

    async def capture_driver_context(_ctx, request_context):
        seen["effective_model"] = request_context.get("effective_model")
        raise RuntimeError("stop after driver tools")

    monkeypatch.setattr(
        AgentBuilder,
        "_collect_driver_tools_and_prompts",
        staticmethod(capture_driver_context),
    )

    ctx = SimpleNamespace(
        agent_id="agent",
        request=SimpleNamespace(model_slot_override=None),
        workspace=None,
        extras={},
    )

    with pytest.raises(RuntimeError, match="stop after driver tools"):
        await AgentBuilder.__new__(AgentBuilder).build(ctx)

    assert seen["effective_model"] == SESSION_SLOT
    assert ctx.extras["effective_model"] == SESSION_SLOT
