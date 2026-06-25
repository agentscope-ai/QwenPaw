# -*- coding: utf-8 -*-
"""Legacy session deserialization for agentscope 1.x payloads.

The single load-bearing export is :func:`msg_from_dict`, used via the
``Msg.from_dict`` polyfill installed in ``_compat/__init__.py``.  It
rehydrates session JSON written by 1.x — translating the old field
shape (``timestamp`` → ``created_at``) and the old per-modality block
types (``image`` / ``audio`` / ``video`` → ``DataBlock``;
``tool_use`` → ``ToolCallBlock``) on the fly.  See the in-tree caller
``agents/command_handler.py:_load_history``.

Once all on-disk sessions have been re-saved in the 2.0 format this
whole module can be deleted together with the polyfill.
"""
from __future__ import annotations

import json
import mimetypes
from typing import Any, Mapping

from agentscope.message import (
    Base64Source,
    DataBlock,
    ToolCallBlock,
    URLSource,
)


_MODALITY_DEFAULT_MIME = {
    "image": "image/*",
    "audio": "audio/*",
    "video": "video/*",
}


def _coerce_source(
    source: Any,
    modality: str,
) -> Base64Source | URLSource:
    """Normalize the legacy ``source`` dict to a 2.0 source model.

    The old blocks accepted dicts like ``{"type": "url", "url": ...}`` or
    ``{"type": "base64", "data": ..., "media_type": ...}``.  In 2.0
    ``media_type`` is required, so we infer it from the URL extension /
    modality when the caller omitted it.
    """
    if isinstance(source, (Base64Source, URLSource)):
        return source
    if not isinstance(source, Mapping):
        raise TypeError(
            f"Unsupported source for media block: {type(source)!r}",
        )

    src_type = source.get("type")
    if src_type == "url":
        url = source["url"]
        media_type = source.get("media_type")
        if not media_type:
            guessed, _ = mimetypes.guess_type(str(url))
            media_type = guessed or _MODALITY_DEFAULT_MIME.get(
                modality,
                "application/octet-stream",
            )
        return URLSource(type="url", url=url, media_type=media_type)
    if src_type == "base64":
        media_type = source.get("media_type") or _MODALITY_DEFAULT_MIME.get(
            modality,
            "application/octet-stream",
        )
        return Base64Source(
            type="base64",
            data=source["data"],
            media_type=media_type,
        )
    raise ValueError(f"Unknown source type: {src_type!r}")


# ---------------------------------------------------------------------------
# Msg deserialization shim.
# Sessions saved by 1.x stored messages as ``{id, name, role, content,
# metadata, timestamp}``; 2.0 uses ``{name, content, role, id, metadata,
# created_at, finished_at, usage}``.  ``Msg.from_dict`` is gone in 2.0,
# so we provide a translator that accepts either shape.
# ---------------------------------------------------------------------------


# pylint: disable=too-many-return-statements
def _coerce_block(block: Any) -> Any:
    """Map a stored content block dict to a 2.0 block instance.

    Old per-modality blocks (``image`` / ``audio`` / ``video``) are
    rewritten to the unified ``DataBlock``; legacy ``tool_use`` blocks
    are rewritten to ``ToolCallBlock`` (with ``input`` JSON-encoded if
    needed).  Anything else is returned as-is so the union discriminator
    on ``Msg.content`` can handle it.
    """
    if not isinstance(block, Mapping):
        return block
    btype = block.get("type")
    if btype in ("image", "audio", "video"):
        source = block.get("source")
        if source is None:
            return block
        return DataBlock(
            source=_coerce_source(source, btype),
            name=block.get("name"),
        )
    if btype == "tool_use":
        raw = block.get("input") or block.get("raw_input") or "{}"
        if isinstance(raw, str):
            input_str = raw
        else:
            input_str = json.dumps(raw, ensure_ascii=False)
        return ToolCallBlock(
            id=block.get("id", ""),
            name=block.get("name", ""),
            input=input_str,
        )
    if btype == "tool_result":
        output = block.get("output")
        # TODO: handle ``state`` field on tool_result blocks.
        if isinstance(output, list):
            new_block = dict(block)
            new_block["output"] = [_coerce_block(b) for b in output]
            return new_block
        return block
    return block


def msg_from_dict(data: Mapping[str, Any]) -> Any:
    """Build an :class:`agentscope.message.Msg` from a saved dict.

    Handles both 1.x (``timestamp``) and 2.0 (``created_at``) shapes.
    Skips fields that are not recognised so partially-corrupt fixtures
    don't break loading.
    """
    from agentscope.message import Msg  # local import to ease shim usage

    payload: dict[str, Any] = dict(data)

    # Field rename: 1.x ``timestamp`` -> 2.0 ``created_at``.
    if "created_at" not in payload and "timestamp" in payload:
        payload["created_at"] = payload.pop("timestamp")
    else:
        payload.pop("timestamp", None)

    # Translate legacy content blocks in place.
    content = payload.get("content")
    if isinstance(content, str):
        # 1.x stored plain-text content as a bare string; 2.0 requires a list
        # of typed blocks.  Wrap it in a single text block.
        payload["content"] = [{"type": "text", "text": content}]
        content = payload["content"]
    if isinstance(content, list):
        payload["content"] = [_coerce_block(b) for b in content]
        content = payload["content"]

    # 2.0 restricts ``system`` messages to text-only blocks and ``user``
    # messages to text/data blocks.  1.x qwenpaw routinely stored
    # ``tool_result`` blocks under ``role="system"`` (and similar tool
    # plumbing under ``role="user"``); promote those to ``assistant`` so
    # the model validator accepts them.
    role = payload.get("role")
    if isinstance(content, list) and role in ("system", "user"):
        allowed_types = {"text"} if role == "system" else {"text", "data"}
        for block in content:
            btype = getattr(block, "type", None)
            if btype is None and isinstance(block, Mapping):
                btype = block.get("type")
            if btype is not None and btype not in allowed_types:
                payload["role"] = "assistant"
                break

    # Drop fields that the 2.0 model doesn't define (extra="forbid" by
    # default on pydantic v2 BaseModel subclasses).
    allowed = set(Msg.model_fields)
    payload = {k: v for k, v in payload.items() if k in allowed}

    # ``name`` is required in 2.0; fall back to role when absent.
    if "name" not in payload:
        payload["name"] = payload.get("role") or "assistant"

    return Msg.model_validate(payload)
