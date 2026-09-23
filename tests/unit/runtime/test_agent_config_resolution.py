# -*- coding: utf-8 -*-
"""Tests for runtime agent-configuration resolution.

Covers the stable error codes a client branches on, which requests may be
answered without an agent configuration, and the request-scoped snapshot
the runtime pins before any hook runs.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.exceptions import (
    AGENT_CONFIG_UNAVAILABLE,
    AgentConfigConflictError,
    ConfigurationException,
)
from qwenpaw.runtime import configuration as configuration_module
from qwenpaw.runtime.configuration import (
    is_config_independent_command,
    load_runtime_agent_config,
)
from qwenpaw.runtime.runtime import Runtime
from qwenpaw.schemas import AgentRequest

pytestmark = [pytest.mark.unit, pytest.mark.p1]


def _request(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        input=[
            SimpleNamespace(
                content=[SimpleNamespace(type="text", text=text)],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# load_runtime_agent_config
# ---------------------------------------------------------------------------


class TestLoadRuntimeAgentConfig:
    async def test_returns_the_loaded_configuration(self, monkeypatch):
        config = SimpleNamespace(id="agent-1")
        monkeypatch.setattr(
            configuration_module,
            "load_agent_config_async",
            AsyncMock(return_value=config),
        )

        assert await load_runtime_agent_config("agent-1") is config

    @pytest.mark.parametrize(
        "error",
        [
            OSError("disk gone"),
            ValueError("corrupt json"),
            TypeError("bad shape"),
        ],
    )
    async def test_codeless_failures_become_unavailable(
        self,
        monkeypatch,
        error,
    ):
        monkeypatch.setattr(
            configuration_module,
            "load_agent_config_async",
            AsyncMock(side_effect=error),
        )

        with pytest.raises(ConfigurationException) as caught:
            await load_runtime_agent_config("agent-1")

        assert caught.value.error_code == AGENT_CONFIG_UNAVAILABLE
        assert caught.value.config_key == "agent"

    async def test_failure_keeps_its_own_code(self, monkeypatch):
        monkeypatch.setattr(
            configuration_module,
            "load_agent_config_async",
            AsyncMock(side_effect=AgentConfigConflictError("agent-1")),
        )

        with pytest.raises(ConfigurationException) as caught:
            await load_runtime_agent_config("agent-1")

        assert caught.value.error_code == "AGENT_CONFIG_STALE"

    async def test_missing_model_verdict_is_untouched(self, monkeypatch):
        error = ConfigurationException(
            "No active model configured; pick one in the UI",
            config_key="active_model",
            error_code="MODEL_NOT_CONFIGURED",
        )
        monkeypatch.setattr(
            configuration_module,
            "load_agent_config_async",
            AsyncMock(side_effect=error),
        )

        with pytest.raises(ConfigurationException) as caught:
            await load_runtime_agent_config("agent-1")

        assert caught.value.error_code == "MODEL_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# is_config_independent_command
# ---------------------------------------------------------------------------


class TestIsConfigIndependentCommand:
    @pytest.mark.parametrize(
        "text",
        [
            "/model",
            "/model help",
            "/model -h",
            "/model --help",
            "/model list",
            "/model info",
            "/model info openai:gpt-4o",
            "/MODEL LIST",
        ],
    )
    def test_read_only_forms_qualify(self, text):
        assert is_config_independent_command(_request(text)) is True

    @pytest.mark.parametrize(
        "text",
        [
            "hello",
            "/model openai:gpt-4o",
            "/model reset",
            "/status",
            "",
        ],
    )
    def test_other_requests_do_not(self, text):
        assert is_config_independent_command(_request(text)) is False

    def test_reads_a_plain_dict_request(self):
        request = {"input": [{"content": [{"text": "/model list"}]}]}
        assert is_config_independent_command(request) is True

    def test_tolerates_an_empty_request(self):
        assert (
            is_config_independent_command(SimpleNamespace(input=[])) is False
        )
        assert is_config_independent_command(SimpleNamespace()) is False


# ---------------------------------------------------------------------------
# Runtime._resolve_agent_config
# ---------------------------------------------------------------------------


def _runtime(**kwargs) -> Runtime:
    return Runtime(workspace=SimpleNamespace(), app_services=None, **kwargs)


def _ctx(agent_id="agent-1", agent_config=None) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id=agent_id,
        agent_config=agent_config,
        extras={},
    )


class TestResolveAgentConfig:
    async def test_pins_one_snapshot_per_request(self, monkeypatch):
        config = SimpleNamespace(id="agent-1")
        loader = AsyncMock(return_value=config)
        monkeypatch.setattr(
            configuration_module,
            "load_agent_config_async",
            loader,
        )
        runtime = _runtime()
        ctx = _ctx()

        assert await runtime._resolve_agent_config(ctx, _request("hi")) is True
        assert ctx.agent_config is config
        # A second resolution in the same request must not read again.
        assert await runtime._resolve_agent_config(ctx, _request("hi")) is True
        assert loader.await_count == 1

    async def test_reuses_a_preloaded_configuration(self, monkeypatch):
        loader = AsyncMock()
        monkeypatch.setattr(
            configuration_module,
            "load_agent_config_async",
            loader,
        )
        config = SimpleNamespace(id="agent-1")

        runtime = _runtime(agent_config=config)
        request = AgentRequest(
            input=[
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            ],
        )
        ctx = runtime._build_context(request)

        # The workspace already loaded the configuration for this request.
        assert ctx.agent_config is config
        assert await runtime._resolve_agent_config(ctx, request) is True
        loader.assert_not_awaited()

    async def test_unavailable_config_stops_a_normal_turn(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            configuration_module,
            "load_agent_config_async",
            AsyncMock(side_effect=OSError("disk gone")),
        )
        runtime = _runtime()
        ctx = _ctx()

        assert (
            await runtime._resolve_agent_config(ctx, _request("hi")) is False
        )
        assert runtime.config_error.error_code == AGENT_CONFIG_UNAVAILABLE

    async def test_unavailable_config_still_answers_model_commands(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            configuration_module,
            "load_agent_config_async",
            AsyncMock(side_effect=OSError("disk gone")),
        )
        runtime = _runtime()
        ctx = _ctx()

        resolved = await runtime._resolve_agent_config(
            ctx,
            _request("/model list"),
        )

        assert resolved is True
        assert ctx.extras["agent_config_error"] is runtime.config_error

    async def test_a_caller_supplied_error_is_reused(self):
        error = ConfigurationException(
            "temporarily unavailable",
            config_key="agent",
            error_code=AGENT_CONFIG_UNAVAILABLE,
        )
        runtime = _runtime(config_error=error)
        ctx = _ctx()

        assert (
            await runtime._resolve_agent_config(ctx, _request("hi")) is False
        )
        assert runtime.config_error is error

        allowed = _ctx()
        assert (
            await runtime._resolve_agent_config(
                allowed,
                _request("/model"),
            )
            is True
        )
        assert allowed.extras["agent_config_error"] is error
