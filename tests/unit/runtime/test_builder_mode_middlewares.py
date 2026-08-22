# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""``AgentBuilder`` collects request-scoped middlewares from active modes."""
from __future__ import annotations

import types

import pytest

from qwenpaw.config.config import (
    AgentProfileConfig,
    LightContextConfig,
    ModelSlotConfig,
)
from qwenpaw.modes.advisor import AdvisorMiddleware, AdvisorMode
from qwenpaw.modes.base import AgentMode
from qwenpaw.runtime.builder import AgentBuilder


class _Sentinel:
    """Stands in for a MiddlewareBase instance."""


class _StaticMode(AgentMode):
    def __init__(self, name, active, contributions=(), raise_on=None):
        self.name = name
        self._active = active
        self._contributions = list(contributions)
        self._raise_on = raise_on

    def is_active(self, ctx):
        if self._raise_on == "is_active":
            raise RuntimeError("boom")
        return self._active

    def middlewares(self, ctx, agent_config):
        if self._raise_on == "middlewares":
            raise RuntimeError("boom")
        return list(self._contributions)


def _ctx(modes):
    plugins = types.SimpleNamespace(modes=list(modes))
    return types.SimpleNamespace(
        workspace=types.SimpleNamespace(plugins=plugins),
        agent_id="agent-1",
        session_id="s",
        workspace_dir=None,
    )


def test_collects_only_from_active_modes():
    a, b = _Sentinel(), _Sentinel()
    ctx = _ctx(
        [
            _StaticMode("on", True, [a]),
            _StaticMode("off", False, [_Sentinel()]),
            _StaticMode("on2", True, [b]),
        ],
    )
    assert AgentBuilder._collect_mode_middlewares(ctx, None) == [a, b]


def test_base_mode_contributes_nothing_by_default():
    class _Bare(AgentMode):
        name = "bare"

        def is_active(self, ctx):
            return True

    assert not AgentBuilder._collect_mode_middlewares(_ctx([_Bare()]), None)


def test_a_failing_mode_does_not_break_the_others(caplog):
    good = _Sentinel()
    ctx = _ctx(
        [
            _StaticMode("bad-active", True, raise_on="is_active"),
            _StaticMode("bad-build", True, raise_on="middlewares"),
            _StaticMode("good", True, [good]),
        ],
    )
    with caplog.at_level("WARNING"):
        assert AgentBuilder._collect_mode_middlewares(ctx, None) == [good]
    assert "bad-active" in caplog.text and "bad-build" in caplog.text


def test_missing_workspace_or_plugins_is_fine():
    assert not AgentBuilder._collect_mode_middlewares(
        types.SimpleNamespace(),
        None,
    )
    ctx = types.SimpleNamespace(workspace=types.SimpleNamespace())
    assert not AgentBuilder._collect_mode_middlewares(ctx, None)


@pytest.fixture
def agent_config():
    cfg = AgentProfileConfig(id="agent-1", name="Agent")
    cfg.running.light_context_config = LightContextConfig(strategy="native")
    cfg.active_model = ModelSlotConfig(provider_id="dash", model="qwen3-max")
    return cfg


def _build(ctx, agent_config):
    return AgentBuilder._build_middlewares(ctx, agent_config)


def test_advisor_middleware_is_last_when_mode_enabled(agent_config):
    agent_config.advisor_mode.enabled = True
    ctx = _ctx([AdvisorMode()])
    ctx.app_services = None
    ctx.agent_config = agent_config
    middlewares = _build(ctx, agent_config)
    advisors = [m for m in middlewares if isinstance(m, AdvisorMiddleware)]
    assert len(advisors) == 1
    assert middlewares[-1] is advisors[0], "mode middlewares sit innermost"


def test_advisor_middleware_absent_when_mode_disabled(agent_config):
    ctx = _ctx([AdvisorMode()])
    ctx.app_services = None
    ctx.agent_config = agent_config
    middlewares = _build(ctx, agent_config)
    assert not any(isinstance(m, AdvisorMiddleware) for m in middlewares)
