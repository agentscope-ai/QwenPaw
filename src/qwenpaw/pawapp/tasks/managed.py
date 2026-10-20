# -*- coding: utf-8 -*-
"""Host-managed execution for small Apps; external engines keep TaskAdapter.

The journal shares the Host task database. Replay is opt-in: a handler marked
safe must be read-only or use submission_id to deduplicate external effects.
This is single-Host execution, not a distributed worker lease protocol.
"""

# The managed journal is part of TaskStore's implementation boundary.
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import json
import hashlib
from dataclasses import dataclass
from typing import Any, NoReturn

from .binding import Readiness
from .contracts import (
    TERMINAL_STATUSES,
    ArtifactRef,
    ExecutorEvent,
    ExecutorRunRef,
    ProjectRef,
    TaskAnswer,
    TaskSubmission,
    TaskExperienceUpdate,
    TaskInputRequest,
    TaskStoreError,
    canonical_json,
    content_digest,
)
from .coordinator import CommandLookup, SubmissionLookup

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS managed_runs (
        task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
        state TEXT NOT NULL,
        answers_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS managed_events (
        task_id TEXT NOT NULL REFERENCES managed_runs(task_id),
        sequence INTEGER NOT NULL, event_key TEXT NOT NULL,
        event_json TEXT NOT NULL,
        PRIMARY KEY(task_id, sequence), UNIQUE(task_id, event_key)
    )""",
    """CREATE TABLE IF NOT EXISTS managed_commands (
        task_id TEXT NOT NULL REFERENCES managed_runs(task_id),
        command_id TEXT NOT NULL, meaning TEXT NOT NULL, receipt TEXT NOT NULL,
        PRIMARY KEY(task_id, command_id)
    )""",
)


@dataclass(frozen=True)
class ActionResult:
    summary: str
    data: dict[str, Any] | None = None
    project: ProjectRef | None = None


class TaskExecution:
    """The only execution context a simple handler needs.

    Use stable keys for reports and artifact source IDs. These are checkpoints,
    not authorization: Host dispatch grants and scoped stores enforce access.
    """

    def __init__(
        self,
        adapter: ManagedHandlerAdapter,
        submission: TaskSubmission,
    ):
        self._adapter = adapter
        self.submission = submission
        self.inputs = dict(submission.inputs)
        self.scope = submission.handle.scope
        self.submission_id = submission.handle.submission_id

    async def fail(
        self,
        key: str,
        *,
        text: str,
        project: ProjectRef | None = None,
    ) -> NoReturn:
        """Stop with a deliberate public failure; never pass raw exceptions."""
        await self._adapter.emit(
            self.submission,
            "failure:" + key,
            status="failed",
            text_result=text,
            project_ref=project,
        )
        # _execute preserves an already-terminal journal. Raising stops the
        # handler so it cannot publish success after reporting this failure.
        raise TaskStoreError("action_failed")

    async def report(
        self,
        key: str,
        *,
        text: str | None = None,
        experience: TaskExperienceUpdate | dict | None = None,
        project: ProjectRef | None = None,
    ) -> None:
        await self._adapter.emit(
            self.submission,
            "report:" + key,
            status="running",
            text_result=text,
            experience_update=experience,
            project_ref=project,
        )

    async def request_input(
        self,
        request: TaskInputRequest,
        *,
        approval: bool = False,
    ) -> tuple[TaskAnswer, ...]:
        request = TaskInputRequest.model_validate(request)
        while True:
            record = await self._adapter.record(self.submission)
            answer = json.loads(record["answers_json"]).get(request.request_id)
            if answer is not None:
                if answer["request"] != request.model_dump(mode="json"):
                    raise TaskStoreError("managed_input_conflict")
                return tuple(
                    TaskAnswer.model_validate(a) for a in answer["answers"]
                )
            await self._adapter.emit(
                self.submission,
                "input:" + request.request_id,
                status=(
                    "waiting_for_approval" if approval else "waiting_for_input"
                ),
                input_request=request,
            )
            await asyncio.sleep(0.1)

    async def publish(
        self,
        *,
        source_id: str,
        name: str,
        media_type: str,
        content: bytes,
        presentation=None,
    ) -> ArtifactRef:
        if self._adapter.artifacts is None:
            raise TaskStoreError("artifact_store_unavailable")
        source = {
            "source_id": source_id,
            "name": name,
            "path": name,
            "media_type": media_type,
            "size_bytes": len(content),
            "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            "presentation": presentation,
        }
        ref = await self._adapter.artifacts.publish(
            self.submission,
            source,
            content,
        )
        await self._adapter.emit(
            self.submission,
            "artifact:" + source_id,
            artifact_ref=ref,
        )
        return ref


class ManagedHandlerAdapter:
    submission_protocol_version = 1

    def __init__(self, store, registration, artifacts=None):
        self.store = store
        self.registration = registration
        self.artifacts = artifacts
        self._jobs = {}
        self._lock = asyncio.Lock()

    async def readiness(self, scope, inputs):
        if self.registration.readiness is not None:
            return await self.registration.readiness(scope, inputs)
        return Readiness(state="ready")

    async def aclose(self):
        jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        self._jobs.clear()

    @staticmethod
    def run_ref(submission):
        return ExecutorRunRef(
            executor_id="qwenpaw.managed",
            session_id=content_digest(
                submission.handle.scope.model_dump(mode="json"),
            ),
            run_id=submission.handle.submission_id,
        )

    async def record(self, submission):
        def read(connection):
            self.store._get(
                connection,
                submission.handle.scope,
                submission.handle.task_id,
            )
            row = connection.execute(
                "SELECT * FROM managed_runs WHERE task_id = ?",
                (submission.handle.task_id,),
            ).fetchone()
            return dict(row) if row is not None else None

        return await self.store._run(read)

    async def submit(self, submission):
        def insert(connection):
            self.store._get(
                connection,
                submission.handle.scope,
                submission.handle.task_id,
            )
            connection.execute(
                (
                    "INSERT OR IGNORE INTO managed_runs(task_id, "
                    "state) VALUES (?, 'ready')"
                ),
                (submission.handle.task_id,),
            )

        await self.store._run(insert, write=True)
        return self.run_ref(submission)

    async def query(self, submission):
        row = await self.record(submission)
        return SubmissionLookup(
            state="accepted" if row else "not_found",
            run_ref=self.run_ref(submission) if row else None,
        )

    def _append(self, connection, submission, key, fields):
        task_id = submission.handle.task_id
        previous = connection.execute(
            (
                "SELECT sequence, event_json FROM managed_events "
                "WHERE task_id=? AND event_key=?"
            ),
            (task_id, key),
        ).fetchone()
        sequence = (
            previous["sequence"]
            if previous
            else connection.execute(
                "SELECT COUNT(*) FROM managed_events WHERE task_id=?",
                (task_id,),
            ).fetchone()[0]
        )
        event = ExecutorEvent(
            run_ref=self.run_ref(submission),
            sequence=sequence,
            cursor=str(sequence),
            **fields,
        )
        if previous:
            if (
                ExecutorEvent.model_validate_json(
                    previous["event_json"],
                ).replay_digest
                != event.replay_digest
            ):
                raise TaskStoreError("managed_replay_conflict")
            return event
        state = connection.execute(
            "SELECT state FROM managed_runs WHERE task_id=?",
            (task_id,),
        ).fetchone()[0]
        if state in TERMINAL_STATUSES:
            raise TaskStoreError("task_terminal")
        connection.execute(
            "INSERT INTO managed_events VALUES (?, ?, ?, ?)",
            (task_id, sequence, key, event.model_dump_json()),
        )
        if event.status is not None:
            connection.execute(
                "UPDATE managed_runs SET state=? WHERE task_id=?",
                (event.status, task_id),
            )
        return event

    async def emit(self, submission, key, **fields):
        return await self.store._run(
            lambda c: self._append(c, submission, key, fields),
            write=True,
        )

    async def _execute(self, submission):
        try:
            await self.emit(submission, "started", status="running")
            result = await self.registration.handler(
                TaskExecution(self, submission),
            )
            if isinstance(result, str):
                result = ActionResult(result)
            if not isinstance(result, ActionResult):
                raise TaskStoreError("invalid_handler_result")
            submission.action.validate_result(result.data)
            await self.emit(
                submission,
                "completed",
                status="succeeded",
                text_result=result.summary,
                result_data=result.data,
                project_ref=result.project,
            )
        except Exception:
            record = await self.record(submission)
            if record["state"] not in TERMINAL_STATUSES:
                await self.emit(
                    submission,
                    "failed",
                    status="failed",
                    text_result="The App action failed.",
                    detail={"reason_code": "handler_failed"},
                )

    async def _ensure_job(self, submission):
        async with self._lock:
            task_id = submission.handle.task_id
            record = await self.record(submission)
            if record["state"] in TERMINAL_STATUSES or task_id in self._jobs:
                return
            if (
                record["state"] != "ready"
                and self.registration.recovery != "replay_safe"
            ):
                await self.emit(
                    submission,
                    "interrupted",
                    status="interrupted",
                    text_result=(
                        "Execution was interrupted. Inspect its effects "
                        "before starting again."
                    ),
                    detail={"reason_code": "host_restarted"},
                )
                return
            # Mark before entering user code, even if the process dies before
            # the first handler await. Unknown effects are never rerun by
            # default.
            await self.emit(submission, "started", status="running")
            job = asyncio.create_task(self._execute(submission))
            self._jobs[task_id] = job
            job.add_done_callback(
                lambda finished: self._jobs.pop(task_id, None),
            )

    async def attach(self, submission):
        await self._ensure_job(submission)
        after = submission.handle.executor_sequence
        after = -1 if after is None else after
        while True:
            # Read state before events: a handler may commit its terminal
            # event between reads. Observing terminal state after an older
            # event snapshot would close the stream without that event.
            record = await self.record(submission)

            def read(connection):
                return connection.execute(
                    (
                        "SELECT event_json FROM managed_events WHERE "
                        "task_id=? AND sequence>? ORDER BY sequence"
                    ),
                    (submission.handle.task_id, after),
                ).fetchall()

            rows = await self.store._run(read)
            for row in rows:
                event = ExecutorEvent.model_validate_json(row[0])
                after = event.sequence
                yield event
                if event.status in TERMINAL_STATUSES:
                    return
            if record["state"] in TERMINAL_STATUSES:
                return
            if record["state"] in {
                "waiting_for_input",
                "waiting_for_approval",
            }:
                # Replaying the question lets the coordinator release its
                # worker
                # slot after restart. The original event digest remains
                # identical.
                latest = await self.store._run(
                    lambda c: c.execute(
                        (
                            "SELECT event_json FROM managed_events WHERE "
                            "task_id=? ORDER BY sequence DESC LIMIT 1"
                        ),
                        (submission.handle.task_id,),
                    ).fetchone(),
                )
                if latest is not None:
                    yield ExecutorEvent.model_validate_json(latest[0])
                    return
            await asyncio.sleep(0.05)

    async def command(self, submission, command):
        task_id = submission.handle.task_id
        meaning = content_digest(
            {
                "kind": command.kind,
                "request_id": command.request_id,
                "payload": command.payload,
            },
        )

        def apply(connection):
            prior = connection.execute(
                (
                    "SELECT meaning, receipt FROM managed_commands "
                    "WHERE task_id=? AND command_id=?"
                ),
                (task_id, command.command_id),
            ).fetchone()
            if prior:
                if prior[0] != meaning:
                    raise TaskStoreError("command_conflict")
                return CommandLookup.model_validate_json(prior[1])
            row = connection.execute(
                "SELECT * FROM managed_runs WHERE task_id=?",
                (task_id,),
            ).fetchone()
            receipt = CommandLookup(state="accepted")
            if command.kind == "cancel":
                if row["state"] not in TERMINAL_STATUSES:
                    self._append(
                        connection,
                        submission,
                        "cancelled",
                        {"status": "cancelled"},
                    )
            else:
                event = connection.execute(
                    (
                        "SELECT event_json FROM managed_events WHERE "
                        "task_id=? ORDER BY sequence DESC LIMIT 1"
                    ),
                    (task_id,),
                ).fetchone()
                pending = (
                    ExecutorEvent.model_validate_json(event[0]).input_request
                    if event
                    else None
                )
                if (
                    pending is None
                    or pending.request_id != command.request_id
                    or row["state"]
                    not in {"waiting_for_input", "waiting_for_approval"}
                ):
                    receipt = CommandLookup(
                        state="rejected",
                        reason="stale_request",
                    )
                else:
                    answers = json.loads(row["answers_json"])
                    answers[pending.request_id] = {
                        "request": pending.model_dump(mode="json"),
                        "answers": command.payload["answers"],
                    }
                    connection.execute(
                        (
                            "UPDATE managed_runs SET answers_json=? WHERE "
                            "task_id=?"
                        ),
                        (canonical_json(answers), task_id),
                    )
                    self._append(
                        connection,
                        submission,
                        "answer:" + command.request_id,
                        {"status": "running"},
                    )
            connection.execute(
                "INSERT INTO managed_commands VALUES (?, ?, ?, ?)",
                (
                    task_id,
                    command.command_id,
                    meaning,
                    receipt.model_dump_json(),
                ),
            )
            return receipt

        receipt = await self.store._run(apply, write=True)
        if command.kind == "cancel":
            job = self._jobs.get(task_id)
            if job is not None:
                job.cancel()
                await asyncio.gather(job, return_exceptions=True)
        return receipt

    async def query_command(self, submission, command):
        def read(connection):
            row = connection.execute(
                (
                    "SELECT receipt FROM managed_commands WHERE "
                    "task_id=? AND command_id=?"
                ),
                (submission.handle.task_id, command.command_id),
            ).fetchone()
            return (
                CommandLookup.model_validate_json(row[0])
                if row
                else CommandLookup(state="not_found")
            )

        return await self.store._run(read)
