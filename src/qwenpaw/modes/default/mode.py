# -*- coding: utf-8 -*-
"""Default loop mode for ordinary ReAct requests."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..base import AgentMode
from ...loop.gates import (
    StopGate,
    StopHandler,
    StopHandlerRegistration,
)
from ...loop.gates.doom_loop import DoomLoopGate
from ...loop.gates.iteration import IterationGate
from ...loop.gates.rubric import StandaloneRubricGate
from ...loop.gates.runner import clear_pending_gate_state
from ...runtime.hooks import HookContext

if TYPE_CHECKING:
    from ...config.config import AgentsRunningConfig

logger = logging.getLogger(__name__)


def resolve_max_iterations(
    running_config: "AgentsRunningConfig",
) -> int:
    """Resolve the effective iteration limit with legacy compatibility."""
    configured = running_config.loop.iteration.max_iterations
    if configured is not None:
        return configured
    return running_config.max_iters


class DefaultMode(AgentMode):
    """Own the fallback gate policy used outside explicit loop modes."""

    name = "default"

    def __init__(self) -> None:
        self._handler = StopHandler()
        self._config_key: str | None = None

    @property
    def handler(self) -> StopHandler:
        """Expose the mode-owned handler for runtime tests and inspection."""
        return self._handler

    def setup(self, workspace: object) -> None:
        """Register an initially empty default-scoped handler."""
        super().setup(workspace)
        workspace.plugins.stop_handlers.append(
            StopHandlerRegistration(
                plugin_id="__default_mode__",
                handler=self._handler,
                priority=0,
                name="default-stop-handler",
                scope="default",
            ),
        )

    async def on_turn_start(self, ctx: HookContext) -> None:
        """Apply current config and prepare gates for a new user turn."""
        running_config = ctx.agent_config.running
        config_key = self._make_config_key(running_config)
        if config_key != self._config_key:
            self._handler.replace(self._build_gates(running_config))
            self._config_key = config_key
        self._handler.reset_turn()

    def on_conversation_reset(self, ctx: HookContext) -> None:
        """Clear current-session gates and deferred agent decisions."""
        self._handler.reset_session()
        clear_pending_gate_state(ctx.agent)

    def is_active(self, ctx: HookContext) -> bool:  # noqa: ARG002
        """Default behavior is available for every request."""
        return True

    @staticmethod
    def _make_config_key(running_config: Any) -> str:
        """Build a stable comparison key for hot-loaded loop config."""
        loop_config = running_config.loop
        dump_json = getattr(loop_config, "model_dump_json", None)
        if callable(dump_json):
            loop_key = dump_json()
        else:
            loop_key = repr(loop_config)
        max_iterations = resolve_max_iterations(running_config)
        return f"{loop_key}:{max_iterations}"

    @staticmethod
    def _build_gates(
        running_config: "AgentsRunningConfig",
    ) -> list[StopGate]:
        """Build the configured default gate chain."""
        loop_config = running_config.loop
        gates: list[StopGate] = []

        if loop_config.iteration.enabled:
            gates.append(
                IterationGate(
                    max_iterations=resolve_max_iterations(running_config),
                ),
            )
        if loop_config.doom_loop.enabled:
            gates.append(
                DoomLoopGate(
                    window_size=loop_config.doom_loop.window_size,
                    similarity_threshold=(
                        loop_config.doom_loop.similarity_threshold
                    ),
                    stages=loop_config.doom_loop.stages,
                ),
            )
        if loop_config.rubric.enabled:
            gates.append(
                StandaloneRubricGate(
                    prompt=loop_config.rubric.prompt,
                    max_interventions=(loop_config.rubric.max_interventions),
                ),
            )

        logger.debug(
            "DefaultMode configured %d gate(s)",
            len(gates),
        )
        return gates


__all__ = ["DefaultMode", "resolve_max_iterations"]
