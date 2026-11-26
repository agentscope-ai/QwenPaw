# -*- coding: utf-8 -*-
"""Default loop mode for ordinary ReAct requests."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..catalog import LoopModeInfo
from ..base import AgentMode
from ...loop.gates import (
    StopGate,
    StopHandler,
    StopHandlerRegistration,
    StopHandlerResult,
)
from ...loop.gates.doom_loop import DoomLoopGate
from ...loop.gates.iteration import IterationGate
from ...loop.gates.loop_gate import LoopGate
from ...loop.gates.rubric import QualitativeRubricGate
from ...loop.gates.runner import clear_pending_gate_state
from ...runtime.hooks import HookContext

if TYPE_CHECKING:
    from ...config.config import AgentsRunningConfig

logger = logging.getLogger(__name__)


def resolve_max_iterations(
    running_config: "AgentsRunningConfig",
) -> int | None:
    """Use the iteration gate as the default-mode budget policy."""
    if not running_config.loop.iteration.enabled:
        return None
    configured = running_config.loop.iteration.max_iterations
    if configured is not None:
        return configured
    return running_config.max_iters


class DefaultMode(AgentMode):
    """Own the fallback gate policy used outside explicit loop modes."""

    name = "default"

    def describe_loop(self, workspace: object) -> LoopModeInfo | None:
        """Expose this mode through the shared loop catalog."""
        return LoopModeInfo(
            id=self.name,
            name=self.name,
            slash_command=f"",
            description=f"The standard guarded agent loop.",
            source=f"builtin",
        )

    def __init__(self) -> None:
        self._handlers: dict[str, StopHandler] = {}
        self._config_keys: dict[str, str] = {}

    @property
    def handler(self) -> StopHandler:
        """Return the current session's independent gate chain."""
        sid = LoopGate._session_id()  # pylint: disable=protected-access
        if sid not in self._handlers:
            self._handlers[sid] = StopHandler()
        return self._handlers[sid]

    async def _check_stop(self, ctx: Any) -> StopHandlerResult:
        """Resolve the handler in the active request's session context."""
        return await self.handler(ctx)

    def setup(self, workspace: object) -> None:
        """Register an initially empty default-scoped handler."""
        super().setup(workspace)
        workspace.plugins.stop_handlers.append(
            StopHandlerRegistration(
                plugin_id="__default_mode__",
                handler=self._check_stop,
                priority=0,
                name="default-stop-handler",
                scope="default",
            ),
        )

    async def on_turn_start(self, ctx: HookContext) -> None:
        """Apply current config and prepare gates for a new user turn."""
        running_config = ctx.agent_config.running
        sid = LoopGate._session_id()  # pylint: disable=protected-access
        handler = self.handler
        config_key = self._make_config_key(running_config)
        if config_key != self._config_keys.get(sid):
            handler.replace(self._build_gates(running_config))
            self._config_keys[sid] = config_key
        handler.reset_turn()

    async def on_conversation_reset(self, ctx: HookContext) -> None:
        """Clear current-session gates and deferred agent decisions."""
        sid = LoopGate._session_id()  # pylint: disable=protected-access
        self.handler.reset_session()
        self._handlers.pop(sid, None)
        self._config_keys.pop(sid, None)
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

        max_iterations = resolve_max_iterations(running_config)
        if max_iterations is not None:
            gates.append(
                IterationGate(
                    max_iterations=max_iterations,
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
                QualitativeRubricGate(
                    rubric=loop_config.rubric.prompt,
                    max_evaluations=(loop_config.rubric.max_interventions),
                    use_decision_model=loop_config.rubric.use_decision_model,
                ),
            )

        logger.debug(
            "DefaultMode configured %d gate(s)",
            len(gates),
        )
        return gates


__all__ = ["DefaultMode", "resolve_max_iterations"]
