# -*- coding: utf-8 -*-
"""Translate ACP ``session_update`` objects into normalized ``TuiEvent``s.

Kept free of Textual and of the connection runtime so it is trivially
unit-testable (see ``tests/cli/test_tui_normalize.py``). The shapes here match
the ``acp.schema`` types verified against ``agent-client-protocol`` 0.9.x:

* ``AgentMessageChunk`` / ``AgentThoughtChunk`` carry a single content block
  whose ``.text`` is already a *delta* (the QwenPaw ACP server emits deltas).
* ``ToolCallStart`` / ``ToolCallProgress`` share ``tool_call_id`` so the UI can
  find-or-update one panel.
* ``AgentPlanUpdate`` and ``UsageUpdate`` map straight across.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from .events import (
    AvailableCommands,
    FileLink,
    PlanEntry,
    PlanUpdate,
    SessionTitle,
    SlashCommand,
    TextDelta,
    ThoughtDelta,
    TokenUsage,
    ToolCall,
    TransportError,
    TuiEvent,
    Usage,
    UserTurn,
)

# Tool-content block types that carry a file/resource URI worth linking.
_LINK_BLOCK_TYPES = ("resource_link", "image", "audio", "resource")


def _is_local_file_uri(uri: str) -> bool:
    """Whether *uri* is a local file safe to surface as a one-click link.

    A clicked ``FileLink`` is handed to ``App.open_url`` (the OS handler), so a
    buggy or hostile agent emitting an ``http(s)://`` (or other-scheme)
    ``resource_link`` could drive a one-click browser open. QwenPaw only emits
    local files here (e.g. ``send_file_to_user``), so restrict to ``file://``
    and bare local paths; everything else is dropped.
    """
    scheme = urlparse(uri).scheme.lower()
    # "" = bare path; a single alpha char is a Windows drive letter (C:\...).
    return scheme in ("", "file") or (len(scheme) == 1 and scheme.isalpha())


# ``_meta`` key QwenPaw sets on an ``agent_message_chunk`` to mark it as an
# error; mirrors the ACP server's ``ACP_ERROR_META_KEY``.
_ERROR_META_KEY = "qwenpaw.error"


def _block_text(content: Any) -> str:
    """Pull text out of an ACP content block (object or dict)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return str(content.get("text", "") or "")
    return str(getattr(content, "text", "") or "")


# Containers whose compact JSON form fits here stay on one line; longer
# ones are indented so nested tool params/outputs stay readable.
_JSON_INLINE_MAX = 60

# Never try to parse/pretty-print huge payloads (e.g. a base64 blob in a
# tool result): the panel truncates them for display anyway and json.loads
# on megabytes of text would stall the UI's event loop.
_JSON_PRETTY_MAX = 100_000


def _json_value_text(value: Any) -> str:
    """JSON-encode one param value: compact when short, indented when not."""
    compact = json.dumps(value, ensure_ascii=False)
    if not isinstance(value, (dict, list)):
        return compact
    if len(compact) <= _JSON_INLINE_MAX:
        return compact
    return json.dumps(value, ensure_ascii=False, indent=2)


def pretty_json(text: str) -> str:
    """Re-indent *text* if it is a (non-tiny) JSON document.

    Anything that isn't a JSON object/array — or is short enough to read
    inline — is returned unchanged.
    """
    stripped = text.strip()
    if (
        len(stripped) <= _JSON_INLINE_MAX
        or len(stripped) > _JSON_PRETTY_MAX
        or stripped[0] not in "{["
    ):
        return text
    try:
        value = json.loads(stripped)
    except ValueError:
        return text
    if not isinstance(value, (dict, list)):
        return text
    return json.dumps(value, ensure_ascii=False, indent=2)


def _tool_output_text(content: Any) -> str:
    """Flatten a tool-call ``content`` list into display text."""
    if not content:
        return ""
    parts: list[str] = []
    for item in content:
        inner = (
            item.get("content")
            if isinstance(item, dict)
            else getattr(item, "content", None)
        )
        text = _block_text(inner)
        if text:
            parts.append(text)
    return pretty_json("\n".join(parts))


def _attr(obj: Any, key: str) -> Any:
    """Read ``key`` from a dict or an attribute-style object."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _tool_links(content: Any) -> tuple[FileLink, ...]:
    """Pull file/resource links out of a tool-call ``content`` list.

    Recognises ACP ``resource_link`` blocks (and image/audio/resource blocks
    that carry a ``uri``), e.g. the link QwenPaw emits for
    ``send_file_to_user``.
    """
    if not content:
        return ()
    links: list[FileLink] = []
    for item in content:
        inner = _attr(item, "content")
        if inner is None:
            continue
        if _attr(inner, "type") not in _LINK_BLOCK_TYPES:
            continue
        uri = _attr(inner, "uri")
        if not uri:
            continue
        if not _is_local_file_uri(str(uri)):
            # Skip non-local schemes (e.g. http) — not safe to one-click open.
            continue
        links.append(
            FileLink(
                uri=str(uri),
                name=str(_attr(inner, "name") or ""),
                mime_type=(
                    str(_attr(inner, "mime_type"))
                    if _attr(inner, "mime_type")
                    else None
                ),
            ),
        )
    return tuple(links)


def tool_input_text(raw_input: Any) -> str:
    """Render raw tool input parameters into readable display text.

    ``raw_input`` is whatever the agent sent (usually a dict like
    ``{"command": "ls -la"}``). One ``key: value`` line per parameter so the
    actual command/path/etc. is visible in the panel; long nested values are
    pretty-printed as indented JSON. Also used for the permission prompt.
    """
    if raw_input is None:
        return ""
    if isinstance(raw_input, str):
        return pretty_json(raw_input.strip())
    if isinstance(raw_input, dict):
        lines: list[str] = []
        for key, value in raw_input.items():
            text = value if isinstance(value, str) else _json_value_text(value)
            lines.append(f"{key}: {text}")
        return "\n".join(lines)
    return str(raw_input)


# pylint: disable-next=too-many-return-statements
def normalize_update(update: Any) -> list[TuiEvent]:
    """Convert one ACP ``session_update`` payload into zero or more events.

    Accepts the typed ``acp.schema`` objects. Unknown updates yield ``[]`` so
    the UI degrades gracefully rather than crashing on protocol additions.
    """
    kind = getattr(update, "session_update", None)

    if kind == "agent_message_chunk":
        meta = getattr(update, "field_meta", None)
        # QwenPaw reports per-call token usage as an (otherwise empty)
        # message chunk tagged with ``_meta.usage`` (inputTokens / etc.).
        if isinstance(meta, dict) and isinstance(meta.get("usage"), dict):
            u = meta["usage"]
            return [
                TokenUsage(
                    input_tokens=int(u.get("inputTokens", 0) or 0),
                    output_tokens=int(u.get("outputTokens", 0) or 0),
                    total_tokens=int(u.get("totalTokens", 0) or 0),
                    model=str(u.get("model")) if u.get("model") else None,
                ),
            ]
        text = _block_text(getattr(update, "content", None))
        if not text:
            return []
        # QwenPaw tags failed turns via ``_meta`` so we can render them as
        # an error instead of a normal assistant reply (see the ACP server's
        # ``ACP_ERROR_META_KEY``). Other agents omit it → plain text.
        if isinstance(meta, dict) and meta.get(_ERROR_META_KEY):
            return [TransportError(text)]
        return [TextDelta(text)]

    if kind == "agent_thought_chunk":
        text = _block_text(getattr(update, "content", None))
        return [ThoughtDelta(text)] if text else []

    if kind in ("tool_call", "tool_call_update"):
        return [
            ToolCall(
                tool_call_id=getattr(update, "tool_call_id", ""),
                # Keep an absent title empty rather than coercing to "tool":
                # the agent only sends the real name on the *start* event, so a
                # placeholder here would clobber it on the completion update
                # (which carries title=None). The widget fills the fallback.
                title=getattr(update, "title", None) or "",
                kind=getattr(update, "kind", None),
                status=getattr(update, "status", None),
                output=_tool_output_text(getattr(update, "content", None))
                or None,
                params=tool_input_text(getattr(update, "raw_input", None))
                or None,
                links=_tool_links(getattr(update, "content", None)),
            ),
        ]

    if kind == "plan":
        entries = [
            PlanEntry(
                content=getattr(e, "content", "") or "",
                status=getattr(e, "status", "pending") or "pending",
                priority=getattr(e, "priority", "medium") or "medium",
            )
            for e in (getattr(update, "entries", None) or [])
        ]
        return [PlanUpdate(entries=entries)]

    if kind == "usage_update":
        return [
            Usage(
                used=int(getattr(update, "used", 0) or 0),
                size=int(getattr(update, "size", 0) or 0),
            ),
        ]

    if kind == "available_commands_update":
        commands = [
            SlashCommand(
                name=name,
                description=getattr(c, "description", "") or "",
            )
            for c in (getattr(update, "available_commands", None) or [])
            if (name := getattr(c, "name", "") or "")
        ]
        return [AvailableCommands(commands=commands)]

    if kind == "session_info_update":
        title = getattr(update, "title", None)
        return [SessionTitle(str(title))] if title else []

    if kind == "user_message_chunk":
        # Emitted only while a resumed session replays its saved transcript;
        # surface it so the prior user turns render in the rebuilt history.
        text = _block_text(getattr(update, "content", None))
        return [UserTurn(text)] if text else []

    # current_mode / config_option: not surfaced in the chat transcript (yet).
    return []
