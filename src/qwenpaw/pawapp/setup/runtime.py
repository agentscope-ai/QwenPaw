# -*- coding: utf-8 -*-
"""Generic, bounded readiness coordinator for registered PawApp checks."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ..tasks.binding import ActionRegistration
from ..tasks.contracts import (
    ProjectRef,
    TaskScope,
    TaskStoreError,
    TaskSubmission,
    content_digest,
)
from .contracts import (
    PrepareResult,
    ReadinessResult,
    SetupPresentation,
    SetupResult,
    SuggestedValue,
)
from .store import SetupStore

logger = logging.getLogger(__name__)

TaskSetupWaker = Callable[[TaskScope, str], Awaitable[None]]


class SetupCoordinator:
    """Resolve App declarations without interpreting domain configuration."""

    def __init__(
        self,
        *,
        checks: Callable[[], dict],
        entries: Callable[[], dict],
        store: SetupStore | None = None,
        timeout: float = 5.0,
        empty_ttl: float = 30.0,
    ):
        if timeout <= 0 or empty_ttl <= 0:
            raise ValueError("setup timing values must be positive")
        self._checks = checks
        self._entries = entries
        self.store = store
        self.timeout = timeout
        self.empty_ttl = empty_ttl
        self._task_waker: TaskSetupWaker | None = None

    def set_task_waker(self, waker: TaskSetupWaker | None) -> None:
        self._task_waker = waker

    def entry(self, app_id: str, entry_id: str):
        registration = self._entries().get((app_id, entry_id))
        if registration is None:
            raise TaskStoreError("entry_unavailable")
        return registration

    async def _check(
        self,
        registration,
        scope: TaskScope,
        inputs: dict[str, Any],
    ) -> ReadinessResult:
        requirement = registration.requirement
        now = time.time()
        try:
            async with asyncio.timeout(self.timeout):
                result = await registration.checker(scope, inputs)
        except TimeoutError:
            return ReadinessResult(
                requirement_id=requirement.id,
                state="unknown",
                reason_code="setup_check_timeout",
                reason="The setup check timed out; retry is available.",
                checked_at=now,
                expires_at=now,
            )
        except Exception:  # noqa: BLE001
            # App exceptions may contain connection details. Keep logs and
            # public results on the stable, secret-free contract surface.
            logger.warning(
                "PawApp setup check failed for %s/%s",
                scope.app_id,
                requirement.id,
            )
            return ReadinessResult(
                requirement_id=requirement.id,
                state="unknown",
                reason_code="setup_check_failed",
                reason="The setup check failed; retry is available.",
                checked_at=now,
                expires_at=now,
            )
        if not isinstance(result, ReadinessResult):
            raise TaskStoreError("invalid_readiness_result")
        if result.requirement_id != requirement.id:
            raise TaskStoreError("readiness_requirement_mismatch")
        if result.expires_at <= time.time():
            return ReadinessResult(
                requirement_id=requirement.id,
                state="unknown",
                reason_code="readiness_expired",
                reason="The setup result expired; retry is available.",
                checked_at=time.time(),
                expires_at=time.time(),
            )
        return result

    async def _prepare_requirements(
        self,
        scope: TaskScope,
        registration: ActionRegistration,
        inputs: dict[str, Any],
        requirement_ids: tuple[str, ...],
    ) -> PrepareResult:
        now = time.time()
        checks = self._checks()
        selected = []
        requirements = []
        for requirement_id in requirement_ids:
            check = checks.get((scope.app_id, requirement_id))
            if check is None:
                raise TaskStoreError("setup_check_unavailable")
            requirement = check.requirement
            if registration.action.action_id not in requirement.required_for:
                raise TaskStoreError("setup_requirement_mismatch")
            self.entry(scope.app_id, requirement.setup_entry_ref)
            selected.append(check)
            requirements.append(requirement)

        results = tuple(
            await asyncio.gather(
                *(self._check(item, scope, inputs) for item in selected),
            ),
        )
        state = "ready"
        if any(item.state == "unknown" for item in results):
            state = "unknown"
        if any(item.state not in {"ready", "unknown"} for item in results):
            state = "blocked"
        expires_at = min(
            (item.expires_at for item in results),
            default=now + self.empty_ttl,
        )
        return PrepareResult(
            app_id=scope.app_id,
            action_id=registration.action.action_id,
            descriptor_digest=registration.action.descriptor_digest,
            state=state,
            requirements=tuple(requirements),
            results=results,
            checked_at=now,
            expires_at=expires_at,
        )

    async def prepare_for_task(
        self,
        scope: TaskScope,
        registration: ActionRegistration,
        inputs: dict[str, Any],
    ) -> PrepareResult:
        """Check only eager requirements declared by the selected action."""
        return await self._prepare_requirements(
            scope,
            registration,
            inputs,
            registration.requirement_ids,
        )

    async def prepare_deferred_requirement(
        self,
        scope: TaskScope,
        registration: ActionRegistration,
        inputs: dict[str, Any],
        requirement_id: str,
    ) -> PrepareResult:
        if requirement_id not in registration.deferred_requirement_ids:
            raise TaskStoreError("setup_requirement_mismatch")
        return await self._prepare_requirements(
            scope,
            registration,
            inputs,
            (requirement_id,),
        )

    def _store(self) -> SetupStore:
        if self.store is None:
            raise TaskStoreError("setup_runtime_unavailable")
        return self.store

    async def request(
        self,
        scope: TaskScope,
        registration: ActionRegistration,
        prepared: PrepareResult,
        *,
        idempotency_key: str,
        input_digest: str,
        origin_ref: str,
        presentation: SetupPresentation,
        entry_id: str | None = None,
        requirement_ids: tuple[str, ...] = (),
        task_id: str | None = None,
        attempt: int | None = None,
        project_ref: ProjectRef | None = None,
        plan_digest: str | None = None,
        expected_revisions: dict[str, int] | None = None,
        scopes: tuple[str, ...] = (),
        suggested_values: tuple[SuggestedValue, ...] = (),
        return_target: str,
        expires_in_seconds: float = 900,
    ):
        """Persist one request for actionable blockers from a fresh prepare."""
        if prepared.descriptor_digest != registration.action.descriptor_digest:
            raise TaskStoreError("descriptor_changed")
        if (
            prepared.app_id != scope.app_id
            or prepared.action_id != registration.action.action_id
        ):
            raise TaskStoreError("setup_requirement_mismatch")
        actionable = {
            result.requirement_id
            for result in prepared.results
            if result.state
            in {"needs_input", "needs_configuration", "needs_authorization"}
        }
        selected_ids = requirement_ids or tuple(
            requirement.id
            for requirement in prepared.requirements
            if requirement.id in actionable
        )
        if not selected_ids or not set(selected_ids).issubset(actionable):
            raise TaskStoreError("unsupported_setup")
        selected = tuple(
            requirement
            for requirement in prepared.requirements
            if requirement.id in selected_ids
        )
        entries = {item.setup_entry_ref for item in selected}
        if entry_id is None:
            if len(entries) != 1:
                raise TaskStoreError("setup_entry_required")
            entry_id = next(iter(entries))
        if entries != {entry_id}:
            raise TaskStoreError("setup_requirement_entry_mismatch")
        entry = self.entry(scope.app_id, entry_id).descriptor
        if presentation not in entry.presentations:
            raise TaskStoreError("presentation_unsupported")
        if project_ref is not None and project_ref.app_id != scope.app_id:
            raise TaskStoreError("setup_project_scope_mismatch")
        if not 60 <= expires_in_seconds <= 3600:
            raise TaskStoreError("invalid_setup_expiry")
        selected_id_set = set(selected_ids)
        checked_revisions = {
            result.requirement_id: result.checked_revision
            for result in prepared.results
            if result.checked_revision is not None
            and result.requirement_id in selected_id_set
        }
        supplied_revisions = expected_revisions or {}
        if not set(supplied_revisions).issubset(selected_id_set):
            raise TaskStoreError("setup_revision_scope_mismatch")
        if any(
            key in supplied_revisions and supplied_revisions[key] != value
            for key, value in checked_revisions.items()
        ):
            raise TaskStoreError("context_conflict")
        return await self._store().create(
            scope,
            idempotency_key=idempotency_key,
            meaning_context={"input_digest": input_digest},
            values={
                "descriptor_digest": registration.action.descriptor_digest,
                "input_digest": input_digest,
                "entry_id": entry_id,
                "requirement_ids": tuple(item.id for item in selected),
                "origin_ref": origin_ref,
                "task_id": task_id,
                "action_id": registration.action.action_id,
                "attempt": attempt,
                "project_ref": project_ref,
                "plan_digest": plan_digest,
                "expected_revisions": {
                    **supplied_revisions,
                    **checked_revisions,
                },
                "scopes": scopes,
                "suggested_values": suggested_values,
                "presentation": presentation,
                "expires_at": time.time() + expires_in_seconds,
                "return_target": return_target,
            },
        )

    async def request_for_task(
        self,
        submission: TaskSubmission,
        registration: ActionRegistration,
        prepared: PrepareResult,
        *,
        requirement_id: str,
        attempt: int,
        plan_digest: str | None = None,
    ):
        handle = submission.handle
        if (
            handle.scope.app_id != registration.action.app_id
            or handle.action_id != registration.action.action_id
            or handle.descriptor_digest
            != registration.action.descriptor_digest
            or requirement_id not in registration.deferred_requirement_ids
            or attempt < 1
        ):
            raise TaskStoreError("setup_requirement_mismatch")
        requirement = next(
            (
                item
                for item in prepared.requirements
                if item.id == requirement_id
            ),
            None,
        )
        if requirement is None or len(prepared.requirements) != 1:
            raise TaskStoreError("setup_requirement_mismatch")
        entry = self.entry(
            handle.scope.app_id,
            requirement.setup_entry_ref,
        ).descriptor
        presentation = (
            "app_entry"
            if "app_entry" in entry.presentations
            else entry.presentations[0]
        )
        input_digest = content_digest(submission.inputs)
        idempotency_key = content_digest(
            {
                "domain": "qwenpaw:pawapp-task-setup-request",
                "version": 1,
                "task_id": handle.task_id,
                "app_id": handle.scope.app_id,
                "action_id": handle.action_id,
                "requirement_id": requirement_id,
                "descriptor_digest": handle.descriptor_digest,
                "plan_digest": plan_digest,
                "input_digest": input_digest,
                "attempt": attempt,
            },
        )
        return_target = (
            handle.origin.return_session_ref
            or handle.origin.app_session_ref
            or handle.origin.origin_ref
        )
        return await self.request(
            handle.scope,
            registration,
            prepared,
            idempotency_key=idempotency_key,
            input_digest=input_digest,
            origin_ref=handle.origin.origin_ref,
            presentation=presentation,
            entry_id=requirement.setup_entry_ref,
            requirement_ids=(requirement_id,),
            task_id=handle.task_id,
            attempt=attempt,
            project_ref=handle.project_ref,
            plan_digest=plan_digest,
            return_target=return_target,
        )

    async def get(self, scope: TaskScope, request_id: str):
        return await self._store().get(scope, request_id)

    async def backend_request(
        self,
        principal_id: str,
        app_id: str,
        request_id: str,
    ):
        """Resolve one request for its trusted, same-process App backend."""
        scope = await self._store().backend_scope(
            principal_id,
            app_id,
            request_id,
        )
        return scope, await self.get(scope, request_id)

    async def open(self, scope: TaskScope, request_id: str):
        record = await self.get(scope, request_id)
        if record.request.state in {
            "saved",
            "cancelled",
            "failed",
            "expired",
        }:
            raise TaskStoreError("setup_request_closed")
        if record.open_action is not None:
            return record
        entry = self.entry(scope.app_id, record.request.entry_id)
        if record.request.presentation not in entry.descriptor.presentations:
            raise TaskStoreError("presentation_unsupported")
        action = await entry.opener(record.request)
        return await self._store().opened(scope, request_id, action)

    async def waiting_external(self, scope: TaskScope, request_id: str):
        self.entry(
            scope.app_id,
            (await self.get(scope, request_id)).request.entry_id,
        )
        return await self._store().waiting_external(scope, request_id)

    async def _wake_linked_task(self, record) -> None:
        task_id = record.request.task_id
        if task_id is None or self._task_waker is None:
            return
        try:
            await self._task_waker(record.request.scope, task_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "PawApp task wake failed after setup terminal transition",
            )

    async def complete(self, scope: TaskScope, result: SetupResult):
        record = await self.get(scope, result.request_id)
        self.entry(scope.app_id, record.request.entry_id)
        record = await self._store().complete(scope, result)
        await self._wake_linked_task(record)
        return record

    async def cancel(self, scope: TaskScope, request_id: str):
        record = await self._store().cancel(scope, request_id)
        await self._wake_linked_task(record)
        return record
