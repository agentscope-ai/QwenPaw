# -*- coding: utf-8 -*-
"""Date-stamped, independently readable SQLite backups before replacement."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import StorageIdentityError


def _backup_sqlite(
    source: Path,
    migration_id: str,
    prior_identity: dict,
) -> Path:
    """Materialize committed WAL pages without renaming the source files."""
    source = source.resolve()
    uri = f"{source.as_uri()}?mode=ro"
    stamp = datetime.now(timezone.utc).strftime(f"%Y%m%dT%H%M%S.%fZ")
    directory = source.parent / f"backups"
    destination = directory / f"{source.name}.{stamp}.{uuid4().hex}.backup"
    manifest_path = destination.with_name(f"{destination.name}.json")
    # Open the source first: missing/corrupt sources are not empty databases.
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as origin:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.close(descriptor)
        try:
            with closing(sqlite3.connect(destination)) as target:
                origin.backup(target)
                results = target.execute(f"PRAGMA quick_check").fetchall()
                if results != [(f"ok",)]:
                    raise StorageIdentityError(
                        f"SQLite backup integrity check failed",
                    )
            with destination.open(f"r+b") as stream:
                digest = hashlib.file_digest(stream, f"sha256").hexdigest()
                os.fsync(stream.fileno())
            manifest = {
                f"status": f"verified",
                f"created_at": stamp,
                f"source": str(source),
                f"migration_id": migration_id,
                f"prior_identity": prior_identity,
                f"sha256": digest,
                f"size_bytes": destination.stat().st_size,
            }
            descriptor = os.open(
                manifest_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, f"w", encoding=f"utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            # A missing verified manifest makes this artifact non-restorable.
            # Preserve it for diagnosis; never touch the original database.
            if destination.exists():
                destination.rename(
                    destination.with_name(f"{destination.name}.failed"),
                )
            raise
    return destination


async def backup_sqlite(
    source: Path,
    *,
    migration_id: str,
    prior_identity: dict,
) -> Path:
    """Back up off-loop; a failure must abort replacement of the target."""
    return await asyncio.to_thread(
        _backup_sqlite,
        source,
        migration_id,
        prior_identity,
    )
