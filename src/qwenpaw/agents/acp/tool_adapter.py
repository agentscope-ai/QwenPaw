# -*- coding: utf-8 -*-
"""ACP to ToolResponse adapter helpers for delegate_external_agent."""

from pathlib import Path
from typing import Any, Optional, Tuple

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse


def _text_block(text: str) -> TextBlock:
    return TextBlock(type="text", text=text)


def response_blocks(
    blocks: list[TextBlock],
    *,
    stream: bool = False,
    is_last: bool = True,
) -> ToolResponse:
    return ToolResponse(content=blocks, stream=stream, is_last=is_last)


def response_text(
    text: str,
    *,
    stream: bool = False,
    is_last: bool = True,
) -> ToolResponse:
    return response_blocks([_text_block(text)], stream=stream, is_last=is_last)


def _header_text(*, runner_name: str, execution_cwd: Path) -> str:
    return f"runner: {runner_name} " f"working directory: {execution_cwd}"


def _string(value: Any) -> str:
    return str(value or "").strip()


def _option_parts(option: Any) -> Optional[Tuple[str, str]]:
    option_id = None
    title = None
    if isinstance(option, dict):
        option_id = _string(
            option.get("optionId")
            or option.get("option_id")
            or option.get("id"),
        )
        title = _string(option.get("title") or option.get("name"))
    else:
        option_id = _string(
            getattr(option, "option_id", None)
            or getattr(option, "optionId", None)
            or getattr(option, "id", None),
        )
        title = _string(
            getattr(option, "title", None) or getattr(option, "name", None),
        )
    title = title or option_id or "option"
    if not title:
        return None
    return title, option_id


def _render_text_event(event: dict[str, Any]) -> Optional[str]:
    text = _string(event.get("text"))
    return f"[assistant]\n{text}" if text else None


def _render_tool_event(event: dict[str, Any]) -> Optional[str]:
    kind = _string(event.get("kind"))
    detail = _string(event.get("detail") or event.get("title"))
    return f"[tool_call] {kind} ({detail})" if kind and detail else None


def _render_status_event(event: dict[str, Any]) -> Optional[str]:
    status = _string(event.get("status")) or "unknown"
    if status == "run_finished":
        return None
    summary = _string(event.get("summary"))
    if status == "agent_thinking":
        return summary or "agent thinking..."
    return "\n".join(part for part in [f"[status] {status}", summary] if part)


def _render_permission_event(event: dict[str, Any]) -> str:
    title = _string(
        event.get("title") or event.get("reason") or "permission request",
    )
    options = [
        f"{name} ({option_id})" if option_id else name
        for parts in (_option_parts(opt) for opt in event.get("options") or [])
        if parts
        for name, option_id in [parts]
    ]
    return "\n".join(
        part
        for part in [
            f"[permission_request] {title}",
            f"options: {', '.join(options)}" if options else "",
        ]
        if part
    )


def _render_error_event(event: dict[str, Any]) -> Optional[str]:
    message_text = _string(event.get("message") or "Unknown error")
    return f"[error] {message_text}" if message_text else None


def render_event_text(event: dict[str, Any]) -> Optional[str]:
    event_type = _string(event.get("type")).lower()
    if event_type == "text":
        return _render_text_event(event)
    if event_type.startswith("tool_"):
        return _render_tool_event(event)
    if event_type == "status":
        return _render_status_event(event)
    if event_type == "permission_request":
        return _render_permission_event(event)
    if event_type == "error":
        return _render_error_event(event)
    return None


def format_stream_snapshot_response(
    snapshot_items: list[str],
    *,
    runner_name: str,
    execution_cwd: Path,
    include_header: bool = False,
) -> Optional[ToolResponse]:
    del runner_name
    del execution_cwd
    del include_header
    blocks: list[TextBlock] = []
    for text in snapshot_items:
        cleaned = (text or "").strip()
        if cleaned:
            blocks.append(_text_block(cleaned))
    if not blocks:
        return None
    return response_blocks(blocks, stream=True, is_last=False)


def format_final_assistant_response(
    *,
    runner_name: str,
    execution_cwd: Path,
    final_event: Optional[dict[str, Any]],
) -> ToolResponse:
    text = None
    if final_event is not None:
        text = render_event_text(final_event or {})
    body = text or "completed without text output"
    return response_blocks(
        [
            _text_block(
                _header_text(
                    runner_name=runner_name,
                    execution_cwd=execution_cwd,
                ),
            ),
            _text_block(body),
        ],
        is_last=True,
    )


def format_permission_suspended_response(
    *,
    suspended_permission: Any,
) -> ToolResponse:
    agent = getattr(suspended_permission, "agent", "unknown")
    tool_name = getattr(
        suspended_permission,
        "tool_name",
        "external-agent",
    )
    tool_kind = getattr(suspended_permission, "tool_kind", "other")
    details = [
        f"- Agent: `{agent}`",
        f"- Tool: `{tool_name}` (kind: `{tool_kind}`)",
    ]
    action = getattr(suspended_permission, "action", None)
    if action:
        details.append(f"- Action: `{action}`")
    paths = list(getattr(suspended_permission, "paths", []) or [])
    if paths:
        details.append("- Files:")
        details.extend(f"  - `{path}`" for path in paths)
    else:
        target = getattr(suspended_permission, "target", None)
        if target:
            details.append(f"- Target: `{target}`")
    command = getattr(suspended_permission, "command", None)
    if command:
        details.append(f"- Command: `{command}`")
    summary = getattr(suspended_permission, "summary", None)
    if summary:
        details.append(f"- Summary: {summary}")

    options = [
        f"  - **{name}** (`{option_id}`)" if option_id else f"  - **{name}**"
        for parts in (
            _option_parts(opt)
            for opt in getattr(suspended_permission, "options", []) or []
        )
        if parts
        for name, option_id in [parts]
    ]

    intro = (
        "🔐 **External Agent Permission Request**\n\n"
        "Do not make permission decisions on the user's behalf. "
        "Clearly present the permission details and available options, "
        "then ask the user for confirmation.\n\n"
    )
    reply_hint = (
        "\n\nReply with one exact option id using "
        '`delegate_external_agent(action="respond", runner=..., message=...)`.'
    )
    text = (
        intro
        + "\n".join(details)
        + ("\n\nOptions:\n" + "\n".join(options) if options else "")
        + reply_hint
    )
    return response_text(text)


def format_close_response(*, runner_name: str, closed: bool) -> ToolResponse:
    if closed:
        text = f"Closed the bound ACP session for runner '{runner_name}'."
    else:
        text = (
            "No bound ACP session found for runner "
            f"'{runner_name}' in the current chat."
        )
    return response_text(text)
