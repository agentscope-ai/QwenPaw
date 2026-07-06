# -*- coding: utf-8 -*-
"""Tests for wiring execution-layer result limiting from config."""

from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.config.config import (
    LightContextConfig,
    ToolResultPruningConfig,
)
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.tool_calls import ToolCoordinator, ToolCoordinatorMiddleware


def test_builder_uses_execution_layer_limit_independent_of_recent_limit(
    tmp_path,
):
    pruning_config = ToolResultPruningConfig(
        pruning_recent_msg_max_bytes=4096,
        execution_layer_max_bytes=8192,
    )
    agent_config = SimpleNamespace(
        id="agent-1",
        running=SimpleNamespace(
            light_context_config=LightContextConfig(
                tool_result_pruning_config=pruning_config,
            ),
        ),
    )
    ctx = SimpleNamespace(
        app_services=SimpleNamespace(tool_coordinator=ToolCoordinator()),
        workspace=SimpleNamespace(workspace_dir=str(tmp_path)),
    )

    build_middlewares = getattr(AgentBuilder, "_build_middlewares")
    middlewares = build_middlewares(ctx, agent_config)
    coordinator_middleware = next(
        mw for mw in middlewares if isinstance(mw, ToolCoordinatorMiddleware)
    )

    limiter = getattr(coordinator_middleware, "_result_limiter")
    assert getattr(limiter, "_max_text_bytes") == 8192
