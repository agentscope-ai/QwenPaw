# -*- coding: utf-8 -*-
"""Host dispatch/reconciliation boundary for explicitly registered adapters.

No existing EngineClient is silently wrapped: an adapter must implement the
durable submission/replay protocol before it can be registered here.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Protocol

from pydantic import model_validator

from .contracts import (
    TERMINAL_STATUSES,
    ActionDescriptor,
    Contract,
    ExecutorEvent,
    ExecutorRunRef,
    TaskOrigin,
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


class TaskAdapter(Protocol):
    """Protocol 1 requires durable executor-side deduplication and lookup.

    submit must return the same run for a submission_id, including concurrent
    or post-restart retries. query must report unknown if acceptance cannot
    be determined. attach replays after an opaque cursor in source order and
    reports explicit terminal events; stream exhaustion is not completion.
    """

    submission_protocol_version: int

    async def submit(self, submission: TaskSubmission) -> ExecutorRunRef:
        ...

    async def query(self, submission_id: str) -> SubmissionLookup:
        ...

    def attach(
        self,
        run_ref: ExecutorRunRef,
        cursor: str | None,
    ) -> AsyncIterator[ExecutorEvent]:
        ...


AuthorizeAction = Callable[
    [TaskScope, ActionDescriptor, TaskOrigin, dict[str, Any]],
    Awaitable[None],
]


@dataclass(frozen=True)
class _Binding:
    action: ActionDescriptor
    adapter: TaskAdapter


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

    def register(self, action: ActionDescriptor, adapter: TaskAdapter) -> None:
        if getattr(adapter, "submission_protocol_version", None) != 1:
            raise TaskStoreError("unsupported_submission_protocol")
        key = (action.app_id, action.action_id)
        if key in self._bindings:
            raise TaskStoreError("action_already_registered")
        action = ActionDescriptor.model_validate_json(action.model_dump_json())
        self._bindings[key] = _Binding(action, adapter)

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
            lookup = await binding.adapter.query(handle.submission_id)
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

    async def consume(self, scope: TaskScope, task_id: str) -> TaskSubmission:
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
            async for event in binding.adapter.attach(
                handle.executor_run_ref,
                handle.replay_cursor,
            ):
                submission = await self.store.apply_event(
                    scope,
                    task_id,
                    event,
                )
                if submission.handle.status in TERMINAL_STATUSES:
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
