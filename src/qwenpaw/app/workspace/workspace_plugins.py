# -*- coding: utf-8 -*-
"""Per-workspace pluggable layer.

Holds the three per-workspace registries that ``Runtime.run()``
reads each request:

* :class:`SlashCommandRegistry` — slash dispatch
* :class:`HookRegistry`         — 8-phase hook orchestration
* ``modes``                     — list of :class:`AgentMode` instances

Every field is **per-workspace** — no cross-workspace sharing. The
matching cross-workspace container is ``AppServiceManager`` and is strictly
limited to its three coordinators (see ``app/app_services/``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...runtime.hooks import HookRegistry
from ...runtime.occupancy import occupancy_conflict
from ...runtime.prompt_manager import PromptManager
from ...runtime.slash_command_registry import SlashCommandRegistry
from ...runtime.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from ...loop.gates import StopHandlerRegistration
    from ...modes.base import AgentMode
    from ...runtime.hooks import HookContext

logger = logging.getLogger(__name__)


@dataclass
class WorkspacePlugins:
    """Per-workspace pluggable registries."""

    slash_command_registry: SlashCommandRegistry = field(
        default_factory=SlashCommandRegistry,
    )
    hook_registry: HookRegistry = field(default_factory=HookRegistry)
    tool_registry: ToolRegistry = field(default_factory=ToolRegistry)
    prompt_manager: PromptManager = field(default_factory=PromptManager)
    modes: list["AgentMode"] = field(default_factory=list)
    stop_handlers: list["StopHandlerRegistration"] = field(
        default_factory=list,
    )

    def register_mode(self, mode: "AgentMode", workspace: object) -> None:
        """Run ``setup`` first, then enter the table.

        Duplicate names are rejected — collisions usually mean two
        bootstrap paths both think they own the mode and silently
        double-registering would cause subtle dispatch ambiguities.
        A failed ``setup`` rolls back via ``teardown`` and does not
        leave the mode in the table.
        """
        occupant = next(
            (m for m in self.modes if m.name == mode.name),
            None,
        )
        if occupant is not None:
            raise ValueError(
                occupancy_conflict(
                    "AgentMode",
                    mode.name,
                    getattr(occupant, "owner_plugin_id", "") or "",
                ),
            )
        try:
            mode.setup(workspace)
        except Exception:
            _safe_mode_teardown(mode, workspace)
            raise
        self.modes.append(mode)

    def unregister_mode(self, name: str, workspace: object) -> bool:
        """Remove a mode by name and run ``teardown``. ``True`` if present."""
        for index, mode in enumerate(self.modes):
            if mode.name != name:
                continue
            self.modes.pop(index)
            _safe_mode_teardown(mode, workspace)
            return True
        return False

    def register_stop_handler(self, reg: "StopHandlerRegistration") -> None:
        """Append a stop handler; duplicate names name the occupant."""
        occupant = next(
            (item for item in self.stop_handlers if item.name == reg.name),
            None,
        )
        if occupant is not None:
            owner = getattr(occupant, "owner_plugin_id", "") or ""
            raise ValueError(
                occupancy_conflict("stop handler", reg.name, owner),
            )
        self.stop_handlers.append(reg)

    def unregister_stop_handler(self, name: str) -> bool:
        """Remove a stop handler by name. ``True`` if it was present."""
        before = len(self.stop_handlers)
        self.stop_handlers = [
            item for item in self.stop_handlers if item.name != name
        ]
        return len(self.stop_handlers) < before

    def active_mode_names(self, ctx: "HookContext") -> set[str]:
        """Return the names of every mode reporting ``is_active(ctx)``.

        Used by ``ToolRegistry.filter`` (and any other code that needs
        the runtime-active set) so per-workspace mode state never leaks
        into cross-workspace containers.
        """
        return {m.name for m in self.modes if m.is_active(ctx)}


def _safe_mode_teardown(mode: "AgentMode", workspace: object) -> None:
    teardown = getattr(mode, "teardown", None)
    if not callable(teardown):
        return
    try:
        teardown(workspace)
    except Exception:  # noqa: BLE001
        logger.exception(
            "AgentMode %r teardown failed",
            getattr(mode, "name", mode),
        )


__all__ = ["WorkspacePlugins"]
