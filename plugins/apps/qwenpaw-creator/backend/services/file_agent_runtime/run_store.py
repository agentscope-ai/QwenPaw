# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Atomic file store for top-level Creator Agent runs."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from contextlib import contextmanager
import os
from pathlib import Path
import stat
from typing import Any

from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.errors import RuntimeFileError
from services.runtime_files.locking import CrossProcessFileLock
from services.runtime_files.models import utc_now
from services.runtime_files.path_safety import require_safe_runtime_segment

from .models import (
    AgentRunStatus,
    CreatorAgentRunRecord,
    TERMINAL_AGENT_RUN_STATUSES,
)


class AgentRunStoreError(RuntimeFileError):
    pass


class AgentRunStateConflict(AgentRunStoreError):
    pass


_TRANSITIONS: dict[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.QUEUED: frozenset(
        {
            AgentRunStatus.RUNNING,
            AgentRunStatus.FAILED,
            AgentRunStatus.CANCELLED,
        },
    ),
    AgentRunStatus.RUNNING: TERMINAL_AGENT_RUN_STATUSES,
}


class CreatorAgentRunStore:
    def __init__(
        self,
        data_root: str | os.PathLike[str],
        *,
        lock_timeout_seconds: float | None = 10.0,
    ) -> None:
        root = Path(data_root).expanduser()
        if not root.is_absolute():
            raise ValueError("Agent Runtime data root must be absolute")
        root.mkdir(parents=True, exist_ok=True)
        self.data_root = root.resolve(strict=True)
        self.lock_timeout_seconds = lock_timeout_seconds

    def create(
        self,
        record: CreatorAgentRunRecord | Mapping[str, Any],
    ) -> CreatorAgentRunRecord:
        candidate = CreatorAgentRunRecord.model_validate(record)
        project_id = self._safe(candidate.project_id, "project_id")
        run_id = self._safe(candidate.run_id, "run_id")
        if candidate.status is not AgentRunStatus.QUEUED:
            raise AgentRunStateConflict("new Agent run must start QUEUED")
        with self._project_lock(project_id):
            store = self._store(project_id, run_id)
            created = store.try_create(candidate)
            if created is not None:
                return created.value
            existing = store.read()
            if existing.model_dump(mode="json") == candidate.model_dump(
                mode="json",
            ):
                return existing
            raise AgentRunStateConflict(f"Agent run already exists: {run_id}")

    def get(self, project_id: str, run_id: str) -> CreatorAgentRunRecord:
        project_id = self._safe(project_id, "project_id")
        run_id = self._safe(run_id, "run_id")
        self._require_project(project_id)
        record = self._store(project_id, run_id).read()
        if record.project_id != project_id or record.run_id != run_id:
            raise AgentRunStoreError("Agent run path and identity disagree")
        return record

    def list(self, project_id: str) -> list[CreatorAgentRunRecord]:
        project_id = self._safe(project_id, "project_id")
        with self._project_lock(project_id):
            root = self._runtime_root(project_id) / "agent-runs"
            if not root.exists():
                return []
            if root.is_symlink() or not root.is_dir():
                raise AgentRunStoreError("agent-runs must be a real directory")
            records: list[CreatorAgentRunRecord] = []
            for path in root.glob("*.json"):
                if path.is_symlink() or not path.is_file():
                    raise AgentRunStoreError(
                        "Agent run must be a regular file",
                    )
                run_id = self._safe(path.stem, "run_id")
                record = self._store(project_id, run_id).read()
                if record.project_id != project_id or record.run_id != run_id:
                    raise AgentRunStoreError(
                        "Agent run path and identity disagree",
                    )
                records.append(record)
            return sorted(records, key=lambda item: item.created_at)

    def transition(
        self,
        project_id: str,
        run_id: str,
        *,
        expected_status: AgentRunStatus
        | str
        | Collection[AgentRunStatus | str],
        status: AgentRunStatus | str,
        updates: Mapping[str, Any] | None = None,
    ) -> CreatorAgentRunRecord:
        project_id = self._safe(project_id, "project_id")
        run_id = self._safe(run_id, "run_id")
        expected_values = (
            {AgentRunStatus(expected_status)}
            if isinstance(expected_status, (str, AgentRunStatus))
            else {AgentRunStatus(item) for item in expected_status}
        )
        target = AgentRunStatus(status)
        with self._project_lock(project_id):
            store = self._store(project_id, run_id)
            current = store.read()
            if current.status not in expected_values:
                raise AgentRunStateConflict(
                    "Agent run status conflict: "
                    f"expected={sorted(item.value for item in expected_values)}, "
                    f"actual={current.status.value}",
                )
            if target not in _TRANSITIONS.get(current.status, frozenset()):
                raise AgentRunStateConflict(
                    f"illegal Agent run transition: {current.status.value} -> {target.value}",
                )
            update_values = dict(updates or {})
            forbidden = {
                "run_id",
                "project_id",
                "session_id",
                "goal_id",
                "conversation_id",
                "round_id",
                "caused_by_message_id",
                "caused_by_message_seq",
                "caused_by_request_id",
                "origin",
                "review_policy",
                "review_boundary",
                "input_generation",
                "input_etag",
                "status",
                "created_at",
                "updated_at",
            } & set(update_values)
            if forbidden:
                raise AgentRunStateConflict(
                    f"Agent run update changes immutable fields: {sorted(forbidden)}",
                )
            updated = CreatorAgentRunRecord.model_validate(
                current.model_copy(
                    update={
                        **update_values,
                        "status": target,
                        "updated_at": utc_now(),
                    },
                ),
            )
            store.write(updated)
            return updated

    def _store(
        self,
        project_id: str,
        run_id: str,
    ) -> AtomicJsonRecordStore[CreatorAgentRunRecord]:
        return AtomicJsonRecordStore(
            self._runtime_root(project_id) / "agent-runs" / f"{run_id}.json",
            CreatorAgentRunRecord,
        )

    def _runtime_root(self, project_id: str) -> Path:
        return self.data_root / project_id / "runtime"

    def _require_project(self, project_id: str) -> None:
        root = self.data_root / project_id
        try:
            root_stat = root.lstat()
            project_stat = (root / "project.json").lstat()
        except FileNotFoundError as exc:
            raise AgentRunStoreError(
                f"Project does not exist: {project_id}",
            ) from exc
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(
            root_stat.st_mode,
        ):
            raise AgentRunStoreError("Project root must be a real directory")
        if stat.S_ISLNK(project_stat.st_mode) or not stat.S_ISREG(
            project_stat.st_mode,
        ):
            raise AgentRunStoreError("project.json must be a regular file")

    @contextmanager
    def _project_lock(self, project_id: str):
        with CrossProcessFileLock(
            self.data_root / ".locks" / f"project-{project_id}.lock",
            timeout_seconds=self.lock_timeout_seconds,
            shared=True,
        ):
            self._require_project(project_id)
            with CrossProcessFileLock(
                self._runtime_root(project_id)
                / "locks"
                / "agent-run-runtime.lock",
                timeout_seconds=self.lock_timeout_seconds,
            ):
                yield

    @staticmethod
    def _safe(value: str, label: str) -> str:
        return require_safe_runtime_segment(value, label=label)


__all__ = [
    "AgentRunStateConflict",
    "AgentRunStoreError",
    "CreatorAgentRunStore",
]
