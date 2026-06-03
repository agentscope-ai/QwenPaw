# -*- coding: utf-8 -*-
"""Hook ApprovalService so console pending approvals drive the desktop pet."""

from __future__ import annotations

import logging
from typing import Any

from emitter import schedule_emit_pet_event

logger = logging.getLogger("qwenpaw.pet_desktop")

_PATCHED = False
_ORIG_CREATE_PENDING: Any = None
_ORIG_RESOLVE_REQUEST: Any = None
_ORIG_CANCEL_ALL: Any = None


def patch_approval_service() -> None:
    """Wrap ApprovalService lifecycle methods.

    Same backing store as ``/console/push-messages``. Emits use
    ``schedule_emit_pet_event`` so sync ``httpx`` never blocks the
    asyncio event loop while a tool call awaits user approval.
    """
    global _PATCHED, _ORIG_CREATE_PENDING
    global _ORIG_RESOLVE_REQUEST, _ORIG_CANCEL_ALL

    if _PATCHED:
        return

    from qwenpaw.app.approvals.service import ApprovalService
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    _ORIG_CREATE_PENDING = ApprovalService.create_pending
    _ORIG_RESOLVE_REQUEST = ApprovalService.resolve_request
    _ORIG_CANCEL_ALL = ApprovalService.cancel_all_pending_by_root_session

    async def create_pending_wrapped(self, **kwargs: Any):
        pending = await _ORIG_CREATE_PENDING(self, **kwargs)
        try:
            tool_label = str(pending.tool_name or "tool")[:36]
            schedule_emit_pet_event(
                "approval.pending",
                # Second line keeps the tool name visible; a single long
                # "Approval required: <tool>" line is clipped by the narrow
                # pet bubble (~95px wide at default scale).
                text=f"Approval required\n{tool_label}",
                session_id=pending.session_id,
                agent_id=pending.agent_id,
                channel=pending.channel,
                tool_name=pending.tool_name,
            )
            logger.info(
                "QwenPaw Pet: scheduled approval.pending tool=%s",
                pending.tool_name,
            )
        except Exception:
            logger.warning(
                "QwenPaw Pet: schedule approval.pending failed",
                exc_info=True,
            )
        return pending

    async def resolve_request_wrapped(self, request_id: str, decision: Any):
        resolved = await _ORIG_RESOLVE_REQUEST(self, request_id, decision)
        if resolved is None:
            return None
        try:
            if decision == ApprovalDecision.APPROVED:
                schedule_emit_pet_event(
                    "approval.approved",
                    text=(
                        "Approved\n"
                        f"{str(resolved.tool_name or 'tool')[:36]}"
                    ),
                    session_id=resolved.session_id,
                    agent_id=resolved.agent_id,
                    decision=decision.value,
                )
            elif decision == ApprovalDecision.DENIED:
                schedule_emit_pet_event(
                    "approval.denied",
                    text=(
                        "Denied\n" f"{str(resolved.tool_name or 'tool')[:36]}"
                    ),
                    duration_ms=1200,
                    session_id=resolved.session_id,
                    agent_id=resolved.agent_id,
                    decision=decision.value,
                )
            else:
                schedule_emit_pet_event(
                    "approval.timed_out",
                    text="Approval timed out",
                    duration_ms=1500,
                    session_id=resolved.session_id,
                    agent_id=resolved.agent_id,
                    decision=decision.value,
                )
            logger.info(
                "QwenPaw Pet: scheduled approval decision=%s tool=%s",
                getattr(decision, "value", decision),
                resolved.tool_name,
            )
        except Exception:
            logger.warning(
                "QwenPaw Pet: schedule approval.resolved failed",
                exc_info=True,
            )
        return resolved

    async def cancel_all_wrapped(self, root_session_id: str) -> int:
        n = await _ORIG_CANCEL_ALL(self, root_session_id)
        if n > 0:
            try:
                schedule_emit_pet_event(
                    "approval.bulk_cancel",
                    text="Approvals cancelled",
                    duration_ms=900,
                    session_id=root_session_id,
                )
            except Exception:
                logger.warning(
                    "QwenPaw Pet: schedule approval.bulk_cancel failed",
                    exc_info=True,
                )
        return n

    ApprovalService.create_pending = create_pending_wrapped
    ApprovalService.resolve_request = resolve_request_wrapped
    ApprovalService.cancel_all_pending_by_root_session = cancel_all_wrapped
    _PATCHED = True
    logger.info(
        "QwenPaw Pet: patched ApprovalService "
        "(create_pending / resolve / cancel)",
    )


def restore_approval_service() -> None:
    """Restore ApprovalService class methods."""
    global _PATCHED

    if not _PATCHED:
        return

    from qwenpaw.app.approvals.service import ApprovalService

    ApprovalService.create_pending = _ORIG_CREATE_PENDING
    ApprovalService.resolve_request = _ORIG_RESOLVE_REQUEST
    ApprovalService.cancel_all_pending_by_root_session = _ORIG_CANCEL_ALL
    _PATCHED = False
    logger.info("QwenPaw Pet: restored ApprovalService")
