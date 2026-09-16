# -*- coding: utf-8 -*-
"""ACP permission handling."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

from .core import SuspendedPermission

# Argument keys that carry a filesystem path, most specific first.  Mirrors
# the vocabulary already used for display parsing in
# ``ACPHostedClient._tool_detail`` and in ``_TOOL_FILE_PARAMS``.
_PATH_ARG_KEYS = (
    "path",
    "file_path",
    "filePath",
    "abs_path",
    "absolute_path",
    "target_file",
    "notebook_path",
    "old_path",
    "new_path",
)

# Keys whose values a permission-time delta extends rather than replaces:
# the update usually carries only what the user is being asked about, while
# the tool arguments arrived earlier in the ToolCallStart.
_MERGEABLE_LIST_KEYS = frozenset({"content", "locations"})

# How many paths a permission prompt lists before falling back to a count.
# Display-only: the boundary check in ``_is_hard_blocked`` must see every
# path, so ``_paths`` itself is uncapped.
_MAX_DISPLAY_PATHS = 5


def _is_blank(value: Any) -> bool:
    """Return True for values that carry nothing worth merging."""
    if value is None:
        return True
    return isinstance(value, (str, list, dict, tuple)) and not value


def _content_block_text(content: Any) -> str | None:
    """Return the text of a ``type == "content"`` tool-call content block."""
    if not isinstance(content, dict) or content.get("type") != "content":
        return None
    block = content.get("content")
    if not isinstance(block, dict):
        return None
    text = block.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def _json_object(text: str) -> dict[str, Any] | None:
    """Parse *text* as a JSON object, or return None.

    The leading-``{`` guard keeps ordinary prose — such as a runner's
    human-readable approval description — out of the JSON parser.
    """
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _command_from_args(args: dict[str, Any]) -> str | None:
    """Return the shell command described by tool arguments, if any."""
    command = args.get("command")
    if isinstance(command, str) and command.strip():
        return command.strip()
    argv = args.get("args") or args.get("argv")
    if isinstance(argv, list):
        parts = [str(item).strip() for item in argv if str(item).strip()]
        if parts:
            return " ".join(parts)
    return None


class ACPPermissionAdapter:
    def __init__(self, cwd: str, *, trusted: bool = False):
        self.cwd = str(Path(cwd).expanduser().resolve())
        self._trusted = trusted

    def build_suspended_permission(
        self,
        *,
        agent: str,
        tool_call: Any,
        options: list[Any],
        prior_state: Any = None,
    ) -> SuspendedPermission:
        tool_call_payload = self._merged_payload(tool_call, prior_state)
        command = self._command_with_prior(tool_call, prior_state)
        paths = self._paths(tool_call_payload)
        target = self._target(tool_call_payload)
        if not paths and command:
            target = command
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
            target=target,
            action=self._action(tool_call_payload),
            summary=self._summary(tool_call_payload),
            command=command,
            paths=paths[:_MAX_DISPLAY_PATHS],
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
            candidate = str(
                opt.get("optionId") or opt.get("option_id") or "",
            ).strip()
            if candidate == key:
                return opt
        return None

    def selected_response(
        self,
        option: dict[str, Any] | None,
    ) -> RequestPermissionResponse:
        if option is None:
            return self.cancelled_response()
        option_id = str(
            option.get("optionId") or option.get("option_id") or "selected",
        )
        return RequestPermissionResponse(
            outcome=AllowedOutcome(option_id=option_id, outcome="selected"),
        )

    def cancelled_response(self) -> RequestPermissionResponse:
        return RequestPermissionResponse(
            outcome=DeniedOutcome(outcome="cancelled"),
        )

    def is_hard_blocked(
        self,
        tool_call: Any,
        *,
        prior_state: Any = None,
    ) -> bool:
        return self._is_hard_blocked(
            self._merged_payload(tool_call, prior_state),
            command=self._command_with_prior(tool_call, prior_state),
        )

    def _merged_payload(
        self,
        tool_call: Any,
        prior_state: Any = None,
    ) -> dict[str, Any]:
        """Return *tool_call* as a payload, filled in from *prior_state*.

        ``session/request_permission`` carries a ``ToolCallUpdate``, whose
        only required field is ``toolCallId``.  Runners that send the full
        argument set once — in ``ToolCallStart`` — leave the permission-time
        update with no path and no command to inspect, so the boundary check
        would see nothing and pass.  *prior_state* is the accumulated
        ``ToolCallView`` for the same id; its values fill only the gaps, and
        list-valued ``content``/``locations`` are concatenated with the
        permission-time values first, so current arguments take precedence
        while earlier arguments remain available as a fallback.
        """
        payload = self._tool_call_payload(tool_call)
        if prior_state is None:
            return payload
        prior = self._tool_call_payload(prior_state)
        if not prior:
            return payload
        merged = dict(prior)
        for key, value in payload.items():
            if _is_blank(value):
                continue
            existing = merged.get(key)
            # ``ToolCallView`` keeps these as tuples, so accept both.
            if key in _MERGEABLE_LIST_KEYS and isinstance(
                existing,
                (list, tuple),
            ):
                extra = value if isinstance(value, (list, tuple)) else [value]
                merged[key] = [*extra, *existing]
            else:
                merged[key] = value
        return merged

    def _argument_dicts(
        self,
        tool_call: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return tool arguments a runner embedded in content text blocks.

        kimi-cli never populates ``rawInput``; it serialises the tool
        arguments as a JSON string inside a ``type == "content"`` text block
        (``kimi_cli/acp/session.py:387-398``).  Non-JSON text is skipped, so
        a runner's prose approval description is never mistaken for
        arguments.
        """
        args: list[dict[str, Any]] = []
        for content in tool_call.get("content") or []:
            text = _content_block_text(content)
            if text is None:
                continue
            parsed = _json_object(text)
            if parsed is not None:
                args.append(parsed)
        return args

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
        command = self._argument_command(tool_call)
        if command is not None:
            return command
        return self._title_command(tool_call)

    def _argument_command(self, tool_call: dict[str, Any]) -> str | None:
        """Return a command carried by structured tool arguments."""
        raw_input = tool_call.get("rawInput")
        if raw_input is None:
            raw_input = tool_call.get("raw_input")
        candidates: list[dict[str, Any]] = []
        if isinstance(raw_input, dict):
            candidates.append(raw_input)
        candidates.extend(self._argument_dicts(tool_call))
        for args in candidates:
            command = _command_from_args(args)
            if command is not None:
                return command
        return None

    def _title_command(self, tool_call: dict[str, Any]) -> str | None:
        """Use an execute call's title when no structured command exists."""
        # Fallback: when no argument source carries a command/argv, use title
        # for execute-kind calls.  Title is human-readable text (e.g.
        # "Shutdown the dev server") so hard-block regexes like \bshutdown\b
        # may false-positive here.  This is an accepted trade-off: blocking a
        # benign title is safer than letting an unvetted command through.
        kind = tool_call.get("kind")
        title = tool_call.get("title")
        if (
            isinstance(kind, str)
            and kind.strip().lower() == "execute"
            and isinstance(title, str)
            and title.strip()
        ):
            return title.strip()
        return None

    def _command_with_prior(
        self,
        tool_call: Any,
        prior_state: Any = None,
    ) -> str | None:
        """Prefer the permission request's command over accumulated state."""
        payload = self._tool_call_payload(tool_call)
        command = self._argument_command(payload)
        if command is not None:
            return command

        prior = self._tool_call_payload(prior_state)
        command = self._argument_command(prior)
        if command is not None:
            return command

        return self._title_command(payload) or self._title_command(prior)

    def _paths(self, tool_call: dict[str, Any]) -> list[str]:
        """Return every filesystem path this tool call mentions.

        Uncapped on purpose: ``_is_hard_blocked`` iterates this list, so
        truncating it here would let an out-of-workspace target slip through
        whenever it is not among the first few paths of a multi-file call.
        Truncation belongs at the display boundary instead — see
        ``_MAX_DISPLAY_PATHS``.
        """
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

        def add_from_args(args: dict[str, Any]) -> None:
            for key in _PATH_ARG_KEYS:
                value = args.get(key)
                if isinstance(value, list):
                    for item in value:
                        add_path(item)
                else:
                    add_path(value)

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
            add_from_args(raw_input)

        for args in self._argument_dicts(tool_call):
            add_from_args(args)

        return paths

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

    def _is_hard_blocked(
        self,
        tool_call: dict[str, Any],
        *,
        command: str | None = None,
    ) -> bool:
        from qwenpaw.security.tool_guard.safety_checks import (
            is_command_destructive,
            is_path_outside_boundary,
        )

        if command is None:
            command = self._command(tool_call)
        command = str(command or "")
        # Pass ACP session cwd so relative rm targets (e.g. ``../``) resolve
        # against the same root as path-boundary checks.
        if is_command_destructive(command, cwd=self.cwd):
            return True

        for path_value in self._paths(tool_call):
            # self.cwd is resolve()'d in __init__ — skip re-resolving it.
            if is_path_outside_boundary(
                path_value,
                self.cwd,
                cwd_is_resolved=True,
            ):
                return True
        return False
