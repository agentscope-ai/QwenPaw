# -*- coding: utf-8 -*-
"""The single cross-workspace service container.

Strict whitelist of three fields (``task_tracker`` / ``tool_coordinator`` /
``approval_coordinator``). Adding any other field here is a contract
break — per-workspace state belongs on ``Workspace.service_manager`` /
``Workspace.plugins`` instead.

``start`` / ``stop`` are called by FastAPI lifespan (the very first thing
to come up so hooks running in any later phase can read
``ctx.app_services.*`` safely). The existing ``TaskTracker`` has no
lifecycle methods yet, so ``start``/``stop`` delegate via ``hasattr`` to
stay forward-compatible without forcing an out-of-scope edit to
``task_tracker.py``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .approval_coordinator import ApprovalCoordinator
from ...tool_calls import ToolCoordinator

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..task_tracker import TaskTracker


class AppServiceManager:
    """Hold the three cross-workspace coordinators and own their lifecycle.

    Fields (frozen by contract — do not extend):

    * ``task_tracker``        — :class:`TaskTracker`
    * ``tool_coordinator``    — :class:`ToolCoordinator`
    * ``approval_coordinator`` — :class:`ApprovalCoordinator`
    """

    __slots__ = (
        "task_tracker",
        "tool_coordinator",
        "approval_coordinator",
    )

    def __init__(
        self,
        *,
        task_tracker: "TaskTracker | None" = None,
    ) -> None:
        if task_tracker is None:
            from ..task_tracker import TaskTracker

            task_tracker = TaskTracker()
        self.task_tracker = task_tracker
        self.tool_coordinator = ToolCoordinator(
            offload_on_deadline=self._load_offload_policy(),
        )
        self.approval_coordinator = ApprovalCoordinator()

    @staticmethod
    def _load_offload_policy() -> bool:
        """Read offload_policy from settings.json at startup."""
        try:
            from ...constant import WORKING_DIR

            settings_file = WORKING_DIR / "settings.json"
            if settings_file.is_file():
                data = json.loads(settings_file.read_text("utf-8"))
                return data.get("offload_policy") == "offload"
        except Exception:
            logger.debug("Could not load offload_policy, using default")
        return False

    async def start(self) -> None:
        """Bring coordinators online; called once in lifespan startup."""
        start_fn = getattr(self.task_tracker, "start", None)
        if callable(start_fn):
            await start_fn()  # pylint: disable=not-callable

    async def stop(self) -> None:
        """Tear down coordinators in reverse dependency order."""
        await self.tool_coordinator.shutdown()
        stop_fn = getattr(self.task_tracker, "stop", None)
        if callable(stop_fn):
            await stop_fn()  # pylint: disable=not-callable


__all__ = ["AppServiceManager"]
