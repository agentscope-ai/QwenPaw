# -*- coding: utf-8 -*-
"""Convert MCP wire values to finite public SDK results."""

from collections.abc import Mapping
import json

from qwenpaw.plugins.drivers import DriverCallResult
from qwenpaw.plugins.messages import Attachment, ContentBlock


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value


def _resource_text(resource):
    reference = {
        key: resource[key]
        for key in ("type", "uri", "name", "description", "mimeType")
        if key in resource
    }
    body = str(resource.get("text") or "")
    text = json.dumps(reference, ensure_ascii=False)
    return f"{body}\n{text}" if body else text


def content_block(value):
    raw = plain(value)
    kind = raw.get("type", "text")
    metadata = {"mcp": raw}
    if kind == "text":
        return ContentBlock(text=str(raw.get("text", "")), metadata=metadata)
    if kind in {"image", "audio"}:
        mime = str(raw.get("mimeType") or "application/octet-stream")
        return ContentBlock(
            type=kind,
            attachment=Attachment(f"data:{mime};base64,{raw['data']}", mime),
            metadata=metadata,
        )
    resource = raw["resource"] if kind == "resource" else raw
    text = _resource_text(resource)
    # Resource identifiers belong to the MCP server, not the host filesystem.
    if kind != "resource" or resource.get("blob") is None:
        return ContentBlock(text=text, metadata=metadata)
    mime = str(resource.get("mimeType") or "application/octet-stream")
    return ContentBlock(
        type="file",
        text=text,
        attachment=Attachment(
            f"data:{mime};base64,{resource['blob']}",
            mime,
            str(resource.get("name") or ""),
        ),
        metadata=metadata,
    )


def call_result(value):
    raw = plain(value)
    return DriverCallResult(
        content=tuple(content_block(item) for item in raw.get("content", ())),
        is_error=bool(raw.get("isError", raw.get("is_error", False))),
        structured_content=raw.get(
            "structuredContent",
            raw.get("structured_content"),
        ),
        metadata={
            "mcp": {
                key: item
                for key, item in raw.items()
                if key
                not in {
                    "content",
                    "isError",
                    "is_error",
                    "structuredContent",
                    "structured_content",
                }
            },
        },
    )
