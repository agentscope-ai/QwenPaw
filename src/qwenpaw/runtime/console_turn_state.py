# -*- coding: utf-8 -*-
"""Durable console turn status and explicit last-turn regeneration."""

from __future__ import annotations

from typing import Any
from pathlib import Path
from urllib.parse import unquote, urlparse

CLIENT_ID = "qwenpaw_client_message_id"
TURN_STATE = "qwenpaw_turn_state"
REGENERATE_FROM = "qwenpaw_regenerate_from"


def repair_invalid_history_images(data: dict) -> None:
    """Quarantine undecodable local image blocks, without deleting files.

    Old failed turns may already contain damaged uploads. Keeping such blocks
    in model context makes every later request fail before it can respond.
    Preserve their source metadata and replace only the unusable model block
    with an explicit notice. Remote images are never fetched here.
    """
    from PIL import Image

    for message in (data.get("state") or {}).get("context") or []:
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            continue
        for index, block in enumerate(content):
            source = block.get("source") or {}
            if not str(source.get("media_type", "")).startswith("image/"):
                continue
            parsed = urlparse(str(source.get("url", "")))
            if parsed.scheme != "file":
                continue
            path = Path(unquote(parsed.path))
            if not path.is_file():
                continue
            try:
                with Image.open(path) as image:
                    image.verify()
            except (OSError, SyntaxError, ValueError):
                metadata = message.get("metadata") or {}
                message["metadata"] = metadata
                metadata.setdefault("qwenpaw_invalid_images", []).append(block)
                content[index] = {
                    "type": "text",
                    "text": (
                        "[An earlier image attachment is damaged. "
                        "Ask the user to upload it again.]"
                    ),
                }


def stamp_console_turn(
    data: dict,
    request: Any,
    status: str,
    error: BaseException | None = None,
) -> None:
    """Keep terminal status with its user turn, including empty responses."""
    if getattr(request, "channel", None) != "console":
        return
    inputs = getattr(request, "input", None) or []
    metadata = getattr(inputs[0], "metadata", None) if inputs else None
    client_id = (metadata or {}).get(CLIENT_ID)
    if not client_id:
        return
    context = (data.get("state") or {}).get("context") or []
    for message in reversed(context):
        meta = message.get("metadata") or {}
        if message.get("role") == "user" and meta.get(CLIENT_ID) == client_id:
            terminal = {"status": status}
            if status == "failed" and error is not None:
                terminal["error"] = {
                    "code": type(error).__name__,
                    "message": str(error),
                }
            message["metadata"] = {**meta, TURN_STATE: terminal}
            return


def prepare_console_regeneration(data: dict, request: Any) -> None:
    """Rewind only the explicitly requested last user turn, in memory.

    Nothing is written until the replacement succeeds. Never infer a target
    from matching text: identical consecutive user messages are legitimate.
    """
    target = (getattr(request, "request_context", None) or {}).get(
        REGENERATE_FROM,
    )
    if not target:
        return
    if getattr(request, "channel", None) != "console":
        raise ValueError("Regeneration is only supported for console chats")
    state = data.get("state") or {}
    context = state.get("context") or []
    for index in range(len(context) - 1, -1, -1):
        message = context[index]
        if message.get("role") != "user":
            continue
        matches = (
            message.get("id") == target.get("message_id")
            if isinstance(target, dict)
            else (message.get("metadata") or {}).get(CLIENT_ID) == target
        )
        if not matches:
            raise ValueError(
                "The regeneration target is no longer the last turn",
            )
        state["context"] = context[:index]
        # Scroll bookkeeping is derived from the context. Rebuild it rather
        # than retaining removed response IDs or a summary of that response.
        data.pop("scroll", None)
        return
    raise ValueError("The regeneration target was not found")
