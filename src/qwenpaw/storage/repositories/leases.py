# -*- coding: utf-8 -*-
"""Database-clock session ownership with monotonic fencing tokens."""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.database import Database, Transaction
from ..errors import StorageMaintenanceError
from ..schema import fence_write


@dataclass(frozen=True)
class SessionLease:
    """Ownership must be checked in the same transaction as the write."""

    store_id: str
    session_id: str
    owner_id: str
    token: int


class Leases:
    """Acquire and renew one session without deleting its token history."""

    def __init__(self, db: Database, epoch: int) -> None:
        self.db, self.epoch = db, epoch

    async def acquire(
        self,
        store_id: str,
        session_id: str,
        owner_id: str,
        *,
        ttl: float = 30,
    ) -> SessionLease:
        """Claim an unowned or expired session; a new owner advances token."""
        if ttl <= 0 or ttl > 300:
            raise ValueError(f"Lease TTL must be in (0, 300]")
        db = self.db
        async with db.transaction(write=True) as tx:
            await fence_write(db, tx, self.epoch)
            now = db.clock()
            row = await tx.one(
                f"SELECT * FROM {db.table('leases')} "
                f"WHERE store_id={db.bind(1)} AND session_id={db.bind(2)}",
                store_id,
                session_id,
            )
            if row is None:
                await tx.execute(
                    f"INSERT INTO {db.table('leases')} "
                    f"VALUES ({db.binds(3)}, 1, {now}+{db.bind(4)})",
                    store_id,
                    session_id,
                    owner_id,
                    ttl,
                )
                return SessionLease(store_id, session_id, owner_id, 1)
            # Even the same owner must advance its token after expiry: an
            # older task under that owner must not resume after a new claim.
            renewed = await tx.one(
                f"UPDATE {db.table('leases')} SET "
                f"token=CASE WHEN expires_at>{now} "
                f"THEN token ELSE token+1 END, "
                f"owner_id={db.bind(1)}, expires_at={now}+{db.bind(2)} "
                f"WHERE store_id={db.bind(3)} AND session_id={db.bind(4)} "
                f"AND (owner_id={db.bind(5)} OR expires_at<={now}) "
                f"RETURNING token",
                owner_id,
                ttl,
                store_id,
                session_id,
                owner_id,
            )
            if renewed is None:
                raise StorageMaintenanceError(
                    f"Session is owned by another instance",
                )
            return SessionLease(
                store_id,
                session_id,
                owner_id,
                renewed[f"token"],
            )

    async def renew(self, lease: SessionLease, *, ttl: float = 30) -> None:
        """Do not resurrect expired ownership during a delayed renewal."""
        if ttl <= 0 or ttl > 300:
            raise ValueError(f"Lease TTL must be in (0, 300]")
        db = self.db
        async with db.transaction(write=True) as tx:
            await fence_write(db, tx, self.epoch)
            await check_lease(db, tx, lease)
            await tx.execute(
                f"UPDATE {db.table('leases')} "
                f"SET expires_at={db.clock()}+{db.bind(1)} "
                f"WHERE store_id={db.bind(2)} AND session_id={db.bind(3)}",
                ttl,
                lease.store_id,
                lease.session_id,
            )

    async def release(self, lease: SessionLease) -> None:
        """Expire only the exact owner; never erase its fencing counter."""
        db = self.db
        async with db.transaction(write=True) as tx:
            await fence_write(db, tx, self.epoch)
            await tx.execute(
                f"UPDATE {db.table('leases')} SET expires_at=0 "
                f"WHERE store_id={db.bind(1)} AND session_id={db.bind(2)} "
                f"AND owner_id={db.bind(3)} AND token={db.bind(4)}",
                lease.store_id,
                lease.session_id,
                lease.owner_id,
                lease.token,
            )


async def check_lease(
    db: Database,
    tx: Transaction,
    lease: SessionLease,
) -> None:
    """Reject a stale writer inside its already fenced write transaction."""
    row = await tx.one(
        f"SELECT token FROM {db.table('leases')} "
        f"WHERE store_id={db.bind(1)} AND session_id={db.bind(2)} "
        f"AND owner_id={db.bind(3)} AND token={db.bind(4)} "
        f"AND expires_at>{db.clock()}",
        lease.store_id,
        lease.session_id,
        lease.owner_id,
        lease.token,
    )
    if row is None:
        raise StorageMaintenanceError(
            f"Session ownership expired or was replaced",
        )
