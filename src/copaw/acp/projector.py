# -*- coding: utf-8 -*-
"""Project ACP events into CoPaw messages that work across channels."""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from agentscope.message import Msg, TextBlock

from .types import AcpEvent

logger = logging.getLogger(__name__)


class ACPEventProjector:
    """Convert ACP events into channel-safe CoPaw messages."""

    def __init__(self, *, harness: str, show_tool_calls: bool = True):
        self.harness = harness
        self.show_tool_calls = show_tool_calls
        self._assistant_message_id = f"acp_assistant_{uuid4().hex}"
        self._assistant_buffer = ""
        self._pending_tool_starts: dict[str, dict[str, Any]] = {}
        self._pending_tool_results: dict[str, dict[str, Any]] = {}

    # pylint: disable=too-many-return-statements,too-many-branches
    def project(
        self,
        event: AcpEvent,
    ) -> list[tuple[Msg, bool]]:
        """Project one ACP event into one or more messages."""
        emitted: list[tuple[Msg, bool]] = []

        if event.type == "assistant_chunk":
            text = str(event.payload.get("text") or "")
            if not text:
                return []
            self._assistant_buffer += text
            msg = self._assistant_message(self._assistant_buffer)
            logger.debug(
                "ACP projector: assistant_chunk, buffer_len=%d, "
                "msg_id=%s, content=%s...",
                len(self._assistant_buffer),
                self._assistant_message_id,
                str(msg.content)[:30],
            )
            emitted.append((msg, False))
            return emitted

        if event.type == "thought_chunk":
            return []

        if event.type == "run_finished":
            logger.info(
                "ACP projector: run_started, type=%s, buffer_len=%d, "
                "msg_id=%s",
                event.type,
                len(self._assistant_buffer),
                self._assistant_message_id,
            )
            flushed = self._flush_assistant(last=True)
            logger.info(
                "ACP projector: run_finished flushed %d messages, "
                "content_len=%d",
                len(flushed),
                len(str(flushed[0][0].content)) if flushed else 0,
            )
            return flushed

        # Handle events that don't need to flush assistant buffer first
        if event.type in {"commands_update", "usage_update"}:
            return []

        # For non-assistant events (tool, plan, etc.), flush current assistant
        # message and start a new message sequence for subsequent chunks.
        logger.debug(
            "ACP projector: %s, flushing assistant buffer_len=%d, msg_id=%s",
            event.type,
            len(self._assistant_buffer),
            self._assistant_message_id,
        )
        flushed = self._flush_assistant(last=True)
        logger.debug(
            "ACP projector: %s flushed %d messages",
            event.type,
            len(flushed),
        )
        emitted.extend(flushed)

        if (
            event.type in {"tool_start", "tool_update", "tool_end"}
            and not self.show_tool_calls
        ):
            return emitted

        if event.type == "tool_start":
            tool_id = self._tool_call_id(event.payload)
            self._pending_tool_results.pop(tool_id, None)
            if self._has_tool_input(event.payload):
                emitted.append((self._tool_use_message(event.payload), True))
            else:
                self._pending_tool_starts[tool_id] = dict(event.payload)
        elif event.type == "tool_update":
            tool_id = self._tool_call_id(event.payload)
            self._pending_tool_results[tool_id] = dict(event.payload)
            pending_start = self._pending_tool_starts.get(tool_id)
            if pending_start is not None and self._has_tool_input(
                event.payload,
            ):
                emitted.append(
                    (
                        self._tool_use_message(
                            self._merge_tool_payloads(
                                pending_start,
                                event.payload,
                            ),
                        ),
                        True,
                    ),
                )
                self._pending_tool_starts.pop(tool_id, None)
        elif event.type == "tool_end":
            tool_id = self._tool_call_id(event.payload)
            pending_start = self._pending_tool_starts.pop(tool_id, None)
            pending = self._pending_tool_results.pop(tool_id, None)
            merged_pending = self._merge_tool_payloads(
                pending_start,
                pending or {},
            )
            if pending_start is not None:
                emitted.append(
                    (
                        self._tool_use_message(
                            self._merge_tool_payloads(
                                pending_start,
                                pending or event.payload,
                            ),
                        ),
                        True,
                    ),
                )
            emitted.append(
                (
                    self._tool_result_message(
                        self._merge_tool_payloads(
                            merged_pending,
                            event.payload,
                        ),
                    ),
                    True,
                ),
            )
        elif event.type == "plan_update":
            emitted.append(
                (self._text_message(self._format_plan(event.payload)), True),
            )
        elif event.type == "permission_request":
            emitted.append(
                (
                    self._text_message(
                        str(event.payload.get("summary") or ""),
                    ),
                    True,
                ),
            )
        elif event.type == "permission_resolved":
            emitted.append(
                (
                    self._text_message(
                        str(event.payload.get("summary") or ""),
                    ),
                    True,
                ),
            )
        elif event.type == "error":
            emitted.append(
                (
                    self._text_message(
                        str(event.payload.get("message") or "ACP run failed"),
                    ),
                    True,
                ),
            )

        return emitted

    def finalize(self) -> list[tuple[Msg, bool]]:
        """Flush any buffered assistant output when the run stops."""
        logger.debug(
            "ACP projector: finalize, buffer_len=%d, msg_id=%s",
            len(self._assistant_buffer),
            self._assistant_message_id,
        )
        flushed = self._flush_assistant(last=True)
        if self.show_tool_calls:
            for payload in self._pending_tool_starts.values():
                flushed.append((self._tool_use_message(payload), True))
            for payload in self._pending_tool_results.values():
                flushed.append((self._tool_result_message(payload), True))
        self._pending_tool_starts.clear()
        self._pending_tool_results.clear()
        logger.debug(
            "ACP projector: finalize flushed %d messages, new_msg_id=%s",
            len(flushed),
            self._assistant_message_id,
        )
        return flushed

    def _flush_assistant(self, *, last: bool) -> list[tuple[Msg, bool]]:
        if not self._assistant_buffer:
            logger.debug(
                "ACP projector: _flush_assistant empty buffer, msg_id=%s",
                self._assistant_message_id,
            )
            return []
        message = self._assistant_message(self._assistant_buffer)
        old_id = self._assistant_message_id
        if last:
            self._assistant_buffer = ""
            self._assistant_message_id = f"acp_assistant_{uuid4().hex}"
        # Use INFO level for last=True to track message completion
        log_fn = logger.info if last else logger.debug
        log_fn(
            "ACP projector: _flush_assistant last=%s, "
            "msg_id=%s->%s, content=%s...",
            last,
            old_id[:16],
            self._assistant_message_id[:16],
            str(message.content)[:30],
        )
        return [(message, last)]

    def _assistant_message(self, text: str) -> Msg:
        message = Msg(
            name="Friday",
            role="assistant",
            content=[TextBlock(type="text", text=text)],
            metadata={"source": "acp", "harness": self.harness},
        )
        message.id = self._assistant_message_id
        return message

    def _text_message(self, text: str) -> Msg:
        return Msg(
            name="Friday",
            role="assistant",
            content=[TextBlock(type="text", text=text)],
            metadata={"source": "acp", "harness": self.harness},
        )

    def _tool_use_message(self, payload: dict[str, Any]) -> Msg:
        tool_call_id = self._tool_call_id(payload)
        tool_name = str(payload.get("name") or "external_agent_tool")
        tool_input = payload.get("input")
        if not isinstance(tool_input, dict):
            tool_input = {
                "raw": payload.get("raw") or self._stringify(payload),
            }

        return Msg(
            name="Friday",
            role="assistant",
            content=[
                {
                    "type": "tool_use",
                    "id": tool_call_id,
                    "name": tool_name,
                    "input": tool_input,
                    "raw_input": "",
                },
            ],
            metadata={"source": "acp", "harness": self.harness},
        )

    def _tool_result_message(self, payload: dict[str, Any]) -> Msg:
        tool_call_id = self._tool_call_id(payload)
        tool_name = str(payload.get("name") or "external_agent_tool")
        output = payload.get("output")
        if output is None:
            status = payload.get("status")
            detail = payload.get("detail") or payload.get("summary")
            parts = [part for part in [status, detail] if part]
            output = "\n".join(str(part) for part in parts) or self._stringify(
                payload,
            )
        elif not isinstance(output, str):
            output = self._stringify(output)

        return Msg(
            name="system",
            role="system",
            content=[
                {
                    "type": "tool_result",
                    "id": tool_call_id,
                    "name": tool_name,
                    "output": output,
                },
            ],
            metadata={"source": "acp", "harness": self.harness},
        )

    def _tool_call_id(self, payload: dict[str, Any]) -> str:
        return str(
            payload.get("id")
            or payload.get("toolCallId")
            or f"acp_tool_{uuid4().hex}",
        )

    def _merge_tool_payloads(
        self,
        pending: dict[str, Any] | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not pending:
            return payload

        merged = dict(pending)
        for key, value in payload.items():
            if key == "name" and merged.get("name"):
                continue
            if (
                key == "input"
                and isinstance(merged.get("input"), dict)
                and isinstance(value, dict)
            ):
                merged["input"] = {
                    **merged["input"],
                    **{
                        item_key: item_value
                        for item_key, item_value in value.items()
                        if item_value not in (None, "")
                    },
                }
                continue
            if value not in (None, "", {}):
                merged[key] = value
            elif key not in merged:
                merged[key] = value
        return merged

    @staticmethod
    def _has_tool_input(payload: dict[str, Any]) -> bool:
        tool_input = payload.get("input")
        return isinstance(tool_input, dict) and bool(tool_input)

    def _format_plan(self, payload: dict[str, Any]) -> str:
        plan = (
            payload.get("plan")
            or payload.get("steps")
            or payload.get("items")
            or payload
        )
        if isinstance(plan, list):
            lines = ["ACP plan update:"]
            for item in plan:
                if isinstance(item, dict):
                    label = (
                        item.get("label")
                        or item.get("title")
                        or item.get("description")
                        or self._stringify(item)
                    )
                    status = item.get("status") or "pending"
                else:
                    label = str(item)
                    status = "pending"
                mark = (
                    "x"
                    if str(status).lower() in {"done", "completed", "finished"}
                    else " "
                )
                lines.append(f"- [{mark}] {label}")
            return "\n".join(lines)
        return "ACP plan update:\n" + self._stringify(plan)

    def _format_commands(self, payload: dict[str, Any]) -> str:
        commands = (
            payload.get("commands")
            or payload.get("availableCommands")
            or payload
        )
        if isinstance(commands, list):
            command_list = ", ".join(
                str(item.get("name") if isinstance(item, dict) else item)
                for item in commands
            )
            return f"Available commands update: {command_list}"
        return "Available commands update:\n" + self._stringify(commands)

    def _format_usage(self, payload: dict[str, Any]) -> str:
        return "Usage update:\n" + self._stringify(payload)

    def _stringify(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, indent=2)
