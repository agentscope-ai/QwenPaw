# -*- coding: utf-8 -*-
"""E2B sandbox provider: routes CoPaw tool execution into E2B sandboxes.

This provider implements SandboxProvider by wrapping SandboxRegistry.
The E2B SDK is redirected to sandbox-manager (instead of E2B cloud) via:

    E2B_API_URL=http://<sandbox-manager-host>/e2b
    E2B_API_KEY=<bearer_token>

The CoPaw Pod and the E2B sandbox Pod run as separate, independent
Kubernetes Pods. Communication is over HTTP (E2B SDK protocol).

Usage::

    provider = E2BSandboxProvider(template_id="base")
    sandbox = await provider.get_or_create(session_id, user_id)
    # pass sandbox to CoPawAgent — it routes shell/python into the remote Pod
    await provider.release(session_id, user_id)
"""

import logging
from typing import Optional

from ...app.runner.sandbox_registry import (
    SandboxRegistry,
)  # pylint: disable=no-name-in-module

logger = logging.getLogger(__name__)


class E2BSandboxProvider:
    """SandboxProvider implementation backed by E2B (via sandbox-manager).

    Wraps SandboxRegistry so that the E2B-specific creation/release logic
    stays in sandbox_registry.py while runner.py only sees the generic
    SandboxProvider interface.

    The E2B sandbox Pods are completely separate from the CoPaw Pod;
    they communicate over the HTTP API exposed by sandbox-manager.
    """

    def __init__(self, template_id: str = "base") -> None:
        """Initialize E2BSandboxProvider.

        Args:
            template_id: E2B template name used when creating new sandboxes.
                Must match a template configured in sandbox-manager.
        """
        self._registry = SandboxRegistry(template_id=template_id)
        logger.info(
            "E2BSandboxProvider initialized (template_id=%s)",
            template_id,
        )

    async def get_or_create(
        self,
        session_id: str,
        user_id: str = "",
    ) -> Optional[object]:
        """Return existing E2B sandbox for (user_id, session_id) or create one.

        Args:
            session_id: CoPaw session identifier.
            user_id: Caller user identifier (tenant isolation key).

        Returns:
            e2b.Sandbox instance bound to the session.
        """
        return await self._registry.get_or_create(session_id, user_id)

    async def release(
        self,
        session_id: str,
        user_id: str = "",
    ) -> None:
        """Kill and remove the E2B sandbox for (user_id, session_id).

        Args:
            session_id: CoPaw session identifier.
            user_id: Caller user identifier.
        """
        await self._registry.release(session_id, user_id)

    async def release_all(self) -> None:
        """Kill all tracked E2B sandboxes. Called on runner shutdown."""
        await self._registry.release_all()

    @property
    def template_id(self) -> str:
        """Return the E2B template ID used for new sandboxes."""
        return self._registry.template_id

    def __len__(self) -> int:
        return len(self._registry)
