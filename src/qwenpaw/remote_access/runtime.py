# -*- coding: utf-8 -*-
"""Lifecycle-owned Platform connection for a single QwenPaw Runtime."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlencode

from ..utils.io_utils import run_sync_io
from .connection import RelayNodeConnectionService, RelayNodeSupervisor
from .enrollment import RelayEnrollmentService
from .node_transport import RelayNodeTransport
from .operation_dispatcher import RelayLocalApi, RuntimeEndpoint
from .run_state import RelayRuns
from .store import RelayNodeStateError, RelayNodeStore

logger = logging.getLogger(__name__)


class PlatformRuntimeConnection:
    """Own one binding, account login, and reconnect loop."""

    def __init__(
        self,
        secret_dir: Path,
        endpoint: RuntimeEndpoint,
        *,
        store: RelayNodeStore | None = None,
        runs: RelayRuns | None = None,
        hub_managed: bool = False,
    ) -> None:
        self.store = store or RelayNodeStore(secret_dir / "platform-node.json")
        self.account = RelayEnrollmentService(self.store)
        self.runs = runs if runs is not None else RelayRuns()
        local_api = RelayLocalApi(endpoint)
        self._local_api = local_api
        self.supervisor = RelayNodeSupervisor(
            RelayNodeConnectionService(
                self.store,
                RelayNodeTransport(
                    local_api.dispatcher(),
                    runs=self.runs,
                    sync_runs=local_api.sync_runs if hub_managed else None,
                ),
            ),
        )

    async def start(self) -> None:
        """Restore the registered Node before the first Console visit."""
        async with self.store.mutation_lock:
            try:
                state = await asyncio.to_thread(self.store.load)
            except RelayNodeStateError as exc:
                logger.warning(
                    "Cannot restore Platform binding: %s",
                    type(exc.__cause__).__name__,
                )
                return
            if state and state.registered_node:
                self.supervisor.start()

    async def disconnect(self) -> bool:
        """Stop access locally before contacting the account service."""
        async with self.store.mutation_lock:
            await self.close()
            self.account.cancel_login()
            try:
                state = await asyncio.to_thread(self.store.load)
            except RelayNodeStateError:
                await run_sync_io(self.store.quarantine)
                return False
            await run_sync_io(self.store.path.unlink, missing_ok=True)
        return await self.account.revoke_binding(state)

    async def close(self) -> None:
        """Detach streams and close the outbound transport at shutdown."""
        try:
            await self.supervisor.stop()
        finally:
            await self._local_api.close()

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
