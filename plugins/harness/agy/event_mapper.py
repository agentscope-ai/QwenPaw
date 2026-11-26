# -*- coding: utf-8 -*-
"""Translate ACP session updates into provider-neutral harness events."""

from __future__ import annotations

import difflib
import json
from typing import Any

from qwenpaw.plugins.harnesses import HarnessEvent, HarnessEventKind

# A tool's output is shown in the chat and kept in the session; a build log
# or a large file read does not need to be there whole.
_MAX_TOOL_OUTPUT_CHARS = 20_000
_FINISHED = {"completed", "failed"}
# What ACP calls the tool when the agent gives no better name.
_GENERIC_KINDS = {"", "other"}


class AgyEventMapper:
    """Map one turn's updates, remembering each tool call across them.

    A tool call arrives as a start followed by updates that each carry only
    what changed, so the name and the latest output are kept per call.
    """

    def __init__(self) -> None:
        self._names: dict[str, str] = {}
        self._outputs: dict[str, str] = {}
        # Calls that have not finished, in the order they started, with the
        # last status reported for each.
        self._open: dict[str, str] = {}
        # Whether the prompt being answered has produced text yet.
        self._text_in_prompt = False

    def begin_prompt(self) -> None:
        """Note that a new message is being sent to the session."""
        self._text_in_prompt = False

    def convert(self, update: Any) -> list[HarnessEvent]:
        """Convert one ``session/update`` payload."""
        kind = _field(update, "session_update", "sessionUpdate")
        if kind == "agent_message_chunk":
            events = _text_event(
                HarnessEventKind.TEXT_DELTA,
                _block_text(_field(update, "content")),
            )
            self._text_in_prompt = self._text_in_prompt or bool(events)
            return events
        if kind == "user_message_chunk":
            # The CLI repeats the message it was sent before it answers.
            # Text that came before that is not the answer: the CLI wrote
            # it on its own after the last turn, when something it had left
            # running finished, and held it back until now.
            if self._text_in_prompt:
                self._text_in_prompt = False
                return _text_event(HarnessEventKind.TEXT_DELTA, "\n\n")
            return []
        if kind == "agent_thought_chunk":
            return _text_event(
                HarnessEventKind.REASONING_DELTA,
                _block_text(_field(update, "content")),
            )
        if kind == "plan":
            return _text_event(
                HarnessEventKind.REASONING_DELTA,
                _plan_text(_field(update, "entries")),
            )
        if kind in {"tool_call", "tool_call_update"}:
            return self._tool(update)
        return []

    def unfinished(self) -> list[str]:
        """Ids of the tool calls that are running, in the order they began.

        A call that waits for an approval is not running yet.
        """
        return [
            call_id
            for call_id, status in self._open.items()
            if status == "in_progress"
        ]

    def close(self) -> list[HarnessEvent]:
        """Finish tool calls the turn left open, as when it was cancelled.

        Without an output a started call stays "running" in the chat for
        good.
        """
        events = [
            HarnessEvent(
                kind=HarnessEventKind.TOOL_COMPLETED,
                item_id=call_id,
                tool_name=self._names.get(call_id, "tool"),
                text=self._outputs.get(call_id, ""),
                data={"is_error": True, "interrupted": True},
            )
            for call_id in sorted(self._open)
        ]
        self._open.clear()
        return events

    def _tool(self, update: Any) -> list[HarnessEvent]:
        call_id = str(_field(update, "tool_call_id", "toolCallId") or "")
        if not call_id:
            return []
        events: list[HarnessEvent] = []
        if call_id not in self._names:
            name = _tool_name(update)
            self._names[call_id] = name
            self._open[call_id] = ""
            events.append(
                HarnessEvent(
                    kind=HarnessEventKind.TOOL_STARTED,
                    item_id=call_id,
                    tool_name=name,
                    data={"arguments": _arguments(update)},
                ),
            )
        output = _output_text(update)
        if output:
            self._outputs[call_id] = output
        status = str(_field(update, "status") or "")
        if status and call_id in self._open:
            self._open[call_id] = status
        if status in _FINISHED and call_id in self._open:
            del self._open[call_id]
            events.append(
                HarnessEvent(
                    kind=HarnessEventKind.TOOL_COMPLETED,
                    item_id=call_id,
                    tool_name=self._names[call_id],
                    text=self._outputs.pop(call_id, ""),
                    data={"is_error": status == "failed"},
                ),
            )
        return events


def _field(value: Any, *names: str) -> Any:
    """Read a field from an SDK model or from the raw JSON it came from."""
    for name in names:
        if isinstance(value, dict):
            if name in value:
                return value[name]
        elif hasattr(value, name):
            return getattr(value, name)
    return None


def _text_event(kind: HarnessEventKind, text: str) -> list[HarnessEvent]:
    return [HarnessEvent(kind=kind, text=text)] if text else []


def _block_text(block: Any) -> str:
    if _field(block, "type") != "text":
        return ""
    return str(_field(block, "text") or "")


def _plan_text(entries: Any) -> str:
    lines = []
    for entry in entries or []:
        content = str(_field(entry, "content") or "").strip()
        if not content:
            continue
        mark = {"completed": "x", "in_progress": "~"}.get(
            str(_field(entry, "status") or ""),
            " ",
        )
        lines.append(f"- [{mark}] {content}")
    return "\n".join(lines) + "\n" if lines else ""


def _tool_name(update: Any) -> str:
    """The agent's own tool name when the title gives it, else the kind."""
    title = str(_field(update, "title") or "").strip()
    kind = str(_field(update, "kind") or "").strip()
    if kind in _GENERIC_KINDS:
        # agy titles a tool it has no kind for "Run <tool>".
        name = title.removeprefix("Run ").strip()
        if name and " " not in name:
            return name
        return title or "tool"
    return kind


def _arguments(update: Any) -> dict[str, Any]:
    raw = _field(update, "raw_input", "rawInput")
    arguments = dict(raw) if isinstance(raw, dict) else {}
    if raw is not None and not isinstance(raw, dict):
        arguments["input"] = raw
    title = str(_field(update, "title") or "").strip()
    if title:
        arguments.setdefault("title", title)
    return arguments


def _output_text(update: Any) -> str:
    parts: list[str] = []
    for item in _field(update, "content") or []:
        item_type = _field(item, "type")
        if item_type == "content":
            text = _block_text(_field(item, "content"))
        elif item_type == "diff":
            text = _diff_text(item)
        else:
            text = ""
        if text:
            parts.append(text)
    if not parts:
        raw = _field(update, "raw_output", "rawOutput")
        if isinstance(raw, str):
            parts.append(raw)
        elif raw is not None:
            parts.append(json.dumps(raw, ensure_ascii=False, default=str))
    text = "\n".join(parts)
    if len(text) > _MAX_TOOL_OUTPUT_CHARS:
        omitted = len(text) - _MAX_TOOL_OUTPUT_CHARS
        text = (
            text[:_MAX_TOOL_OUTPUT_CHARS]
            + f"\n… ({omitted} more characters not shown)"
        )
    return text


def _diff_text(item: Any) -> str:
    path = str(_field(item, "path") or "")
    old = str(_field(item, "old_text", "oldText") or "")
    new = str(_field(item, "new_text", "newText") or "")
    diff = "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        ),
    )
    return diff or path


__all__ = ["AgyEventMapper"]
