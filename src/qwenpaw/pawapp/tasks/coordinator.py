# -*- coding: utf-8 -*-
"""Host dispatch/reconciliation boundary for explicitly registered adapters.

No existing EngineClient is silently wrapped: an adapter must implement the
durable submission/replay protocol before it can be registered here.
"""

from __future__ import annotations

from copy import deepcopy
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable, Literal, Protocol

from pydantic import model_validator

from .contracts import (
    TERMINAL_STATUSES,
    WAITING_STATUSES,
    ActionDescriptor,
    Contract,
    ExecutorEvent,
    ExecutorRunRef,
    TaskOrigin,
    TaskExperienceDefinition,
    TaskCommand,
    TaskScope,
    TaskStoreError,
    TaskSubmission,
)
from .store import TaskStore


class SubmissionLookup(Contract):
    state: Literal["accepted", "not_found", "unknown"]
    run_ref: ExecutorRunRef | None = None

    @model_validator(mode="after")
    def validate_run(self) -> SubmissionLookup:
        if (self.state == "accepted") != (self.run_ref is not None):
            raise ValueError("only accepted submissions carry a run reference")
        return self


class CommandLookup(Contract):
    state: Literal["accepted", "rejected", "not_found", "unknown"]
    reason: str | None = None


class TaskAdapter(Protocol):
    """Protocol 1 requires durable executor-side deduplication and lookup.

    submit must return the same run for a submission_id, including concurrent
    or post-restart retries. query must report unknown if acceptance cannot
    be determined. attach replays after an opaque cursor in source order and
    reports explicit terminal events; stream exhaustion is not completion.
    Every operation receives the persisted submission, including trusted scope,
    so adapters can recover without process-local identity/run caches.
    """

    submission_protocol_version: int

    async def submit(self, submission: TaskSubmission) -> ExecutorRunRef:
        ...

    async def query(self, submission: TaskSubmission) -> SubmissionLookup:
        ...

    def attach(
        self,
        submission: TaskSubmission,
    ) -> AsyncGenerator[ExecutorEvent, None]:
        ...

    async def command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        ...

    async def query_command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        ...


AuthorizeAction = Callable[
    [TaskScope, ActionDescriptor, TaskOrigin, dict[str, Any]],
    Awaitable[None],
]
CommitEvent = Callable[
    [TaskSubmission, ExecutorEvent],
    Awaitable[TaskSubmission],
]


@dataclass(frozen=True)
class _Binding:
    action: ActionDescriptor
    adapter: TaskAdapter
    experience: TaskExperienceDefinition | None = None


class TaskCoordinator:
    """Core boundary, separate from transport and scope resolution.

    The required authorize callback must check permission tags, effects and
    origin ownership against Host policy. There is no default allow policy.
    Successful dispatch identities and subsequent changes are durable events.
    """

    def __init__(self, store: TaskStore, *, authorize: AuthorizeAction):
        self.store = store
        self._authorize = authorize
        self._bindings: dict[tuple[str, str], _Binding] = {}

    def register(
        self,
        action: ActionDescriptor,
        adapter: TaskAdapter,
        experience: TaskExperienceDefinition | None = None,
    ) -> None:
        if getattr(adapter, "submission_protocol_version", None) != 1:
            raise TaskStoreError("unsupported_submission_protocol")
        key = (action.app_id, action.action_id)
        if key in self._bindings:
            raise TaskStoreError("action_already_registered")
        action = ActionDescriptor.model_validate_json(action.model_dump_json())
        if experience is not None:
            experience = TaskExperienceDefinition.model_validate_json(
                experience.model_dump_json(),
            )
            if experience.action_id != action.action_id:
                raise TaskStoreError("experience_action_mismatch")
        self._bindings[key] = _Binding(action, adapter, experience)

    def describe(self, app_id: str, action_id: str) -> ActionDescriptor:
        binding = self._binding(app_id, action_id)
        return ActionDescriptor.model_validate_json(
            binding.action.model_dump_json(),
        )

    def _binding(self, app_id: str, action_id: str) -> _Binding:
        try:
            return self._bindings[(app_id, action_id)]
        except KeyError as exc:
            raise TaskStoreError("action_not_found") from exc

    async def dispatch(
        self,
        scope: TaskScope,
        action_id: str,
        *,
        request_id: str,
        inputs: dict,
        origin: TaskOrigin,
    ) -> TaskSubmission:
        action = self.describe(scope.app_id, action_id)
        inputs = deepcopy(inputs)
        action.validate_inputs(inputs)
        # Policy sees the requested resources but cannot rewrite execution.
        await self._authorize(
            scope,
            self.describe(scope.app_id, action_id),
            origin,
            deepcopy(inputs),
        )
        submission = await self.store.create(
            scope,
            action,
            request_id=request_id,
            inputs=inputs,
            origin=origin,
            experience=self._binding(scope.app_id, action_id).experience,
        )
        if await self.store.begin_submission(scope, submission.handle.task_id):
            submission = await self.store.get(scope, submission.handle.task_id)
            return await self._submit(submission)
        return await self.store.get(scope, submission.handle.task_id)

    async def _submit(self, submission: TaskSubmission) -> TaskSubmission:
        handle = submission.handle
        binding = self._binding(handle.scope.app_id, handle.action_id)
        try:
            run_ref = await binding.adapter.submit(submission)
        except Exception:
            await self.store.mark_recovery(
                handle.scope,
                handle.task_id,
                state="reconciling",
                reason="submission_unknown",
            )
            raise
        return await self.store.record_accepted(
            handle.scope,
            handle.task_id,
            run_ref,
        )

    async def reconcile(
        self,
        scope: TaskScope,
        task_id: str,
    ) -> TaskSubmission:
        """Query the original identity; never create a replacement run."""
        submission = await self.store.get(scope, task_id)
        handle = submission.handle
        if handle.status in TERMINAL_STATUSES:
            return submission
        binding = self._binding(scope.app_id, handle.action_id)
        if binding.action.descriptor_digest != handle.descriptor_digest:
            raise TaskStoreError("descriptor_changed")
        await self._authorize(
            scope,
            self.describe(scope.app_id, handle.action_id),
            handle.origin,
            deepcopy(submission.inputs),
        )
        if handle.submission_state == "prepared":
            if await self.store.begin_submission(scope, task_id):
                return await self._submit(await self.store.get(scope, task_id))
            return await self.store.get(scope, task_id)
        try:
            lookup = await binding.adapter.query(submission)
        except Exception:
            lookup = SubmissionLookup(state="unknown")
        if lookup.state == "accepted" and lookup.run_ref is not None:
            return await self.store.record_accepted(
                scope,
                task_id,
                lookup.run_ref,
            )
        if lookup.state == "not_found" and handle.executor_run_ref is None:
            # Only protocol-1 adapters can reach this branch. The executor
            # arbitrates simultaneous retries with the SAME submission_id.
            return await self._submit(submission)
        return await self.store.mark_recovery(
            scope,
            task_id,
            state="unresolved",
            reason="submission_unknown",
        )

    # pylint: disable-next=too-many-return-statements,too-many-branches
    async def deliver_command(
        self,
        scope: TaskScope,
        task_id: str,
        command_id: str,
    ) -> TaskCommand:
        """Deliver or reconcile one durable command using its original ID."""
        submission = await self.store.get(scope, task_id)
        binding = self._binding(scope.app_id, submission.handle.action_id)
        if (
            binding.action.descriptor_digest
            != submission.handle.descriptor_digest
        ):
            raise TaskStoreError("descriptor_changed")
        await self._authorize(
            scope,
            self.describe(scope.app_id, submission.handle.action_id),
            submission.handle.origin,
            deepcopy(submission.inputs),
        )
        command = await self.store.command(scope, task_id, command_id)
        if command.state in {"accepted", "rejected"}:
            return command
        if submission.handle.status in TERMINAL_STATUSES:
            return await self.store.mark_command(
                scope,
                task_id,
                command_id,
                state="accepted" if command.kind == "cancel" else "rejected",
                reason=(
                    "already_terminal"
                    if command.kind == "cancel"
                    else "stale_request"
                ),
            )
        if submission.handle.executor_run_ref is None:
            submission = await self.reconcile(scope, task_id)
        if submission.handle.status in TERMINAL_STATUSES:
            return await self.store.mark_command(
                scope,
                task_id,
                command_id,
                state="accepted" if command.kind == "cancel" else "rejected",
                reason=(
                    "already_terminal"
                    if command.kind == "cancel"
                    else "stale_request"
                ),
            )
        if submission.handle.executor_run_ref is None:
            return await self.store.mark_command(
                scope,
                task_id,
                command_id,
                state="unknown",
                reason="submission_unknown",
            )

        submission, command, started = await self.store.begin_command(
            scope,
            task_id,
            command_id,
        )
        if not started:
            try:
                lookup = await binding.adapter.query_command(
                    submission,
                    command,
                )
            except Exception:
                lookup = CommandLookup(state="unknown")
            if lookup.state in {"accepted", "rejected"}:
                return await self.store.mark_command(
                    scope,
                    task_id,
                    command_id,
                    state=lookup.state,
                    reason=lookup.reason,
                )
            if lookup.state == "unknown":
                return await self.store.mark_command(
                    scope,
                    task_id,
                    command_id,
                    state="unknown",
                    reason="command_unknown",
                )
        try:
            lookup = await binding.adapter.command(submission, command)
        except Exception:
            try:
                lookup = await binding.adapter.query_command(
                    submission,
                    command,
                )
            except Exception:
                lookup = CommandLookup(state="unknown")
        if lookup.state == "not_found":
            lookup = CommandLookup(state="unknown", reason="command_unknown")
        return await self.store.mark_command(
            scope,
            task_id,
            command_id,
            state=lookup.state,
            reason=lookup.reason,
        )

    async def consume(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        commit_event: CommitEvent | None = None,
    ) -> TaskSubmission:
        """Attach/replay an accepted run. EOF leaves task facts intact."""
        submission = await self.store.get(scope, task_id)
        handle = submission.handle
        if handle.status in TERMINAL_STATUSES:
            return submission
        if handle.executor_run_ref is None:
            raise TaskStoreError("submission_not_accepted")
        binding = self._binding(scope.app_id, handle.action_id)
        if binding.action.descriptor_digest != handle.descriptor_digest:
            raise TaskStoreError("descriptor_changed")
        await self._authorize(
            scope,
            self.describe(scope.app_id, handle.action_id),
            handle.origin,
            deepcopy(submission.inputs),
        )
        try:
            async with aclosing(binding.adapter.attach(submission)) as stream:
                async for event in stream:
                    if commit_event is None:
                        submission = await self.store.apply_event(
                            scope,
                            task_id,
                            event,
                        )
                    else:
                        submission = await commit_event(submission, event)
                    if submission.handle.status in (
                        TERMINAL_STATUSES | WAITING_STATUSES
                    ):
                        return submission
        except Exception:
            await self.store.mark_recovery(
                scope,
                task_id,
                state="reconciling",
                reason="stream_disconnected",
            )
            raise
        return await self.store.mark_recovery(
            scope,
            task_id,
            state="reconciling",
            reason="stream_eof",
        )
