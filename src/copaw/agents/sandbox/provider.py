# -*- coding: utf-8 -*-
# pylint: disable=unnecessary-ellipsis
"""SandboxProvider Protocol: the plugin interface for sandbox backends.

CoPaw core depends only on this interface. Concrete implementations
(E2B, local no-op, remote HTTP, etc.) are injected at runtime via
AgentRunner.sandbox_provider.

To add a new sandbox backend:
  1. Create a class that implements the three async methods below.
  2. Instantiate it in runner.py init_handler and assign it to
     ``self.sandbox_provider``.

No base class is required — Python's structural subtyping (Protocol)
means any object with the right method signatures is accepted.
"""

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class SandboxProvider(Protocol):
    """Abstract plugin interface for sandbox implementations.

    Concrete implementations must provide three async methods:
      - get_or_create: return (or lazily create) a sandbox for the session
      - release: kill and remove the sandbox after a query completes
      - release_all: kill all sandboxes on runner shutdown
    """

    async def get_or_create(
        self,
        session_id: str,
        user_id: str = "",
    ) -> Optional[object]:
        """Return the sandbox instance for (user_id, session_id).

        Creates a new sandbox if one does not already exist for the pair.

        Args:
            session_id: CoPaw session identifier.
            user_id: Caller user identifier (used for tenant isolation).

        Returns:
            A sandbox instance (e.g. e2b.Sandbox), or None when no
            sandbox is needed (NullSandboxProvider).
        """
        ...

    async def release(
        self,
        session_id: str,
        user_id: str = "",
    ) -> None:
        """Release the sandbox associated with (user_id, session_id).

        No-op if no sandbox is tracked for the given pair.

        Args:
            session_id: CoPaw session identifier.
            user_id: Caller user identifier (must match get_or_create call).
        """
        ...

    async def release_all(self) -> None:
        """Release all tracked sandboxes.

        Called on AgentRunner shutdown to ensure no orphaned sandboxes.
        """
        ...
