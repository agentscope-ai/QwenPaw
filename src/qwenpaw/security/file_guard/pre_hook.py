# -*- coding: utf-8 -*-
"""File guard pre-hook for tool calls."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from .shell_sandbox import prepare_sandboxed_shell_command
from .whitelist import FileWhitelistPolicy

FileAccessKind = Literal["read", "write"]

_TOOL_ACCESS_PARAMS: dict[str, tuple[FileAccessKind, tuple[str, ...]]] = {
    "read_file": ("read", ("file_path",)),
    "write_file": ("write", ("file_path",)),
    "edit_file": ("write", ("file_path",)),
    "append_file": ("write", ("file_path",)),
    "send_file_to_user": ("read", ("file_path",)),
    "view_text_file": ("read", ("file_path", "path")),
    "write_text_file": ("write", ("file_path", "path")),
}


@dataclass
class FileGuardPreHookResult:
    """Pre-hook result for one tool call."""

    allowed: bool
    message: str = ""
    warning: str = ""


def is_file_guard_whitelist_enabled() -> bool:
    """Return whether whitelist-based pre-hook should run."""
    return FileWhitelistPolicy.from_config().enabled


def _working_dir_value(tool_input: dict[str, Any]) -> str:
    raw = tool_input.get("cwd")
    if isinstance(raw, str) and raw.strip():
        return raw
    wd = get_current_workspace_dir() or WORKING_DIR
    return str(Path(wd))


def _allow_or_reason(
    policy: FileWhitelistPolicy,
    path: str,
    access: FileAccessKind,
) -> tuple[bool, str]:
    if policy.allows(path, access):
        return True, ""
    return (
        False,
        "Access blocked by file whitelist policy: "
        f"{access} is not allowed for '{path}'.",
    )


def _check_regular_file_tools(
    tool_name: str,
    tool_input: dict[str, Any],
    policy: FileWhitelistPolicy,
) -> FileGuardPreHookResult:
    config = _TOOL_ACCESS_PARAMS.get(tool_name)
    if config is None:
        return FileGuardPreHookResult(allowed=True)
    access_mode, params = config
    denied: list[str] = []
    for key in params:
        val = tool_input.get(key)
        if not isinstance(val, str) or not val.strip():
            continue
        allowed, _reason = _allow_or_reason(policy, val, access_mode)
        if not allowed:
            denied.append(val)
    if not denied:
        return FileGuardPreHookResult(allowed=True)
    detail = "\n".join(f"- {p}" for p in denied[:10])
    return FileGuardPreHookResult(
        allowed=False,
        message=(
            "File tool call blocked by whitelist policy.\n"
            f"Tool: {tool_name}\n"
            f"Access: {access_mode}\n"
            "Denied paths:\n"
            f"{detail}"
        ),
    )


def apply_file_guard_pre_hook(
    tool_call: dict[str, Any],
) -> FileGuardPreHookResult:
    """Apply whitelist pre-hook and mutate tool input when needed."""
    tool_name = str(tool_call.get("name", ""))
    tool_input = tool_call.get("input")
    if not isinstance(tool_input, dict):
        return FileGuardPreHookResult(allowed=True)

    policy = FileWhitelistPolicy.from_config()

    if tool_name == "execute_shell_command":
        command = tool_input.get("command")
        if not isinstance(command, str) or not command.strip():
            return FileGuardPreHookResult(allowed=True)
        prepared = prepare_sandboxed_shell_command(
            command=command,
            working_dir=_working_dir_value(tool_input),
        )
        if prepared.blocked_reason:
            return FileGuardPreHookResult(
                allowed=False,
                message=(
                    "Shell sandbox preparation failed.\n"
                    f"{prepared.blocked_reason}"
                ),
            )
        tool_input["command"] = prepared.command
        return FileGuardPreHookResult(
            allowed=True,
            warning=prepared.warning,
        )

    if not policy.enabled:
        return FileGuardPreHookResult(allowed=True)

    return _check_regular_file_tools(tool_name, tool_input, policy)
