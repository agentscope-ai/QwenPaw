# -*- coding: utf-8 -*-
"""Short-lived signals shared by session lifecycle consumers."""

from dataclasses import dataclass
from typing import Literal

SESSION_SAVE_SUCCEEDED_KEY = "qwenpaw.session_save_succeeded"


@dataclass
class SessionSaveResult:
    """Run-local persistence fact used to authorize history handover."""

    status: Literal["unknown", "saved", "failed"] = "unknown"


def record_session_save(ctx, succeeded: bool) -> None:
    ctx.extras[SESSION_SAVE_SUCCEEDED_KEY] = succeeded
    request_context = getattr(ctx.request, "request_context", None)
    result = (
        request_context.get("_session_save_result")
        if isinstance(request_context, dict)
        else None
    )
    if isinstance(result, SessionSaveResult):
        result.status = "saved" if succeeded else "failed"


__all__ = [
    "SESSION_SAVE_SUCCEEDED_KEY",
    "SessionSaveResult",
    "record_session_save",
]
