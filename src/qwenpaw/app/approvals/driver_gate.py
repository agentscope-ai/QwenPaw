# -*- coding: utf-8 -*-
"""QwenPaw application approval gate for Driver policy."""

from __future__ import annotations

from ...constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
from ...drivers.errors import (
    ApprovalRequiredError,
    DriverPermissionDeniedError,
)
from ...drivers.policy import DriverInvocationContext
from ...security.tool_guard.approval import ApprovalDecision

from .models import ApprovalRequestSummary


class QwenPawDriverApprovalGate:
    """Bridge Driver policy approval requests into QwenPaw approval service."""

    async def request_approval(
        self,
        context: DriverInvocationContext,
    ) -> None:
        # Reuse QwenPaw's approval Future flow: this coroutine pauses until
        # the console or command approval endpoint resolves the pending
        # request.
        ctx = context.request_context
        session_id = str(ctx.get("session_id") or "")
        driver_label = f"driver:{context.protocol}:{context.driver_name}"
        driver_ref = f"{context.protocol}:{context.driver_name}"
        target_name = str(context.target.name or "")
        has_tool_target = context.target.kind == "tool" and bool(
            target_name,
        )
        display_tool_name = target_name if has_tool_target else driver_label
        display_tool_source = driver_ref
        if has_tool_target:
            result_summary = (
                f"Tool '{display_tool_name}' from '{display_tool_source}' "
                f"requires approval for {context.operation}."
            )
        else:
            result_summary = (
                f"Driver '{driver_ref}' requires approval for "
                f"{context.operation}."
            )
        if not session_id:
            raise ApprovalRequiredError(
                "Driver approval required but request_context.session_id "
                f"is missing: {context.subject} -> {context.driver_name}",
            )

        from . import get_approval_service

        svc = get_approval_service()
        tool_call_id = str(ctx.get("tool_call_id") or "")
        if tool_call_id:
            await svc.cancel_stale_pending_for_tool_call(
                session_id,
                tool_call_id,
            )

        pending = await svc.create_pending_summary(
            session_id=session_id,
            root_session_id=str(ctx.get("root_session_id") or session_id),
            owner_agent_id=str(
                ctx.get("root_agent_id") or ctx.get("agent_id") or "",
            ),
            user_id=str(ctx.get("user_id") or ""),
            channel=str(ctx.get("channel") or ""),
            agent_id=str(ctx.get("agent_id") or "unknown"),
            summary=ApprovalRequestSummary(
                source_type="driver_policy",
                name=driver_label,
                severity="medium",
                findings_count=1,
                result_summary=result_summary,
            ),
            timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
            extra={
                "display": {
                    "tool_name": display_tool_name,
                    "tool_source": display_tool_source,
                },
                "driver": {
                    "name": context.driver_name,
                    "protocol": context.protocol,
                    "operation": context.operation,
                    "subject": context.subject,
                    "extras": context.extras,
                },
                "tool_call": {
                    "id": tool_call_id,
                    "name": driver_label,
                    "input": context.extras,
                },
            },
        )
        decision = await svc.wait_for_approval(
            pending.request_id,
            TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
        )
        if decision == ApprovalDecision.APPROVED:
            return
        raise DriverPermissionDeniedError(
            context.driver_name,
            context.subject,
            context.operation,
            reason=f"User approval decision was {decision.value}.",
        )
