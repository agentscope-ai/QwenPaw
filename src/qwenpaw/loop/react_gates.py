# -*- coding: utf-8 -*-
"""Register default StopHandler + Gates for ReAct mode.

Ensures that even without an explicit loop mode (/goal, /mission),
the agent still has Gate-based iteration control, repetition
protection, and completion checks active.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .gates import (
    StopHandler,
    StopHandlerRegistration,
)
from .gates.doom_loop import DoomLoopGate
from .gates.iteration import IterationGate
from .gates.rubric import StandaloneRubricGate

if TYPE_CHECKING:
    from ..config.config import (
        AgentsRunningConfig,
    )

logger = logging.getLogger(__name__)

_REACT_HANDLER_NAME = "react-default-stop-handler"


def resolve_max_iterations(
    running_config: "AgentsRunningConfig",
) -> int:
    """Resolve effective max iterations with legacy compat.

    Priority: loop.iteration.max_iterations > max_iters
    """
    loop_cfg = running_config.loop
    if loop_cfg.iteration.max_iterations is not None:
        return loop_cfg.iteration.max_iterations
    return running_config.max_iters


def register_react_gates(
    workspace: Any,
    running_config: "AgentsRunningConfig",
) -> StopHandler:
    """Register default ReAct StopHandler with configured gates.

    Idempotent: skips if already registered for this workspace.

    Args:
        workspace: The workspace/agent-workspace object
            (may be None).
        running_config: Agent runtime configuration.

    Returns:
        The StopHandler instance (for testing or extension).
    """
    if getattr(workspace, "_react_gates_registered", False):
        return _get_or_create_handler(workspace)

    loop_cfg = running_config.loop
    handler = _get_or_create_handler(workspace)

    # 1. Iteration Gate
    if loop_cfg.iteration.enabled:
        effective_max = resolve_max_iterations(running_config)
        gate = IterationGate(max_iterations=effective_max)
        gate.activate()
        handler.register(gate)
        logger.debug(
            "ReactGates: IterationGate (max=%d)",
            effective_max,
        )

    # 2. DoomLoop Gate
    if loop_cfg.doom_loop.enabled:
        gate = DoomLoopGate(
            window_size=loop_cfg.doom_loop.window_size,
            similarity_threshold=(loop_cfg.doom_loop.similarity_threshold),
            stages=loop_cfg.doom_loop.stages,
        )
        gate.activate()
        handler.register(gate)
        logger.debug("ReactGates: DoomLoopGate registered")

    # 3. Rubric Gate (completion check)
    if loop_cfg.rubric.enabled:
        gate = StandaloneRubricGate(
            prompt=loop_cfg.rubric.prompt,
            max_interventions=(loop_cfg.rubric.max_interventions),
        )
        handler.register(gate)
        logger.debug(
            "ReactGates: StandaloneRubricGate registered",
        )

    setattr(workspace, "_react_gates_registered", True)
    return handler


def _get_or_create_handler(
    workspace: Any,
) -> StopHandler:
    """Get or create StopHandler on workspace."""
    existing = getattr(workspace, "_stop_handler", None)
    if isinstance(existing, StopHandler):
        return existing

    handler = StopHandler()
    setattr(workspace, "_stop_handler", handler)

    plugins = getattr(workspace, "plugins", None)
    if plugins is not None:
        if not hasattr(plugins, "stop_handlers"):
            plugins.stop_handlers = []
        plugins.stop_handlers.append(
            StopHandlerRegistration(
                plugin_id="__react_default__",
                handler=handler,
                priority=0,
                name=_REACT_HANDLER_NAME,
                scope="default",
            ),
        )
    else:
        logger.warning(
            "_get_or_create_handler: no plugins on ws",
        )
    return handler


__all__ = [
    "register_react_gates",
    "resolve_max_iterations",
]
