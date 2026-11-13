# -*- coding: utf-8 -*-
"""Per-workspace workspace + sandbox manager (interface only).

The concrete implementation is provided by a separate workstream.
This module defines the lifecycle contract (``start`` / ``stop``)
and the relationship between ``WorkspaceManager`` and ``Sandbox``.

``WorkspaceManager`` is per-workspace, held by ``Workspace.service_manager``.
``Sandbox`` handles resource-boundary checks; tools declare their
requirements via ``ToolDescriptor.requires_sandbox``.
``GuardedFunctionTool.check_permissions`` calls sandbox checks
before ``tool.func()``, so individual tools don't need to.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sandbox import Sandbox


class WorkspaceManager:
    """Per-workspace resource manager for file system roots, shell, and I/O.

    Parameters
    ----------
    working_dir:
        The agent's workspace root directory.
    sandbox:
        The sandbox instance enforcing resource boundaries.
    """

    def __init__(
        self,
        *,
        working_dir: Path,
        sandbox: "Sandbox | None" = None,
    ) -> None:
        self.working_dir: Path = working_dir
        self.sandbox: Sandbox | None = sandbox

    async def start(self) -> None:
        """Initialize workspace resources.

        Concrete implementation sets up working directory,
        validates paths, and prepares the sandbox.
        """

    async def stop(self) -> None:
        """Release workspace resources.

        Concrete implementation cleans up temporary files
        and shuts down sandbox enforcement.
        """


__all__ = ["WorkspaceManager"]
