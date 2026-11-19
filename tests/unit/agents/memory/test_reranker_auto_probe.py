# -*- coding: utf-8 -*-
"""Regression tests for the reranker auto-probe sweep configuration path."""

import secrets
import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory import reranker_auto_probe as module
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentsRunningConfig,
    ReMeLightMemoryConfig,
    RerankerConfig,
)

_TEST_BASE_URL = "https://api.example.com/v1"


def _reranker(**overrides) -> RerankerConfig:
    values = {
        "enabled": True,
        "api_key": f"probe-{secrets.token_hex(12)}",
        "base_url": _TEST_BASE_URL,
        "model_name": "probe-reranker",
        "auto_verify_interval_hours": 24,
    }
    values.update(overrides)
    return RerankerConfig(**values)


def _agent_config(reranker: RerankerConfig | None) -> AgentProfileConfig:
    """Build the real profile model with the runtime nesting."""
    return AgentProfileConfig(
        id="default",
        name="Default",
        running=AgentsRunningConfig(
            reme_light_memory_config=ReMeLightMemoryConfig(
                reranker_config=reranker or RerankerConfig(),
            ),
        ),
    )


def _sweep_environment(
    reranker: RerankerConfig | None,
    probe,
    *,
    history: list[dict] | None = None,
    appended: list[dict] | None = None,
) -> ExitStack:
    """Patch every collaborator _sweep_once reaches through local imports."""
    stack = ExitStack()
    stack.enter_context(
        patch(
            "qwenpaw.config.config.load_agent_config",
            return_value=_agent_config(reranker),
        ),
    )
    stack.enter_context(
        patch(
            "qwenpaw.config.utils.load_config",
            return_value=SimpleNamespace(
                agents=SimpleNamespace(
                    profiles={"default": SimpleNamespace()},
                ),
            ),
        ),
    )
    stack.enter_context(
        patch(
            "qwenpaw.agents.memory.reme_reranker.test_reranker_model",
            probe,
        ),
    )
    stack.enter_context(
        patch(
            "qwenpaw.agents.memory.reranker_history.get_history",
            return_value=history or [],
        ),
    )
    sink = appended if appended is not None else []

    def _append(_fingerprint, record):
        sink.append(record)
        return list(sink)

    stack.enter_context(
        patch(
            "qwenpaw.agents.memory.reranker_history.append_record",
            side_effect=_append,
        ),
    )
    return stack


_SUCCESS = SimpleNamespace(
    success=True,
    latency_ms=12,
    precision=1.0,
    correct_count=5,
    total=5,
    message="ok",
)


@pytest.mark.asyncio
async def test_sweep_reaches_probe_through_running_memory_config() -> None:
    """The sweep must read reranker_config from
    running.reme_light_memory_config, not from the profile root — a real
    AgentProfileConfig previously produced zero probe calls."""
    probe = AsyncMock(return_value=_SUCCESS)
    appended: list[dict] = []
    with _sweep_environment(_reranker(), probe, appended=appended):
        await module._sweep_once()

    assert probe.await_count == 1
    # The sweep probes the operator-saved service, so local/private endpoints
    # are allowed exactly like the runtime path.
    assert probe.await_args.kwargs["allow_private"] is True
    assert len(appended) == 1
    assert appended[0]["precision"] == 1.0
    assert appended[0]["total"] == 5


@pytest.mark.asyncio
async def test_sweep_skips_when_reranker_missing() -> None:
    probe = AsyncMock()
    with _sweep_environment(None, probe):
        await module._sweep_once()

    assert probe.await_count == 0


@pytest.mark.asyncio
async def test_sweep_skips_when_interval_is_zero() -> None:
    probe = AsyncMock()
    with _sweep_environment(_reranker(auto_verify_interval_hours=0), probe):
        await module._sweep_once()

    assert probe.await_count == 0


@pytest.mark.asyncio
async def test_sweep_skips_when_interval_has_not_elapsed() -> None:
    probe = AsyncMock()
    recent = [{"ts": (time.time() - 3600) * 1000}]
    with _sweep_environment(_reranker(), probe, history=recent):
        await module._sweep_once()

    assert probe.await_count == 0


@pytest.mark.asyncio
async def test_sweep_does_not_record_failed_probe() -> None:
    probe = AsyncMock(
        return_value=SimpleNamespace(
            success=False,
            latency_ms=5,
            precision=None,
            correct_count=0,
            total=0,
            message="boom",
        ),
    )
    appended: list[dict] = []
    with _sweep_environment(_reranker(), probe, appended=appended):
        await module._sweep_once()

    assert probe.await_count == 1
    assert appended == []
