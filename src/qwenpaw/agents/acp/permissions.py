# -*- coding: utf-8 -*-
"""ACP permission handling."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import PermissionResolution, SuspendedPermission

BLOCKED_COMMAND_PATTERNS = (
    "rm -rf /",
    "sudo rm -rf",
    "mkfs",
    "dd if=",
)


class ACPPermissionAdapter:
    def __init__(self, cwd: str):
        self.cwd = str(Path(cwd).expanduser().resolve())

    async def resolve_permission(
        self,
        *,
        agent: str,
        request_payload: dict[str, Any],
    ) -> PermissionResolution:
        tool_call = self._extract_tool_call(request_payload)
        options = request_payload.get("options")
        if not isinstance(options, list):
            options = []

        if self._is_hard_blocked(tool_call):
            return PermissionResolution(
                result={"outcome": {"outcome": "cancelled"}},
            )

        return PermissionResolution(
            suspended=SuspendedPermission(
                request_id=None,
                payload=request_payload,
                options=list(options),
                agent=agent,
                tool_name=self._tool_name(tool_call),
                tool_kind=self._tool_kind(tool_call),
                target=self._target(tool_call),
                action=self._action(tool_call),
                summary=self._summary(tool_call),
                command=self._command(tool_call),
                paths=self._paths(tool_call),
                requires_user_confirmation=True,
            ),
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
            candidate = str(opt.get("optionId") or "").strip()
            if candidate == key:
                return opt
        return None

    def selected_result(self, option: dict[str, Any] | None) -> dict[str, Any]:
        if option is None:
            return {"outcome": {"outcome": "cancelled"}}
        option_id = option.get("optionId") or "selected"
        return {
            "outcome": {
                "outcome": "selected",
                "optionId": option_id,
            },
        }

    def _extract_tool_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        tool_call = payload.get("toolCall")
        if isinstance(tool_call, dict):
            return tool_call
        return {}

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
        raw_input = tool_call.get("rawInput")
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
