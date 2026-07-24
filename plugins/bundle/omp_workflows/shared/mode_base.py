# -*- coding: utf-8 -*-
"""Shared AgentMode scaffolding for OMP workflow modes."""

from __future__ import annotations

import logging
import weakref
from typing import Any, ClassVar

from agentscope.message import Msg, TextBlock

from qwenpaw.modes.base import AgentMode
from qwenpaw.runtime.hooks import HookContext

logger = logging.getLogger(__name__)


class OMPModeBase(AgentMode):
    """Common setup / lifecycle for OMP workflow modes.

    Subclasses must set ``name``, ``gate_cls``, ``plugin_id``,
    ``handler_name``, and ``scope``.
    """

    gate_cls: type
    plugin_id: str
    handler_name: str
    scope: str

    _instances: ClassVar[list[weakref.ReferenceType]] = []

    def __init__(self) -> None:
        self._gate: Any = None
        self._workspace_ref: weakref.ReferenceType[Any] | None = None
        OMPModeBase._instances.append(weakref.ref(self))

    def setup(self, workspace: object) -> None:
        super().setup(workspace)
        self._workspace_ref = weakref.ref(workspace)
        from qwenpaw.loop.gates import StopHandler, StopHandlerRegistration

        handler = StopHandler()
        gate = self.gate_cls()
        handler.register(gate)
        self._gate = gate

        plugins = getattr(workspace, "plugins", None)
        if plugins is not None:
            # Defensive: matches MissionMode / older WorkspacePlugins
            if not hasattr(plugins, "stop_handlers"):
                plugins.stop_handlers = []
            plugins.stop_handlers.append(
                StopHandlerRegistration(
                    plugin_id=self.plugin_id,
                    handler=handler,
                    priority=0,
                    name=self.handler_name,
                    scope=self.scope,
                ),
            )

    def is_active(
        self,
        ctx: Any,  # pylint: disable=unused-argument
    ) -> bool:
        # Follows upstream MissionMode pattern (LoopGate lacks public API)
        # pylint: disable=protected-access
        return self._gate is not None and self._gate._state() is not None

    async def on_conversation_reset(
        self,
        ctx: HookContext,  # pylint: disable=unused-argument
    ) -> None:
        """Clear gate state on /new and /clear."""
        if self._gate is not None:
            self._gate.reset_session()

    def claim_workflow(self) -> None:
        """Deactivate peer OMP workflows so only this scope is active.

        ``_filter_by_scope`` keeps the first active non-default scope;
        without mutual exclusion a later ``/ralph`` would be ignored
        while an earlier ``/ultraqa`` gate still holds session state.

        Only peers bound to the **same workspace** are deactivated —
        modes from other workspaces must keep their own gates.
        """
        my_ws = self._workspace_ref() if self._workspace_ref else None
        alive: list[weakref.ReferenceType] = []
        for ref in OMPModeBase._instances:
            mode = ref()
            if mode is None:
                continue
            alive.append(ref)
            # pylint: disable=protected-access
            peer_gate = mode._gate
            if mode is self or peer_gate is None:
                continue
            peer_ws = mode._workspace_ref() if mode._workspace_ref else None
            if my_ws is not None and peer_ws is not my_ws:
                continue
            if peer_gate._state() is not None:
                logger.info(
                    "Deactivating peer OMP mode '%s' for '%s'",
                    mode.name,
                    self.name,
                )
                peer_gate.reset_session()
        OMPModeBase._instances = alive


def info_msg(text: str) -> Msg:
    """Build a system info message for slash-command help/errors."""
    return Msg(
        name="system",
        content=[TextBlock(type="text", text=text)],
        role="system",
    )


def rewrite_user_msg(ctx: Any, text: str) -> None:
    """Replace the last user message content with *text*."""
    msgs = getattr(ctx, "input_msgs", None)
    if not msgs:
        return
    last = msgs[-1]
    if isinstance(last, Msg):
        last.content = [TextBlock(type="text", text=text)]


__all__ = ["OMPModeBase", "info_msg", "rewrite_user_msg"]
