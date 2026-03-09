# -*- coding: utf-8 -*-
"""Base classes for the multi-channel approval framework.

Each channel that wants to support tool-guard approval must implement
an ``ApprovalHandler`` subclass and register it with the central
``ApprovalService`` via ``register_handler()``.

Adding a new channel
--------------------
1. Create ``src/copaw/app/approvals/handlers/<channel>.py``.
2. Subclass ``ApprovalHandler`` and implement the three abstract methods.
3. Register the handler in ``_auto_register_builtin_handlers`` inside
   ``service.py`` (or call ``get_approval_service().register_handler(...)``
   at startup).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import PendingApproval
    from ...security.tool_guard.models import ToolGuardResult


class ApprovalHandler(ABC):
    """Channel-specific approval behaviour.

    Each channel provides its own handler to customise how approval
    URLs are built and how the user-facing approval message is
    formatted.  The heavy lifting (pending store, futures, timeouts)
    lives in the shared ``ApprovalService``.
    """

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Return the canonical channel name (e.g. ``'console'``)."""

    @abstractmethod
    def build_action_url(
        self,
        base_url: str,
        request_id: str,
        action: str,
    ) -> str:
        """Return the full URL for an approval *action* (``approve`` /
        ``deny``).

        Parameters
        ----------
        base_url:
            Server base URL (e.g. ``http://127.0.0.1:8088``).
        request_id:
            UUID of the pending approval.
        action:
            Either ``"approve"`` or ``"deny"``.
        """

    @abstractmethod
    def format_approval_message(
        self,
        tool_name: str,
        guard_result: "ToolGuardResult",
        pending: "PendingApproval",
        findings_text: str,
    ) -> str:
        """Return a user-facing message asking for approval.

        The returned string is injected into the ``ToolResultBlock``
        output shown to the user.  It should be valid Markdown for the
        target channel.

        Parameters
        ----------
        tool_name:
            Name of the tool being guarded.
        guard_result:
            The ``ToolGuardResult`` with findings.
        pending:
            The ``PendingApproval`` record (contains URLs etc.).
        findings_text:
            Pre-formatted findings summary (from
            ``format_findings_summary``).
        """

    @property
    def needs_proactive_send(self) -> bool:
        """Whether this channel needs a proactive push via ChannelManager.

        Channels that consume agent streaming events in real time
        (e.g. the web console) can set this to ``False``.  Channels
        whose message pipeline only forwards *completed* events
        (e.g. DingTalk) should return ``True`` so that the approval
        message is sent proactively before awaiting the user decision.
        """
        return False
