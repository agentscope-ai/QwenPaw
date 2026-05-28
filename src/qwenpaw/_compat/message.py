# -*- coding: utf-8 -*-
"""Shims for message block names that changed in agentscope 2.0.

The 2.0 schema dropped per-modality block classes (``ImageBlock``,
``AudioBlock``, ``VideoBlock``) in favour of a single ``DataBlock`` whose
type is fixed at ``"data"`` and whose modality is inferred from the
attached ``source.media_type``.  Likewise, ``ToolUseBlock`` was renamed
to ``ToolCallBlock`` with a tighter contract:

    * ``input`` is now a JSON-encoded ``str`` instead of a free-form
      ``dict``,
    * the ``raw_input`` field is gone (the encoded ``input`` is
      authoritative).

This module exposes thin wrappers so legacy call sites in qwenpaw keep
working unchanged while we incrementally rewrite them to construct
``DataBlock`` / ``ToolCallBlock`` directly.

TODO(as2-migration): delete this module once every caller has been
ported to ``agentscope.message`` 2.0 block constructors.
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


# ---------------------------------------------------------------------------
# Media block factories.
# Old call sites do e.g. ``ImageBlock(type="image", source={"type": "url",
# "url": "..."})``.  We accept the same signature for compatibility but
# build the unified ``DataBlock`` underneath, defaulting ``media_type`` to
# the modality if the caller didn't provide one.
# ---------------------------------------------------------------------------


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


def _make_media_block(
    modality: str,
    *,
    type: str | None = None,  # pylint: disable=redefined-builtin
    source: Any,
    name: str | None = None,
    **_ignored: Any,
) -> DataBlock:
    """Build a :class:`DataBlock` from legacy modality-specific kwargs."""
    # ``type`` kwarg is accepted for backward compatibility but ignored:
    # ``DataBlock.type`` is always ``"data"`` in 2.0.
    del type
    coerced = _coerce_source(source, modality)
    return DataBlock(source=coerced, name=name)


def ImageBlock(**kwargs: Any) -> DataBlock:  # noqa: N802
    """Legacy ``ImageBlock`` constructor → returns a ``DataBlock``."""
    return _make_media_block("image", **kwargs)


def AudioBlock(**kwargs: Any) -> DataBlock:  # noqa: N802
    """Legacy ``AudioBlock`` constructor → returns a ``DataBlock``."""
    return _make_media_block("audio", **kwargs)


def VideoBlock(**kwargs: Any) -> DataBlock:  # noqa: N802
    """Legacy ``VideoBlock`` constructor → returns a ``DataBlock``."""
    return _make_media_block("video", **kwargs)


# ---------------------------------------------------------------------------
# Tool-use block shim.
# ---------------------------------------------------------------------------


def ToolUseBlock(  # noqa: N802
    *,
    id: str,  # pylint: disable=redefined-builtin
    name: str,
    input: Any,  # pylint: disable=redefined-builtin
    type: str | None = None,  # pylint: disable=redefined-builtin
    raw_input: str | None = None,
    **_ignored: Any,
) -> ToolCallBlock:
    """Legacy ``ToolUseBlock`` constructor → returns a ``ToolCallBlock``.

    The new block stores ``input`` as a JSON string; if the caller passes
    a dict (the old convention) we serialize it.  ``raw_input`` is
    accepted but ignored — the encoded ``input`` is authoritative in 2.0.
    """
    del type, raw_input
    if isinstance(input, str):
        input_str = input
    else:
        input_str = json.dumps(input, ensure_ascii=False)
    return ToolCallBlock(id=id, name=name, input=input_str)


# ---------------------------------------------------------------------------
# Msg deserialization shim.
# Sessions saved by 1.x stored messages as ``{id, name, role, content,
# metadata, timestamp}``; 2.0 uses ``{name, content, role, id, metadata,
# created_at, finished_at, usage}``.  ``Msg.from_dict`` is gone in 2.0,
# so we provide a translator that accepts either shape.
# ---------------------------------------------------------------------------


def _coerce_block(block: Any) -> Any:
    """Map a stored content block dict to a 2.0 block instance.

    Old per-modality blocks (``image`` / ``audio`` / ``video``) are
    rewritten to the unified ``DataBlock``.  Anything else is returned
    as-is so the union discriminator on ``Msg.content`` can handle it.
    """
    if not isinstance(block, Mapping):
        return block
    btype = block.get("type")
    if btype in ("image", "audio", "video"):
        source = block.get("source")
        if source is None:
            return block
        return _make_media_block(
            btype,
            source=source,
            name=block.get("name"),
        )
    if btype == "tool_use":
        # Legacy tool_use → tool_call.
        return ToolUseBlock(
            id=block.get("id", ""),
            name=block.get("name", ""),
            input=block.get("input") or block.get("raw_input") or "{}",
        )
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
