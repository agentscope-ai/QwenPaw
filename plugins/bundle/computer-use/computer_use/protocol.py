# -*- coding: utf-8 -*-
"""Protocol models shared by the Computer Use client and transports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from qwenpaw.app.computer_use import COMPUTER_USE_PROTOCOL_VERSION

PROTOCOL_VERSION = COMPUTER_USE_PROTOCOL_VERSION

# Every method name this adapter may put on the wire. The helper matches on
# these, so the two sides have to agree exactly -- a name only one of them
# knows
# fails as an unsupported operation at run time, with nothing to catch it
# earlier. A contract test compares this set against the helper's dispatch.
#
# Tool-level action names are a separate vocabulary: several of them map onto
# one
# method here (a double click and a right click are both ``click``), and some
# never reach the helper at all.
NATIVE_METHODS = frozenset(
    {
        "click",
        "close_window",
        "drag",
        "end_turn",
        "hello",
        "invoke_element",
        "launch_app",
        "list_apps",
        "list_windows",
        "observe_window",
        "press_key",
        "scroll",
        "sequence",
        "set_value",
        "type_text",
    },
)


class ComputerUseProtocolError(RuntimeError):
    """A stable native protocol failure with an actionable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NativeRequest:
    """One client-to-native request with trusted execution metadata."""

    method: str
    params: Mapping[str, Any]
    session_id: str
    turn_id: str
    deadline_ms: int
    request_id: str = ""

    def to_message(self) -> dict[str, Any]:
        """Serialize the request at the framing-neutral protocol boundary.

        Every request passes through here, so it is where the declared method
        vocabulary is enforced. Without that the constant would only be
        documentation, and a typo would travel to the helper to come back as an
        unsupported operation.
        """
        if self.method not in NATIVE_METHODS:
            raise ComputerUseProtocolError(
                "invalid_request",
                f"{self.method!r} is not a Computer Use protocol method.",
            )
        return {
            "request_id": self.request_id or uuid.uuid4().hex,
            "method": self.method,
            "params": dict(self.params),
            "meta": {
                "session_id": self.session_id,
                "turn_id": self.turn_id,
                "deadline_ms": self.deadline_ms,
            },
            "protocol_version": PROTOCOL_VERSION,
        }


def parse_response(message: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a native response or raise a stable protocol error."""
    if bool(message.get("ok")):
        result = message.get("result", {})
        return result if isinstance(result, dict) else {"value": result}
    error = message.get("error", {})
    if isinstance(error, Mapping):
        code = str(error.get("code") or "native_error")
        detail = str(error.get("message") or code)
    else:
        code = "native_error"
        detail = str(error or code)
    raise ComputerUseProtocolError(code, detail)


def approval_reply(
    request_id: str,
    *,
    allowed: bool,
    source: str,
) -> dict[str, Any]:
    """Build the one-time reply for a native App approval request."""
    return {
        "request_id": request_id,
        "result": {
            "decision": "allow" if allowed else "deny",
            "source": source,
        },
        "protocol_version": PROTOCOL_VERSION,
    }
