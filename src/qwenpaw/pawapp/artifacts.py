# -*- coding: utf-8 -*-
"""Host-owned immutable artifact publication and scoped reads."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import math
import os
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .tasks.contracts import (
    ArtifactProducer,
    ArtifactCollection,
    ArtifactRef,
    TaskScope,
    TaskStoreError,
    TaskSubmission,
    canonical_json,
)

_T = TypeVar("_T")
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_TASK_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_TASK_ARTIFACTS = 128
MAX_ARTIFACT_LIST_LIMIT = 100
_SCHEMA_VERSION = 2
_GRANT_SCHEMA = """CREATE TABLE IF NOT EXISTS artifact_grants (
    artifact_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    principal_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    target_app_id TEXT NOT NULL,
    handoff_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(artifact_id, version, target_app_id, handoff_id)
)"""
_SCHEMA = (
    """CREATE TABLE artifact_versions (
        artifact_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        principal_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        app_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        logical_key TEXT NOT NULL,
        source_key TEXT NOT NULL UNIQUE,
        digest TEXT NOT NULL,
        ref_json TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY(artifact_id, version)
    )""",
    """CREATE INDEX artifact_scope ON artifact_versions(
        principal_id, workspace_id, app_id, artifact_id, version
    )""",
    """CREATE INDEX artifact_task ON artifact_versions(task_id)""",
    """CREATE TABLE artifact_audit (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL NOT NULL,
        principal_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        app_id TEXT NOT NULL,
        artifact_id TEXT NOT NULL,
        version INTEGER,
        operation TEXT NOT NULL,
        outcome TEXT NOT NULL
    )""",
    _GRANT_SCHEMA,
)


class _Publication(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=512)
    path: str = Field(min_length=1, max_length=4096)
    media_type: str = Field(min_length=1, max_length=256)
    size_bytes: int = Field(ge=0, le=MAX_ARTIFACT_BYTES)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("name")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        if value in {".", ".."} or any(char in value for char in "/\\\x00"):
            raise ValueError("artifact name must be a plain filename")
        return value

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        if (
            value.startswith(("/", "~"))
            or "\\" in value
            or "\x00" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("artifact path must be normalized and relative")
        return value


class ArtifactStore:
    """Content-addressed blobs with scoped, versioned metadata.

    Published versions are retained for the lifetime of the owning task. No
    automatic deletion runs in protocol 1. Per-file and per-task quotas bound
    local storage until a later retention policy is introduced.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "artifacts.sqlite3"
        self.blobs = self.root / "blobs" / "sha256"

    @classmethod
    async def open(cls, root: Path) -> ArtifactStore:
        store = cls(root)
        await asyncio.to_thread(store._initialize)
        return store

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.blobs.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(
            self.path,
            os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.close(descriptor)
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            elif version == 1:
                connection.execute(_GRANT_SCHEMA)
                connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            elif version != _SCHEMA_VERSION:
                raise TaskStoreError("unsupported_artifact_store_version")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def _run(
        self,
        operation: Callable[[sqlite3.Connection], _T],
        *,
        write: bool = False,
    ) -> _T:
        def transaction() -> _T:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                result = operation(connection)
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

        return await asyncio.to_thread(transaction)

    @staticmethod
    def _read_blob(blob: Path) -> bytes:
        descriptor = os.open(
            blob,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise TaskStoreError("artifact_blob_unavailable")
            return stream.read(MAX_ARTIFACT_BYTES + 1)

    def _write_blob(self, digest: str, content: bytes) -> None:
        blob = self.blobs / digest.removeprefix("sha256:")
        if os.path.lexists(blob):
            try:
                existing = self._read_blob(blob)
            except OSError:
                raise TaskStoreError("artifact_blob_unavailable") from None
            actual = "sha256:" + hashlib.sha256(existing).hexdigest()
            if len(existing) != len(content) or actual != digest:
                raise TaskStoreError("artifact_blob_conflict")
            return
        temporary = blob.with_name(
            f".{blob.name}.{os.getpid()}.{time.time_ns()}",
        )
        try:
            descriptor = os.open(
                temporary,
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, blob)
            except FileExistsError:
                try:
                    existing = self._read_blob(blob)
                except OSError:
                    raise TaskStoreError(
                        "artifact_blob_unavailable",
                    ) from None
                actual = "sha256:" + hashlib.sha256(existing).hexdigest()
                if len(existing) != len(content) or actual != digest:
                    raise TaskStoreError("artifact_blob_conflict")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    async def publish(
        self,
        submission: TaskSubmission,
        source: dict[str, Any],
        content: bytes,
    ) -> ArtifactRef:
        """Validate bytes and idempotently publish one executor artifact."""
        try:
            publication = _Publication.model_validate(source)
        except ValueError:
            raise TaskStoreError("invalid_artifact_metadata") from None
        if len(content) != publication.size_bytes:
            raise TaskStoreError("artifact_size_mismatch")
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if digest != publication.digest:
            raise TaskStoreError("artifact_digest_mismatch")
        handle = submission.handle
        run = handle.executor_run_ref
        if run is None:
            raise TaskStoreError("artifact_run_missing")
        logical_payload = [
            handle.scope.model_dump(mode="json"),
            handle.task_id,
            run.model_dump(mode="json"),
            publication.path,
        ]
        logical_key = hashlib.sha256(
            canonical_json(logical_payload).encode("utf-8"),
        ).hexdigest()
        artifact_id = "art_" + logical_key[:40]
        source_key = hashlib.sha256(
            canonical_json(
                [run.model_dump(mode="json"), publication.source_id],
            ).encode("utf-8"),
        ).hexdigest()

        def operation(connection: sqlite3.Connection) -> ArtifactRef:
            existing = connection.execute(
                "SELECT digest, ref_json FROM artifact_versions "
                "WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            if existing is not None:
                if existing["digest"] != digest:
                    raise TaskStoreError("artifact_source_conflict")
                return ArtifactRef.model_validate_json(existing["ref_json"])
            used = connection.execute(
                "SELECT COALESCE("
                "SUM(json_extract(ref_json, '$.size_bytes')), 0) "
                "FROM artifact_versions WHERE task_id = ?",
                (handle.task_id,),
            ).fetchone()[0]
            count = connection.execute(
                "SELECT COUNT(*) FROM artifact_versions WHERE task_id = ?",
                (handle.task_id,),
            ).fetchone()[0]
            if count >= MAX_TASK_ARTIFACTS:
                raise TaskStoreError("artifact_task_count_exceeded")
            if used + len(content) > MAX_TASK_ARTIFACT_BYTES:
                raise TaskStoreError("artifact_task_quota_exceeded")
            self._write_blob(digest, bytes(content))
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM artifact_versions "
                "WHERE logical_key = ?",
                (logical_key,),
            ).fetchone()
            version = int(row[0]) + 1
            created_at = time.time()
            ref = ArtifactRef(
                artifact_id=artifact_id,
                type="qwenpaw:file",
                version=version,
                name=publication.name,
                media_type=publication.media_type,
                size_bytes=publication.size_bytes,
                digest=digest,
                producer=ArtifactProducer(
                    app_id=handle.scope.app_id,
                    action_id=handle.action_id,
                    task_id=handle.task_id,
                    executor_id=run.executor_id,
                    session_id=run.session_id,
                    run_id=run.run_id,
                    source_id=publication.source_id,
                ),
                created_at=created_at,
            )
            connection.execute(
                """INSERT INTO artifact_versions
                (artifact_id, version, principal_id, workspace_id, app_id,
                 task_id, logical_key, source_key, digest, ref_json,
                 created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact_id,
                    version,
                    handle.scope.principal_id,
                    handle.scope.workspace_id,
                    handle.scope.app_id,
                    handle.task_id,
                    logical_key,
                    source_key,
                    digest,
                    ref.model_dump_json(),
                    created_at,
                ),
            )
            return ref

        return await self._run(operation, write=True)

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        scope: TaskScope,
        artifact_id: str,
        version: int | None,
        operation: str,
        outcome: str,
    ) -> None:
        connection.execute(
            "INSERT INTO artifact_audit VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                time.time(),
                scope.principal_id,
                scope.workspace_id,
                scope.app_id,
                artifact_id,
                version,
                operation,
                outcome,
            ),
        )

    async def read(
        self,
        scope: TaskScope,
        artifact_id: str,
        version: int,
    ) -> tuple[ArtifactRef, bytes]:
        """Read verified bytes, hiding whether inaccessible refs exist."""

        def operation(
            connection: sqlite3.Connection,
        ) -> tuple[ArtifactRef, str] | None:
            row = connection.execute(
                """SELECT ref_json, digest FROM artifact_versions
                WHERE artifact_id = ? AND version = ? AND principal_id = ?
                AND workspace_id = ? AND (
                    app_id = ? OR EXISTS (
                        SELECT 1 FROM artifact_grants grant_row
                        WHERE grant_row.artifact_id =
                            artifact_versions.artifact_id
                        AND grant_row.version = artifact_versions.version
                        AND grant_row.principal_id = ?
                        AND grant_row.workspace_id = ?
                        AND grant_row.target_app_id = ?
                    )
                )""",
                (
                    artifact_id,
                    version,
                    scope.principal_id,
                    scope.workspace_id,
                    scope.app_id,
                    scope.principal_id,
                    scope.workspace_id,
                    scope.app_id,
                ),
            ).fetchone()
            if row is None:
                self._audit(
                    connection,
                    scope,
                    artifact_id,
                    version,
                    "read",
                    "not_found",
                )
                return None
            self._audit(
                connection,
                scope,
                artifact_id,
                version,
                "read",
                "allowed",
            )
            ref = ArtifactRef.model_validate_json(row["ref_json"])
            return ref, row["digest"]

        result = await self._run(operation, write=True)
        if result is None:
            raise TaskStoreError("artifact_not_found")
        ref, digest = result
        blob = self.blobs / digest.removeprefix("sha256:")
        try:
            content = await asyncio.to_thread(self._read_blob, blob)
        except OSError:
            raise TaskStoreError("artifact_blob_unavailable") from None
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual != digest or len(content) != ref.size_bytes:
            raise TaskStoreError("artifact_blob_corrupt")
        return ref, content

    @staticmethod
    def _encode_cursor(created_at: float, artifact_id: str, version: int) -> str:
        payload = canonical_json([created_at, artifact_id, version]).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[float, str, int]:
        if not cursor or len(cursor) > 512:
            raise TaskStoreError("invalid_artifact_cursor")
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode(padded.encode())
            value = json.loads(raw.decode())
            if (
                not isinstance(value, list)
                or len(value) != 3
                or isinstance(value[0], bool)
                or not isinstance(value[0], (int, float))
                or not math.isfinite(float(value[0]))
                or not isinstance(value[1], str)
                or not value[1]
                or isinstance(value[2], bool)
                or not isinstance(value[2], int)
                or value[2] < 1
            ):
                raise ValueError
            return float(value[0]), value[1], value[2]
        except (
            ValueError,
            TypeError,
            binascii.Error,
            json.JSONDecodeError,
            UnicodeError,
        ):
            raise TaskStoreError("invalid_artifact_cursor") from None

    async def list(
        self,
        scope: TaskScope,
        *,
        limit: int = 25,
        cursor: str | None = None,
        task_id: str | None = None,
        media_type: str | None = None,
    ) -> ArtifactCollection:
        """List the latest version of each artifact in one authorized scope."""
        if limit < 1 or limit > MAX_ARTIFACT_LIST_LIMIT:
            raise TaskStoreError("invalid_artifact_limit")
        decoded = self._decode_cursor(cursor) if cursor else None
        if task_id is not None and not task_id:
            raise TaskStoreError("invalid_artifact_task")
        if media_type is not None and not media_type:
            raise TaskStoreError("invalid_artifact_media_type")

        filters = [
            "principal_id = ?",
            "workspace_id = ?",
            "app_id = ?",
        ]
        params: list[object] = [
            scope.principal_id,
            scope.workspace_id,
            scope.app_id,
        ]
        if task_id is not None:
            filters.append("task_id = ?")
            params.append(task_id)
        where = " AND ".join(filters)
        latest = (
            "SELECT artifact_id, MAX(version) AS version "
            f"FROM artifact_versions WHERE {where} GROUP BY artifact_id"
        )
        outer_filters = ["latest.artifact_id = versions.artifact_id"]
        outer_params: list[object] = []
        if media_type is not None:
            outer_filters.append(
                "json_extract(versions.ref_json, '$.media_type') = ?",
            )
            outer_params.append(media_type)
        if decoded is not None:
            created_at, artifact_id, version = decoded
            outer_filters.append(
                "(versions.created_at < ? OR "
                "(versions.created_at = ? AND "
                "(versions.artifact_id < ? OR "
                "(versions.artifact_id = ? AND versions.version < ?))))",
            )
            outer_params.extend(
                [created_at, created_at, artifact_id, artifact_id, version],
            )
        outer_where = " AND ".join(outer_filters)

        def operation(connection: sqlite3.Connection) -> ArtifactCollection:
            count_filter = ""
            count_params = list(params)
            if media_type is not None:
                count_filter = (
                    " WHERE json_extract(versions.ref_json, "
                    "'$.media_type') = ?"
                )
                count_params.append(media_type)
            count_row = connection.execute(
                "SELECT COUNT(*) FROM artifact_versions AS versions "
                f"JOIN ({latest}) AS latest ON "
                "latest.artifact_id = versions.artifact_id AND "
                "latest.version = versions.version"
                + count_filter,
                count_params,
            ).fetchone()
            total_count = int(count_row[0])
            rows = connection.execute(
                "SELECT versions.ref_json, versions.created_at "
                "FROM artifact_versions AS versions "
                f"JOIN ({latest}) AS latest ON "
                "latest.artifact_id = versions.artifact_id AND "
                "latest.version = versions.version "
                f"WHERE {outer_where} "
                "ORDER BY versions.created_at DESC, versions.artifact_id DESC, "
                "versions.version DESC LIMIT ?",
                params + outer_params + [limit + 1],
            ).fetchall()
            has_more = len(rows) > limit
            selected = rows[:limit]
            items = tuple(
                ArtifactRef.model_validate_json(row["ref_json"])
                for row in selected
            )
            next_cursor = None
            if has_more and selected:
                last = selected[-1]
                ref = items[-1]
                next_cursor = self._encode_cursor(
                    float(last["created_at"]),
                    ref.artifact_id,
                    ref.version,
                )
            return ArtifactCollection(
                app_id=scope.app_id,
                items=items,
                total_count=total_count,
                next_cursor=next_cursor,
            )

        return await self._run(operation)

    async def grant(
        self,
        owner: TaskScope,
        ref: ArtifactRef,
        *,
        target_app_id: str,
        handoff_id: str,
    ) -> None:
        """Grant one immutable version through a durable scoped handoff."""
        if (
            ref.producer.app_id != owner.app_id
            or not target_app_id
            or not handoff_id
        ):
            raise TaskStoreError("invalid_artifact_grant")

        def operation(connection: sqlite3.Connection) -> None:
            row = connection.execute(
                """SELECT ref_json FROM artifact_versions
                WHERE artifact_id = ? AND version = ? AND principal_id = ?
                AND workspace_id = ? AND app_id = ?""",
                (
                    ref.artifact_id,
                    ref.version,
                    owner.principal_id,
                    owner.workspace_id,
                    owner.app_id,
                ),
            ).fetchone()
            if row is None or ArtifactRef.model_validate_json(
                row["ref_json"],
            ) != ref:
                raise TaskStoreError("artifact_not_found")
            connection.execute(
                """INSERT OR IGNORE INTO artifact_grants
                (artifact_id, version, principal_id, workspace_id,
                 target_app_id, handoff_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ref.artifact_id,
                    ref.version,
                    owner.principal_id,
                    owner.workspace_id,
                    target_app_id,
                    handoff_id,
                    time.time(),
                ),
            )

        await self._run(operation, write=True)


__all__ = [
    "ArtifactStore",
    "MAX_ARTIFACT_BYTES",
    "MAX_ARTIFACT_LIST_LIMIT",
    "MAX_TASK_ARTIFACT_BYTES",
    "MAX_TASK_ARTIFACTS",
]
