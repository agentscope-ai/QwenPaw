# -*- coding: utf-8 -*-
"""Simple in-memory store for pending inline-diff approvals.

Independent of ToolGuardResult / tool-guard engine; used only by
CodingModeMixin and the /coding-mode/diff-approval route.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_GC_MAX_AGE = 7200.0  # 2 hours
_GC_MAX_ITEMS = 200


@dataclass
class PendingDiffApproval:
    """One pending diff approval record."""

    request_id: str
    session_id: str
    tool_name: str
    file_path: str
    diff: str
    old_content: str
    new_content: str
    created_at: float
    future: "asyncio.Future[str]"  # resolves to "approve" | "reject"
    extra: dict[str, Any] = field(default_factory=dict)


class DiffApprovalService:
    """Singleton store for pending diff approvals."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[str, PendingDiffApproval] = {}

    async def create_pending(
        self,
        *,
        request_id: str,
        session_id: str,
        tool_name: str,
        file_path: str,
        diff: str,
        old_content: str,
        new_content: str,
        extra: dict[str, Any] | None = None,
    ) -> PendingDiffApproval:
        """Register a new pending diff approval and return it.

        Args:
            request_id: Unique approval identifier (UUID).
            session_id: Session that owns this approval.
            tool_name: Write tool being intercepted.
            file_path: File being modified.
            diff: Unified diff string.
            old_content: Current file content.
            new_content: Proposed new file content.
            extra: Additional metadata.

        Returns:
            The created ``PendingDiffApproval`` record.
        """
        loop = asyncio.get_running_loop()
        record = PendingDiffApproval(
            request_id=request_id,
            session_id=session_id,
            tool_name=tool_name,
            file_path=file_path,
            diff=diff,
            old_content=old_content,
            new_content=new_content,
            created_at=time.time(),
            future=loop.create_future(),
            extra=dict(extra or {}),
        )
        async with self._lock:
            self._pending[request_id] = record
            self._gc_locked()
        logger.debug(
            "DiffApproval pending: id=%s tool=%s file=%s",
            request_id[:8],
            tool_name,
            file_path,
        )
        return record

    async def resolve(
        self,
        request_id: str,
        decision: str,
    ) -> bool:
        """Resolve a pending diff approval.

        Args:
            request_id: Approval identifier.
            decision: ``"approve"`` or ``"reject"``.

        Returns:
            ``True`` when the record was found and resolved,
            ``False`` when not found or already resolved.
        """
        async with self._lock:
            record = self._pending.pop(request_id, None)
        if record is None:
            return False
        if not record.future.done():
            record.future.set_result(decision)
        logger.info(
            "DiffApproval resolved: id=%s decision=%s",
            request_id[:8],
            decision,
        )
        return True

    def _gc_locked(self) -> None:
        """Remove stale entries (called under lock)."""
        now = time.time()
        stale = [
            k
            for k, v in self._pending.items()
            if now - v.created_at > _GC_MAX_AGE
        ]
        for k in stale:
            self._pending.pop(k, None)
        if len(self._pending) > _GC_MAX_ITEMS:
            oldest = sorted(
                self._pending.keys(),
                key=lambda k: self._pending[k].created_at,
            )
            for k in oldest[: len(self._pending) - _GC_MAX_ITEMS]:
                self._pending.pop(k, None)


_service: DiffApprovalService | None = None


def get_diff_approval_service() -> DiffApprovalService:
    """Return the global diff approval service (lazy-init singleton).

    Returns:
        Global ``DiffApprovalService`` instance.
    """
    global _service  # pylint: disable=global-statement
    if _service is None:
        _service = DiffApprovalService()
    return _service
