# -*- coding: utf-8 -*-
"""Durable, authenticated context handoff between Host-owned PawApps."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Annotated, Callable, Literal, TypeVar
from urllib.parse import quote

from pydantic import Field

from .artifacts import ArtifactStore
from .tasks.contracts import (
    ArtifactRef,
    Contract,
    Engagement,
    Identity,
    ProjectRef,
    TaskScope,
    TaskStoreError,
    TaskSubmission,
    canonical_json,
    content_digest,
)

_T = TypeVar("_T")
_SCHEMA_VERSION = 1
_APP_ID = Annotated[
    str,
    Field(min_length=1, max_length=256, pattern=r"^[a-z0-9][a-z0-9-]*$"),
]
_SCHEMA = (
    """CREATE TABLE handoffs (
        handoff_id TEXT PRIMARY KEY,
        principal_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        source_app_id TEXT NOT NULL,
        target_app_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        context_revision INTEGER NOT NULL,
        request_digest TEXT NOT NULL,
        request_json TEXT NOT NULL,
        created_at REAL NOT NULL,
        UNIQUE(
            principal_id, workspace_id, task_id,
            target_app_id, context_revision
        )
    )""",
    """CREATE INDEX handoff_target ON handoffs(
        principal_id, workspace_id, target_app_id, handoff_id
    )""",
    """CREATE TABLE handoff_audit (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL NOT NULL,
        principal_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        app_id TEXT NOT NULL,
        handoff_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        outcome TEXT NOT NULL
    )""",
)


class ContextScope(Contract):
    workspace_id: Identity
    source_app_id: _APP_ID
    action_id: Identity
    engagement: Engagement


class TaskContext(Contract):
    """Bounded task state passed to an App; full chat history is excluded."""

    schema_version: Literal[1] = 1
    context_id: Identity
    revision: int = Field(ge=1)
    task_id: Identity
    goal: Annotated[str, Field(max_length=16000)]
    scope: ContextScope
    artifact_refs: tuple[ArtifactRef, ...] = Field(max_length=128)
    decision_refs: tuple[ArtifactRef, ...] = Field(
        default=(),
        max_length=128,
    )
    project_ref: ProjectRef
    resume_ref: Identity


class HandoffRequest(Contract):
    schema_version: Literal[1] = 1
    handoff_id: Identity
    source_app_id: _APP_ID
    target_app_id: _APP_ID
    context: TaskContext
    created_at: float


class OpenAppAction(Contract):
    schema_version: Literal[1] = 1
    app_id: _APP_ID
    handoff_id: Identity
    path: Annotated[str, Field(pattern=r"^/apps/[a-z0-9][a-z0-9-]*\?handoff=")]
    project_ref: ProjectRef


class HandoffStore:
    """Scoped handoff snapshots; the opaque URL ID carries no authority."""

    def __init__(self, path: Path, artifacts: ArtifactStore):
        self.path = Path(path)
        self.artifacts = artifacts

    @classmethod
    async def open(
        cls,
        path: Path,
        artifacts: ArtifactStore,
    ) -> HandoffStore:
        store = cls(path, artifacts)
        await asyncio.to_thread(store._initialize)
        return store

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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
            elif version != _SCHEMA_VERSION:
                raise TaskStoreError("unsupported_handoff_store_version")
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
    def _goal(submission: TaskSubmission) -> str:
        candidate = submission.inputs.get("text")
        if not isinstance(candidate, str) or not candidate.strip():
            candidate = submission.action.summary
        return candidate[:16000]

    @staticmethod
    def _context(submission: TaskSubmission) -> TaskContext:
        handle = submission.handle
        if handle.project_ref is None:
            raise TaskStoreError("project_unavailable")
        if handle.project_ref.app_id != handle.scope.app_id:
            raise TaskStoreError("invalid_project_ref")
        return TaskContext(
            context_id="context_"
            + content_digest(
                [
                    handle.scope.principal_id,
                    handle.scope.workspace_id,
                    handle.task_id,
                ],
            )[:32],
            revision=max(1, handle.event_sequence),
            task_id=handle.task_id,
            goal=HandoffStore._goal(submission),
            scope=ContextScope(
                workspace_id=handle.scope.workspace_id,
                source_app_id=handle.scope.app_id,
                action_id=handle.action_id,
                engagement=handle.origin.engagement,
            ),
            artifact_refs=handle.output_refs,
            project_ref=handle.project_ref,
            resume_ref=handle.task_id,
        )

    @staticmethod
    def _action(request: HandoffRequest) -> OpenAppAction:
        return OpenAppAction(
            app_id=request.target_app_id,
            handoff_id=request.handoff_id,
            path=(
                f"/apps/{request.target_app_id}?handoff="
                + quote(request.handoff_id, safe="")
            ),
            project_ref=request.context.project_ref,
        )

    @staticmethod
    def _audit(
        connection: sqlite3.Connection,
        scope: TaskScope,
        handoff_id: str,
        operation: str,
        outcome: str,
    ) -> None:
        connection.execute(
            """INSERT INTO handoff_audit
            (created_at, principal_id, workspace_id, app_id,
             handoff_id, operation, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                scope.principal_id,
                scope.workspace_id,
                scope.app_id,
                handoff_id,
                operation,
                outcome,
            ),
        )

    async def _grant(
        self,
        request: HandoffRequest,
        principal_id: str,
    ) -> None:
        source = TaskScope(
            principal_id=principal_id,
            workspace_id=request.context.scope.workspace_id,
            app_id=request.source_app_id,
        )
        refs = request.context.artifact_refs + request.context.decision_refs
        for ref in refs:
            await self.artifacts.grant(
                source,
                ref,
                target_app_id=request.target_app_id,
                handoff_id=request.handoff_id,
            )

    async def create(
        self,
        submission: TaskSubmission,
        *,
        target_app_id: str,
    ) -> OpenAppAction:
        context = self._context(submission)
        # Validate the target independently of the eventual URL constructor.
        OpenAppAction(
            app_id=target_app_id,
            handoff_id="validation",
            path=f"/apps/{target_app_id}?handoff=validation",
            project_ref=context.project_ref,
        )
        handle = submission.handle

        def operation(connection: sqlite3.Connection) -> HandoffRequest:
            row = connection.execute(
                """SELECT request_digest, request_json FROM handoffs
                WHERE principal_id = ? AND workspace_id = ? AND task_id = ?
                AND target_app_id = ? AND context_revision = ?""",
                (
                    handle.scope.principal_id,
                    handle.scope.workspace_id,
                    handle.task_id,
                    target_app_id,
                    context.revision,
                ),
            ).fetchone()
            if row is not None:
                request = HandoffRequest.model_validate_json(
                    row["request_json"],
                )
                payload = request.model_dump(mode="json")
                if (
                    content_digest(payload) != row["request_digest"]
                    or request.source_app_id != handle.scope.app_id
                    or request.target_app_id != target_app_id
                    or request.context != context
                ):
                    raise TaskStoreError("handoff_conflict")
                self._audit(
                    connection,
                    handle.scope,
                    request.handoff_id,
                    "create",
                    "replayed",
                )
                return request

            request = HandoffRequest(
                handoff_id="handoff_" + uuid.uuid4().hex,
                source_app_id=handle.scope.app_id,
                target_app_id=target_app_id,
                context=context,
                created_at=time.time(),
            )
            payload = request.model_dump(mode="json")
            connection.execute(
                """INSERT INTO handoffs
                (handoff_id, principal_id, workspace_id, source_app_id,
                 target_app_id, task_id, context_revision, request_digest,
                 request_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request.handoff_id,
                    handle.scope.principal_id,
                    handle.scope.workspace_id,
                    handle.scope.app_id,
                    target_app_id,
                    handle.task_id,
                    context.revision,
                    content_digest(payload),
                    canonical_json(payload),
                    request.created_at,
                ),
            )
            self._audit(
                connection,
                handle.scope,
                request.handoff_id,
                "create",
                "created",
            )
            return request

        request = await self._run(operation, write=True)
        await self._grant(request, handle.scope.principal_id)
        return self._action(request)

    async def resolve(
        self,
        scope: TaskScope,
        handoff_id: str,
    ) -> HandoffRequest:
        def operation(connection: sqlite3.Connection):
            row = connection.execute(
                """SELECT principal_id, workspace_id, source_app_id,
                target_app_id, task_id, request_digest, request_json
                FROM handoffs WHERE handoff_id = ? AND principal_id = ?
                AND workspace_id = ? AND target_app_id = ?""",
                (
                    handoff_id,
                    scope.principal_id,
                    scope.workspace_id,
                    scope.app_id,
                ),
            ).fetchone()
            if row is None:
                self._audit(
                    connection,
                    scope,
                    handoff_id,
                    "resolve",
                    "not_found",
                )
                return "not_found", None, None
            try:
                request = HandoffRequest.model_validate_json(
                    row["request_json"],
                )
            except ValueError:
                self._audit(
                    connection,
                    scope,
                    handoff_id,
                    "resolve",
                    "corrupt",
                )
                return "corrupt", None, None
            if (
                content_digest(request.model_dump(mode="json"))
                != row["request_digest"]
                or request.handoff_id != handoff_id
                or request.source_app_id != row["source_app_id"]
                or request.target_app_id != row["target_app_id"]
                or request.target_app_id != scope.app_id
                or request.context.task_id != row["task_id"]
                or request.context.scope.workspace_id != row["workspace_id"]
                or request.context.scope.source_app_id
                != request.source_app_id
            ):
                self._audit(
                    connection,
                    scope,
                    handoff_id,
                    "resolve",
                    "corrupt",
                )
                return "corrupt", None, None
            self._audit(
                connection,
                scope,
                handoff_id,
                "resolve",
                "authorized",
            )
            return "authorized", request, row["principal_id"]

        result = await self._run(operation, write=True)
        outcome, request, principal_id = result
        if outcome != "authorized":
            raise TaskStoreError(
                "handoff_not_found"
                if outcome == "not_found"
                else "handoff_corrupt",
            )
        assert request is not None and principal_id is not None
        await self._grant(request, principal_id)
        return request


__all__ = [
    "ContextScope",
    "HandoffRequest",
    "HandoffStore",
    "OpenAppAction",
    "TaskContext",
]
