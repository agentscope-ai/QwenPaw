# -*- coding: utf-8 -*-
"""Generic, bounded readiness coordinator for registered PawApp checks."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from ..tasks.binding import ActionRegistration
from ..tasks.contracts import TaskScope, TaskStoreError
from .contracts import PrepareResult, ReadinessResult

logger = logging.getLogger(__name__)


class SetupCoordinator:
    """Resolve App declarations without interpreting domain configuration."""

    def __init__(
        self,
        *,
        checks: Callable[[], dict],
        entries: Callable[[], dict],
        timeout: float = 5.0,
        empty_ttl: float = 30.0,
    ):
        if timeout <= 0 or empty_ttl <= 0:
            raise ValueError("setup timing values must be positive")
        self._checks = checks
        self._entries = entries
        self.timeout = timeout
        self.empty_ttl = empty_ttl

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

    async def prepare_for_task(
        self,
        scope: TaskScope,
        registration: ActionRegistration,
        inputs: dict[str, Any],
    ) -> PrepareResult:
        """Check only the requirements declared by the selected action."""
        now = time.time()
        checks = self._checks()
        selected = []
        requirements = []
        for requirement_id in registration.requirement_ids:
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
