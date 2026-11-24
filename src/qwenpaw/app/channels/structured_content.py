# -*- coding: utf-8 -*-
"""Host-filtered channel display projection; no raw hidden tool payloads."""

import json
from types import SimpleNamespace

from qwenpaw.channel_protocol.models import validate_content_part
from qwenpaw.channel_protocol.structured_content import (
    validate_structured_parts,
)
from qwenpaw.schemas import ContentType, MessageType
from .renderer import blocks_to_semantic_parts, _truncate_tool_text


def _part(item):
    value = item.part.model_dump(mode="json", exclude_none=True)
    kind = value["type"]
    if kind in {"text", "refusal"}:
        part = {"type": "text", "text": value[kind]}
    else:
        locator = "data" if kind == "audio" else kind + "_url"
        if not value.get(locator):
            # A runtime-only reference has no transport locator.
            return None
        part = {
            key: value[key]
            for key in ("type", locator, "filename", "mime_type", "format")
            if key in value
        }
    if kind not in {"text", "refusal"} and item.mime_type:
        part["mime_type"] = item.mime_type
    return {**validate_content_part(part), "role": item.role}


def _output_parts(output, name, style):
    display = style.display_config
    try:
        output = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        pass
    if not isinstance(output, list):
        if not display.show_tool_results:
            return None
        return (
            _truncate_tool_text(
                "" if output is None else str(output),
                display.tool_result_max_length,
            )
            if display.show_tool_details
            else "..."
        )
    parts = []
    remaining = display.tool_result_max_length
    text_seen = False
    for item in blocks_to_semantic_parts(output, display):
        part = _part(item)
        if part is None:
            continue
        if part["type"] != "text":
            if display.show_tool_results or name not in style.internal_tools:
                parts.append(part)
            continue
        if not display.show_tool_results:
            continue
        if not display.show_tool_details:
            if not text_seen:
                parts.append(
                    {"type": "text", "text": "...", "role": "rendered"},
                )
            text_seen = True
            continue
        if display.tool_result_max_length and remaining == 0:
            continue
        text = part["text"]
        part["text"] = _truncate_tool_text(text, remaining)
        if display.tool_result_max_length:
            remaining = max(0, remaining - len(text))
        parts.append(part)
    if (
        display.show_tool_results
        and not display.show_tool_details
        and not text_seen
    ):
        parts.append({"type": "text", "text": "...", "role": "rendered"})
    return parts


def project_structured_content(renderer, message):
    """Retain tool identity and ordered output under existing display policy."""
    kind = getattr(message, "type", None)
    calls = {
        MessageType.FUNCTION_CALL,
        MessageType.PLUGIN_CALL,
        MessageType.MCP_TOOL_CALL,
    }
    results = {
        MessageType.FUNCTION_CALL_OUTPUT,
        MessageType.PLUGIN_CALL_OUTPUT,
        MessageType.MCP_TOOL_CALL_OUTPUT,
    }
    content_items = getattr(message, "content", ()) or ()

    def tool_data(content):
        data = getattr(content, "data", None)
        return (
            data
            if (
                getattr(content, "type", None) == ContentType.DATA
                and isinstance(data, dict)
                and data.get("name") is not None
                and (
                    data.get("arguments") is not None
                    or data.get("output") is not None
                )
            )
            else None
        )

    if kind not in calls | results and not any(
        tool_data(c) for c in content_items
    ):
        return list(
            validate_structured_parts(
                [
                    part
                    for item in renderer.message_to_semantic_parts(message)
                    if (part := _part(item)) is not None
                ],
            ),
        )
    style = renderer.style
    display = style.display_config
    parts = []
    for content in content_items:
        data = tool_data(content)
        if data is None:
            if kind not in calls | results:
                parts.extend(
                    part
                    for item in renderer.message_to_semantic_parts(
                        SimpleNamespace(type=None, content=[content]),
                    )
                    if (part := _part(item)) is not None
                )
            continue
        name = data.get("name") or "tool"
        identity = {"id": data.get("call_id") or "", "name": name}
        if "state" in data:
            identity["state"] = data["state"]
        is_call = kind in calls or (
            kind not in results and data.get("output") is None
        )
        if is_call:
            if display.show_tool_calls:
                parts.append(
                    {
                        "type": "tool_call",
                        **identity,
                        "arguments": (
                            _truncate_tool_text(
                                data.get("arguments") or "{}",
                                display.tool_call_max_length,
                            )
                            if display.show_tool_details
                            else "..."
                        ),
                    },
                )
        else:
            output = _output_parts(data.get("output", ""), name, style)
            if display.show_tool_results:
                parts.append(
                    {"type": "tool_result", **identity, "output": output},
                )
            elif isinstance(output, list):
                # External tool media remains displayable, just as in the
                # existing renderer; hidden result text/identity stays hidden.
                parts.extend(output)
    return list(validate_structured_parts(parts))
