# -*- coding: utf-8 -*-
"""Explicit, reversible migration with fenced restart activation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from ..contracts.database import Database
from ..errors import MigrationConflictError, StorageMaintenanceError
from ..repositories.records import encode
from ..schema import identity, validate
from ..migration.snapshot import (
    export_snapshot,
    import_snapshot,
    read_manifest,
    ORDER,
)


async def inspect(db: Database) -> dict:
    """Read identity and exact replacement counts, without changing data."""
    meta = await validate(db)
    counts = {}
    async with db.transaction() as tx:
        for table in ORDER:
            row = await tx.one(f"SELECT COUNT(*) AS n FROM {db.table(table)}")
            assert row is not None
            counts[table] = row[f"n"]
    return {f"identity": meta, f"counts": counts}


async def _transition(
    db: Database,
    expected: dict,
    status: str,
    job_id: str,
) -> None:
    async with db.transaction(write=True) as tx:
        current = await identity(db, tx)
        if current != expected:
            raise MigrationConflictError(
                f"Storage changed since the migration plan",
            )
        if status == f"frozen":
            active = await tx.one(
                f"SELECT token FROM {db.table('leases')} "
                f"WHERE expires_at>{db.clock()} LIMIT 1",
            )
            if active is not None:
                raise StorageMaintenanceError(
                    f"Drain active sessions before migrating storage",
                )
        row = await tx.one(
            f"UPDATE {db.table('metadata')} SET status={db.bind(1)}, "
            f"migration_id={db.bind(2)} WHERE singleton=1 "
            f"AND revision={db.bind(3)} AND status={db.bind(4)} "
            f"AND epoch={db.bind(5)} RETURNING singleton",
            status,
            job_id,
            expected[f"revision"],
            expected[f"status"],
            expected[f"epoch"],
        )
        if row is None:
            raise MigrationConflictError(
                f"Concurrent migration or writer detected",
            )


async def _restore_status(db: Database, before: dict, job_id: str) -> None:
    async with db.transaction(write=True) as tx:
        await tx.execute(
            f"UPDATE {db.table('metadata')} SET status={db.bind(1)}, "
            f"migration_id={db.bind(2)} WHERE singleton=1 "
            f"AND migration_id={db.bind(3)} AND status='frozen'",
            before[f"status"],
            before[f"migration_id"],
            job_id,
        )


async def _save_job(
    db: Database,
    job_id: str,
    phase: str,
    payload: dict,
) -> None:
    async with db.transaction(write=True) as tx:
        await tx.execute(
            f"INSERT INTO {db.table('migration_jobs')} VALUES ({db.binds(3)}) "
            f"ON CONFLICT (job_id) DO UPDATE "
            f"SET phase=excluded.phase, payload=excluded.payload",
            job_id,
            phase,
            encode(payload),
        )


class MigrationService:
    """Coordinate two backend endpoints through one migration state machine.

    Both databases must already be open and initialized. The service never
    owns their connections and never selects a driver from configuration.
    """

    def __init__(self, source: Database, target: Database) -> None:
        self.source = source
        self.target = target

    async def plan(self) -> dict:
        """Bind approval to both dataset revisions and the exact namespaces."""
        source, target = self.source, self.target
        origin, destination = await inspect(source), await inspect(target)
        if origin[f"identity"][f"status"] != f"active":
            raise StorageMaintenanceError(f"Source is not active")
        if destination[f"identity"][f"status"] not in (f"active", f"retired"):
            raise StorageMaintenanceError(
                f"Target already has a pending migration",
            )
        value = {
            f"source": origin,
            f"target": destination,
            f"source_config": source.config.model_dump(by_alias=True),
            f"target_config": target.config.model_dump(by_alias=True),
            f"source_root": str(source.root.resolve()),
            f"target_root": str(target.root.resolve()),
            f"requires_overwrite": any(destination[f"counts"].values()),
        }
        value[f"plan_hash"] = hashlib.sha256(
            encode(value).encode(),
        ).hexdigest()
        return value

    async def migrate(  # pylint: disable=too-many-statements
        self,
        approved: dict,
        *,
        backup_root: Path,
        overwrite_hash: str | None = None,
    ) -> dict:
        """Copy confirmed data; leave both ends fenced until restart."""
        source, target = self.source, self.target
        current = await self.plan()
        if current != approved:
            raise MigrationConflictError(f"Migration plan is stale")
        if (
            current[f"requires_overwrite"]
            and overwrite_hash != current[f"plan_hash"]
        ):
            raise MigrationConflictError(
                f"Target contains data; confirm its plan hash",
            )
        job_id = str(uuid4())
        origin = current[f"source"][f"identity"]
        destination = current[f"target"][f"identity"]
        backup = backup_root / job_id
        payload = {**current, f"job_id": job_id, f"backup": str(backup)}
        await _save_job(source, job_id, f"planned", payload)
        await _transition(source, origin, f"frozen", job_id)
        target_frozen = False
        prepared = False
        try:
            # If aliases point at the same physical namespace, its status has
            # just changed and this comparison rejects copying onto itself.
            await _transition(target, destination, f"frozen", job_id)
            target_frozen = True
            if current[f"requires_overwrite"]:
                native_backup = await target.backup_native(
                    migration_id=job_id,
                    prior_identity=destination,
                )
                payload[f"native_backup"] = (
                    str(native_backup) if native_backup is not None else None
                )
                await _save_job(source, job_id, f"copying", payload)
            await _save_job(target, job_id, f"copying", payload)
            await export_snapshot(source, backup / f"source")
            await export_snapshot(target, backup / f"target")
            manifest = await read_manifest(backup / f"source")
            epoch = max(origin[f"epoch"], destination[f"epoch"]) + 1
            async with target.transaction(write=True) as tx:
                meta = await identity(target, tx)
                if (
                    meta[f"status"] != f"frozen"
                    or meta[f"migration_id"] != job_id
                ):
                    raise MigrationConflictError(
                        f"Target migration ownership changed",
                    )
                await import_snapshot(target, tx, backup / f"source", manifest)
                await tx.execute(
                    f"UPDATE {target.table('metadata')} SET "
                    f"deployment_id={target.bind(1)}, "
                    f"dataset_id={target.bind(2)}, "
                    f"epoch={target.bind(3)}, revision={target.bind(4)}, "
                    f"status='prepared' WHERE singleton=1",
                    target.config.deployment_id,
                    origin[f"dataset_id"],
                    epoch,
                    origin[f"revision"],
                )
                await tx.execute(
                    f"UPDATE {target.table('migration_jobs')} "
                    f"SET phase='prepared' "
                    f"WHERE job_id={target.bind(1)}",
                    job_id,
                )
            prepared = True
            # Re-read complete target data before allowing activation. A failed
            # verification leaves both sides fenced for explicit recovery.
            verified = await export_snapshot(target, backup / f"verification")
            if verified[f"tables"] != manifest[f"tables"]:
                raise MigrationConflictError(f"Target verification failed")
            frozen = await identity(source)
            await _transition(source, frozen, f"retired", job_id)
            await _save_job(source, job_id, f"awaiting_restart", payload)
            await _save_job(target, job_id, f"awaiting_restart", payload)
            return {
                f"job_id": job_id,
                f"epoch": epoch,
                f"status": f"awaiting_restart",
                f"backup": str(backup),
                f"native_backup": payload.get(f"native_backup"),
                f"message": (
                    f"Migration verified. " f"Restart to activate storage."
                ),
            }
        except BaseException:
            # Inspect the commit record even if COMMIT's response was lost.
            # Never reactivate the source if target commit is uncertain.
            target_meta = await identity(target)
            prepared = prepared or (
                target_meta[f"migration_id"] == job_id
                and target_meta[f"status"] in (f"prepared", f"active")
            )
            if not prepared:
                if target_frozen:
                    await _restore_status(target, destination, job_id)
                await _restore_status(source, origin, job_id)
            raise

    async def activate(self, job_id: str) -> int:
        """Activate only after restart has selected the migrated target."""
        source, target = self.source, self.target
        origin = await identity(source)
        if (
            origin[f"status"] != f"retired"
            or origin[f"migration_id"] != job_id
        ):
            raise StorageMaintenanceError(
                f"Source is not fenced for this migration",
            )
        async with target.transaction(write=True) as tx:
            destination = await identity(target, tx)
            if destination[f"migration_id"] != job_id:
                raise MigrationConflictError(
                    f"Target belongs to another migration",
                )
            if destination[f"dataset_id"] != origin[f"dataset_id"]:
                raise MigrationConflictError(f"Dataset identity changed")
            if destination[f"status"] not in (f"prepared", f"active"):
                raise StorageMaintenanceError(f"Target is not prepared")
            await tx.execute(
                f"UPDATE {target.table('metadata')} "
                f"SET status='active' WHERE singleton=1",
            )
            await tx.execute(
                f"UPDATE {target.table('migration_jobs')} "
                f"SET phase='complete' "
                f"WHERE job_id={target.bind(1)}",
                job_id,
            )
        return destination[f"epoch"]

    async def recover(
        self,
        job_id: str,
        *,
        backup_root: Path,
    ) -> dict:
        """Recover an interrupted copy while preventing concurrent writers."""
        source, target = self.source, self.target
        origin, destination = await identity(source), await identity(target)
        if origin[f"migration_id"] != job_id:
            raise MigrationConflictError(
                f"Source belongs to another migration",
            )
        if destination[f"migration_id"] != job_id:
            raise MigrationConflictError(
                f"Target belongs to another migration",
            )
        async with source.transaction() as tx:
            job = await tx.one(
                f"SELECT payload FROM {source.table('migration_jobs')} "
                f"WHERE job_id={source.bind(1)}",
                job_id,
            )
        if job is None:
            raise MigrationConflictError(f"Migration journal is missing")
        payload = json.loads(job[f"payload"])
        if destination[f"status"] == f"active":
            if origin[f"status"] != f"retired":
                raise StorageMaintenanceError(
                    f"Ambiguous migration activation",
                )
            return {f"job_id": job_id, f"status": f"complete"}
        if (
            destination[f"status"] == f"frozen"
            and origin[f"status"] == f"frozen"
        ):
            # Replacement and the prepared marker share one target transaction.
            # A frozen target therefore still contains the pre-migration data.
            await _restore_status(
                target,
                payload[f"target"][f"identity"],
                job_id,
            )
            await _restore_status(
                source,
                payload[f"source"][f"identity"],
                job_id,
            )
            await _save_job(source, job_id, f"aborted", payload)
            return {f"job_id": job_id, f"status": f"aborted"}
        if destination[f"status"] != f"prepared" or origin[f"status"] not in (
            f"frozen",
            f"retired",
        ):
            raise StorageMaintenanceError(
                f"Migration requires manual diagnosis",
            )
        manifest = await read_manifest(Path(payload[f"backup"]) / f"source")
        expected = manifest[f"identity"]
        for key in (f"dataset_id", f"revision", f"format_version"):
            if (
                origin[key] != expected[key]
                or destination[key] != expected[key]
            ):
                raise MigrationConflictError(
                    f"Migration identity or revision changed",
                )
        verified = await export_snapshot(
            target,
            backup_root / f"recovery-{job_id}-{uuid4().hex}",
        )
        if verified[f"tables"] != manifest[f"tables"]:
            raise MigrationConflictError(
                f"Prepared target differs from source snapshot",
            )
        if origin[f"status"] == f"frozen":
            await _transition(source, origin, f"retired", job_id)
        await _save_job(source, job_id, f"awaiting_restart", payload)
        await _save_job(target, job_id, f"awaiting_restart", payload)
        return {f"job_id": job_id, f"status": f"awaiting_restart"}
