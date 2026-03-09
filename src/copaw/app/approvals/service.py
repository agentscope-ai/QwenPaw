# -*- coding: utf-8 -*-
"""Multi-channel approval service for sensitive tool execution.

The ``ApprovalService`` is the single central store for pending /
completed approval records.  Channel-specific behaviour (URL
construction, message formatting) is delegated to ``ApprovalHandler``
subclasses registered via ``register_handler()``.

Backward compatibility
----------------------
``ConsoleApprovalService`` and ``get_console_approval_service`` are
kept as thin aliases so existing imports continue to work.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...security.tool_guard.approval import (
    ApprovalDecision,
    format_findings_summary,
)
from .base import ApprovalHandler

if TYPE_CHECKING:
    from ...security.tool_guard.models import ToolGuardResult

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://127.0.0.1:8088"
_DEFAULT_TIMEOUT_SECONDS = 300.0


# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------


@dataclass
class PendingApproval:
    """In-memory record for one pending approval (channel-agnostic)."""

    request_id: str
    session_id: str
    user_id: str
    channel: str
    tool_name: str
    created_at: float
    approve_url: str
    deny_url: str
    future: asyncio.Future[ApprovalDecision]
    status: str = "pending"
    resolved_at: float | None = None
    result_summary: str = ""
    findings_count: int = 0
    extra: dict = field(default_factory=dict)


# ------------------------------------------------------------------
# Service
# ------------------------------------------------------------------


class ApprovalService:
    """Central approval service with pluggable per-channel handlers.

    Usage::

        svc = get_approval_service()
        svc.register_handler(ConsoleApprovalHandler())
        svc.register_handler(DingTalkApprovalHandler())

        if svc.supports_channel("dingtalk"):
            pending = await svc.create_pending(channel="dingtalk", ...)
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[str, PendingApproval] = {}
        self._completed: dict[str, PendingApproval] = {}
        self._handlers: dict[str, ApprovalHandler] = {}
        self._channel_manager: Any | None = None

    def set_channel_manager(self, channel_manager: Any) -> None:
        """Inject the ``ChannelManager`` for proactive notifications."""
        self._channel_manager = channel_manager

    # ------------------------------------------------------------------
    # Handler registry
    # ------------------------------------------------------------------

    def register_handler(self, handler: ApprovalHandler) -> None:
        """Register a channel-specific ``ApprovalHandler``."""
        self._handlers[handler.channel_name] = handler
        logger.info(
            "Approval handler registered for channel: %s",
            handler.channel_name,
        )

    def unregister_handler(self, channel: str) -> bool:
        """Remove a handler.  Returns ``True`` if it existed."""
        return self._handlers.pop(channel, None) is not None

    def get_handler(self, channel: str) -> ApprovalHandler | None:
        """Return the handler for *channel*, or ``None``."""
        return self._handlers.get(channel)

    def supports_channel(self, channel: str) -> bool:
        """``True`` when *channel* has a registered handler."""
        return channel in self._handlers

    @property
    def registered_channels(self) -> list[str]:
        """Return a sorted list of registered channel names."""
        return sorted(self._handlers)

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _base_url() -> str:
        return os.getenv(
            "COPAW_TOOL_GUARD_APPROVAL_BASE_URL",
            os.getenv("COPAW_BASE_URL", _DEFAULT_BASE_URL),
        ).rstrip("/")

    @staticmethod
    def _timeout_seconds() -> float:
        raw = os.getenv("COPAW_TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS")
        if raw is None:
            return _DEFAULT_TIMEOUT_SECONDS
        try:
            return max(float(raw), 1.0)
        except (TypeError, ValueError):
            return _DEFAULT_TIMEOUT_SECONDS

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
        extra: dict | None = None,
    ) -> PendingApproval:
        """Create a pending approval record and return it.

        The caller is responsible for presenting the approve/deny URLs
        to the user (e.g. via a chat message).

        Raises ``ValueError`` if no handler is registered for *channel*.
        """
        handler = self._handlers.get(channel)
        if handler is None:
            raise ValueError(
                f"No approval handler registered for channel '{channel}'. "
                f"Registered: {self.registered_channels}",
            )

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        base_url = self._base_url()

        approve_url = handler.build_action_url(base_url, request_id, "approve")
        deny_url = handler.build_action_url(base_url, request_id, "deny")

        pending = PendingApproval(
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            tool_name=tool_name,
            created_at=time.time(),
            approve_url=approve_url,
            deny_url=deny_url,
            future=loop.create_future(),
            result_summary=format_findings_summary(result),
            findings_count=result.findings_count,
            extra=dict(extra or {}),
        )

        async with self._lock:
            self._pending[request_id] = pending

        return pending

    async def await_decision(
        self,
        pending: PendingApproval,
        *,
        notification_text: str | None = None,
    ) -> ApprovalDecision:
        """Await the user decision (with configurable timeout).

        Args:
            pending: The pending approval record.
            notification_text: Pre-formatted approval message.  When
                provided **and** the channel handler declares
                ``needs_proactive_send``, the text is pushed to the
                user via ``ChannelManager.send_text`` before awaiting
                the decision.  This ensures channels whose message
                pipeline only forwards *completed* events (e.g.
                DingTalk) still display the approval prompt.
        """
        # Proactive push for channels that need it
        await self._maybe_send_notification(pending, notification_text)

        try:
            decision = await asyncio.wait_for(
                pending.future,
                timeout=self._timeout_seconds(),
            )
        except asyncio.TimeoutError:
            decision = ApprovalDecision.TIMEOUT
            await self.resolve_request(pending.request_id, decision)

        return decision

    async def _maybe_send_notification(
        self,
        pending: PendingApproval,
        notification_text: str | None,
    ) -> None:
        """Push the approval message proactively if the channel requires it."""
        if notification_text is None:
            return
        handler = self._handlers.get(pending.channel)
        if handler is None or not handler.needs_proactive_send:
            return
        if self._channel_manager is None:
            logger.debug(
                "Skipping proactive approval notification: "
                "no channel_manager set on ApprovalService",
            )
            return
        try:
            await self._channel_manager.send_text(
                channel=pending.channel,
                user_id=pending.user_id,
                session_id=pending.session_id,
                text=notification_text,
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "Failed to send proactive approval notification "
                "to channel '%s'",
                pending.channel,
                exc_info=True,
            )

    async def resolve_request(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> PendingApproval | None:
        """Resolve one pending approval request."""
        async with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None:
                pending = self._completed.get(request_id)
                return pending  # already resolved or unknown

            pending.status = decision.value
            pending.resolved_at = time.time()
            self._completed[request_id] = pending

        if not pending.future.done():
            pending.future.set_result(decision)

        return pending

    async def get_request(self, request_id: str) -> PendingApproval | None:
        """Get a request by id whether pending or already resolved."""
        async with self._lock:
            return self._pending.get(request_id) or self._completed.get(
                request_id,
            )

    def format_approval_message(
        self,
        *,
        channel: str,
        tool_name: str,
        guard_result: "ToolGuardResult",
        pending: PendingApproval,
    ) -> str:
        """Format the approval message using the channel-specific handler.

        Falls back to a plain-text message if no handler is registered.
        """
        findings_text = format_findings_summary(guard_result)
        handler = self._handlers.get(channel)
        if handler is not None:
            return handler.format_approval_message(
                tool_name,
                guard_result,
                pending,
                findings_text,
            )
        # Fallback (should not happen in normal flow)
        return (
            f"⚠️ Sensitive tool requires approval\n\n"
            f"- Tool: {tool_name}\n"
            f"- Max severity: {guard_result.max_severity.value}\n"
            f"- Findings: {guard_result.findings_count}\n\n"
            f"{findings_text}\n\n"
            f"Approve: {pending.approve_url}\n"
            f"Deny: {pending.deny_url}"
        )


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_approval_service: ApprovalService | None = None


def _auto_register_builtin_handlers(service: ApprovalService) -> None:
    """Register built-in channel handlers on first creation."""
    from .handlers.console import ConsoleApprovalHandler
    from .handlers.dingtalk import DingTalkApprovalHandler

    service.register_handler(ConsoleApprovalHandler())
    service.register_handler(DingTalkApprovalHandler())


def get_approval_service() -> ApprovalService:
    """Return the process-wide approval service singleton.

    Built-in handlers (console, dingtalk) are registered automatically
    on first call.
    """
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
        _auto_register_builtin_handlers(_approval_service)
    return _approval_service


# ------------------------------------------------------------------
# Backward-compatible aliases
# ------------------------------------------------------------------

ConsoleApprovalService = ApprovalService
"""Deprecated alias — use ``ApprovalService`` instead."""


def get_console_approval_service() -> ApprovalService:
    """Deprecated — use ``get_approval_service()`` instead."""
    return get_approval_service()
