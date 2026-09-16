# -*- coding: utf-8 -*-
"""Host-owned task lifecycle, readiness and dispatch boundary."""

import asyncio
import logging
import time
from dataclasses import dataclass
from functools import partial
from typing import Callable

from .binding import ActionRegistration, AuthorizeOrigin, ManagedTaskAdapter
from .contracts import (
    TERMINAL_STATUSES,
    TaskScope,
    TaskStoreError,
    content_digest,
)
from .coordinator import TaskCoordinator
from .policy import FileTaskPolicy, TaskGrant
from .store import TaskStore

logger = logging.getLogger(__name__)


class _ReadyAdapter:
    """Recheck readiness immediately before every new submission attempt."""

    def __init__(self, adapter, artifacts, require_ready):
        self.adapter = adapter
        self.artifacts = artifacts
        self.require_ready = require_ready
        self.submission_protocol_version = adapter.submission_protocol_version

    async def submit(self, submission):
        await self.require_ready(
            submission.handle.scope,
            submission.inputs,
        )
        return await self.adapter.submit(submission)

    async def query(self, submission):
        return await self.adapter.query(submission)

    async def attach(self, submission):
        async for event in self.adapter.attach(submission):
            materialize = getattr(self.adapter, "materialize_event", None)
            if materialize is not None:
                if self.artifacts is None:
                    raise TaskStoreError("artifact_store_unavailable")
                event = await materialize(submission, event, self.artifacts)
            yield event

    async def command(self, submission, command):
        return await self.adapter.command(submission, command)

    async def query_command(self, submission, command):
        return await self.adapter.query_command(submission, command)


@dataclass
class _RuntimeBinding:
    registration: ActionRegistration
    adapter: ManagedTaskAdapter
    coordinator: TaskCoordinator


class HostTaskRuntime:
    """One supervisor per Host process; durable facts remain in TaskStore.

    The Engine arbitrates duplicate submissions. This supervisor owns task
    recovery; a separate leased worker delivers summaries to Main Chat.
    """

    def __init__(
        self,
        store: TaskStore,
        *,
        policy: FileTaskPolicy,
        registrations: Callable[[], dict],
        authorize_origin: AuthorizeOrigin,
        artifacts=None,
        handoffs=None,
        setup=None,
        interval: float = 2.0,
    ):
        self.store = store
        self.policy = policy
        self._registrations = registrations
        self._authorize_origin = authorize_origin
        self.artifacts = artifacts
        self.handoffs = handoffs
        self.setup = setup
        self._interval = interval
        self._bindings: dict[tuple[str, str], _RuntimeBinding] = {}
        self._workers: dict[str, tuple[tuple[str, str], asyncio.Task]] = {}
        self._lock = asyncio.Lock()
        self._supervisor: asyncio.Task | None = None
        self._closed = False
        self._retry_at: dict[str, float] = {}
        self._forced_rewake: set[str] = set()

    async def start(self):
        if self._closed:
            raise TaskStoreError("task_runtime_closed")
        if self._supervisor is None:
            self._supervisor = asyncio.create_task(self._supervise())

    async def aclose(self):
        self._closed = True
        jobs = [job for _, job in self._workers.values()]
        if self._supervisor is not None:
            jobs.append(self._supervisor)
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        async with self._lock:
            for binding in self._bindings.values():
                await binding.adapter.aclose()
            self._bindings.clear()
            self._workers.clear()

    async def _sync(self):
        async with self._lock:
            if self._closed:
                raise TaskStoreError("task_runtime_closed")
            registrations = self._registrations()
            for key, binding in list(self._bindings.items()):
                if registrations.get(key) is binding.registration:
                    continue
                jobs = [
                    job
                    for worker_key, job in self._workers.values()
                    if worker_key == key
                ]
                for job in jobs:
                    job.cancel()
                await asyncio.gather(*jobs, return_exceptions=True)
                await binding.adapter.aclose()
                del self._bindings[key]
            for key, registration in registrations.items():
                if key not in self._bindings:
                    adapter = registration.factory()
                    coordinator = TaskCoordinator(
                        self.store,
                        authorize=self._authorize,
                    )
                    try:
                        coordinator.register(
                            registration.action,
                            _ReadyAdapter(
                                adapter,
                                self.artifacts,
                                partial(
                                    self._require_ready,
                                    registration,
                                    adapter,
                                ),
                            ),
                        )
                    except Exception:
                        await adapter.aclose()
                        raise
                    self._bindings[key] = _RuntimeBinding(
                        registration,
                        adapter,
                        coordinator,
                    )

    async def _authorize(self, scope, action, origin, inputs):
        registration = self._registrations().get(
            (scope.app_id, action.action_id),
        )
        if registration is None:
            raise TaskStoreError("action_not_found")
        if registration.action.descriptor_digest != action.descriptor_digest:
            raise TaskStoreError("descriptor_changed")
        try:
            await self.policy.check(scope, action, inputs)
            await self._authorize_origin(scope, origin)
        except TaskStoreError as exc:
            await self.store.audit(
                scope,
                action.action_id,
                "authorize",
                exc.code,
            )
            raise

    async def describe(self, scope: TaskScope, action_id: str):
        await self._sync()
        binding = self._binding(scope, action_id)
        await self.policy.check(scope, binding.registration.action)
        return binding.coordinator.describe(scope.app_id, action_id)

    async def catalog(self, principal_id, workspace_id, *, intent=""):
        """Compact granted descriptors; no readiness probes or dispatch."""
        await self._sync()
        result = []
        for (app_id, action_id), binding in sorted(self._bindings.items()):
            scope = TaskScope(
                principal_id=principal_id,
                workspace_id=workspace_id,
                app_id=app_id,
            )
            action = binding.coordinator.describe(app_id, action_id)
            try:
                await self.policy.check(scope, action)
            except TaskStoreError as exc:
                if exc.code == "action_forbidden":
                    continue
                raise
            result.append(
                {
                    "app_id": app_id,
                    "action_id": action_id,
                    "summary": action.summary,
                    "engagements": action.engagements,
                    "required_inputs": action.input_schema.get("required", []),
                },
            )
        if intent:
            # Intent is a ranking hint, not a reason to hide granted actions
            # whose descriptions use another language or vocabulary.
            result.sort(
                key=lambda item: intent.casefold()
                not in (
                    " ".join(
                        item[key]
                        for key in (
                            "app_id",
                            "action_id",
                            "summary",
                        )
                    ).casefold()
                ),
            )
        return result

    async def grant_catalog(self, principal_id: str, workspace_id: str):
        """Return live registered actions and this operator's grant state."""
        await self._sync()
        policy = await self.policy.read()
        actions = []
        for (app_id, action_id), binding in sorted(self._bindings.items()):
            action = binding.registration.action
            scope = TaskScope(
                principal_id=principal_id,
                workspace_id=workspace_id,
                app_id=app_id,
            )
            related = tuple(
                grant
                for grant in policy.grants
                if grant.scope == scope and grant.action_id == action_id
            )
            current = next(
                (
                    grant
                    for grant in related
                    if grant.descriptor_digest == action.descriptor_digest
                ),
                None,
            )
            actions.append(
                {
                    "app_id": app_id,
                    "action_id": action_id,
                    "summary": action.summary,
                    "descriptor_digest": action.descriptor_digest,
                    "input_schema": action.input_schema,
                    "permissions": action.permissions,
                    "effects": action.effects,
                    "settings_entry": binding.registration.settings_entry,
                    "enabled": current is not None,
                    "stale": any(
                        grant.descriptor_digest != action.descriptor_digest
                        for grant in related
                    ),
                    "input_values": (
                        current.input_values if current is not None else {}
                    ),
                },
            )
        return {"revision": policy.revision, "actions": actions}

    @staticmethod
    def _grant_input_values(action, input_values):
        properties = action.input_schema.get("properties", {})
        if not isinstance(properties, dict) or len(input_values) > 32:
            raise TaskStoreError("invalid_grant_constraints")
        normalized = {}
        for key, raw_values in input_values.items():
            field = properties.get(key)
            invalid_field = (
                not isinstance(key, str)
                or not isinstance(field, dict)
                or field.get("type") != "string"
            )
            invalid_values = (
                not isinstance(raw_values, list)
                or not raw_values
                or len(raw_values) > 64
            )
            if invalid_field or invalid_values:
                raise TaskStoreError("invalid_grant_constraints")
            values = []
            for value in raw_values:
                if (
                    not isinstance(value, str)
                    or not value
                    or len(value) > 2048
                ):
                    raise TaskStoreError("invalid_grant_constraints")
                if value not in values:
                    values.append(value)
            normalized[key] = values
        return normalized

    async def set_action_grant(
        self,
        scope: TaskScope,
        action_id: str,
        *,
        enabled: bool,
        input_values: dict,
        expected_revision: int,
    ):
        """Pin or revoke one live action descriptor for a Host operator."""
        await self._sync()
        binding = self._binding(scope, action_id)
        action = binding.registration.action
        normalized = (
            self._grant_input_values(action, input_values) if enabled else {}
        )
        await self.policy.set_grant(
            TaskGrant(
                scope=scope,
                action_id=action_id,
                descriptor_digest=action.descriptor_digest,
                input_values=normalized,
            ),
            enabled=enabled,
            expected_revision=expected_revision,
        )
        await self.store.audit(
            scope,
            action_id,
            "grant",
            "enabled" if enabled else "revoked",
        )
        return await self.grant_catalog(
            scope.principal_id,
            scope.workspace_id,
        )

    def _binding(self, scope, action_id):
        key = (scope.app_id, action_id)
        binding = self._bindings.get(key)
        if (
            binding is None
            or self._registrations().get(key) is not binding.registration
        ):
            raise TaskStoreError("action_not_found")
        return binding

    async def _readiness(
        self,
        registration,
        adapter,
        scope,
        inputs,
    ):
        prepared = None
        if self.setup is not None and registration.requirement_ids:
            prepared = await self.setup.prepare_for_task(
                scope,
                registration,
                inputs,
            )
            if prepared.state != "ready":
                return prepared, prepared.blocking_results[0].reason_code
        legacy = await adapter.readiness(scope, inputs)
        if legacy.state != "ready":
            return prepared, legacy.reason
        return prepared, None

    async def _require_ready(
        self,
        registration,
        adapter,
        scope,
        inputs,
    ):
        _prepared, reason = await self._readiness(
            registration,
            adapter,
            scope,
            inputs,
        )
        if reason is not None:
            raise TaskStoreError(reason)

    async def dispatch(
        self,
        scope,
        action_id,
        *,
        request_id,
        inputs,
        origin,
        prepare=False,
    ):
        await self._sync()
        binding = self._binding(scope, action_id)
        action = binding.coordinator.describe(scope.app_id, action_id)
        action.validate_inputs(inputs)
        if origin.engagement not in action.engagements:
            raise TaskStoreError("unsupported_engagement")
        await self._authorize(scope, action, origin, inputs)
        # A retry of an accepted/uncertain request returns its durable handle,
        # even if settings are now unavailable. It must not become a new task.
        existing = await self.store.find_request(scope, request_id)
        if existing is None or prepare:
            prepared, reason = await self._readiness(
                binding.registration,
                binding.adapter,
                scope,
                inputs,
            )
            if reason is not None:
                await self.store.audit(
                    scope,
                    action_id,
                    "prepare" if prepare else "dispatch",
                    reason,
                    request_id=request_id,
                )
                if prepared is not None and prepared.state != "ready":
                    entries = tuple(
                        dict.fromkeys(
                            requirement.setup_entry_ref
                            for requirement in prepared.requirements
                            if any(
                                result.requirement_id == requirement.id
                                and result.state != "ready"
                                for result in prepared.results
                            )
                        ),
                    )
                    return {
                        "state": "blocked",
                        "reason": reason,
                        "setup": "required",
                        "setup_entries": entries,
                        "readiness": prepared,
                    }
                return {
                    "state": "blocked",
                    "reason": reason,
                    "setup": "unsupported_setup",
                    "settings_entry": binding.registration.settings_entry,
                }
        if prepare:
            result = {"state": "ready"}
            if prepared is not None:
                result["readiness"] = prepared
            return result
        await self._authorize(scope, action, origin, inputs)
        # Audit intent before creating durable work. Recovery has its own
        # authorization check; a probe never grants permission to execute.
        await self.store.audit(
            scope,
            action_id,
            "dispatch",
            "authorized",
            request_id=request_id,
        )
        submission = await self.store.create(
            scope,
            action,
            request_id=request_id,
            inputs=inputs,
            origin=origin,
        )
        self._wake(submission)
        return {"state": "accepted", "task": submission.handle}

    async def create_setup_request(
        self,
        scope,
        action_id,
        *,
        idempotency_key,
        inputs,
        origin,
        presentation,
        entry_id=None,
        requirement_ids=(),
        project_ref=None,
        plan_digest=None,
        expected_revisions=None,
        scopes=(),
        suggested_values=(),
        expires_in_seconds=900,
    ):
        """Prepare again and persist setup without creating latent work."""
        if self.setup is None:
            raise TaskStoreError("setup_runtime_unavailable")
        await self._sync()
        binding = self._binding(scope, action_id)
        action = binding.coordinator.describe(scope.app_id, action_id)
        action.validate_inputs(inputs)
        if origin.engagement not in action.engagements:
            raise TaskStoreError("unsupported_engagement")
        await self._authorize(scope, action, origin, inputs)
        if not binding.registration.requirement_ids:
            raise TaskStoreError("unsupported_setup")
        prepared = await self.setup.prepare_for_task(
            scope,
            binding.registration,
            inputs,
        )
        record, replayed = await self.setup.request(
            scope,
            binding.registration,
            prepared,
            idempotency_key=idempotency_key,
            input_digest=content_digest(inputs),
            origin_ref=origin.origin_ref,
            presentation=presentation,
            entry_id=entry_id,
            requirement_ids=requirement_ids,
            project_ref=project_ref,
            plan_digest=plan_digest,
            expected_revisions=expected_revisions,
            scopes=scopes,
            suggested_values=suggested_values,
            return_target=origin.origin_ref,
            expires_in_seconds=expires_in_seconds,
        )
        await self.store.audit(
            scope,
            action_id,
            "setup",
            "replayed" if replayed else "requested",
            request_id=record.request.request_id,
        )
        return record, replayed

    async def get(self, scope, task_id):
        submission = await self.store.get(scope, task_id)
        await self._authorize(
            scope,
            submission.action,
            submission.handle.origin,
            submission.inputs,
        )
        return submission

    async def open_app(self, scope, task_id):
        """Issue an authenticated handoff for the task's App-owned project."""
        if self.handoffs is None:
            raise TaskStoreError("handoff_store_unavailable")
        submission = await self.get(scope, task_id)
        project = submission.handle.project_ref
        if project is None:
            raise TaskStoreError("project_unavailable")
        return await self.handoffs.create(
            submission,
            target_app_id=project.app_id,
        )

    async def resolve_handoff(self, scope, handoff_id):
        if self.handoffs is None:
            raise TaskStoreError("handoff_store_unavailable")
        return await self.handoffs.resolve(scope, handoff_id)

    async def answer(
        self,
        scope,
        task_id,
        *,
        command_id,
        request_id,
        answers,
    ):
        await self._sync()
        submission = await self.get(scope, task_id)
        command = await self.store.prepare_answer(
            scope,
            task_id,
            command_id=command_id,
            request_id=request_id,
            answers=answers,
        )
        binding = self._binding(scope, submission.handle.action_id)
        command = await binding.coordinator.deliver_command(
            scope,
            task_id,
            command.command_id,
        )
        await self.store.audit(
            scope,
            submission.handle.action_id,
            "answer",
            command.state,
            request_id=command_id,
            task_id=task_id,
        )
        self._wake(await self.store.get(scope, task_id), force=True)
        return command

    async def cancel(self, scope, task_id, *, reason=None):
        await self._sync()
        submission = await self.get(scope, task_id)
        command = await self.store.prepare_cancel(
            scope,
            task_id,
            reason=reason,
        )
        if command.state not in {"accepted", "rejected"}:
            binding = self._binding(scope, submission.handle.action_id)
            command = await binding.coordinator.deliver_command(
                scope,
                task_id,
                command.command_id,
            )
        await self.store.audit(
            scope,
            submission.handle.action_id,
            "cancel",
            command.state,
            request_id=command.command_id,
            task_id=task_id,
        )
        self._wake(await self.store.get(scope, task_id), force=True)
        return command

    def _wake(self, submission, *, force=False):
        handle = submission.handle
        if self._closed or handle.status in TERMINAL_STATUSES:
            return
        if force:
            self._retry_at.pop(handle.task_id, None)
        current = self._workers.get(handle.task_id)
        if current is not None and not current[1].done():
            if force and handle.task_id not in self._forced_rewake:
                self._forced_rewake.add(handle.task_id)
                current[1].add_done_callback(
                    lambda _job: self._rewake(submission),
                )
            return
        if (
            sum(not job.done() for _, job in self._workers.values()) >= 32
            or self._retry_at.get(handle.task_id, 0) > time.monotonic()
        ):
            return
        key = (handle.scope.app_id, handle.action_id)
        if key not in self._bindings:
            return
        job = asyncio.create_task(self._drive(handle.scope, handle.task_id))
        job.add_done_callback(self._worker_finished)
        self._workers[handle.task_id] = (key, job)

    def _rewake(self, submission):
        self._forced_rewake.discard(submission.handle.task_id)
        self._wake(submission, force=True)

    @staticmethod
    def _worker_finished(job):
        if not job.cancelled() and job.exception() is not None:
            logger.error("PawApp task recovery persistence failed")

    async def _drive(self, scope, task_id):
        try:
            submission = await self.store.get(scope, task_id)
            binding = self._binding(scope, submission.handle.action_id)
            await self._authorize(
                scope,
                submission.action,
                submission.handle.origin,
                submission.inputs,
            )
            # Unknown sends query acceptance first. _ReadyAdapter checks
            # configuration if reconciliation needs to submit the same ID.
            submission = await binding.coordinator.reconcile(scope, task_id)
            if submission.handle.executor_run_ref is not None:
                command = await self.store.pending_command(scope, task_id)
                if command is not None:
                    await binding.coordinator.deliver_command(
                        scope,
                        task_id,
                        command.command_id,
                    )
                await binding.coordinator.consume(scope, task_id)
        except Exception as exc:
            # Never copy transport response bodies, prompts or tokens to logs.
            code = (
                exc.code
                if isinstance(exc, TaskStoreError)
                else "recovery_error"
            )
            await self.store.mark_recovery(
                scope,
                task_id,
                state="unresolved",
                reason=code,
            )
        finally:
            self._retry_at[task_id] = time.monotonic() + max(self._interval, 5)

    async def _supervise(self):
        while True:
            try:
                await self._sync()
                self._workers = {
                    key: value
                    for key, value in self._workers.items()
                    if not value[1].done()
                }
                self._retry_at = {
                    key: deadline
                    for key, deadline in self._retry_at.items()
                    if deadline > time.monotonic()
                }
                cursor = ""
                while True:
                    page = await self.store.recoverable(after=cursor)
                    for submission in page:
                        self._wake(submission)
                    if len(page) < 100:
                        break
                    cursor = page[-1].handle.task_id
            except Exception:
                logger.error("PawApp task recovery scan failed; will retry")
            await asyncio.sleep(self._interval)
