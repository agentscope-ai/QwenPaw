# -*- coding: utf-8 -*-
"""Approval service for sensitive tool execution.

The ``ApprovalService`` is the single central store for pending /
completed approval records.  Approval is granted exclusively via
the ``/daemon approve`` command in the chat interface.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...security.tool_guard.approval import ApprovalDecision

if TYPE_CHECKING:
    from ...security.tool_guard.models import ToolGuardResult

logger = logging.getLogger(__name__)

_GC_MAX_AGE_SECONDS = 3600.0
_GC_MAX_COMPLETED = 500
_GC_PENDING_MAX_AGE_SECONDS = 1800.0
_GC_MAX_PENDING = 200


# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------


@dataclass
class PendingApproval:
    """In-memory record for one pending approval."""

    request_id: str
    session_id: str
    user_id: str
    channel: str
    tool_name: str
    created_at: float
    future: asyncio.Future[ApprovalDecision]
    status: str = "pending"
    resolved_at: float | None = None
    result_summary: str = ""
    findings_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------
# Service
# ------------------------------------------------------------------


class ApprovalService:
    """Central approval service.

    Tracks pending and completed approval records.  Approval is
    resolved via ``/daemon approve`` (see ``runner.py`` and
    ``daemon_commands.py``).
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[str, PendingApproval] = {}
        self._completed: dict[str, PendingApproval] = {}
        self._channel_manager: Any | None = None

    def set_channel_manager(self, channel_manager: Any) -> None:
        """Store a reference to the channel manager for push notifications."""
        self._channel_manager = channel_manager

    # ------------------------------------------------------------------
    # Core approval lifecycle
    # ------------------------------------------------------------------

    async def create_pending(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        tool_name: str,
        result: "ToolGuardResult",
        extra: dict[str, Any] | None = None,
    ) -> PendingApproval:
        """Create a pending approval record and return it."""
        from ...security.tool_guard.approval import format_findings_summary

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()

        pending = PendingApproval(
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            tool_name=tool_name,
            created_at=time.time(),
            future=loop.create_future(),
            result_summary=format_findings_summary(result),
            findings_count=result.findings_count,
            extra=dict(extra or {}),
        )

        async with self._lock:
            self._pending[request_id] = pending
            self._gc_pending_locked()
            self._gc_completed_locked()

        return pending

    async def resolve_request(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> PendingApproval | None:
        """Resolve one pending approval request."""
        async with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None:
                return self._completed.get(request_id)

            pending.status = decision.value
            pending.resolved_at = time.time()
            self._completed[request_id] = pending
            self._gc_completed_locked()

        if not pending.future.done():
            pending.future.set_result(decision)

        return pending

    async def get_request(self, request_id: str) -> PendingApproval | None:
        """Get a request by id whether pending or already resolved."""
        async with self._lock:
            return self._pending.get(request_id) or self._completed.get(
                request_id,
            )

    async def get_pending_by_session(
        self,
        session_id: str,
    ) -> PendingApproval | None:
        """Return the next pending approval for *session_id* (FIFO).

        Pending approvals are consumed in creation order, so repeated
        ``/approve`` inputs walk the queue from oldest to newest.
        """
        async with self._lock:
            for pending in self._pending.values():
                if (
                    pending.session_id == session_id
                    and pending.status == "pending"
                ):
                    return pending
        return None

    async def get_all_pending_by_session(
        self,
        session_id: str,
    ) -> list[PendingApproval]:
        """Return all pending approvals for *session_id* (FIFO order)."""
        async with self._lock:
            return [
                p
                for p in self._pending.values()
                if p.session_id == session_id and p.status == "pending"
            ]

    async def cancel_stale_pending_for_tool_call(
        self,
        session_id: str,
        tool_call_id: str,
    ) -> int:
        """Cancel pending approvals whose stored tool_call id matches.

        When a tool call is replayed (e.g. after ``/approve`` triggers
        sibling replay), the guard may create a *new* pending for the
        same logical tool call.  This method cancels the old pending
        first so orphaned records don't accumulate.

        Returns the number of records cancelled.
        """
        now = time.time()
        cancelled = 0
        async with self._lock:
            to_cancel = [
                k
                for k, p in self._pending.items()
                if p.session_id == session_id
                and p.status == "pending"
                and isinstance(p.extra.get("tool_call"), dict)
                and p.extra["tool_call"].get("id") == tool_call_id
            ]
            for k in to_cancel:
                pending = self._pending.pop(k)
                if not pending.future.done():
                    pending.future.set_result(ApprovalDecision.TIMEOUT)
                pending.status = "superseded"
                pending.resolved_at = now
                self._completed[k] = pending
                cancelled += 1
        if cancelled:
            logger.info(
                "Tool guard: cancelled %d stale pending approval(s) "
                "for tool_call %s (session %s)",
                cancelled,
                tool_call_id,
                session_id[:8],
            )
        return cancelled

    async def consume_approval(
        self,
        session_id: str,
        tool_name: str,
        tool_params: dict[str, Any] | None = None,
    ) -> bool:
        """Check and consume a one-shot tool approval.

        If *tool_name* was recently approved via ``/daemon approve``
        for *session_id*, remove the completed record and return
        ``True`` so the caller can skip the guard check.

        When *tool_params* is given, the approved call's stored
        parameters are compared.  A mismatch causes the approval
        to be rejected (returns ``False``), preventing an approved
        ``rm foo.txt`` from being used to execute ``rm -rf /``.
        """
        async with self._lock:
            for key, completed in list(self._completed.items()):
                if (
                    completed.session_id == session_id
                    and completed.tool_name == tool_name
                    and completed.status == "approved"
                ):
                    if tool_params is not None:
                        approved_call = completed.extra.get(
                            "tool_call",
                            {},
                        )
                        approved_params = approved_call.get(
                            "input",
                            {},
                        )
                        if approved_params != tool_params:
                            logger.warning(
                                "Tool guard: params mismatch for "
                                "'%s' (session %s), rejecting "
                                "stale approval",
                                tool_name,
                                session_id[:8],
                            )
                            del self._completed[key]
                            return False
                    del self._completed[key]
                    return True
        return False

    # ------------------------------------------------------------------
    # Garbage collection
    # ------------------------------------------------------------------

    def _gc_pending_locked(self) -> None:
        """Evict stale pending records whose futures were never resolved.

        Caller must hold ``_lock``.
        """
        now = time.time()
        expired = [
            k
            for k, v in self._pending.items()
            if now - v.created_at > _GC_PENDING_MAX_AGE_SECONDS
        ]
        for k in expired:
            pending = self._pending.pop(k)
            if not pending.future.done():
                pending.future.set_result(ApprovalDecision.TIMEOUT)
            pending.status = "timeout"
            pending.resolved_at = now
            self._completed[k] = pending

        overflow = len(self._pending) - _GC_MAX_PENDING
        if overflow <= 0:
            return
        ordered = sorted(
            self._pending.items(),
            key=lambda item: item[1].created_at,
        )
        for key, pending in ordered[:overflow]:
            del self._pending[key]
            if not pending.future.done():
                pending.future.set_result(ApprovalDecision.TIMEOUT)
            pending.status = "timeout"
            pending.resolved_at = now
            self._completed[key] = pending

    def _gc_completed_locked(self) -> None:
        """Remove stale/overflow completed records.

        Caller must hold ``_lock``.
        """
        now = time.time()
        expired = [
            k
            for k, v in self._completed.items()
            if v.resolved_at and now - v.resolved_at > _GC_MAX_AGE_SECONDS
        ]
        for k in expired:
            del self._completed[k]

        # Still over cap: evict oldest completed records first.
        overflow = len(self._completed) - _GC_MAX_COMPLETED
        if overflow <= 0:
            return
        ordered = sorted(
            self._completed.items(),
            key=lambda item: item[1].resolved_at or item[1].created_at,
        )
        for key, _pending in ordered[:overflow]:
            del self._completed[key]


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_approval_service: ApprovalService | None = None


def get_approval_service() -> ApprovalService:
    """Return the process-wide approval service singleton."""
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service
