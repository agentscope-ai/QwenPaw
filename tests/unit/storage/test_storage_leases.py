# -*- coding: utf-8 -*-
"""Reject old owners after release, expiry, and backend epoch changes."""

import pytest

from qwenpaw.storage.errors import StorageMaintenanceError
from qwenpaw.storage.repositories.leases import Leases, check_lease
from qwenpaw.storage.schema import fence_write


@pytest.mark.asyncio
async def test_takeover_advances_token_and_rejects_stale_owner(db):
    leases = Leases(db, 1)
    first = await leases.acquire(f"store", f"session", f"owner-a")
    with pytest.raises(StorageMaintenanceError):
        await leases.acquire(f"store", f"session", f"owner-b")
    await leases.renew(first)
    await leases.release(first)
    second = await leases.acquire(f"store", f"session", f"owner-b")
    assert second.token > first.token
    with pytest.raises(StorageMaintenanceError):
        await leases.renew(first)
    await leases.release(first)
    async with db.transaction(write=True) as tx:
        await fence_write(db, tx, 1)
        await check_lease(db, tx, second)
        with pytest.raises(StorageMaintenanceError):
            await check_lease(db, tx, first)


@pytest.mark.asyncio
async def test_expired_owner_cannot_renew_and_same_owner_gets_new_token(db):
    leases = Leases(db, 1)
    first = await leases.acquire(f"store", f"session", f"owner")
    async with db.transaction(write=True) as tx:
        await tx.execute(f"UPDATE {db.table('leases')} SET expires_at=0")
    with pytest.raises(StorageMaintenanceError):
        await leases.renew(first)
    second = await leases.acquire(f"store", f"session", f"owner")
    assert second.token > first.token
