"""AgentScope Runtime events emitted by Chat-owned input paths."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ...constant import QWENPAW_RECEIVED_AT_KEY


def _serialize_content_part(part: Any) -> dict[str, Any]:
    if isinstance(part, BaseModel):
        payload = part.model_dump(mode="json", exclude_none=True)
    elif isinstance(part, dict):
        payload = dict(part)
    elif isinstance(part, str):
        payload = {"type": "text", "text": part}
    else:
        raise TypeError(
            f"unsupported user content part: {type(part).__name__}"
        )
    payload["status"] = "completed"
    return payload


def user_message_sse(
    content_parts: tuple[Any, ...],
    event_id: str,
    *,
    metadata: dict[str, Any],
) -> str:
    """Build the canonical stream event for an accepted external user input."""
    payload = {
        "id": event_id,
        "object": "message",
        "role": "user",
        "type": "message",
        "status": "completed",
        "created_at": datetime.fromisoformat(
            metadata[QWENPAW_RECEIVED_AT_KEY]
        ).timestamp(),
        "content": [_serialize_content_part(part) for part in content_parts],
        "metadata": metadata,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


__all__ = ["user_message_sse"]
