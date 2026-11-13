# -*- coding: utf-8 -*-
"""Strict wire-level ownership identity helpers."""

from __future__ import annotations

from typing import Any, Mapping

from ..errors import BrowserError, ErrorCause, ErrorCategory

OwnerKey = tuple[str, str]


def require_owner(params: Mapping[str, Any]) -> OwnerKey:
    """Return a complete owner or raise a teaching error for malformed wire."""
    workspace_id = str(params.get("workspace_id") or "")
    session_id = str(params.get("session_id") or "")
    if not workspace_id or not session_id:
        raise BrowserError(
            category=ErrorCategory.FATAL,
            cause=ErrorCause.API_MISUSE,
            suggested_action="fatal",
            reason="request is missing owner identity",
            detail=(
                f"workspace_id={workspace_id!r} " f"session_id={session_id!r}"
            ),
        )
    return workspace_id, session_id
