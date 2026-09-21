# -*- coding: utf-8 -*-
"""Host-owned task lifecycle, readiness and dispatch boundary."""

import asyncio
from copy import deepcopy
import logging
import time
from dataclasses import dataclass
from functools import partial
from typing import Callable

from .binding import ActionRegistration, AuthorizeOrigin, ManagedTaskAdapter
from .contracts import (
    TERMINAL_STATUSES,
    ExecutorEvent,
    TaskScope,
    TaskStoreError,
    content_digest,
)
from .coordinator import TaskCoordinator
from .policy import (
    FileTaskPolicy,
    TaskGrant,
    build_task_capabilities,
)
from .store import TaskStore

logger = logging.getLogger(__name__)

_ACTIONABLE_SETUP_STATES = frozenset(
    {"needs_input", "needs_configuration", "needs_authorization"},
)
_ACTIVE_SETUP_STATES = frozenset(
    {"requested", "opened", "waiting_external"},
)


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
        if self.setup is not None:
            self.setup.set_task_waker(self._wake_setup_task)
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

    async def _authorize_action(self, scope, action, origin):
        """Check an action grant before an App resolves optional inputs."""
        registration = self._registrations().get(
            (scope.app_id, action.action_id),
        )
        if registration is None:
            raise TaskStoreError("action_not_found")
        if registration.action.descriptor_digest != action.descriptor_digest:
            raise TaskStoreError("descriptor_changed")
        try:
            await self.policy.check(scope, action)
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
        binding = self._public_binding(scope, action_id)
        await self.policy.check(scope, binding.registration.action)
        return binding.coordinator.describe(scope.app_id, action_id)

    async def catalog(self, principal_id, workspace_id, *, intent=""):
        """Compact granted descriptors; no readiness probes or dispatch."""
        await self._sync()
        result = []
        for (app_id, action_id), binding in sorted(self._bindings.items()):
            if binding.registration.exposure != "host_public":
                continue
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
        """Return action grants plus higher-level capability bundle state."""
        await self._sync()
        policy = await self.policy.read()
        actions = []
        public_actions = []
        for (app_id, action_id), binding in sorted(self._bindings.items()):
            if binding.registration.exposure != "host_public":
                continue
            action = binding.registration.action
            public_actions.append(action)
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
        action_by_key = {
            (item["app_id"], item["action_id"]): item for item in actions
        }
        capabilities = []
        for capability in build_task_capabilities(public_actions):
            states = [
                action_by_key[(capability.app_id, action_id)]
                for action_id in capability.action_ids
            ]
            enabled_count = sum(1 for item in states if item["enabled"])
            capabilities.append(
                {
                    **capability.model_dump(mode="json"),
                    "enabled": enabled_count == len(states),
                    "partial": 0 < enabled_count < len(states),
                    "stale": any(item["stale"] for item in states),
                },
            )
        return {
            "revision": policy.revision,
            "actions": actions,
            "capabilities": capabilities,
        }

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
        binding = self._public_binding(scope, action_id)
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

    async def set_capability_grant(
        self,
        scope: TaskScope,
        capability_id: str,
        *,
        enabled: bool,
        expected_revision: int,
    ):
        """Atomically grant or revoke every public action in one bundle."""
        await self._sync()
        public_actions = [
            binding.registration.action
            for binding in self._bindings.values()
            if binding.registration.exposure == "host_public"
            and binding.registration.action.app_id == scope.app_id
        ]
        capability = next(
            (
                item
                for item in build_task_capabilities(public_actions)
                if item.capability_id == capability_id
            ),
            None,
        )
        if capability is None:
            raise TaskStoreError("action_not_found")

        policy = await self.policy.read()
        actions = {
            action_id: self._public_binding(
                scope,
                action_id,
            ).registration.action
            for action_id in capability.action_ids
        }
        grants = tuple(
            TaskGrant(
                scope=scope,
                action_id=action_id,
                descriptor_digest=actions[action_id].descriptor_digest,
                input_values=next(
                    (
                        grant.input_values
                        for grant in policy.grants
                        if grant.scope == scope
                        and grant.action_id == action_id
                        and grant.descriptor_digest
                        == actions[action_id].descriptor_digest
                    ),
                    {},
                ),
            )
            for action_id in capability.action_ids
        )
        await self.policy.set_grants(
            grants,
            enabled=enabled,
            expected_revision=expected_revision,
        )
        outcome = "enabled" if enabled else "revoked"
        for action_id in capability.action_ids:
            await self.store.audit(
                scope,
                action_id,
                "capability_grant",
                outcome,
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

    def _public_binding(self, scope, action_id):
        binding = self._binding(scope, action_id)
        if binding.registration.exposure != "host_public":
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
                return (
                    prepared,
                    prepared.blocking_results[0].reason_code,
                    None,
                )
        resolved_inputs = deepcopy(inputs)
        if registration.input_resolver is not None:
            resolved_inputs = await registration.input_resolver(
                scope,
                resolved_inputs,
            )
            registration.action.validate_inputs(resolved_inputs)
        legacy = await adapter.readiness(scope, resolved_inputs)
        if legacy.state != "ready":
            return prepared, legacy.reason, None
        return prepared, None, resolved_inputs

    async def _require_ready(
        self,
        registration,
        adapter,
        scope,
        inputs,
    ):
        _prepared, reason, _resolved_inputs = await self._readiness(
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
        binding = self._public_binding(scope, action_id)
        registration = binding.registration
        action = binding.coordinator.describe(scope.app_id, action_id)
        action.validate_inputs(inputs)
        if origin.engagement not in action.engagements:
            raise TaskStoreError("unsupported_engagement")
        if registration.input_resolver is None:
            await self._authorize(scope, action, origin, inputs)
        else:
            await self._authorize_action(scope, action, origin)
        # A retry of an accepted/uncertain request returns its durable handle,
        # even if settings are now unavailable. It must not become a new task.
        existing = await self.store.find_request(scope, request_id)
        if existing is not None and registration.input_resolver is not None:
            if (
                existing.action != action
                or existing.handle.origin != origin
                or any(
                    key not in existing.inputs or existing.inputs[key] != value
                    for key, value in inputs.items()
                )
            ):
                raise TaskStoreError("request_conflict")
            await self._authorize(
                scope,
                action,
                origin,
                existing.inputs,
            )
            return {"state": "accepted", "task": existing.handle}
        resolved_inputs = deepcopy(inputs)
        if existing is None or prepare:
            prepared, reason, prepared_inputs = await self._readiness(
                registration,
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
            assert prepared_inputs is not None
            resolved_inputs = prepared_inputs
        if registration.input_resolver is not None:
            await self._authorize(
                scope,
                action,
                origin,
                resolved_inputs,
            )
        if prepare:
            result = {"state": "ready"}
            if prepared is not None:
                result["readiness"] = prepared
            return result
        if registration.input_resolver is None:
            await self._authorize(scope, action, origin, resolved_inputs)
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
            inputs=resolved_inputs,
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
        binding = self._public_binding(scope, action_id)
        action = binding.coordinator.describe(scope.app_id, action_id)
        action.validate_inputs(inputs)
        if origin.engagement not in action.engagements:
            raise TaskStoreError("unsupported_engagement")
        if binding.registration.input_resolver is None:
            await self._authorize(scope, action, origin, inputs)
        else:
            await self._authorize_action(scope, action, origin)
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

    async def _wake_setup_task(self, scope, task_id):
        submission = await self.store.get(scope, task_id)
        self._wake(submission, force=True)

    async def _prepare_deferred(self, binding, submission, requirement_id):
        if self.setup is None:
            raise TaskStoreError("setup_runtime_unavailable")
        prepared = await self.setup.prepare_deferred_requirement(
            submission.handle.scope,
            binding.registration,
            submission.inputs,
            requirement_id,
        )
        if len(prepared.results) != 1:
            raise TaskStoreError("setup_requirement_mismatch")
        return prepared, prepared.results[0]

    async def _commit_event(
        self,
        binding,
        submission,
        event: ExecutorEvent,
    ):
        need = event.setup_need
        if need is None:
            return await self.store.apply_event(
                submission.handle.scope,
                submission.handle.task_id,
                event,
            )
        if need.requirement_id not in (
            binding.registration.deferred_requirement_ids
        ):
            raise TaskStoreError("setup_requirement_mismatch")
        prepared, result = await self._prepare_deferred(
            binding,
            submission,
            need.requirement_id,
        )
        if result.state == "ready":
            return await self.store.apply_event(
                submission.handle.scope,
                submission.handle.task_id,
                event.model_copy(
                    update={"status": "running", "setup_need": None},
                ),
            )
        if result.state in _ACTIONABLE_SETUP_STATES:
            attempt = submission.handle.setup_attempt + 1
            record, _replayed = await self.setup.request_for_task(
                submission,
                binding.registration,
                prepared,
                requirement_id=need.requirement_id,
                attempt=attempt,
            )
            return await self.store.apply_event(
                submission.handle.scope,
                submission.handle.task_id,
                event,
                setup_request_id=record.request.request_id,
                setup_attempt=attempt,
            )
        if result.state == "unavailable":
            return await self.store.fail_after_setup(
                submission.handle.scope,
                submission.handle.task_id,
                expected_request_id=None,
                expected_attempt=submission.handle.setup_attempt,
                reason_code=result.reason_code or "setup_unavailable",
            )
        raise TaskStoreError(result.reason_code or "setup_readiness_unknown")

    @staticmethod
    def _validate_setup_link(submission, record):
        handle = submission.handle
        request = record.request
        if (
            request.scope != handle.scope
            or request.task_id != handle.task_id
            or request.action_id != handle.action_id
            or request.descriptor_digest != handle.descriptor_digest
            or request.input_digest != content_digest(submission.inputs)
            or request.attempt != handle.setup_attempt
            or len(request.requirement_ids) != 1
        ):
            raise TaskStoreError("setup_link_conflict")
        return request.requirement_ids[0]

    async def _reconcile_setup(self, binding, submission):
        handle = submission.handle
        if (
            handle.status != "waiting_for_setup"
            or handle.setup_request_id is None
        ):
            return submission, False
        if self.setup is None:
            raise TaskStoreError("setup_runtime_unavailable")
        record = await self.setup.get(handle.scope, handle.setup_request_id)
        requirement_id = self._validate_setup_link(submission, record)
        if requirement_id not in binding.registration.deferred_requirement_ids:
            raise TaskStoreError("setup_requirement_mismatch")
        if record.request.state in _ACTIVE_SETUP_STATES:
            return submission, True
        if record.request.state == "cancelled":
            await self.store.prepare_cancel(
                handle.scope,
                handle.task_id,
                reason="setup_cancelled",
            )
            return await self.store.get(handle.scope, handle.task_id), False
        if record.request.state in {"failed", "expired"}:
            return (
                await self.store.fail_after_setup(
                    handle.scope,
                    handle.task_id,
                    expected_request_id=record.request.request_id,
                    expected_attempt=handle.setup_attempt,
                    reason_code="setup_" + record.request.state,
                ),
                True,
            )
        prepared, result = await self._prepare_deferred(
            binding,
            submission,
            requirement_id,
        )
        if result.state == "ready":
            return (
                await self.store.resume_after_setup(
                    handle.scope,
                    handle.task_id,
                    expected_request_id=record.request.request_id,
                    expected_attempt=handle.setup_attempt,
                ),
                False,
            )
        if result.state in _ACTIONABLE_SETUP_STATES:
            next_attempt = handle.setup_attempt + 1
            next_record, _replayed = await self.setup.request_for_task(
                submission,
                binding.registration,
                prepared,
                requirement_id=requirement_id,
                attempt=next_attempt,
                plan_digest=record.request.plan_digest,
            )
            return (
                await self.store.replace_setup_request(
                    handle.scope,
                    handle.task_id,
                    expected_request_id=record.request.request_id,
                    expected_attempt=handle.setup_attempt,
                    request_id=next_record.request.request_id,
                    attempt=next_attempt,
                ),
                True,
            )
        if result.state == "unavailable":
            return (
                await self.store.fail_after_setup(
                    handle.scope,
                    handle.task_id,
                    expected_request_id=record.request.request_id,
                    expected_attempt=handle.setup_attempt,
                    reason_code=result.reason_code or "setup_unavailable",
                ),
                True,
            )
        raise TaskStoreError(result.reason_code or "setup_readiness_unknown")

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
            submission, waiting_for_setup = await self._reconcile_setup(
                binding,
                submission,
            )
            if (
                waiting_for_setup
                or submission.handle.status in TERMINAL_STATUSES
            ):
                return
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
                await binding.coordinator.consume(
                    scope,
                    task_id,
                    commit_event=partial(self._commit_event, binding),
                )
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
