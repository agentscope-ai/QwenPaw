# -*- coding: utf-8 -*-
# pylint:disable=protected-access
"""Handler for /approval command.

Manages tool guard approval requests through unified control commands.
"""

from __future__ import annotations

import logging
import time

from ....app.approvals import (
    ApprovalActor,
    ApprovalIdentityMismatchError,
    ApprovalService,
    PendingApproval,
    get_approval_service,
)
from ....security.tool_guard.approval import ApprovalDecision, ApprovalScope
from ....channel_protocol.models import (
    ApprovalResolutionParams,
    ApprovalResolutionOutcome,
)
from ....channel_protocol.errors import ProtocolValidationError

from .approval_i18n import approval_text
from .base import BaseControlCommandHandler, ControlContext

logger = logging.getLogger(__name__)


class ApprovalCommandHandler(BaseControlCommandHandler):
    """Handler for /approval command.

    Features:
    - Approve/deny pending tool executions
    - List pending approvals visible to the current caller
    - Cancel specific approval requests

    Usage:
        /approval approve [request_id]  # Approve specific or queue head
        /approval deny [request_id] [reason]  # Deny with optional reason
        /approval list                  # List caller-visible approvals
        /approval cancel <request_id>   # Cancel specific request
    """

    command_name = "/approval"

    @classmethod
    def _resolution(cls, context, request_id, outcome, resolved=None):
        if not request_id:
            return
        try:
            context.approval_resolution = ApprovalResolutionParams(
                request_id=request_id,
                outcome=ApprovalResolutionOutcome(outcome),
                actor_user_id=cls._actor(context).user_id,
                tool_name=resolved.tool_name if resolved is not None else None,
            )
        except ProtocolValidationError:
            # The authorization remains committed even if display data cannot
            # fit the bounded wire result. No invented failed decision.
            logger.warning("Approval result exceeds display contract")

    @staticmethod
    def _actor(context: ControlContext) -> ApprovalActor:
        """Build the resolving identity from the current request context."""
        payload = context.payload
        if isinstance(payload, dict):
            channel = str(payload.get("channel") or "")
            root_session_id = str(payload.get("root_session_id") or "")
        else:
            channel = str(getattr(payload, "channel", "") or "")
            root_session_id = str(
                getattr(payload, "root_session_id", "") or "",
            )
        if not channel:
            channel = str(getattr(context.channel, "channel", "") or "console")
        return ApprovalActor(
            session_id=context.session_id,
            root_session_id=root_session_id or context.session_id,
            user_id=context.user_id or context.session_id,
            channel=channel,
            agent_id=context.agent_id,
        )

    @staticmethod
    def _language(context: ControlContext) -> str:
        """Resolve the reply language for this command.

        Prefers the channel's language (set from the agent config, the same
        source ``BaseChannel._acl_msg`` uses), then the agent config itself.
        """
        language = getattr(context.channel, "_language", None)
        if not isinstance(language, str) or not language:
            try:
                config = getattr(context.workspace, "config", None)
            except Exception:  # pylint: disable=broad-except
                config = None
            language = getattr(config, "language", None)
        return language if isinstance(language, str) else ""

    @classmethod
    def _text(cls, context: ControlContext, key: str, **kwargs) -> str:
        return approval_text(cls._language(context), key, **kwargs)

    @classmethod
    def _identity_denied(cls, context: ControlContext) -> str:
        return cls._text(context, "identity_denied")

    @staticmethod
    async def _get_spawn_child_queue_head(
        context: ControlContext,
        svc: ApprovalService,
    ) -> PendingApproval | None:
        """Return the oldest spawned child approval owned by this session."""
        pending_list = await svc.get_pending_by_root_session(
            context.session_id,
        )
        for pending in pending_list:
            if (
                pending.session_id != context.session_id
                and pending.agent_id == context.agent_id
                and pending.owner_agent_id == context.agent_id
                and (pending.extra or {}).get("_spawn_subagent")
            ):
                return pending
        return None

    @classmethod
    async def _get_direct_queue_head(
        cls,
        context: ControlContext,
        svc: ApprovalService,
    ) -> PendingApproval | None:
        """Return the first current-session approval visible to this caller."""
        actor = cls._actor(context)
        for pending in await svc.get_all_pending_by_session(
            context.session_id,
        ):
            if svc.actor_can_resolve(pending, actor):
                return pending
        return None

    async def handle(self, context: ControlContext) -> str:
        """Handle /approval command with various actions.

        Args:
            context: Control command context

        Returns:
            Response text (markdown formatted)
        """
        action = context.args.get("action", "approve")

        if action == "approve":
            return await self._handle_approve(context)
        elif action == "deny":
            return await self._handle_deny(context)
        elif action == "list":
            return await self._handle_list(context)
        elif action == "cancel":
            return await self._handle_cancel(context)
        else:
            return self._usage_hint(context)

    async def _handle_approve(self, context: ControlContext) -> str:
        """Approve a pending tool execution (supports cross-session)."""
        svc = get_approval_service()
        request_id = context.args.get("request_id")

        # Approval scope: `--pattern` records the generalized rule (SIMILAR),
        # `--exact` or omitted records the literal target (EXACT, default).
        scope: ApprovalScope | None = None
        if context.args.get("pattern"):
            scope = ApprovalScope.SIMILAR
        elif context.args.get("exact"):
            scope = ApprovalScope.EXACT

        # If no request_id provided, get queue head (FIFO)
        if not request_id:
            pending = await self._get_direct_queue_head(context, svc)
            if pending is None:
                pending = await self._get_spawn_child_queue_head(context, svc)
            if pending is None:
                return self._text(context, "no_pending")
            request_id = pending.request_id

        # Get pending by request_id (supports cross-session)
        pending = await svc.get_request(request_id)
        if pending is None:
            self._resolution(context, request_id, "unavailable")
            return self._text(
                context,
                "not_found",
                request_id=request_id[:16],
            )

        # Permission check: can only approve own agent's requests
        if pending.agent_id != context.agent_id:
            self._resolution(context, request_id, "forbidden")
            return self._text(
                context,
                "approve_other_agent",
                owner_agent_id=pending.agent_id,
                agent_id=context.agent_id,
            )

        # Resolve the Future to unblock waiting agent
        try:
            resolved = await svc.resolve_request(
                request_id,
                ApprovalDecision.APPROVED,
                scope=scope,
                actor=self._actor(context),
            )
        except ApprovalIdentityMismatchError:
            self._resolution(context, request_id, "forbidden")
            return self._identity_denied(context)

        if resolved is None:
            self._resolution(context, request_id, "unavailable")
            return self._text(
                context,
                "already_resolved",
                request_id=request_id[:16],
            )
        self._resolution(context, request_id, "approved", resolved)

        # Show cross-session hint if applicable
        cross_session_hint = ""
        if pending.session_id != context.session_id:
            if pending.root_session_id == pending.session_id:
                hint_key = "approve_cross_session"
            else:
                hint_key = "approve_cross_subagent"
            cross_session_hint = self._text(
                context,
                hint_key,
                session_id=pending.session_id[:8],
            )

        return self._text(
            context,
            "approved",
            tool_name=resolved.tool_name,
            request_id=request_id[:16],
            hint=cross_session_hint,
        )

    async def _handle_deny(self, context: ControlContext) -> str:
        """Deny a pending tool execution (supports cross-session)."""
        svc = get_approval_service()
        request_id = context.args.get("request_id")
        reason = context.args.get(
            "reason",
            self._text(context, "default_deny_reason"),
        )

        # If no request_id provided, get queue head
        if not request_id:
            pending = await self._get_direct_queue_head(context, svc)
            if pending is None:
                pending = await self._get_spawn_child_queue_head(context, svc)
            if pending is None:
                return self._text(context, "no_pending")
            request_id = pending.request_id

        # Get pending by request_id (supports cross-session)
        pending = await svc.get_request(request_id)
        if pending is None:
            self._resolution(context, request_id, "unavailable")
            return self._text(
                context,
                "not_found",
                request_id=request_id[:16],
            )

        # Permission check: can only deny own agent's requests
        if pending.agent_id != context.agent_id:
            self._resolution(context, request_id, "forbidden")
            return self._text(
                context,
                "deny_other_agent",
                owner_agent_id=pending.agent_id,
                agent_id=context.agent_id,
            )

        # Resolve the Future to unblock waiting agent
        try:
            resolved = await svc.resolve_request(
                request_id,
                ApprovalDecision.DENIED,
                actor=self._actor(context),
            )
        except ApprovalIdentityMismatchError:
            self._resolution(context, request_id, "forbidden")
            return self._identity_denied(context)

        if resolved is None:
            self._resolution(context, request_id, "unavailable")
            return self._text(
                context,
                "already_resolved",
                request_id=request_id[:16],
            )
        self._resolution(context, request_id, "denied", resolved)

        # Show cross-session hint if applicable
        cross_session_hint = ""
        if pending.session_id != context.session_id:
            if pending.root_session_id == pending.session_id:
                hint_key = "deny_cross_session"
            else:
                hint_key = "deny_cross_subagent"
            cross_session_hint = self._text(
                context,
                hint_key,
                session_id=pending.session_id[:8],
            )

        return self._text(
            context,
            "denied",
            tool_name=resolved.tool_name,
            request_id=request_id[:16],
            reason=reason,
            hint=cross_session_hint,
        )

    async def _handle_list(self, context: ControlContext) -> str:
        """List approvals visible under each pending request's policy.

        Supports:
            /approval list           # Current session (includes children)
            /approval list --all     # All sessions for this agent
            /approval list -a        # Same as --all (short form)
        """
        svc = get_approval_service()
        show_all = context.args.get("all", False)

        if show_all:
            # Query all pending approvals for this agent (all sessions)
            pending_list = await svc.get_all_pending_by_agent(
                context.agent_id,
            )
            header = self._text(context, "list_header_all")
        else:
            # Default: query current root session (includes children)
            pending_list = await svc.get_pending_by_root_session(
                context.session_id,
            )
            header = self._text(context, "list_header_session")

        actor = self._actor(context)
        pending_list = [
            pending
            for pending in pending_list
            if svc.actor_can_resolve(pending, actor)
        ]

        if not pending_list:
            return self._text(context, "list_empty")

        lines = [header]
        for i, pending in enumerate(pending_list, 1):
            elapsed = int(time.time() - pending.created_at)
            severity_emoji = self._severity_emoji(pending.severity)

            # Show session info for cross-session cases
            session_info = ""
            if show_all or pending.session_id != context.session_id:
                is_sub = pending.root_session_id != pending.session_id
                session_info = self._text(
                    context,
                    "list_subsession" if is_sub else "list_session",
                    session_id=pending.session_id[:8],
                )

            lines.append(
                self._text(
                    context,
                    "list_item",
                    index=i,
                    tool_name=pending.tool_name,
                    emoji=severity_emoji,
                    severity=pending.severity.upper(),
                    elapsed=elapsed,
                    session_info=session_info,
                    request_id=pending.request_id[:16],
                    findings_count=pending.findings_count,
                ),
            )

        lines.append(self._text(context, "list_footer"))

        return "\n".join(lines)

    async def _handle_cancel(self, context: ControlContext) -> str:
        """Cancel a specific approval request."""
        request_id = context.args.get("request_id")

        if not request_id:
            return self._text(context, "cancel_missing_id")

        svc = get_approval_service()
        try:
            resolved = await svc.resolve_request(
                request_id,
                ApprovalDecision.DENIED,
                actor=self._actor(context),
            )
        except ApprovalIdentityMismatchError:
            self._resolution(context, request_id, "forbidden")
            return self._identity_denied(context)

        if resolved is None:
            self._resolution(context, request_id, "unavailable")
            return self._text(
                context,
                "cancel_not_found",
                request_id=request_id[:16],
            )

        self._resolution(context, request_id, "denied", resolved)

        return self._text(
            context,
            "cancelled",
            tool_name=resolved.tool_name,
            request_id=request_id[:16],
        )

    @staticmethod
    def _severity_emoji(severity: str) -> str:
        """Get emoji for severity level."""
        severity_lower = severity.lower()
        if severity_lower in ("critical", "high"):
            return "🔴"
        elif severity_lower == "medium":
            return "🟡"
        else:  # low, info
            return "🟢"

    @classmethod
    def _usage_hint(cls, context: ControlContext) -> str:
        """Return usage hint for /approval command."""
        return cls._text(context, "usage")


class ApproveCommandHandler(BaseControlCommandHandler):
    """Handler for /approve shorthand command.

    Provides convenient shortcut: /approve [request_id]
    Equivalent to: /approval approve [request_id]
    """

    command_name = "/approve"

    def __init__(self):
        """Initialize with shared approval handler."""
        self._approval_handler = ApprovalCommandHandler()

    async def handle(self, context: ControlContext) -> str:
        """Handle /approve command by delegating to approval handler.

        Args:
            context: Control command context

        Returns:
            Response text from approval handler
        """
        raw_args = context.args.get("_raw_args", "").strip()
        parts = raw_args.split()

        new_args = {"action": "approve"}

        # First non-flag token is the request_id; --exact/--pattern set scope.
        for part in parts:
            if part == "--exact":
                new_args["exact"] = True
            elif part == "--pattern":
                new_args["pattern"] = True
            elif "request_id" not in new_args:
                new_args["request_id"] = part

        context.args = new_args

        # Delegate to approval handler
        return await self._approval_handler._handle_approve(context)


class DenyCommandHandler(BaseControlCommandHandler):
    """Handler for /deny shorthand command.

    Provides convenient shortcut: /deny [request_id] [reason]
    Equivalent to: /approval deny [request_id] [reason]
    """

    command_name = "/deny"

    def __init__(self):
        """Initialize with shared approval handler."""
        self._approval_handler = ApprovalCommandHandler()

    async def handle(self, context: ControlContext) -> str:
        """Handle /deny command by delegating to approval handler.

        Args:
            context: Control command context

        Returns:
            Response text from approval handler
        """
        # Parse args for /deny command
        # Format: /deny [request_id] [reason...]
        raw_args = context.args.get("_raw_args", "").strip()
        parts = raw_args.split(maxsplit=1)

        new_args = {"action": "deny"}

        if parts:
            # First part is request_id (optional)
            new_args["request_id"] = parts[0]

        if len(parts) > 1:
            # Remaining parts are reason
            new_args["reason"] = parts[1]

        context.args = new_args

        # Delegate to approval handler
        return await self._approval_handler._handle_deny(context)
