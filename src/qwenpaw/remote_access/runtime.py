# -*- coding: utf-8 -*-
"""Lifecycle-owned Platform connection for a single QwenPaw Runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlencode

from ..constant import EnvVarLoader
from .connection import RelayNodeConnectionService, RelayNodeSupervisor
from .enrollment import RelayEnrollmentService
from .node_transport import RelayNodeTransport
from .operation_dispatcher import RelayLocalApi
from .store import RelayNodeStore


class PlatformRuntimeConnection:
    """Own one binding, account login, and reconnect loop."""

    def __init__(
        self,
        secret_dir: Path,
        base_url: str | Callable[[], str],
        headers: Callable[[], Mapping[str, str]] | None = None,
        *,
        store: RelayNodeStore | None = None,
    ) -> None:
        self.store = store or RelayNodeStore(secret_dir / "platform-node.json")
        self.account = RelayEnrollmentService(self.store)
        local_api = RelayLocalApi(base_url, headers=headers or self._headers)
        self.supervisor = RelayNodeSupervisor(
            RelayNodeConnectionService(
                self.store,
                RelayNodeTransport(local_api.dispatcher()),
            ),
        )

    @staticmethod
    def _headers() -> dict[str, str]:
        token = EnvVarLoader.get_str("QWENPAW_RUNTIME_INTERNAL_TOKEN", "")
        return {"X-QwenPaw-Runtime-Token": token} if token else {}

    async def start(self) -> None:
        """Restore the registered Node before the first Console visit."""
        state = await asyncio.to_thread(self.store.load)
        if state and state.registered_node:
            self.supervisor.start()

    async def close(self) -> None:
        """Detach streams and close the outbound transport at shutdown."""
        await self.supervisor.stop()

    async def mobile_login(self) -> dict:
        """Create an explicit full-account mobile login request."""
        status = await self.account.status()
        if not status.node_id or not status.platform_url:
            raise ValueError("Bind this QwenPaw to Platform first")
        result = dict(
            await self.account.account_request(
                "POST",
                "/api/v1/qwenpaw-web/login-requests",
                {"node_id": status.node_id},
            ),
        )
        query = urlencode({"node_id": status.node_id})
        result["url"] = (
            f"{status.platform_url}/m/?{query}"
            f"#ticket={result.pop('ticket')}"
        )
        return result
