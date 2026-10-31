# -*- coding: utf-8 -*-
"""Versioned, credential-free proactive reply targets."""

import json
from .errors import ProtocolValidationError

_PREFIX = "qwenpaw-target:v1:"


def encode_reply_target(*, user_id: str, session_id: str) -> str:
    if (
        not isinstance(user_id, str)
        or not isinstance(session_id, str)
        or not (user_id or session_id)
    ):
        raise ProtocolValidationError("Invalid reply target identity")
    return _PREFIX + json.dumps(
        {"user_id": user_id, "session_id": session_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_reply_target(value: str) -> dict | None:
    if not isinstance(value, str):
        raise ProtocolValidationError("Invalid reply target")
    if not value.startswith("qwenpaw-target:"):
        return None
    if not value.startswith(_PREFIX):
        raise ProtocolValidationError("Unsupported reply target version")
    try:
        data = json.loads(value[len(_PREFIX) :])
    except (ValueError, TypeError) as exc:
        raise ProtocolValidationError("Malformed reply target") from exc
    if not isinstance(data, dict) or set(data) != {"user_id", "session_id"}:
        raise ProtocolValidationError("Invalid reply target fields")
    encode_reply_target(**data)
    return data
