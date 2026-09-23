# -*- coding: utf-8 -*-
"""Tenant-scoped JSON records and idempotent usage events."""

from __future__ import annotations

import json
from typing import Any

from ..contracts.database import Database
from ..errors import MigrationConflictError
from ..schema import fence_write


def encode(value: Any) -> str:
    """Serialize portable values deterministically for migration checks."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(f",", f":"),
        allow_nan=False,
    )


class Records:
    """Perform optimistic updates without overwriting other instances."""

    def __init__(self, db: Database, tenant_id: str, epoch: int) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self.epoch = epoch

    async def get(self, collection: str, key: str) -> tuple[Any, int] | None:
        """Load a record and its compare-and-set revision."""
        db = self.db
        async with db.transaction() as tx:
            row = await tx.one(
                f"SELECT payload, revision FROM {db.table('records')} "
                f"WHERE tenant_id={db.bind(1)} "
                f"AND collection={db.bind(2)} AND record_id={db.bind(3)}",
                self.tenant_id,
                collection,
                key,
            )
        if row is None:
            return None
        return json.loads(row[f"payload"]), row[f"revision"]

    async def put(
        self,
        collection: str,
        key: str,
        value: Any,
        *,
        revision: int = 0,
    ) -> int:
        """Create at revision zero, otherwise replace the exact revision."""
        db = self.db
        payload = encode(value)
        async with db.transaction(write=True) as tx:
            await fence_write(db, tx, self.epoch)
            if revision == 0:
                row = await tx.one(
                    f"INSERT INTO {db.table('records')} "
                    f"VALUES ({db.binds(3)}, 1, {db.bind(4)}) "
                    f"ON CONFLICT (tenant_id, collection, record_id) "
                    f"DO NOTHING RETURNING revision",
                    self.tenant_id,
                    collection,
                    key,
                    payload,
                )
            else:
                row = await tx.one(
                    f"UPDATE {db.table('records')} SET payload={db.bind(1)}, "
                    f"revision=revision+1 WHERE tenant_id={db.bind(2)} "
                    f"AND collection={db.bind(3)} AND record_id={db.bind(4)} "
                    f"AND revision={db.bind(5)} RETURNING revision",
                    payload,
                    self.tenant_id,
                    collection,
                    key,
                    revision,
                )
            if row is None:
                raise MigrationConflictError(f"Record revision changed")
        return row[f"revision"]

    async def record_usage(self, event_id: str, payload: dict) -> bool:
        """Persist an event once, independent of retries or replica count."""
        db = self.db
        encoded = encode(payload)
        async with db.transaction(write=True) as tx:
            await fence_write(db, tx, self.epoch)
            row = await tx.one(
                f"INSERT INTO {db.table('usage')} VALUES ({db.binds(3)}) "
                f"ON CONFLICT (tenant_id, event_id) DO NOTHING "
                f"RETURNING event_id",
                self.tenant_id,
                event_id,
                encoded,
            )
            if row is None:
                existing = await tx.one(
                    f"SELECT payload FROM {db.table('usage')} "
                    f"WHERE tenant_id={db.bind(1)} AND event_id={db.bind(2)}",
                    self.tenant_id,
                    event_id,
                )
                assert existing is not None
                if existing[f"payload"] != encoded:
                    raise MigrationConflictError(
                        f"Usage event identity reused",
                    )
        return row is not None
