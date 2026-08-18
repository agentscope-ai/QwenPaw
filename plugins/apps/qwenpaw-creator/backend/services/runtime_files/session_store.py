# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-public-methods,too-many-statements
"""Filesystem session aggregate for the SQLite-free Creator Runtime.

The store deliberately owns only short, durable state transitions.  Provider
and model calls must happen outside its Project-wide lock.  Current aggregate
state is stored as atomic Pydantic JSON while ordered history is stored as
append-only JSONL.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import hashlib
import logging
import os
from pathlib import Path
import shutil
import stat
from typing import Any, Literal
from uuid import uuid4

from domain.enums import CreatorGoalStatus, CreatorSessionStatus
from pydantic import BaseModel

from .atomic_store import (
    AtomicJsonRecordStore,
    atomic_create_bytes,
    canonical_json_bytes,
    fsync_directory,
    json_document_bytes,
)
from .errors import (
    RecordAlreadyExistsError,
    RuntimeFileError,
    RuntimeFileValidationError,
    SequenceConflictError,
)
from .jsonl_store import DurableJsonlStore
from .locking import CrossProcessFileLock
from .models import (
    CreatorConversationRecord,
    CreatorGoalRecord,
    CreatorMessageRecord,
    CreatorSessionRecord,
    MessageChannel,
    MessageClassification,
    MessageContentPart,
    OutboxRecord,
    OutboxState,
    QueuedMessageRecord,
    QueuedMessageState,
    ReviewBoundary,
    ReviewPolicy,
    RuntimeProjectState,
    SessionEventRecord,
    utc_now,
)
from .path_safety import require_safe_runtime_segment

logger = logging.getLogger("qwenpaw.creator.runtime_files.session_store")


# Statuses whose AgentDock mutation requests capture a ReviewBoundary.  A
# running Session yields an interrupt boundary; an idle/settled Session yields
# an idle-goal boundary so user feedback after a run still gates its related
# changes behind a review.  CANCELLED is included: a user who stopped the
# Agent and later sends revision feedback is still commenting on already-produced
# work (the frontend presents that Session as standing by).  Hard-stop transitions
# (INTERRUPT_REQUESTED) and terminal failures (ERROR) stay out: their next
# request is a restart, not feedback.
_REVIEW_ACTIVE_STATUSES = frozenset(
    {
        CreatorSessionStatus.RUNNING,
        CreatorSessionStatus.RESUMING,
        CreatorSessionStatus.WAITING_RUNTIME,
        CreatorSessionStatus.WAITING_EXECUTION_AUTH,
        CreatorSessionStatus.IDLE,
        CreatorSessionStatus.PENDING_REVIEW,
        CreatorSessionStatus.WAITING_USER_INPUT,
        CreatorSessionStatus.CANCELLED,
    },
)
_REVIEW_MUTATING_CLASSIFICATIONS = frozenset(
    {
        MessageClassification.MUTATION_INSTRUCTION,
        MessageClassification.REVIEW_REVISE,
        MessageClassification.WORKSPACE_COMMAND,
    },
)


class SessionStoreError(RuntimeFileError):
    """Base error for filesystem Session aggregate operations."""


class UnsafeSessionPath(SessionStoreError, ValueError):
    pass


class RuntimeSessionNotFound(SessionStoreError):
    pass


class RuntimeConversationNotFound(SessionStoreError):
    pass


class RuntimeGoalNotFound(SessionStoreError):
    pass


class SessionStateConflict(SessionStoreError):
    pass


class MessagePayloadConflict(SessionStoreError):
    """A client message id was reused for a different logical request."""


class RequestAdmissionConflict(SessionStoreError):
    pass


class SessionStoreIntegrityError(SessionStoreError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectRuntimeBootstrap:
    session: CreatorSessionRecord
    default_conversation: CreatorConversationRecord


@dataclass(frozen=True, slots=True)
class MessageAppendResult:
    message: CreatorMessageRecord
    replayed: bool


@dataclass(frozen=True, slots=True)
class RequestAdmissionResult:
    message: CreatorMessageRecord
    review_policy: ReviewPolicy
    review_boundary: ReviewBoundary | None
    replayed: bool


ContentPartInput = MessageContentPart | Mapping[str, Any]


class ProjectRuntimeSessionStore:
    """One Project-scoped Session aggregate implemented only with files."""

    def __init__(
        self,
        data_root: str | os.PathLike[str],
        *,
        lock_timeout_seconds: float | None = 10.0,
    ) -> None:
        raw_root = Path(data_root).expanduser()
        if not raw_root.is_absolute():
            raise UnsafeSessionPath("Runtime data root must be absolute")
        if lock_timeout_seconds is not None and lock_timeout_seconds < 0:
            raise ValueError("lock timeout must be non-negative or None")
        raw_root.mkdir(parents=True, exist_ok=True)
        self.data_root = raw_root.resolve(strict=True)
        if not self.data_root.is_dir():
            raise UnsafeSessionPath("Runtime data root must be a directory")
        self.lock_timeout_seconds = lock_timeout_seconds

    def create_project_runtime(
        self,
        project_id: str,
        *,
        session_id: str | None = None,
        conversation_id: str | None = None,
        conversation_title: str = "Default",
        schema_prompt_hash: str | None = None,
        session_metadata: Mapping[str, Any] | None = None,
        conversation_metadata: Mapping[str, Any] | None = None,
    ) -> ProjectRuntimeBootstrap:
        """Create Session and default Conversation in one directory publish.

        A Project has one Creator Session aggregate.  Retrying bootstrap returns
        that aggregate when explicitly supplied ids agree.  No Goal is created;
        a Goal begins only when the Runtime admits a real user objective.
        """

        project_id = _safe_segment(project_id, "project_id")
        requested_session_id = (
            _safe_segment(session_id, "session_id")
            if session_id is not None
            else None
        )
        requested_conversation_id = (
            _safe_segment(conversation_id, "conversation_id")
            if conversation_id is not None
            else None
        )
        if not conversation_title:
            raise ValueError("conversation_title cannot be empty")
        project_root = self._require_project(project_id)
        with self._project_lock(project_id):
            existing = self._existing_bootstrap_unlocked(project_id)
            if existing is not None:
                self._assert_bootstrap_retry(
                    existing,
                    session_id=requested_session_id,
                    conversation_id=requested_conversation_id,
                )
                recovered = self._recover_session_unlocked(
                    project_id,
                    existing.session.session_id,
                )
                return ProjectRuntimeBootstrap(
                    session=recovered,
                    default_conversation=existing.default_conversation,
                )

            resolved_session_id = requested_session_id or _new_id("session")
            resolved_conversation_id = requested_conversation_id or _new_id(
                "conversation",
            )
            created_at = utc_now()
            session = CreatorSessionRecord(
                session_id=resolved_session_id,
                project_id=project_id,
                schema_prompt_hash=schema_prompt_hash,
                metadata=dict(session_metadata or {}),
                created_at=created_at,
                updated_at=created_at,
            )
            conversation = CreatorConversationRecord(
                conversation_id=resolved_conversation_id,
                project_id=project_id,
                creator_session_id=resolved_session_id,
                title=conversation_title,
                is_default=True,
                metadata=dict(conversation_metadata or {}),
                created_at=created_at,
            )
            runtime_root = project_root / "runtime"
            sessions_root = runtime_root / "sessions"
            temp_root = runtime_root / "temp"
            sessions_root.mkdir(parents=True, exist_ok=True)
            temp_root.mkdir(parents=True, exist_ok=True)
            staged = temp_root / f"session-bootstrap-{uuid4().hex}"
            destination = sessions_root / resolved_session_id
            staged.mkdir(mode=0o700)
            try:
                conversations = staged / "conversations"
                boundaries = staged / "review-boundaries"
                conversations.mkdir(mode=0o700)
                boundaries.mkdir(mode=0o700)
                atomic_create_bytes(
                    staged / "session.json",
                    json_document_bytes(session),
                )
                atomic_create_bytes(
                    conversations / f"{resolved_conversation_id}.json",
                    json_document_bytes(conversation),
                )
                for stream_name in (
                    "messages.jsonl",
                    "events.jsonl",
                    "queued-messages.jsonl",
                    "outbox.jsonl",
                ):
                    atomic_create_bytes(staged / stream_name, b"")
                fsync_directory(conversations)
                fsync_directory(boundaries)
                fsync_directory(staged)
                if destination.exists():
                    raise SessionStateConflict(
                        f"Session already exists: {resolved_session_id}",
                    )
                os.rename(staged, destination)
                fsync_directory(sessions_root)
                fsync_directory(temp_root)
            except BaseException:
                shutil.rmtree(staged, ignore_errors=True)
                raise
            logger.info(
                "session created: project=%s session=%s conversation=%s",
                project_id,
                resolved_session_id,
                resolved_conversation_id,
            )
            return ProjectRuntimeBootstrap(
                session=session,
                default_conversation=conversation,
            )

    def initialize_staged_project(
        self,
        project_root: str | os.PathLike[str],
        project_id: str,
        *,
        session_id: str,
        conversation_id: str,
        conversation_title: str = "Default",
        schema_prompt_hash: str | None = None,
        session_metadata: Mapping[str, Any] | None = None,
        conversation_metadata: Mapping[str, Any] | None = None,
        initial_goal: str | None = None,
        goal_id: str | None = None,
        initial_message_id: str | None = None,
        initial_client_message_id: str | None = None,
    ) -> ProjectRuntimeBootstrap:
        """Bootstrap Runtime files inside an unpublished Project directory.

        This is the lifecycle companion to ``ProjectStore.create``'s staging
        initializer.  The supplied directory is private to the creator until
        the outer Project directory rename, so all records can be assembled
        without exposing a half-created Session.  This method intentionally
        does not acquire the published Project lock or touch ``self.data_root``.
        """

        project_id = _safe_segment(project_id, "project_id")
        session_id = _safe_segment(session_id, "session_id")
        conversation_id = _safe_segment(conversation_id, "conversation_id")
        if not conversation_title:
            raise ValueError("conversation_title cannot be empty")
        staged_root = Path(project_root)
        if (
            not staged_root.is_absolute()
            or staged_root.is_symlink()
            or not staged_root.is_dir()
        ):
            raise UnsafeSessionPath(
                "staged Project root must be an absolute, real directory",
            )
        project_file = staged_root / "project.json"
        if project_file.is_symlink() or not project_file.is_file():
            raise SessionStoreIntegrityError(
                "staged Project must contain a regular project.json",
            )
        runtime_root = staged_root / "runtime"
        if runtime_root.is_symlink() or not runtime_root.is_dir():
            raise SessionStoreIntegrityError(
                "staged Project must contain a real runtime directory",
            )
        sessions_root = runtime_root / "sessions"
        if sessions_root.exists():
            raise SessionStateConflict("staged Project Runtime already exists")

        normalized_goal = (
            initial_goal.strip() if initial_goal is not None else None
        )
        if initial_goal is not None and not normalized_goal:
            raise ValueError("initial_goal cannot be empty")
        if normalized_goal is not None:
            if goal_id is None or initial_message_id is None:
                raise ValueError(
                    "initial Goal bootstrap requires goal_id and initial_message_id",
                )
            goal_id = _safe_segment(goal_id, "goal_id")
            initial_message_id = _safe_nonempty(
                initial_message_id,
                "initial_message_id",
            )
            if initial_client_message_id is None:
                raise ValueError(
                    "initial Goal bootstrap requires initial_client_message_id",
                )
            initial_client_message_id = _safe_nonempty(
                initial_client_message_id,
                "initial_client_message_id",
            )

        created_at = utc_now()
        session = CreatorSessionRecord(
            session_id=session_id,
            project_id=project_id,
            schema_prompt_hash=schema_prompt_hash,
            active_goal_id=goal_id if normalized_goal is not None else None,
            last_message_seq=1 if normalized_goal is not None else 0,
            metadata=dict(session_metadata or {}),
            created_at=created_at,
            updated_at=created_at,
        )
        conversation = CreatorConversationRecord(
            conversation_id=conversation_id,
            project_id=project_id,
            creator_session_id=session_id,
            title=conversation_title,
            is_default=True,
            metadata=dict(conversation_metadata or {}),
            created_at=created_at,
        )

        session_root = sessions_root / session_id
        conversations = session_root / "conversations"
        boundaries = session_root / "review-boundaries"
        goals_root = runtime_root / "goals"
        conversations.mkdir(mode=0o700, parents=True)
        boundaries.mkdir(mode=0o700)
        goals_root.mkdir(mode=0o700)
        atomic_create_bytes(
            session_root / "session.json",
            json_document_bytes(session),
        )
        atomic_create_bytes(
            conversations / f"{conversation_id}.json",
            json_document_bytes(conversation),
        )
        for stream_name in (
            "messages.jsonl",
            "events.jsonl",
            "queued-messages.jsonl",
            "outbox.jsonl",
        ):
            atomic_create_bytes(session_root / stream_name, b"")

        if normalized_goal is not None:
            content_parts = [
                MessageContentPart(type="text", text=normalized_goal),
            ]
            request_hash = _request_hash(
                {
                    "conversation_id": conversation_id,
                    "role": "user",
                    "content_parts": content_parts,
                    "source": "initial_goal",
                    "channel": MessageChannel.COMPOSER,
                    "classification": MessageClassification.MUTATION_INSTRUCTION,
                    "metadata": {"initialCreation": True},
                    "completed_at": None,
                },
            )
            message = CreatorMessageRecord(
                message_id=initial_message_id,
                project_id=project_id,
                creator_session_id=session_id,
                conversation_id=conversation_id,
                message_seq=1,
                role="user",
                content_parts=content_parts,
                client_message_id=initial_client_message_id,
                request_hash=request_hash,
                source="initial_goal",
                channel=MessageChannel.COMPOSER,
                classification=MessageClassification.MUTATION_INSTRUCTION,
                metadata={"initialCreation": True},
                completed_at=created_at,
                created_at=created_at,
            )
            DurableJsonlStore(
                session_root / "messages.jsonl",
                CreatorMessageRecord,
            ).append(message, expected_next_seq=1, written_at=created_at)
            goal = CreatorGoalRecord(
                goal_id=goal_id,
                project_id=project_id,
                creator_session_id=session_id,
                conversation_id=conversation_id,
                root_message_seq=1,
                intent=normalized_goal,
                metadata={"source": "initial_goal", "initialCreation": True},
                created_at=created_at,
                updated_at=created_at,
            )
            atomic_create_bytes(
                goals_root / f"{goal_id}.json",
                json_document_bytes(goal),
            )

        fsync_directory(conversations)
        fsync_directory(boundaries)
        fsync_directory(session_root)
        fsync_directory(sessions_root)
        fsync_directory(goals_root)
        fsync_directory(runtime_root)
        return ProjectRuntimeBootstrap(
            session=session,
            default_conversation=conversation,
        )

    def get_project_session(self, project_id: str) -> CreatorSessionRecord:
        project_id = _safe_segment(project_id, "project_id")
        self._require_project(project_id)
        with self._project_lock(project_id):
            bootstrap = self._existing_bootstrap_unlocked(project_id)
            if bootstrap is None:
                raise RuntimeSessionNotFound(
                    f"Project has no Runtime Session: {project_id}",
                )
            return self._recover_session_unlocked(
                project_id,
                bootstrap.session.session_id,
            )

    def get_project_session_snapshot(
        self,
        project_id: str,
    ) -> CreatorSessionRecord:
        """Read-only variant of :meth:`get_project_session` for HTTP viewers.

        Uses the shared Project lock and never reconciles the Session head, so
        concurrent polling (``/session``, ``/header``) and request admission
        never serialize against the agent driver's exclusive writes.  A stale
        head pointer is acceptable here: the durable streams are authoritative
        for display, and the next writer repairs the head.
        """
        project_id = _safe_segment(project_id, "project_id")
        self._require_project(project_id)
        with self._project_lock_read(project_id):
            bootstrap = self._existing_bootstrap_unlocked(project_id)
            if bootstrap is None:
                raise RuntimeSessionNotFound(
                    f"Project has no Runtime Session: {project_id}",
                )
            return self._read_session_snapshot_unlocked(
                project_id,
                bootstrap.session.session_id,
            )

    def get_session(
        self,
        project_id: str,
        session_id: str,
    ) -> CreatorSessionRecord:
        project_id = _safe_segment(project_id, "project_id")
        session_id = _safe_segment(session_id, "session_id")
        self._require_project(project_id)
        with self._project_lock(project_id):
            return self._recover_session_unlocked(project_id, session_id)

    def set_session_status(
        self,
        project_id: str,
        session_id: str,
        status: CreatorSessionStatus | str,
        *,
        expected_status: CreatorSessionStatus | str | None = None,
    ) -> CreatorSessionRecord:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        resolved_status = CreatorSessionStatus(status)
        resolved_expected = (
            CreatorSessionStatus(expected_status)
            if expected_status is not None
            else None
        )
        with self._project_lock(project_id):
            session = self._recover_session_unlocked(project_id, session_id)
            if (
                resolved_expected is not None
                and session.status is not resolved_expected
            ):
                raise SessionStateConflict(
                    "Session status conflict: "
                    f"expected={resolved_expected.value}, "
                    f"actual={session.status.value}",
                )
            updated = session.model_copy(
                update={"status": resolved_status, "updated_at": utc_now()},
            )
            return self._write_session_unlocked(updated)

    def set_session_error(
        self,
        project_id: str,
        session_id: str,
        *,
        code: str,
        message: str,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> CreatorSessionRecord:
        """Persist a user-visible Runtime failure without crashing the process."""

        project_id, session_id = self._safe_session_ids(project_id, session_id)
        code = _safe_nonempty(code, "code")
        message = _safe_nonempty(message, "message")
        with self._project_lock(project_id):
            session = self._recover_session_unlocked(project_id, session_id)
            updated = session.model_copy(
                update={
                    "status": CreatorSessionStatus.ERROR,
                    "error": {
                        "code": code,
                        "message": message,
                        "retryable": retryable,
                        "details": dict(details or {}),
                    },
                    "updated_at": utc_now(),
                },
            )
            return self._write_session_unlocked(updated)

    def mark_messages_consumed(
        self,
        project_id: str,
        session_id: str,
        *,
        through_seq: int,
        goal_id: str | None = None,
        expected_previous_seq: int | None = None,
    ) -> CreatorSessionRecord:
        """Advance the durable input cursor monotonically under the Runtime lock.

        The cursor points at the latest user input completed by the Agent.  It
        may therefore sit before assistant/tool progress records appended by
        that run.  A stale worker cannot move it backwards or jump beyond the
        durable message stream.
        """

        project_id, session_id = self._safe_session_ids(project_id, session_id)
        if through_seq < 0:
            raise ValueError("through_seq must be non-negative")
        if expected_previous_seq is not None and expected_previous_seq < 0:
            raise ValueError("expected_previous_seq must be non-negative")
        resolved_goal_id = (
            _safe_segment(goal_id, "goal_id") if goal_id is not None else None
        )
        with self._project_lock(project_id):
            session = self._recover_session_unlocked(project_id, session_id)
            if (
                expected_previous_seq is not None
                and session.last_consumed_message_seq != expected_previous_seq
            ):
                raise SessionStateConflict(
                    "Consumed message cursor conflict: "
                    f"expected={expected_previous_seq}, "
                    f"actual={session.last_consumed_message_seq}",
                )
            if through_seq < session.last_consumed_message_seq:
                raise SessionStateConflict(
                    "Consumed message cursor cannot move backwards",
                )
            if through_seq > session.last_message_seq:
                raise SessionStateConflict(
                    "Consumed message cursor exceeds durable message head",
                )
            if resolved_goal_id is not None:
                goal = self._read_goal_unlocked(project_id, resolved_goal_id)
                self._assert_goal_ownership(goal, session_id=session_id)
                if through_seq < goal.last_consumed_message_seq:
                    raise SessionStateConflict(
                        "Goal consumed message cursor cannot move backwards",
                    )
                self._goal_store(project_id, resolved_goal_id).write(
                    goal.model_copy(
                        update={
                            "last_consumed_message_seq": through_seq,
                            "updated_at": utc_now(),
                        },
                    ),
                )
            updated = session.model_copy(
                update={
                    "last_consumed_message_seq": through_seq,
                    "updated_at": utc_now(),
                },
            )
            return self._write_session_unlocked(updated)

    def activate_run(
        self,
        project_id: str,
        session_id: str,
        *,
        goal_id: str,
        run_id: str,
        status: CreatorSessionStatus | str = CreatorSessionStatus.RUNNING,
    ) -> CreatorSessionRecord:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        goal_id = _safe_segment(goal_id, "goal_id")
        run_id = _safe_segment(run_id, "run_id")
        resolved_status = CreatorSessionStatus(status)
        with self._project_lock(project_id):
            session = self._recover_session_unlocked(project_id, session_id)
            goal = self._read_goal_unlocked(project_id, goal_id)
            self._assert_goal_ownership(goal, session_id=session_id)
            if session.active_run_id not in {None, run_id}:
                raise SessionStateConflict(
                    "Another Agent run already owns this Project Session: "
                    f"{session.active_run_id}",
                )
            updated = session.model_copy(
                update={
                    "active_goal_id": goal_id,
                    "active_run_id": run_id,
                    "status": resolved_status,
                    "error": None,
                    "updated_at": utc_now(),
                },
            )
            return self._write_session_unlocked(updated)

    def clear_active_run(
        self,
        project_id: str,
        session_id: str,
        *,
        expected_run_id: str | None = None,
        status: CreatorSessionStatus | str | None = None,
    ) -> CreatorSessionRecord:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        if expected_run_id is not None:
            expected_run_id = _safe_segment(expected_run_id, "run_id")
        with self._project_lock(project_id):
            session = self._recover_session_unlocked(project_id, session_id)
            if (
                expected_run_id is not None
                and session.active_run_id != expected_run_id
            ):
                raise SessionStateConflict(
                    "Active run conflict: "
                    f"expected={expected_run_id!r}, "
                    f"actual={session.active_run_id!r}",
                )
            updates: dict[str, Any] = {
                "active_run_id": None,
                "updated_at": utc_now(),
            }
            if status is not None:
                updates["status"] = CreatorSessionStatus(status)
            updated = session.model_copy(update=updates)
            return self._write_session_unlocked(updated)

    def create_conversation(
        self,
        project_id: str,
        session_id: str,
        *,
        conversation_id: str | None = None,
        title: str,
        is_default: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> CreatorConversationRecord:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        conversation_id = _safe_segment(
            conversation_id or _new_id("conversation"),
            "conversation_id",
        )
        if not title:
            raise ValueError("Conversation title cannot be empty")
        with self._project_lock(project_id):
            self._read_session_unlocked(project_id, session_id)
            existing = self._list_conversations_unlocked(
                project_id,
                session_id,
            )
            if is_default and any(item.is_default for item in existing):
                raise SessionStateConflict(
                    "Project already has a default Conversation",
                )
            record = CreatorConversationRecord(
                conversation_id=conversation_id,
                project_id=project_id,
                creator_session_id=session_id,
                title=title,
                is_default=is_default,
                metadata=dict(metadata or {}),
            )
            store = self._conversation_store(
                project_id,
                session_id,
                conversation_id,
            )
            try:
                store.create(record)
            except RecordAlreadyExistsError as exc:
                raise SessionStateConflict(
                    f"Conversation already exists: {conversation_id}",
                ) from exc
            return record

    def get_conversation(
        self,
        project_id: str,
        session_id: str,
        conversation_id: str,
    ) -> CreatorConversationRecord:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        conversation_id = _safe_segment(conversation_id, "conversation_id")
        with self._project_lock_read(project_id):
            return self._read_conversation_unlocked(
                project_id,
                session_id,
                conversation_id,
            )

    def list_conversations(
        self,
        project_id: str,
        session_id: str,
    ) -> list[CreatorConversationRecord]:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        with self._project_lock_read(project_id):
            self._read_session_snapshot_unlocked(project_id, session_id)
            return self._list_conversations_unlocked(project_id, session_id)

    def create_goal(
        self,
        project_id: str,
        session_id: str,
        conversation_id: str,
        *,
        root_message_seq: int,
        intent: str,
        goal_id: str | None = None,
        success_criteria: Sequence[Any] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> CreatorGoalRecord:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        conversation_id = _safe_segment(conversation_id, "conversation_id")
        goal_id = _safe_segment(goal_id or _new_id("goal"), "goal_id")
        if not intent:
            raise ValueError("Goal intent cannot be empty")
        with self._project_lock(project_id):
            session = self._recover_session_unlocked(project_id, session_id)
            conversation = self._read_conversation_unlocked(
                project_id,
                session_id,
                conversation_id,
            )
            self._assert_conversation_ownership(
                conversation,
                session_id=session_id,
            )
            if not 1 <= root_message_seq <= session.last_message_seq:
                raise SessionStateConflict(
                    "Goal root_message_seq must reference a durable message",
                )
            root_message = self._message_records_unlocked(
                project_id,
                session_id,
            )[root_message_seq - 1]
            if root_message.conversation_id != conversation_id:
                raise SessionStateConflict(
                    "Goal root message belongs to another Conversation",
                )
            record = CreatorGoalRecord(
                goal_id=goal_id,
                project_id=project_id,
                creator_session_id=session_id,
                conversation_id=conversation_id,
                root_message_seq=root_message_seq,
                intent=intent,
                success_criteria=list(success_criteria),
                metadata=dict(metadata or {}),
            )
            store = self._goal_store(project_id, goal_id)
            existing = store.read_or_none()
            if existing is not None:
                comparable_existing = existing.model_dump(
                    exclude={"created_at", "updated_at"},
                )
                comparable_requested = record.model_dump(
                    exclude={"created_at", "updated_at"},
                )
                if comparable_existing != comparable_requested:
                    raise SessionStateConflict(
                        f"Goal already exists with other data: {goal_id}",
                    )
                record = existing
            else:
                store.create(record)
            updated = session.model_copy(
                update={
                    "active_goal_id": goal_id,
                    "updated_at": utc_now(),
                },
            )
            self._write_session_unlocked(updated)
            logger.info(
                "goal created: project=%s goal=%s intent=%s",
                project_id,
                goal_id,
                intent[:50],
            )
            return record

    def get_goal(self, project_id: str, goal_id: str) -> CreatorGoalRecord:
        project_id = _safe_segment(project_id, "project_id")
        goal_id = _safe_segment(goal_id, "goal_id")
        self._require_project(project_id)
        with self._project_lock_read(project_id):
            return self._read_goal_unlocked(project_id, goal_id)

    def set_goal_status(
        self,
        project_id: str,
        goal_id: str,
        status: CreatorGoalStatus | str,
        *,
        expected_status: CreatorGoalStatus | str | None = None,
    ) -> CreatorGoalRecord:
        project_id = _safe_segment(project_id, "project_id")
        goal_id = _safe_segment(goal_id, "goal_id")
        self._require_project(project_id)
        resolved_status = CreatorGoalStatus(status)
        resolved_expected = (
            CreatorGoalStatus(expected_status)
            if expected_status is not None
            else None
        )
        with self._project_lock(project_id):
            goal = self._read_goal_unlocked(project_id, goal_id)
            if (
                resolved_expected is not None
                and goal.status is not resolved_expected
            ):
                raise SessionStateConflict(
                    "Goal status conflict: "
                    f"expected={resolved_expected.value}, "
                    f"actual={goal.status.value}",
                )
            updated = goal.model_copy(
                update={"status": resolved_status, "updated_at": utc_now()},
            )
            self._goal_store(project_id, goal_id).write(updated)
            logger.info(
                "goal status: project=%s goal=%s status=%s",
                project_id,
                goal_id,
                resolved_status.value,
            )
            return CreatorGoalRecord.model_validate(updated)

    def resolve_pending_review(
        self,
        project_id: str,
        session_id: str,
        *,
        actor: str = "file_agent_runtime",
    ) -> CreatorSessionRecord:
        """Publish Review completion before exposing the Session as idle.

        ``IDLE`` is the externally observed completion barrier for polling
        clients.  The Goal projection and ``agent.review.resolved`` event must
        therefore be durable before that status becomes visible.  Keeping all
        three writes under the Project Runtime lock also serializes competing
        supervisors.  The resolution key makes a retry after a process crash
        reuse an event already appended before the final Session write.
        """

        project_id, session_id = self._safe_session_ids(project_id, session_id)
        actor = _safe_nonempty(actor, "actor")
        with self._project_lock(project_id):
            session = self._recover_session_unlocked(project_id, session_id)
            if session.status not in {
                CreatorSessionStatus.PENDING_REVIEW,
                CreatorSessionStatus.IDLE,
            }:
                raise SessionStateConflict(
                    "Review resolution requires a pending Review Session: "
                    f"actual={session.status.value}",
                )
            goal_id = session.active_goal_id
            if goal_id is None:
                raise SessionStateConflict(
                    "Review resolution requires an active Goal",
                )
            goal = self._read_goal_unlocked(project_id, goal_id)
            self._assert_goal_ownership(goal, session_id=session_id)
            if goal.status is CreatorGoalStatus.WAITING_REVIEW:
                goal = goal.model_copy(
                    update={
                        "status": CreatorGoalStatus.COMPLETED,
                        "updated_at": utc_now(),
                    },
                )
                self._goal_store(project_id, goal_id).write(goal)
            elif goal.status is not CreatorGoalStatus.COMPLETED:
                raise SessionStateConflict(
                    "Review resolution requires a waiting or completed Goal: "
                    f"actual={goal.status.value}",
                )

            resolution_key = f"{goal_id}:{goal.updated_at.isoformat()}"
            events = self._event_records_unlocked(project_id, session_id)
            has_resolution_event = any(
                event.event_type == "agent.review.resolved"
                and event.payload.get("resolutionKey") == resolution_key
                for event in events
            )
            if not has_resolution_event:
                event_seq = len(events) + 1
                self._events_store(project_id, session_id).append(
                    SessionEventRecord(
                        event_id=_new_id("event"),
                        project_id=project_id,
                        creator_session_id=session_id,
                        event_seq=event_seq,
                        event_type="agent.review.resolved",
                        actor=actor,
                        payload={
                            "goalId": goal_id,
                            "status": CreatorSessionStatus.IDLE.value,
                            "resolutionKey": resolution_key,
                        },
                    ),
                    expected_next_seq=event_seq,
                )
            else:
                event_seq = len(events)

            updated = session.model_copy(
                update={
                    "status": CreatorSessionStatus.IDLE,
                    "last_event_seq": event_seq,
                    "updated_at": utc_now(),
                },
            )
            return self._write_session_unlocked(updated)

    def append_message(
        self,
        project_id: str,
        session_id: str,
        conversation_id: str,
        *,
        role: Literal["system", "user", "assistant", "tool"],
        content_parts: Sequence[ContentPartInput],
        message_id: str | None = None,
        client_message_id: str | None = None,
        source: str = "runtime",
        channel: MessageChannel | str = MessageChannel.RUNTIME,
        classification: MessageClassification | str | None = None,
        metadata: Mapping[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> MessageAppendResult:
        project_id, session_id, conversation_id = self._safe_message_ids(
            project_id,
            session_id,
            conversation_id,
        )
        if client_message_id is not None:
            client_message_id = _safe_nonempty(
                client_message_id,
                "client_message_id",
            )
        if message_id is not None:
            message_id = _safe_nonempty(message_id, "message_id")
        parts = _normalize_content_parts(content_parts)
        resolved_channel = MessageChannel(channel)
        resolved_classification = (
            MessageClassification(classification)
            if classification is not None
            else None
        )
        metadata_dict = dict(metadata or {})
        request_hash = (
            _request_hash(
                {
                    "conversation_id": conversation_id,
                    "role": role,
                    "content_parts": parts,
                    "source": source,
                    "channel": resolved_channel,
                    "classification": resolved_classification,
                    "metadata": metadata_dict,
                    "completed_at": completed_at,
                },
            )
            if client_message_id is not None
            else None
        )
        with self._project_lock(project_id):
            return self._append_message_unlocked(
                project_id=project_id,
                session_id=session_id,
                conversation_id=conversation_id,
                role=role,
                content_parts=parts,
                message_id=message_id,
                client_message_id=client_message_id,
                request_hash=request_hash,
                source=source,
                channel=resolved_channel,
                classification=resolved_classification,
                review_boundary=None,
                metadata=metadata_dict,
                completed_at=completed_at,
            )

    def admit_user_request(
        self,
        project_id: str,
        session_id: str,
        conversation_id: str,
        *,
        request_id: str,
        client_message_id: str,
        content_parts: Sequence[ContentPartInput],
        channel: MessageChannel | str,
        classification: MessageClassification | str,
        source: str = "user",
        metadata: Mapping[str, Any] | None = None,
        initial_creation: bool = False,
        hard_stop: bool = False,
        admission_guard: Callable[[], bool] | None = None,
    ) -> RequestAdmissionResult:
        """Persist a user request and decide review admission under one lock.

        The active run check, accepted baseline capture, message append and
        ReviewBoundary publication are serialized by the same Project Runtime
        lock.  Therefore a returned ``require_review`` decision always points
        to an already durable boundary.

        ``admission_guard`` runs inside the Project lifecycle boundary right
        before the request becomes durable; returning ``False`` aborts the
        admission with :class:`RequestAdmissionConflict`. Automated writers
        (for example the render self-review loop) use it to re-validate a
        precondition atomically against concurrent Project commits.
        """

        project_id, session_id, conversation_id = self._safe_message_ids(
            project_id,
            session_id,
            conversation_id,
        )
        request_id = _safe_nonempty(request_id, "request_id")
        client_message_id = _safe_nonempty(
            client_message_id,
            "client_message_id",
        )
        parts = _normalize_content_parts(content_parts)
        resolved_channel = MessageChannel(channel)
        resolved_classification = MessageClassification(classification)
        metadata_dict = dict(metadata or {})
        request_hash = _request_hash(
            {
                "request_id": request_id,
                "conversation_id": conversation_id,
                "role": "user",
                "content_parts": parts,
                "source": source,
                "channel": resolved_channel,
                "classification": resolved_classification,
                "metadata": metadata_dict,
                "initial_creation": initial_creation,
                "hard_stop": hard_stop,
            },
        )
        # Review admission and Project commit finalization share this order
        # lock.  The boundary therefore cannot capture an accepted baseline
        # from the crash window after project.json was replaced but before
        # runtime/state.json was advanced.
        with self._project_lifecycle_lock(project_id):
            # The precheck performed while normalizing IDs can race delete.
            # Revalidate only after lifecycle admission, before either Runtime
            # lock is allowed to create parent directories.
            self._require_project(project_id)
            if admission_guard is not None and not admission_guard():
                raise RequestAdmissionConflict(
                    "admission guard rejected the request",
                )
            with (
                self._project_commit_order_lock(project_id),
                self._runtime_lock(project_id),
            ):
                session = self._recover_session_unlocked(
                    project_id,
                    session_id,
                )
                self._read_conversation_unlocked(
                    project_id,
                    session_id,
                    conversation_id,
                )
                existing = self._message_by_client_id_unlocked(
                    project_id,
                    session_id,
                    client_message_id,
                )
                if existing is not None:
                    self._assert_same_message_request(
                        existing,
                        client_message_id=client_message_id,
                        request_hash=request_hash,
                    )
                    if existing.review_boundary is not None:
                        self._ensure_review_boundary_unlocked(
                            project_id,
                            session_id,
                            existing.review_boundary,
                        )
                    return RequestAdmissionResult(
                        message=existing,
                        review_policy=(
                            ReviewPolicy.REQUIRE_REVIEW
                            if existing.review_boundary is not None
                            else ReviewPolicy.AUTO_FIX
                        ),
                        review_boundary=existing.review_boundary,
                        replayed=True,
                    )

                boundary: ReviewBoundary | None = None
                project_state: RuntimeProjectState | None = None
                requires_review = self._requires_review(
                    session,
                    channel=resolved_channel,
                    classification=resolved_classification,
                    initial_creation=initial_creation,
                    hard_stop=hard_stop,
                )
                if requires_review:
                    self._assert_review_active_goal_unlocked(
                        project_id,
                        session,
                    )
                    project_state = self._runtime_state_store(
                        project_id,
                    ).read_or_none()
                    if project_state is None:
                        if session.active_run_id is not None:
                            raise RequestAdmissionConflict(
                                "Cannot capture review boundary without runtime/state.json",
                            )
                        # A brand-new Project has no accepted baseline yet, so
                        # an idle feedback request has nothing to diff against.
                        # Admit it as a plain auto-fix instruction instead of
                        # failing the request.
                        requires_review = False
                    elif project_state.project_id != project_id:
                        raise SessionStoreIntegrityError(
                            "RuntimeProjectState belongs to another Project",
                        )
                if requires_review and project_state is not None:
                    next_message_seq = (
                        self._messages_store(project_id, session_id).last_seq()
                        + 1
                    )
                    boundary = ReviewBoundary(
                        request_message_seq=next_message_seq,
                        request_id=request_id,
                        interrupted_run_id=session.active_run_id,
                        accepted_generation=project_state.accepted_generation,
                        accepted_etag=project_state.accepted_etag,
                    )
                    boundary_path = self.review_boundary_path(
                        project_id,
                        session_id,
                        request_id,
                    )
                    if (
                        AtomicJsonRecordStore(
                            boundary_path,
                            ReviewBoundary,
                        ).read_or_none()
                        is not None
                    ):
                        raise RequestAdmissionConflict(
                            "request_id already owns another ReviewBoundary",
                        )

                append_result = self._append_message_unlocked(
                    project_id=project_id,
                    session_id=session_id,
                    conversation_id=conversation_id,
                    role="user",
                    content_parts=parts,
                    message_id=None,
                    client_message_id=client_message_id,
                    request_hash=request_hash,
                    source=source,
                    channel=resolved_channel,
                    classification=resolved_classification,
                    review_boundary=boundary,
                    metadata=metadata_dict,
                    completed_at=None,
                )
                if boundary is not None:
                    self._ensure_review_boundary_unlocked(
                        project_id,
                        session_id,
                        boundary,
                    )
                result = RequestAdmissionResult(
                    message=append_result.message,
                    review_policy=(
                        ReviewPolicy.REQUIRE_REVIEW
                        if boundary is not None
                        else ReviewPolicy.AUTO_FIX
                    ),
                    review_boundary=boundary,
                    replayed=append_result.replayed,
                )
                logger.info(
                    "message admitted: project=%s session=%s seq=%d replayed=%s",
                    project_id,
                    session_id,
                    append_result.message.message_seq,
                    append_result.replayed,
                )
                return result

    def list_messages(
        self,
        project_id: str,
        session_id: str,
        *,
        after_seq: int = 0,
        limit: int | None = None,
    ) -> list[CreatorMessageRecord]:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        _validate_window(after_seq, limit)
        with self._project_lock_read(project_id):
            self._read_session_snapshot_unlocked(project_id, session_id)
            records = self._message_records_unlocked(project_id, session_id)
            return _window(records, after_seq=after_seq, limit=limit)

    def append_event(
        self,
        project_id: str,
        session_id: str,
        *,
        event_type: str,
        actor: str = "runtime",
        round_id: str | None = None,
        message_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> SessionEventRecord:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        event_type = _safe_nonempty(event_type, "event_type")
        actor = _safe_nonempty(actor, "actor")
        with self._project_lock(project_id):
            session = self._read_session_unlocked(project_id, session_id)
            store = self._events_store(project_id, session_id)
            event_id = _new_id("event")

            def append_for(
                current: CreatorSessionRecord,
            ) -> SessionEventRecord:
                seq = current.last_event_seq + 1
                record = SessionEventRecord(
                    event_id=event_id,
                    project_id=project_id,
                    creator_session_id=session_id,
                    event_seq=seq,
                    event_type=event_type,
                    actor=actor,
                    round_id=round_id,
                    message_id=message_id,
                    payload=dict(payload or {}),
                )
                store.append(record, expected_next_seq=seq)
                return record

            try:
                record = append_for(session)
            except SequenceConflictError:
                # A crash can durably append the event before updating the
                # aggregate head. Pay the full recovery cost only for that
                # exceptional reconciliation path, never for every token.
                session = self._recover_session_unlocked(
                    project_id,
                    session_id,
                )
                record = append_for(session)
            updated = session.model_copy(
                update={
                    "last_event_seq": record.event_seq,
                    "updated_at": utc_now(),
                },
            )
            self._write_session_unlocked(updated)
            logger.debug(
                "event appended: project=%s session=%s type=%s seq=%d",
                project_id,
                session_id,
                event_type,
                record.event_seq,
            )
            return record

    def list_events(
        self,
        project_id: str,
        session_id: str,
        *,
        after_seq: int = 0,
        limit: int | None = None,
    ) -> list[SessionEventRecord]:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        _validate_window(after_seq, limit)
        with self._project_lock_read(project_id):
            # Tail-only read: avoid parsing the whole events.jsonl on every
            # poll.  The durable stream is authoritative for windowing and the
            # next writer repairs a stale head pointer.
            store = self._events_store(project_id, session_id)
            records = store.read_records_after(after_seq, limit=limit)
            return records

    def append_queued_message(
        self,
        project_id: str,
        session_id: str,
        conversation_id: str,
        *,
        client_message_id: str,
        content_parts: Sequence[ContentPartInput],
        source: str = "user",
        metadata: Mapping[str, Any] | None = None,
    ) -> QueuedMessageRecord:
        project_id, session_id, conversation_id = self._safe_message_ids(
            project_id,
            session_id,
            conversation_id,
        )
        client_message_id = _safe_nonempty(
            client_message_id,
            "client_message_id",
        )
        parts = _normalize_content_parts(content_parts)
        metadata_dict = dict(metadata or {})
        request_hash = _request_hash(
            {
                "conversation_id": conversation_id,
                "content_parts": parts,
                "source": source,
                "metadata": metadata_dict,
            },
        )
        with self._project_lock(project_id):
            session = self._recover_session_unlocked(project_id, session_id)
            self._read_conversation_unlocked(
                project_id,
                session_id,
                conversation_id,
            )
            records = self._queued_records_unlocked(project_id, session_id)
            matches = [
                item
                for item in records
                if item.client_message_id == client_message_id
            ]
            if matches:
                existing = matches[-1]
                if existing.request_hash != request_hash:
                    raise MessagePayloadConflict(
                        f"Queued client_message_id payload drift: {client_message_id}",
                    )
                return existing
            store = self._queued_store(project_id, session_id)
            seq = store.last_seq() + 1
            record = QueuedMessageRecord(
                queued_message_id=_new_id("queued-message"),
                queue_seq=seq,
                project_id=project_id,
                creator_session_id=session_id,
                conversation_id=conversation_id,
                client_message_id=client_message_id,
                request_hash=request_hash,
                content_parts=parts,
                source=source,
                metadata=metadata_dict,
            )
            store.append(record, expected_next_seq=seq)
            updated = session.model_copy(
                update={
                    "queued_user_message_count": (
                        session.queued_user_message_count + 1
                    ),
                    "updated_at": utc_now(),
                },
            )
            self._write_session_unlocked(updated)
            return record

    def transition_queued_message(
        self,
        project_id: str,
        session_id: str,
        queued_message_id: str,
        *,
        state: QueuedMessageState | str,
        appended_message_id: str | None = None,
    ) -> QueuedMessageRecord:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        queued_message_id = _safe_segment(
            queued_message_id,
            "queued_message_id",
        )
        resolved_state = QueuedMessageState(state)
        with self._project_lock(project_id):
            session = self._recover_session_unlocked(project_id, session_id)
            records = self._queued_records_unlocked(project_id, session_id)
            existing = next(
                (
                    item
                    for item in reversed(records)
                    if item.queued_message_id == queued_message_id
                ),
                None,
            )
            if existing is None:
                raise SessionStateConflict(
                    f"Queued message not found: {queued_message_id}",
                )
            if existing.state is not QueuedMessageState.QUEUED:
                if (
                    existing.state is resolved_state
                    and existing.appended_message_id == appended_message_id
                ):
                    return existing
                raise SessionStateConflict(
                    f"Queued message is already {existing.state.value}",
                )
            store = self._queued_store(project_id, session_id)
            seq = store.last_seq() + 1
            updated = existing.model_copy(
                update={
                    "queue_seq": seq,
                    "state": resolved_state,
                    "appended_message_id": appended_message_id,
                    "updated_at": utc_now(),
                },
            )
            validated = QueuedMessageRecord.model_validate(updated)
            store.append(validated, expected_next_seq=seq)
            session_updated = session.model_copy(
                update={
                    "queued_user_message_count": max(
                        0,
                        session.queued_user_message_count - 1,
                    ),
                    "updated_at": utc_now(),
                },
            )
            self._write_session_unlocked(session_updated)
            logger.info(
                "queued_message transition: project=%s session=%s id=%s state=%s",
                project_id,
                session_id,
                queued_message_id,
                resolved_state.value,
            )
            return validated

    def list_queued_messages(
        self,
        project_id: str,
        session_id: str,
        *,
        after_seq: int = 0,
        limit: int | None = None,
    ) -> list[QueuedMessageRecord]:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        _validate_window(after_seq, limit)
        with self._project_lock_read(project_id):
            self._read_session_snapshot_unlocked(project_id, session_id)
            records = self._queued_records_unlocked(project_id, session_id)
            return _window(records, after_seq=after_seq, limit=limit)

    def append_outbox(
        self,
        project_id: str,
        session_id: str,
        conversation_id: str,
        *,
        outbox_id: str,
        content_parts: Sequence[ContentPartInput],
        source: str = "frontend_manual_edit",
        metadata: Mapping[str, Any] | None = None,
    ) -> OutboxRecord:
        project_id, session_id, conversation_id = self._safe_message_ids(
            project_id,
            session_id,
            conversation_id,
        )
        outbox_id = _safe_nonempty(outbox_id, "outbox_id")
        parts = _normalize_content_parts(content_parts)
        metadata_dict = dict(metadata or {})
        request_hash = _request_hash(
            {
                "conversation_id": conversation_id,
                "content_parts": parts,
                "source": source,
                "metadata": metadata_dict,
            },
        )
        with self._project_lock(project_id):
            self._recover_session_unlocked(project_id, session_id)
            self._read_conversation_unlocked(
                project_id,
                session_id,
                conversation_id,
            )
            records = self._outbox_records_unlocked(project_id, session_id)
            matches = [item for item in records if item.outbox_id == outbox_id]
            if matches:
                existing = matches[-1]
                if existing.request_hash != request_hash:
                    raise MessagePayloadConflict(
                        f"Outbox id payload drift: {outbox_id}",
                    )
                return existing
            store = self._outbox_store(project_id, session_id)
            seq = store.last_seq() + 1
            record = OutboxRecord(
                record_id=_new_id("outbox-record"),
                outbox_seq=seq,
                project_id=project_id,
                creator_session_id=session_id,
                conversation_id=conversation_id,
                outbox_id=outbox_id,
                request_hash=request_hash,
                content_parts=parts,
                source=source,
                metadata=metadata_dict,
            )
            store.append(record, expected_next_seq=seq)
            return record

    def transition_outbox(
        self,
        project_id: str,
        session_id: str,
        outbox_id: str,
        *,
        state: OutboxState | str,
        linked_message_id: str | None = None,
    ) -> OutboxRecord:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        outbox_id = _safe_nonempty(outbox_id, "outbox_id")
        resolved_state = OutboxState(state)
        with self._project_lock(project_id):
            self._recover_session_unlocked(project_id, session_id)
            records = self._outbox_records_unlocked(project_id, session_id)
            existing = next(
                (
                    item
                    for item in reversed(records)
                    if item.outbox_id == outbox_id
                ),
                None,
            )
            if existing is None:
                raise SessionStateConflict(
                    f"Outbox record not found: {outbox_id}",
                )
            if existing.state is not OutboxState.PENDING:
                if (
                    existing.state is resolved_state
                    and existing.linked_message_id == linked_message_id
                ):
                    return existing
                raise SessionStateConflict(
                    f"Outbox record is already {existing.state.value}",
                )
            store = self._outbox_store(project_id, session_id)
            seq = store.last_seq() + 1
            updated = existing.model_copy(
                update={
                    "outbox_seq": seq,
                    "state": resolved_state,
                    "linked_message_id": linked_message_id,
                    "updated_at": utc_now(),
                },
            )
            validated = OutboxRecord.model_validate(updated)
            store.append(validated, expected_next_seq=seq)
            logger.info(
                "outbox transition: project=%s session=%s id=%s state=%s",
                project_id,
                session_id,
                outbox_id,
                resolved_state.value,
            )
            return validated

    def list_outbox(
        self,
        project_id: str,
        session_id: str,
        *,
        after_seq: int = 0,
        limit: int | None = None,
    ) -> list[OutboxRecord]:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        _validate_window(after_seq, limit)
        with self._project_lock_read(project_id):
            self._read_session_snapshot_unlocked(project_id, session_id)
            records = self._outbox_records_unlocked(project_id, session_id)
            return _window(records, after_seq=after_seq, limit=limit)

    def review_boundary_path(
        self,
        project_id: str,
        session_id: str,
        request_id: str,
    ) -> Path:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        request_id = _safe_nonempty(request_id, "request_id")
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        return (
            self._session_root(project_id, session_id)
            / "review-boundaries"
            / f"{digest}.json"
        )

    def _append_message_unlocked(
        self,
        *,
        project_id: str,
        session_id: str,
        conversation_id: str,
        role: Literal["system", "user", "assistant", "tool"],
        content_parts: list[MessageContentPart],
        message_id: str | None,
        client_message_id: str | None,
        request_hash: str | None,
        source: str,
        channel: MessageChannel,
        classification: MessageClassification | None,
        review_boundary: ReviewBoundary | None,
        metadata: dict[str, Any],
        completed_at: datetime | None,
    ) -> MessageAppendResult:
        session = self._recover_session_unlocked(project_id, session_id)
        conversation = self._read_conversation_unlocked(
            project_id,
            session_id,
            conversation_id,
        )
        self._assert_conversation_ownership(
            conversation,
            session_id=session_id,
        )
        if client_message_id is not None:
            existing = self._message_by_client_id_unlocked(
                project_id,
                session_id,
                client_message_id,
            )
            if existing is not None:
                self._assert_same_message_request(
                    existing,
                    client_message_id=client_message_id,
                    request_hash=request_hash,
                )
                return MessageAppendResult(existing, replayed=True)
        store = self._messages_store(project_id, session_id)
        seq = store.last_seq() + 1
        if (
            review_boundary is not None
            and review_boundary.request_message_seq != seq
        ):
            raise SessionStateConflict(
                "ReviewBoundary message seq no longer matches stream head",
            )
        message = CreatorMessageRecord(
            message_id=message_id or _new_id("message"),
            project_id=project_id,
            creator_session_id=session_id,
            conversation_id=conversation_id,
            message_seq=seq,
            role=role,
            content_parts=content_parts,
            client_message_id=client_message_id,
            request_hash=request_hash,
            source=source,
            channel=channel,
            classification=classification,
            review_boundary=review_boundary,
            metadata=metadata,
            completed_at=completed_at,
        )
        store.append(message, expected_next_seq=seq)
        updated = session.model_copy(
            update={"last_message_seq": seq, "updated_at": utc_now()},
        )
        self._write_session_unlocked(updated)
        return MessageAppendResult(message, replayed=False)

    @staticmethod
    def _assert_same_message_request(
        existing: CreatorMessageRecord,
        *,
        client_message_id: str,
        request_hash: str | None,
    ) -> None:
        if existing.request_hash != request_hash:
            raise MessagePayloadConflict(
                f"client_message_id payload drift: {client_message_id}",
            )

    @staticmethod
    def _requires_review(
        session: CreatorSessionRecord,
        *,
        channel: MessageChannel,
        classification: MessageClassification,
        initial_creation: bool,
        hard_stop: bool,
    ) -> bool:
        if (
            channel is not MessageChannel.AGENTDOCK
            or classification not in _REVIEW_MUTATING_CLASSIFICATIONS
            or initial_creation
            or hard_stop
            or session.status not in _REVIEW_ACTIVE_STATUSES
        ):
            return False
        # Delegated governance means "never ask mid-flight": mainline
        # feedback is auto-applied instead of parked behind a diff review
        # nobody is attending. Imported lazily — runtime_files must not
        # depend on models at module load.
        from models.config import (  # pylint: disable=import-outside-toplevel
            EXECUTION_MODE_DELEGATED,
            get_execution_mode,
        )

        if get_execution_mode() == EXECUTION_MODE_DELEGATED:
            return False
        # A running Session must expose a coherent Goal/Run pair before an
        # interrupt boundary may be captured.
        if session.active_run_id:
            return bool(session.active_goal_id)
        # An idle Session requires review only when a Goal already exists:
        # the request is then feedback (revision comments) on previously produced
        # mainline work.  A Session that has never owned a Goal is receiving
        # its mainline kick-off request (e.g. the first instruction after an
        # attachment-driven Project creation), and every change on that
        # mainline is auto-applied without review.
        return bool(session.active_goal_id)

    def _assert_review_active_goal_unlocked(
        self,
        project_id: str,
        session: CreatorSessionRecord,
    ) -> None:
        if session.active_run_id is None:
            # Idle-goal boundary: no Run is interrupted and the driver will
            # admit a fresh Goal for this feedback request.
            return
        if session.active_goal_id is None:
            raise RequestAdmissionConflict(
                "Review admission requires an active Goal and Run",
            )
        goal = self._read_goal_unlocked(project_id, session.active_goal_id)
        self._assert_goal_ownership(goal, session_id=session.session_id)
        if goal.status not in {
            CreatorGoalStatus.ACTIVE,
            CreatorGoalStatus.RESUME_REQUIRED,
            CreatorGoalStatus.WAITING_REVIEW,
        }:
            raise RequestAdmissionConflict(
                f"Active Goal is terminal: {goal.status.value}; the runtime "
                "reclaims the orphaned run automatically — retry shortly",
            )

    def _ensure_review_boundary_unlocked(
        self,
        project_id: str,
        session_id: str,
        boundary: ReviewBoundary,
    ) -> None:
        path = self.review_boundary_path(
            project_id,
            session_id,
            boundary.request_id,
        )
        store = AtomicJsonRecordStore(path, ReviewBoundary)
        existing = store.read_or_none()
        if existing is None:
            store.create(boundary)
            return
        if existing != boundary:
            raise SessionStoreIntegrityError(
                "ReviewBoundary request id maps to conflicting data",
            )

    def _read_session_snapshot_unlocked(
        self,
        project_id: str,
        session_id: str,
    ) -> CreatorSessionRecord:
        """Read the Session record without reconciling or writing anything.

        Unlike :meth:`_recover_session_unlocked`, this never repairs a stale
        head pointer or persists a recovered record, so it is safe under the
        shared read lock.  Head reconciliation is left to the next writer.
        """
        return self._read_session_unlocked(project_id, session_id)

    def _recover_session_unlocked(
        self,
        project_id: str,
        session_id: str,
    ) -> CreatorSessionRecord:
        session = self._read_session_unlocked(project_id, session_id)
        messages = self._message_records_unlocked(project_id, session_id)
        events = self._event_records_unlocked(project_id, session_id)
        queued = self._queued_records_unlocked(project_id, session_id)
        latest_queued = _latest_by(queued, "queued_message_id")
        queue_count = sum(
            item.state is QueuedMessageState.QUEUED
            for item in latest_queued.values()
        )
        message_head = len(messages)
        event_head = len(events)
        for message in messages:
            if message.review_boundary is not None:
                self._ensure_review_boundary_unlocked(
                    project_id,
                    session_id,
                    message.review_boundary,
                )
        if (
            session.last_message_seq == message_head
            and session.last_event_seq == event_head
            and session.queued_user_message_count == queue_count
        ):
            return session
        if session.last_consumed_message_seq > message_head:
            raise SessionStoreIntegrityError(
                "Consumed message head exceeds durable message stream",
            )
        recovered = session.model_copy(
            update={
                "last_message_seq": message_head,
                "last_event_seq": event_head,
                "queued_user_message_count": queue_count,
                "updated_at": utc_now(),
            },
        )
        return self._write_session_unlocked(recovered)

    def _message_records_unlocked(
        self,
        project_id: str,
        session_id: str,
    ) -> list[CreatorMessageRecord]:
        records = self._messages_store(project_id, session_id).read_records()
        _assert_internal_sequence(
            records,
            attribute="message_seq",
            stream_name="messages",
        )
        return records

    def _event_records_unlocked(
        self,
        project_id: str,
        session_id: str,
    ) -> list[SessionEventRecord]:
        records = self._events_store(project_id, session_id).read_records()
        _assert_internal_sequence(
            records,
            attribute="event_seq",
            stream_name="events",
        )
        return records

    def _queued_records_unlocked(
        self,
        project_id: str,
        session_id: str,
    ) -> list[QueuedMessageRecord]:
        records = self._queued_store(project_id, session_id).read_records()
        _assert_internal_sequence(
            records,
            attribute="queue_seq",
            stream_name="queued messages",
        )
        return records

    def _outbox_records_unlocked(
        self,
        project_id: str,
        session_id: str,
    ) -> list[OutboxRecord]:
        records = self._outbox_store(project_id, session_id).read_records()
        _assert_internal_sequence(
            records,
            attribute="outbox_seq",
            stream_name="outbox",
        )
        return records

    def _message_by_client_id_unlocked(
        self,
        project_id: str,
        session_id: str,
        client_message_id: str,
    ) -> CreatorMessageRecord | None:
        return next(
            (
                item
                for item in self._message_records_unlocked(
                    project_id,
                    session_id,
                )
                if item.client_message_id == client_message_id
            ),
            None,
        )

    def _existing_bootstrap_unlocked(
        self,
        project_id: str,
    ) -> ProjectRuntimeBootstrap | None:
        sessions_root = self._runtime_root(project_id) / "sessions"
        if not sessions_root.exists():
            return None
        session_files: list[Path] = []
        for child in sessions_root.iterdir():
            if child.is_symlink():
                raise SessionStoreIntegrityError(
                    f"Session directory cannot be a symlink: {child}",
                )
            if child.is_dir() and (child / "session.json").exists():
                session_files.append(child / "session.json")
        if not session_files:
            return None
        if len(session_files) != 1:
            raise SessionStoreIntegrityError(
                "A Project must have exactly one Creator Session",
            )
        session = AtomicJsonRecordStore(
            session_files[0],
            CreatorSessionRecord,
        ).read()
        if session.project_id != project_id:
            raise SessionStoreIntegrityError(
                "Session record belongs to another Project",
            )
        if session.session_id != session_files[0].parent.name:
            raise SessionStoreIntegrityError(
                "Session directory and record identity disagree",
            )
        conversations = self._list_conversations_unlocked(
            project_id,
            session.session_id,
        )
        defaults = [item for item in conversations if item.is_default]
        if len(defaults) != 1:
            raise SessionStoreIntegrityError(
                "Creator Session must have exactly one default Conversation",
            )
        return ProjectRuntimeBootstrap(session, defaults[0])

    @staticmethod
    def _assert_bootstrap_retry(
        existing: ProjectRuntimeBootstrap,
        *,
        session_id: str | None,
        conversation_id: str | None,
    ) -> None:
        if (
            session_id is not None
            and existing.session.session_id != session_id
        ):
            raise SessionStateConflict(
                "Project Runtime already exists with another session_id",
            )
        if (
            conversation_id is not None
            and existing.default_conversation.conversation_id
            != conversation_id
        ):
            raise SessionStateConflict(
                "Project Runtime already exists with another conversation_id",
            )

    def _read_session_unlocked(
        self,
        project_id: str,
        session_id: str,
    ) -> CreatorSessionRecord:
        path = self._session_root(project_id, session_id) / "session.json"
        record = AtomicJsonRecordStore(
            path,
            CreatorSessionRecord,
        ).read_or_none()
        if record is None:
            raise RuntimeSessionNotFound(
                f"Runtime Session not found: {session_id}",
            )
        if record.project_id != project_id or record.session_id != session_id:
            raise SessionStoreIntegrityError(
                "Session path and record identity disagree",
            )
        return record

    def _write_session_unlocked(
        self,
        session: CreatorSessionRecord,
    ) -> CreatorSessionRecord:
        validated = CreatorSessionRecord.model_validate(session)
        self._session_store(validated.project_id, validated.session_id).write(
            validated,
        )
        return validated

    def _read_conversation_unlocked(
        self,
        project_id: str,
        session_id: str,
        conversation_id: str,
    ) -> CreatorConversationRecord:
        record = self._conversation_store(
            project_id,
            session_id,
            conversation_id,
        ).read_or_none()
        if record is None:
            raise RuntimeConversationNotFound(
                f"Runtime Conversation not found: {conversation_id}",
            )
        if (
            record.project_id != project_id
            or record.creator_session_id != session_id
            or record.conversation_id != conversation_id
        ):
            raise SessionStoreIntegrityError(
                "Conversation path and record identity disagree",
            )
        return record

    def _list_conversations_unlocked(
        self,
        project_id: str,
        session_id: str,
    ) -> list[CreatorConversationRecord]:
        root = self._session_root(project_id, session_id) / "conversations"
        if not root.exists():
            return []
        records: list[CreatorConversationRecord] = []
        for path in sorted(root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise SessionStoreIntegrityError(
                    f"Conversation must be a regular file: {path}",
                )
            record = AtomicJsonRecordStore(
                path,
                CreatorConversationRecord,
            ).read()
            if (
                record.project_id != project_id
                or record.creator_session_id != session_id
                or path.stem != record.conversation_id
            ):
                raise SessionStoreIntegrityError(
                    "Conversation path and record identity disagree",
                )
            records.append(record)
        return records

    def _read_goal_unlocked(
        self,
        project_id: str,
        goal_id: str,
    ) -> CreatorGoalRecord:
        record = self._goal_store(project_id, goal_id).read_or_none()
        if record is None:
            raise RuntimeGoalNotFound(f"Runtime Goal not found: {goal_id}")
        if record.project_id != project_id or record.goal_id != goal_id:
            raise SessionStoreIntegrityError(
                "Goal path and record identity disagree",
            )
        return record

    @staticmethod
    def _assert_conversation_ownership(
        conversation: CreatorConversationRecord,
        *,
        session_id: str,
    ) -> None:
        if conversation.creator_session_id != session_id:
            raise SessionStateConflict(
                "Conversation belongs to another Runtime Session",
            )

    @staticmethod
    def _assert_goal_ownership(
        goal: CreatorGoalRecord,
        *,
        session_id: str,
    ) -> None:
        if goal.creator_session_id != session_id:
            raise SessionStateConflict(
                "Goal belongs to another Runtime Session",
            )

    def _safe_session_ids(
        self,
        project_id: str,
        session_id: str,
    ) -> tuple[str, str]:
        project_id = _safe_segment(project_id, "project_id")
        session_id = _safe_segment(session_id, "session_id")
        self._require_project(project_id)
        return project_id, session_id

    def _safe_message_ids(
        self,
        project_id: str,
        session_id: str,
        conversation_id: str,
    ) -> tuple[str, str, str]:
        project_id, session_id = self._safe_session_ids(project_id, session_id)
        conversation_id = _safe_segment(conversation_id, "conversation_id")
        return project_id, session_id, conversation_id

    def _require_project(self, project_id: str) -> Path:
        project_root = self.data_root / project_id
        try:
            root_stat = project_root.lstat()
            project_stat = (project_root / "project.json").lstat()
        except FileNotFoundError as exc:
            raise RuntimeSessionNotFound(
                f"Project does not exist: {project_id}",
            ) from exc
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(
            root_stat.st_mode,
        ):
            raise UnsafeSessionPath(
                "Project root must be a regular, non-symlink directory",
            )
        if stat.S_ISLNK(project_stat.st_mode) or not stat.S_ISREG(
            project_stat.st_mode,
        ):
            raise UnsafeSessionPath(
                "project.json must be a regular, non-symlink file",
            )
        return project_root

    def _runtime_root(self, project_id: str) -> Path:
        return self.data_root / project_id / "runtime"

    def _session_root(self, project_id: str, session_id: str) -> Path:
        return self._runtime_root(project_id) / "sessions" / session_id

    @contextmanager
    def _project_lock(self, project_id: str):
        with self._project_lifecycle_lock(project_id):
            self._require_project(project_id)
            with self._runtime_lock(project_id):
                yield

    @contextmanager
    def _project_lock_read(self, project_id: str):
        """Shared-lock variant of :meth:`_project_lock` for read-only paths.

        Both the lifecycle and the runtime lock are taken as ``LOCK_SH`` so
        concurrent readers (for example Plan polling) never block each other;
        they only wait for a writer, which holds the lock for a single short
        durable transition.  Callers must not mutate any file under this lock.
        """
        project_id = _safe_segment(project_id, "project_id")
        with CrossProcessFileLock(
            self.data_root / ".locks" / f"project-{project_id}.lock",
            timeout_seconds=self.lock_timeout_seconds,
            shared=True,
        ):
            self._require_project(project_id)
            with CrossProcessFileLock(
                self._runtime_root(project_id)
                / "locks"
                / "project-runtime.lock",
                timeout_seconds=self.lock_timeout_seconds,
                shared=True,
            ):
                yield

    def _project_lifecycle_lock(self, project_id: str) -> CrossProcessFileLock:
        return CrossProcessFileLock(
            self.data_root / ".locks" / f"project-{project_id}.lock",
            timeout_seconds=self.lock_timeout_seconds,
        )

    def _runtime_lock(self, project_id: str) -> CrossProcessFileLock:
        return CrossProcessFileLock(
            self._runtime_root(project_id) / "locks" / "project-runtime.lock",
            timeout_seconds=self.lock_timeout_seconds,
        )

    def _project_commit_order_lock(
        self,
        project_id: str,
    ) -> CrossProcessFileLock:
        return CrossProcessFileLock(
            self._runtime_root(project_id)
            / "locks"
            / "project-commit-order.lock",
            timeout_seconds=self.lock_timeout_seconds,
        )

    def _session_store(
        self,
        project_id: str,
        session_id: str,
    ) -> AtomicJsonRecordStore[CreatorSessionRecord]:
        return AtomicJsonRecordStore(
            self._session_root(project_id, session_id) / "session.json",
            CreatorSessionRecord,
        )

    def _conversation_store(
        self,
        project_id: str,
        session_id: str,
        conversation_id: str,
    ) -> AtomicJsonRecordStore[CreatorConversationRecord]:
        return AtomicJsonRecordStore(
            self._session_root(project_id, session_id)
            / "conversations"
            / f"{conversation_id}.json",
            CreatorConversationRecord,
        )

    def _goal_store(
        self,
        project_id: str,
        goal_id: str,
    ) -> AtomicJsonRecordStore[CreatorGoalRecord]:
        return AtomicJsonRecordStore(
            self._runtime_root(project_id) / "goals" / f"{goal_id}.json",
            CreatorGoalRecord,
        )

    def _runtime_state_store(
        self,
        project_id: str,
    ) -> AtomicJsonRecordStore[RuntimeProjectState]:
        return AtomicJsonRecordStore(
            self._runtime_root(project_id) / "state.json",
            RuntimeProjectState,
        )

    def _messages_store(
        self,
        project_id: str,
        session_id: str,
    ) -> DurableJsonlStore[CreatorMessageRecord]:
        return DurableJsonlStore(
            self._session_root(project_id, session_id) / "messages.jsonl",
            CreatorMessageRecord,
        )

    def _events_store(
        self,
        project_id: str,
        session_id: str,
    ) -> DurableJsonlStore[SessionEventRecord]:
        return DurableJsonlStore(
            self._session_root(project_id, session_id) / "events.jsonl",
            SessionEventRecord,
        )

    def _queued_store(
        self,
        project_id: str,
        session_id: str,
    ) -> DurableJsonlStore[QueuedMessageRecord]:
        return DurableJsonlStore(
            self._session_root(project_id, session_id)
            / "queued-messages.jsonl",
            QueuedMessageRecord,
        )

    def _outbox_store(
        self,
        project_id: str,
        session_id: str,
    ) -> DurableJsonlStore[OutboxRecord]:
        return DurableJsonlStore(
            self._session_root(project_id, session_id) / "outbox.jsonl",
            OutboxRecord,
        )


RuntimeSessionStore = ProjectRuntimeSessionStore


def _safe_segment(value: str, name: str) -> str:
    try:
        return require_safe_runtime_segment(value, label=name)
    except RuntimeFileValidationError as exc:
        raise UnsafeSessionPath(
            f"{name} must be a safe filesystem identifier",
        ) from exc


def _safe_nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} cannot be empty")
    return value


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _normalize_content_parts(
    values: Sequence[ContentPartInput],
) -> list[MessageContentPart]:
    parts = [MessageContentPart.model_validate(value) for value in values]
    if not parts:
        raise ValueError("content_parts cannot be empty")
    return parts


def _request_hash(value: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(_json_ready(value)),
    ).hexdigest()
    return f"sha256:{digest}"


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_json_ready(item) for item in value]
    return value


def _assert_internal_sequence(
    records: Sequence[Any],
    *,
    attribute: str,
    stream_name: str,
) -> None:
    for expected, record in enumerate(records, start=1):
        if getattr(record, attribute) != expected:
            raise SessionStoreIntegrityError(
                f"{stream_name} record sequence disagrees with JSONL "
                f"envelope at seq {expected}",
            )


def _latest_by(records: Sequence[Any], attribute: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for record in records:
        result[getattr(record, attribute)] = record
    return result


def _validate_window(after_seq: int, limit: int | None) -> None:
    if after_seq < 0:
        raise ValueError("after_seq cannot be negative")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")


def _window(
    records: Sequence[Any],
    *,
    after_seq: int,
    limit: int | None,
) -> list[Any]:
    result = list(records[after_seq:])
    return result if limit is None else result[:limit]
