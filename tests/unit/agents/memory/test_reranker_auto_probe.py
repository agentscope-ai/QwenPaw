# -*- coding: utf-8 -*-
"""Regression tests for the reranker auto-probe sweep configuration path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.agents.memory import reranker_auto_probe as module
from qwenpaw.config.config import RerankerConfig


def _agent_config(reranker: RerankerConfig | None) -> SimpleNamespace:
    """Mirror the real nesting: running.reme_light_memory_config.reranker_config."""
    return SimpleNamespace(
        running=SimpleNamespace(
            reme_light_memory_config=SimpleNamespace(reranker_config=reranker),
        ),
    )


@pytest.mark.asyncio
async def test_sweep_reaches_probe_through_running_memory_config() -> None:
    """The sweep must read reranker_config from
    running.reme_light_memory_config, not from the profile root — a real
    AgentProfileConfig previously produced zero probe calls."""
    reranker = RerankerConfig(
        enabled=True,
        api_key="k",
        base_url="https://api.example.com/v1",
        model_name="m",
        auto_verify_interval_hours=24,
    )
    agent_config = _agent_config(reranker)

    probe = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            latency_ms=12,
            precision=1.0,
            correct_count=5,
            total=5,
            message="ok",
        ),
    )
    append = _record_sink = []
    with (
        patch.dict(
            "sys.modules",
            {},
        ),
        patch(
            "qwenpaw.agents.memory.reranker_auto_probe._sweep_once",
            new=module._sweep_once,
        ),
    ):
        pass

    # Patch the heavy collaborators inside _sweep_once's local imports.
    from unittest.mock import MagicMock

    fake_history = MagicMock()
    fake_history.get_history.return_value = []
    with (
        patch(
            "qwenpaw.config.config.load_agent_config",
            return_value=agent_config,
        ),
        patch(
            "qwenpaw.config.utils.load_config",
            return_value=SimpleNamespace(
                agents=SimpleNamespace(
                    profiles={"default": SimpleNamespace()},
                ),
            ),
        ),
        patch(
            "qwenpaw.agents.memory.reme_reranker.test_reranker_model",
            probe,
        ),
        patch(
            "qwenpaw.agents.memory.reranker_history.get_history",
            return_value=[],
        ),
        patch(
            "qwenpaw.agents.memory.reranker_history.append_record",
            side_effect=lambda fp, rec: append.append(rec),
        ),
    ):
        await module._sweep_once()

    assert probe.await_count == 1
    assert len(append) == 1
    assert append[0]["precision"] == 1.0


@pytest.mark.asyncio
async def test_sweep_skips_when_reranker_missing_at_both_paths() -> None:
    agent_config = _agent_config(None)
    probe = AsyncMock()
    with (
        patch(
            "qwenpaw.config.config.load_agent_config",
            return_value=agent_config,
        ),
        patch(
            "qwenpaw.config.utils.load_config",
            return_value=SimpleNamespace(
                agents=SimpleNamespace(
                    profiles={"default": SimpleNamespace()},
                ),
            ),
        ),
        patch(
            "qwenpaw.agents.memory.reme_reranker.test_reranker_model",
            probe,
        ),
    ):
        await module._sweep_once()

    assert probe.await_count == 0
