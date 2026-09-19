# -*- coding: utf-8 -*-
"""Bounded read-only file-browser configuration and durable task adapter."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qwenpaw.pawapp import ReadinessResult
from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    CommandLookup,
    ExecutorEvent,
    ExecutorRunRef,
    SubmissionLookup,
    TaskCommand,
    TaskScope,
    TaskStoreError,
    TaskSubmission,
)
from qwenpaw.pawapp.tasks.binding import Readiness
from qwenpaw.pawapp.tasks.contracts import content_digest

APP_ID = "qwenpaw-file-browser"
ACTION_ID = "list-directory"
EXECUTOR_ID = "qwenpaw-file-browser.directory"
REQUIREMENT_ID = "default-root"
ENTRY_ID = "file-browser-default-root"
MAX_ENTRIES = 200
MAX_TEXT_BYTES = 64 * 1024
_READINESS_TTL_SECONDS = 30.0


def normalize_directory(value: Any) -> str:
    """Return one canonical absolute directory input without reading it."""
    if not isinstance(value, str):
        raise TaskStoreError("file_browser_directory_invalid")
    candidate = value.strip()
    if not candidate or len(candidate) > 4096 or "\x00" in candidate:
        raise TaskStoreError("file_browser_directory_invalid")
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        raise TaskStoreError("file_browser_directory_not_absolute")
    try:
        return str(path.resolve(strict=False))
    except (OSError, RuntimeError):
        raise TaskStoreError("file_browser_directory_invalid") from None


def directory_available(directory: str) -> bool:
    """Check only the selected directory; do not traverse its contents."""
    try:
        path = Path(directory)
        return path.is_dir() and os.access(path, os.R_OK | os.X_OK)
    except OSError:
        return False


@dataclass(frozen=True)
class DirectoryPreference:
    directory: str | None
    revision: int
    updated_at: float | None


class FileBrowserStore:
    """SQLite-backed AppLocal preferences and executor receipts."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS directory_preferences (
                    principal_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    directory TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (principal_id, workspace_id)
                );
                CREATE TABLE IF NOT EXISTS directory_submissions (
                    submission_id TEXT PRIMARY KEY,
                    meaning_digest TEXT NOT NULL,
                    directory TEXT NOT NULL,
                    state TEXT NOT NULL,
                    text_result TEXT,
                    failure_code TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS directory_setup_saves (
                    request_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    directory TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS directory_commands (
                    submission_id TEXT NOT NULL,
                    command_id TEXT NOT NULL,
                    meaning_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reason TEXT,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (submission_id, command_id)
                );
                """,
            )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def preference(self, scope: TaskScope) -> DirectoryPreference:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT directory, revision, updated_at
                   FROM directory_preferences
                   WHERE principal_id = ? AND workspace_id = ?""",
                (scope.principal_id, scope.workspace_id),
            ).fetchone()
        if row is None:
            return DirectoryPreference(None, 0, None)
        return DirectoryPreference(
            str(row["directory"]),
            int(row["revision"]),
            float(row["updated_at"]),
        )

    def save_preference(
        self,
        scope: TaskScope,
        directory: str,
        *,
        expected_revision: int,
        setup_request_id: str | None = None,
    ) -> DirectoryPreference:
        directory = normalize_directory(directory)
        if not directory_available(directory):
            raise TaskStoreError("file_browser_default_root_unavailable")
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if setup_request_id is not None:
                receipt = connection.execute(
                    """SELECT * FROM directory_setup_saves
                       WHERE request_id = ?""",
                    (setup_request_id,),
                ).fetchone()
                if receipt is not None:
                    if (
                        receipt["principal_id"] != scope.principal_id
                        or receipt["workspace_id"] != scope.workspace_id
                        or receipt["directory"] != directory
                    ):
                        connection.rollback()
                        raise TaskStoreError("setup_result_conflict")
                    connection.commit()
                    return DirectoryPreference(
                        directory,
                        int(receipt["revision"]),
                        float(receipt["created_at"]),
                    )
            row = connection.execute(
                """SELECT revision FROM directory_preferences
                   WHERE principal_id = ? AND workspace_id = ?""",
                (scope.principal_id, scope.workspace_id),
            ).fetchone()
            revision = int(row["revision"]) if row is not None else 0
            if revision != expected_revision:
                connection.rollback()
                raise TaskStoreError("context_conflict")
            next_revision = revision + 1
            connection.execute(
                """INSERT INTO directory_preferences
                   (principal_id, workspace_id, directory, revision,
                    updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(principal_id, workspace_id) DO UPDATE SET
                     directory = excluded.directory,
                     revision = excluded.revision,
                     updated_at = excluded.updated_at""",
                (
                    scope.principal_id,
                    scope.workspace_id,
                    directory,
                    next_revision,
                    now,
                ),
            )
            if setup_request_id is not None:
                connection.execute(
                    """INSERT INTO directory_setup_saves
                       (request_id, principal_id, workspace_id, directory,
                        revision, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        setup_request_id,
                        scope.principal_id,
                        scope.workspace_id,
                        directory,
                        next_revision,
                        now,
                    ),
                )
            connection.commit()
        return DirectoryPreference(directory, next_revision, now)

    @staticmethod
    def _submission_meaning(submission: TaskSubmission) -> str:
        return content_digest(
            {
                "task_id": submission.handle.task_id,
                "scope": submission.handle.scope.model_dump(mode="json"),
                "origin": submission.handle.origin.model_dump(mode="json"),
                "action": submission.action.descriptor_digest,
                "inputs": submission.inputs,
            },
        )

    @staticmethod
    def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    def submission(self, submission: TaskSubmission) -> dict[str, Any] | None:
        submission_id = submission.handle.submission_id
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM directory_submissions
                   WHERE submission_id = ?""",
                (submission_id,),
            ).fetchone()
        if row is None:
            return None
        record = self._row_dict(row)
        if record["meaning_digest"] != self._submission_meaning(
            submission,
        ) or record["directory"] != submission.inputs.get("directory"):
            raise TaskStoreError("file_browser_submission_conflict")
        return record

    def execute(self, submission: TaskSubmission) -> dict[str, Any]:
        submission_id = submission.handle.submission_id
        directory = str(submission.inputs["directory"])
        meaning = self._submission_meaning(submission)
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT * FROM directory_submissions
                   WHERE submission_id = ?""",
                (submission_id,),
            ).fetchone()
            if row is not None:
                record = self._row_dict(row)
                if (
                    record["meaning_digest"] != meaning
                    or record["directory"] != directory
                ):
                    connection.rollback()
                    raise TaskStoreError("file_browser_submission_conflict")
                if record["state"] in {"accepted", "failed"}:
                    connection.commit()
                    return record
            else:
                connection.execute(
                    """INSERT INTO directory_submissions
                       VALUES (?, ?, ?, 'prepared', NULL, NULL, ?, ?)""",
                    (submission_id, meaning, directory, now, now),
                )
            try:
                text_result = render_directory(directory)
                state = "accepted"
                failure_code = None
            except TaskStoreError as exc:
                text_result = None
                state = "failed"
                failure_code = exc.code
            connection.execute(
                """UPDATE directory_submissions
                   SET state = ?, text_result = ?, failure_code = ?,
                       updated_at = ? WHERE submission_id = ?""",
                (state, text_result, failure_code, time.time(), submission_id),
            )
            row = connection.execute(
                """SELECT * FROM directory_submissions
                   WHERE submission_id = ?""",
                (submission_id,),
            ).fetchone()
            connection.commit()
        assert row is not None
        return self._row_dict(row)

    @staticmethod
    def _command_meaning(command: TaskCommand) -> str:
        return content_digest(
            {
                "task_id": command.task_id,
                "command_id": command.command_id,
                "kind": command.kind,
                "request_id": command.request_id,
                "payload": command.payload,
            },
        )

    def command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        submission_id = submission.handle.submission_id
        meaning = self._command_meaning(command)
        state = "accepted" if command.kind == "cancel" else "rejected"
        reason = "task_terminal" if command.kind == "answer" else None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT * FROM directory_commands
                   WHERE submission_id = ? AND command_id = ?""",
                (submission_id, command.command_id),
            ).fetchone()
            if row is None:
                connection.execute(
                    """INSERT INTO directory_commands
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        submission_id,
                        command.command_id,
                        meaning,
                        state,
                        reason,
                        time.time(),
                    ),
                )
            elif row["meaning_digest"] != meaning:
                connection.rollback()
                raise TaskStoreError("file_browser_command_conflict")
            else:
                state, reason = str(row["state"]), row["reason"]
            connection.commit()
        return CommandLookup(state=state, reason=reason)

    def query_command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM directory_commands
                   WHERE submission_id = ? AND command_id = ?""",
                (submission.handle.submission_id, command.command_id),
            ).fetchone()
        if row is None:
            return CommandLookup(state="not_found")
        if row["meaning_digest"] != self._command_meaning(command):
            raise TaskStoreError("file_browser_command_conflict")
        return CommandLookup(state=str(row["state"]), reason=row["reason"])


def _entry_kind(mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def render_directory(directory: str) -> str:
    """Render a stable, bounded snapshot without following child symlinks."""
    canonical = normalize_directory(directory)
    if not directory_available(canonical):
        raise TaskStoreError("file_browser_directory_unavailable")
    entries: list[dict[str, Any]] = []
    truncated = False
    try:
        with os.scandir(canonical) as iterator:
            for index, entry in enumerate(iterator):
                if index >= MAX_ENTRIES:
                    truncated = True
                    break
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    metadata = None
                kind = (
                    _entry_kind(metadata.st_mode)
                    if metadata is not None
                    else "unavailable"
                )
                entries.append(
                    {
                        "name": entry.name,
                        "type": kind,
                        "size_bytes": (
                            metadata.st_size
                            if metadata is not None and kind == "file"
                            else None
                        ),
                        "modified_at": (
                            metadata.st_mtime if metadata is not None else None
                        ),
                    },
                )
    except OSError:
        raise TaskStoreError("file_browser_directory_unavailable") from None
    entries.sort(
        key=lambda item: (
            item["type"] != "directory",
            str(item["name"]).casefold(),
            str(item["name"]),
        ),
    )
    payload = {
        "schema_version": 1,
        "directory": canonical,
        "entries": entries,
        "truncated": truncated,
        "limit": MAX_ENTRIES,
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(rendered.encode("utf-8")) > MAX_TEXT_BYTES:
        raise TaskStoreError("file_browser_result_too_large")
    return rendered


def list_directory_action_descriptor() -> ActionDescriptor:
    return ActionDescriptor(
        app_id=APP_ID,
        action_id=ACTION_ID,
        summary=(
            "List direct children of one Host-authorized directory without "
            "reading file contents or following symlinks."
        ),
        engagements=("delegated", "direct"),
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4096,
                },
            },
            "additionalProperties": False,
        },
        output_types=("text/plain",),
        permissions=("filesystem.directory.read",),
        effects=("filesystem_read",),
        adapter_ref="qwenpaw-file-browser.list-directory.v1",
    )


class FileBrowserTaskAdapter:
    """Protocol-1 adapter backed by immutable directory snapshots."""

    submission_protocol_version = 1

    def __init__(self, store: FileBrowserStore):
        self.store = store

    async def aclose(self) -> None:
        return None

    async def readiness(
        self,
        scope: TaskScope,
        inputs: dict[str, Any],
    ) -> Readiness:
        if scope.app_id != APP_ID:
            return Readiness(
                state="blocked",
                reason="file_browser_scope_mismatch",
            )
        directory = inputs.get("directory")
        try:
            directory = normalize_directory(directory)
        except TaskStoreError as exc:
            return Readiness(state="blocked", reason=exc.code)
        if not directory_available(directory):
            return Readiness(
                state="blocked",
                reason="file_browser_directory_unavailable",
            )
        return Readiness(state="ready")

    @staticmethod
    def _run_ref(submission: TaskSubmission) -> ExecutorRunRef:
        return ExecutorRunRef(
            executor_id=EXECUTOR_ID,
            session_id=content_digest(
                submission.handle.scope.model_dump(mode="json"),
            )[:32],
            run_id=submission.handle.submission_id,
        )

    async def submit(self, submission: TaskSubmission) -> ExecutorRunRef:
        list_directory_action_descriptor().validate_inputs(submission.inputs)
        if submission.handle.scope.app_id != APP_ID:
            raise TaskStoreError("file_browser_scope_mismatch")
        await asyncio.to_thread(self.store.execute, submission)
        return self._run_ref(submission)

    async def query(self, submission: TaskSubmission) -> SubmissionLookup:
        record = await asyncio.to_thread(self.store.submission, submission)
        if record is None:
            return SubmissionLookup(state="not_found")
        if record["state"] == "prepared":
            return SubmissionLookup(state="unknown")
        return SubmissionLookup(
            state="accepted",
            run_ref=self._run_ref(submission),
        )

    async def attach(self, submission: TaskSubmission):
        record = await asyncio.to_thread(self.store.submission, submission)
        if record is None or record["state"] == "prepared":
            raise TaskStoreError("file_browser_submission_unknown")
        if submission.handle.executor_sequence is not None:
            return
        status = "succeeded" if record["state"] == "accepted" else "failed"
        detail: dict[str, Any] = {}
        if record["failure_code"]:
            detail["reason_code"] = str(record["failure_code"])
        yield ExecutorEvent(
            run_ref=self._run_ref(submission),
            sequence=0,
            cursor="file-browser-result-v1",
            status=status,
            text_result=record["text_result"],
            detail=detail,
        )

    async def command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        if command.task_id != submission.handle.task_id:
            raise TaskStoreError("file_browser_command_task_mismatch")
        return await asyncio.to_thread(
            self.store.command,
            submission,
            command,
        )

    async def query_command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        if command.task_id != submission.handle.task_id:
            raise TaskStoreError("file_browser_command_task_mismatch")
        return await asyncio.to_thread(
            self.store.query_command,
            submission,
            command,
        )


def make_setup_checker(store: FileBrowserStore):
    async def check_default_root(
        scope: TaskScope,
        inputs: dict[str, Any],
    ) -> ReadinessResult:
        now = time.time()
        if scope.app_id != APP_ID:
            raise TaskStoreError("setup_scope_mismatch")
        if "directory" in inputs:
            return ReadinessResult(
                requirement_id=REQUIREMENT_ID,
                state="ready",
                checked_at=now,
                expires_at=now + _READINESS_TTL_SECONDS,
            )
        preference = await asyncio.to_thread(store.preference, scope)
        if preference.directory is None:
            return ReadinessResult(
                requirement_id=REQUIREMENT_ID,
                state="needs_configuration",
                reason_code="file_browser_default_root_missing",
                reason="Choose a default directory or provide one explicitly.",
                checked_revision=preference.revision,
                checked_at=now,
                expires_at=now + _READINESS_TTL_SECONDS,
            )
        if not directory_available(preference.directory):
            return ReadinessResult(
                requirement_id=REQUIREMENT_ID,
                state="unavailable",
                reason_code="file_browser_default_root_unavailable",
                reason="The saved default directory is no longer available.",
                checked_revision=preference.revision,
                checked_at=now,
                expires_at=now + _READINESS_TTL_SECONDS,
            )
        return ReadinessResult(
            requirement_id=REQUIREMENT_ID,
            state="ready",
            checked_revision=preference.revision,
            checked_at=now,
            expires_at=now + _READINESS_TTL_SECONDS,
        )

    return check_default_root


def make_input_resolver(store: FileBrowserStore):
    async def resolve(
        scope: TaskScope,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        directory = inputs.get("directory")
        if directory is None:
            preference = await asyncio.to_thread(store.preference, scope)
            directory = preference.directory
        if directory is None:
            raise TaskStoreError("file_browser_default_root_missing")
        return {"directory": normalize_directory(directory)}

    return resolve
