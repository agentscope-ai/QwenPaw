# -*- coding: utf-8 -*-
"""Persist provider-specific tool-call fields without extending AgentScope.

AgentScope's ``ToolCallBlock`` is a strict Pydantic model, so provider
extensions such as Gemini's ``extra_content`` cannot be assigned as normal
fields.  The stream parser attaches the extension transiently, and
``QwenPawAgent._save_to_context`` moves it into the owning ``Msg.metadata``
before session state is serialized.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

TOOL_CALL_EXTRAS_METADATA_KEY = "_qwenpaw_tool_call_extras"
_TRANSIENT_TOOL_CALL_EXTRA_ATTR = "_qwenpaw_tool_call_extra"


def attach_transient_tool_call_extra(
    block: Any,
    *,
    provider_id: str,
    extra_content: Any,
) -> None:
    """Attach an extension to a parsed block until it enters message state."""
    record = {
        "provider_id": provider_id,
        "extra_content": extra_content,
    }
    if isinstance(block, dict):
        block[_TRANSIENT_TOOL_CALL_EXTRA_ATTR] = record
        return

    # ``ToolCallBlock`` rejects unknown fields through Pydantic's normal
    # setattr path. This deliberately relies on the current Pydantic model
    # layout accepting transient attributes through ``object.__setattr__``;
    # the lifecycle tests should fail loudly if a future AgentScope/Pydantic
    # release changes that contract. The agent consumes the attribute before
    # state serialization and persists the value in the owning Msg.metadata.
    object.__setattr__(block, _TRANSIENT_TOOL_CALL_EXTRA_ATTR, record)


def collect_transient_tool_call_extras(
    blocks: Iterable[Any],
) -> dict[str, dict[str, Any]]:
    """Remove and return transient extensions keyed by tool-call id."""
    collected: dict[str, dict[str, Any]] = {}
    for block in blocks:
        if isinstance(block, dict):
            block_type = block.get("type")
            tool_id = block.get("id")
            record = block.pop(_TRANSIENT_TOOL_CALL_EXTRA_ATTR, None)
        else:
            block_type = getattr(block, "type", None)
            tool_id = getattr(block, "id", None)
            record = getattr(block, _TRANSIENT_TOOL_CALL_EXTRA_ATTR, None)
            try:
                object.__delattr__(
                    block,
                    _TRANSIENT_TOOL_CALL_EXTRA_ATTR,
                )
            except AttributeError:
                # Current Pydantic models store the transient attribute in
                # ``__dict__``. Keep this fallback for compatible wrappers;
                # slot-only models are covered by ``object.__delattr__``.
                getattr(block, "__dict__", {}).pop(
                    _TRANSIENT_TOOL_CALL_EXTRA_ATTR,
                    None,
                )

        if (
            block_type not in ("tool_use", "tool_call")
            or not isinstance(tool_id, str)
            or not tool_id
            or not isinstance(record, dict)
            or "extra_content" not in record
        ):
            continue
        collected[tool_id] = deepcopy(record)
    return collected


def persist_tool_call_extras(
    msg: Any,
    extras: dict[str, dict[str, Any]],
) -> None:
    """Merge tool-call extensions into an assistant message's metadata."""
    if not extras:
        return
    metadata = dict(getattr(msg, "metadata", None) or {})
    existing = metadata.get(TOOL_CALL_EXTRAS_METADATA_KEY)
    persisted = dict(existing) if isinstance(existing, dict) else {}
    persisted.update(deepcopy(extras))
    metadata[TOOL_CALL_EXTRAS_METADATA_KEY] = persisted
    msg.metadata = metadata


def tool_call_extras_for_provider(
    msg: Any,
    provider_id: str | None,
) -> dict[str, Any]:
    """Return extensions that originated from the current provider only."""
    if not provider_id:
        return {}
    metadata = getattr(msg, "metadata", None) or {}
    raw = metadata.get(TOOL_CALL_EXTRAS_METADATA_KEY)
    if not isinstance(raw, dict):
        return {}

    matched: dict[str, Any] = {}
    for tool_id, record in raw.items():
        if (
            isinstance(tool_id, str)
            and isinstance(record, dict)
            and record.get("provider_id") == provider_id
            and "extra_content" in record
        ):
            matched[tool_id] = record["extra_content"]
    return matched


__all__ = [
    "TOOL_CALL_EXTRAS_METADATA_KEY",
    "attach_transient_tool_call_extra",
    "collect_transient_tool_call_extras",
    "persist_tool_call_extras",
    "tool_call_extras_for_provider",
]
