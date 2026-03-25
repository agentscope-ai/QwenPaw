# -*- coding: utf-8 -*-
"""Null sandbox provider: no-op implementation for local execution fallback.

When sandbox mode is disabled (config.sandbox.enabled = False) or when
the E2B provider fails to initialise, AgentRunner uses NullSandboxProvider
so that all tool calls run in the CoPaw Pod's local process.

This keeps runner.py's query_handler free of ``if sandbox_provider is None``
guards — it always calls the same SandboxProvider interface regardless of
whether a real sandbox backend is wired up.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class NullSandboxProvider:
    """No-op SandboxProvider: get_or_create always returns None.

    When CoPawAgent receives ``sandbox=None`` it falls back to the
    built-in local ``execute_shell_command`` and ``execute_python_code``
    tools, which run commands in the CoPaw Pod's own process.
    """

    async def get_or_create(
        self,
        session_id: str,  # pylint: disable=unused-argument
        user_id: str = "",  # pylint: disable=unused-argument
    ) -> Optional[object]:
        """Return None — no sandbox is created for local execution.

        Args:
            session_id: CoPaw session identifier (ignored).
            user_id: Caller user identifier (ignored).

        Returns:
            Always None.
        """
        return None

    async def release(
        self,
        session_id: str,
        user_id: str = "",
    ) -> None:
        """No-op: nothing to release.

        Args:
            session_id: CoPaw session identifier (ignored).
            user_id: Caller user identifier (ignored).
        """

    async def release_all(self) -> None:
        """No-op: nothing to release."""
