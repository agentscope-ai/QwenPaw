# -*- coding: utf-8 -*-
"""Normalize Driver identity without interpreting platform metadata."""

from .errors import ProtocolValidationError
from .models import InboundEvent


def normalize_inbound_event(event: InboundEvent) -> dict:
    if not isinstance(event, InboundEvent):
        raise ProtocolValidationError("InboundEvent required")
    meta = dict(event.metadata)
    unknown = event.actor_unknown
    if (
        type(unknown) is not bool
        or unknown
        and (
            event.sender_id != ""
            or event.acl_sender_id != ""
            or meta.get("user_id") != ""
        )
    ):
        raise ProtocolValidationError("Invalid anonymous actor")
    if not unknown and any(
        not isinstance(value, str) or not value
        for value in (event.sender_id, event.acl_sender_id)
    ):
        raise ProtocolValidationError("Standard inbound actor missing")
    if unknown and event.event_kind not in {"message", "message.query"}:
        raise ProtocolValidationError(
            "Anonymous actor requires an ordinary message",
        )
    for key in ("session_id", "user_id", "debounce_key"):
        if key == "user_id" and unknown:
            continue
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            raise ProtocolValidationError(
                "Standard inbound identity missing: " + key,
            )
    meta.update(
        is_group=event.conversation["type"] == "group",
        response_handle=event.response_handle,
    )
    meta.pop("actor_unknown", None)
    if unknown:
        meta["actor_unknown"] = True
    payload = {
        "channel_id": event.channel_key,
        "sender_id": event.sender_id,
        "acl_sender_id": event.acl_sender_id,
        "user_id": meta["user_id"],
        "session_id": meta["session_id"],
        "content_parts": list(event.content_parts),
        "meta": meta,
    }
    if unknown:
        payload["actor_unknown"] = True
    return payload
