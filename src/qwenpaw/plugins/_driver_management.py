# -*- coding: utf-8 -*-
"""Host-issued credential overlays for a single management transaction."""

import copy
import time
from dataclasses import dataclass, field
from typing import Any

from ..drivers.contracts import DriverCard
from ..drivers.credentials.types import CredentialRecord
from .errors import SDKAccessError, StaleContextError


class _OverlayStore:
    def __init__(self, record, base):
        self.record = copy.deepcopy(record)
        self.revision = 0
        self.base = base

    async def get_versioned(self, ref):
        if ref == self.record.ref:
            return copy.deepcopy(self.record), self.revision
        if self.base is not None:
            return await self.base.get_versioned(ref)
        raise SDKAccessError("Credential is outside the management grant")

    async def compare_and_put(
        self,
        ref,
        *,
        expected_revision,
        public,
        secrets,
    ):
        # No await: compare and replace is indivisible on the owning loop.
        if ref != self.record.ref or expected_revision != self.revision:
            raise SDKAccessError("Management credential revision is stale")
        self.record = CredentialRecord(
            ref,
            self.record.kind,
            copy.deepcopy(dict(public)),
            copy.deepcopy(dict(secrets)),
            {**self.record.meta, "updated_at": time.time()},
        )
        self.revision += 1


@dataclass
class CredentialOverlayGrant:
    """Private host capability; never reconstructed from request data."""

    plugin_id: str
    generation: int
    workspace_id: str
    workspace_instance_id: str
    user_id: str
    channel: str
    card: DriverCard = field(repr=False)
    alias: str
    record: CredentialRecord = field(repr=False)
    expires_at: float
    base_store: Any = field(default=None, repr=False)
    store: _OverlayStore = field(init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        self.card = copy.deepcopy(self.card)
        self.record = copy.deepcopy(self.record)
        self.store = _OverlayStore(self.record, self.base_store)

    def check(
        self,
        *,
        plugin_id,
        generation,
        workspace_id,
        workspace_instance_id,
        user_id,
        channel,
    ):
        if self._closed or self.expires_at <= time.monotonic():
            raise StaleContextError("Driver management grant expired")
        if (
            plugin_id,
            generation,
            workspace_id,
            workspace_instance_id,
            user_id,
            channel,
        ) != (
            self.plugin_id,
            self.generation,
            self.workspace_id,
            self.workspace_instance_id,
            self.user_id,
            self.channel,
        ):
            raise SDKAccessError("Driver management grant identity mismatch")

    def close(self):
        self._closed = True
        # Drop token copies as soon as this transaction becomes terminal.
        self.store.record = CredentialRecord(
            self.record.ref,
            self.record.kind,
        )
        self.record = self.store.record
