# -*- coding: utf-8 -*-
"""ACP permission handling."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

from .core import SuspendedPermission

BLOCKED_COMMAND_PATTERNS = (
    "rm -rf /",
    "sudo rm -rf",
    "mkfs",
    "dd if=",
)


class ACPPermissionAdapter:
    def __init__(self, cwd: str):
        self.cwd = str(Path(cwd).expanduser().resolve())

    def build_suspended_permission(
        self,
        *,
        agent: str,
        tool_call: Any,
        options: list[Any],
    ) -> SuspendedPermission:
        tool_call_payload = self._tool_call_payload(tool_call)
        option_payloads: list[dict[str, Any]] = []
        for option in options:
            payload = self._option_payload(option)
            if payload is not None:
                option_payloads.append(payload)
        return SuspendedPermission(
            payload={
                "toolCall": tool_call_payload,
                "options": option_payloads,
            },
            options=option_payloads,
            agent=agent,
            tool_name=self._tool_name(tool_call_payload),
            tool_kind=self._tool_kind(tool_call_payload),
            target=self._target(tool_call_payload),
            action=self._action(tool_call_payload),
            summary=self._summary(tool_call_payload),
            command=self._command(tool_call_payload),
            paths=self._paths(tool_call_payload),
            requires_user_confirmation=True,
        )

    def resolve_option_by_id(
        self,
        options: list[dict[str, Any]],
        option_id: str,
    ) -> dict[str, Any] | None:
        key = option_id.strip()
        if not key:
            return None
        for opt in options:
            if not isinstance(opt, dict):
                continue
            candidate = str(opt.get("optionId") or opt.get("option_id") or "").strip()
            if candidate == key:
                return opt
        return None

    def selected_response(
        self,
        option: dict[str, Any] | None,
    ) -> RequestPermissionResponse:
        if option is None:
            return self.cancelled_response()
        option_id = str(option.get("optionId") or option.get("option_id") or "selected")
        return RequestPermissionResponse(
            outcome=AllowedOutcome(option_id=option_id, outcome="selected"),
        )

    def cancelled_response(self) -> RequestPermissionResponse:
        return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))

    def is_hard_blocked(self, tool_call: Any) -> bool:
        return self._is_hard_blocked(self._tool_call_payload(tool_call))

    def _tool_call_payload(self, tool_call: Any) -> dict[str, Any]:
        if isinstance(tool_call, dict):
            return dict(tool_call)
        model_dump = getattr(tool_call, "model_dump", None)
        if callable(model_dump):
            data = model_dump(by_alias=True, exclude_none=True)
            if isinstance(data, dict):
                return data
        return {}

    def _option_payload(self, option: Any) -> dict[str, Any] | None:
        if isinstance(option, dict):
            return dict(option)
        model_dump = getattr(option, "model_dump", None)
        if callable(model_dump):
            data = model_dump(by_alias=True, exclude_none=True)
            if isinstance(data, dict):
                return data
        return None

    def _tool_name(self, tool_call: dict[str, Any]) -> str:
        title = tool_call.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return "external-agent"

    def _tool_kind(self, tool_call: dict[str, Any]) -> str:
        kind = tool_call.get("kind")
        if isinstance(kind, str) and kind.strip():
            return kind.strip().lower()
        return "other"

    def _action(self, tool_call: dict[str, Any]) -> str | None:
        kind = tool_call.get("kind")
        if isinstance(kind, str) and kind.strip():
            return kind.strip().lower()
        return None

    def _summary(self, tool_call: dict[str, Any]) -> str | None:
        title = tool_call.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return None

    def _command(self, tool_call: dict[str, Any]) -> str | None:
        raw_input = tool_call.get("rawInput") or tool_call.get("raw_input")
        if isinstance(raw_input, dict):
            command = raw_input.get("command")
            if isinstance(command, str) and command.strip():
                return command.strip()
            argv = raw_input.get("args") or raw_input.get("argv")
            if isinstance(argv, list):
                parts = [
                    str(item).strip() for item in argv if str(item).strip()
                ]
                if parts:
                    return " ".join(parts)
        return None

    def _paths(self, tool_call: dict[str, Any]) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()

        def add_path(value: Any) -> None:
            if not isinstance(value, str):
                return
            text = value.strip()
            if not text or text in seen:
                return
            seen.add(text)
            paths.append(text)

        for location in tool_call.get("locations") or []:
            if isinstance(location, dict):
                add_path(location.get("path"))

        for content in tool_call.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "diff":
                add_path(content.get("path"))

        raw_input = tool_call.get("rawInput")
        if raw_input is None:
            raw_input = tool_call.get("raw_input")
        if isinstance(raw_input, dict):
            add_path(raw_input.get("path"))

        return paths[:5]

    def _target(self, tool_call: dict[str, Any]) -> str | None:
        paths = self._paths(tool_call)
        if len(paths) == 1:
            return self._display_path(paths[0])
        if len(paths) > 1:
            return f"{len(paths)} files"
        command = self._command(tool_call)
        if command:
            return command
        return self._summary(tool_call)

    def _display_path(self, value: str) -> str:
        try:
            path = Path(value).expanduser()
            cwd_path = Path(self.cwd)
            if path.is_absolute():
                try:
                    return str(path.resolve().relative_to(cwd_path))
                except ValueError:
                    return str(path)
            return value
        except (OSError, RuntimeError, ValueError):
            return value

    def _is_hard_blocked(self, tool_call: dict[str, Any]) -> bool:
        command = str(self._command(tool_call) or "").lower()
        if any(pattern in command for pattern in BLOCKED_COMMAND_PATTERNS):
            return True

        for path_value in self._paths(tool_call):
            candidate = Path(path_value).expanduser()
            if not candidate.is_absolute():
                candidate = Path(self.cwd) / candidate
            try:
                resolved = candidate.resolve()
            except OSError:
                return True
            if not str(resolved).startswith(self.cwd):
                return True
        return False
