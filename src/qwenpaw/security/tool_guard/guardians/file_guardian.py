# -*- coding: utf-8 -*-
"""Path-based sensitive file guardian.

Blocks tool calls that target files explicitly listed in a sensitive-file set.
"""
from __future__ import annotations

import shlex
import uuid
from pathlib import Path
from typing import Any, Iterable

from ....config.context import get_current_workspace_dir
from ....constant import SECRET_DIR, WORKING_DIR
from ..models import GuardFinding, GuardSeverity, GuardThreatCategory
from . import BaseToolGuardian

# Tool -> parameter names that carry file paths.
_TOOL_FILE_PARAMS: dict[str, tuple[str, ...]] = {
    "read_file": ("file_path",),
    "write_file": ("file_path",),
    "edit_file": ("file_path",),
    "append_file": ("file_path",),
    "send_file_to_user": ("file_path",),
    # agentscope built-ins (may be enabled by users)
    "view_text_file": ("file_path", "path"),
    "write_text_file": ("file_path", "path"),
}

_DEFAULT_DENY_DIRS: list[str] = [str(SECRET_DIR) + "/"]

_SHELL_REDIRECT_OPERATORS = frozenset(
    {">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>", "<", "<<", "<<<"},
)
# Longest-first for startswith: avoids `>` matching before `>>`.
_REDIRECT_OPS_BY_LEN = tuple(
    sorted(_SHELL_REDIRECT_OPERATORS, key=len, reverse=True),
)


def _workspace_root() -> Path:
    """Return current workspace root for resolving relative paths."""
    return Path(get_current_workspace_dir() or WORKING_DIR)


def _normalize_path(raw_path: str) -> str:
    """Normalize *raw_path* to a canonical absolute path string."""
    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = _workspace_root() / p
    return str(p.resolve(strict=False))


def _is_file_guard_enabled() -> bool:
    """Check ``security.file_guard.enabled`` from config."""
    try:
        from qwenpaw.config import load_config

        return bool(load_config().security.file_guard.enabled)
    except Exception:
        return True


def _load_sensitive_files_from_config() -> list[str]:
    """Load ``security.file_guard.sensitive_files`` from config.json.

    When the configured list is empty (fresh install), fall back to
    ``_DEFAULT_DENY_DIRS`` so the secret directory is protected by
    default.
    """
    try:
        from qwenpaw.config import load_config

        configured = list(
            load_config().security.file_guard.sensitive_files or [],
        )
        return configured if configured else list(_DEFAULT_DENY_DIRS)
    except Exception:
        return list(_DEFAULT_DENY_DIRS)


_MIME_PREFIXES = (
    "text/",
    "application/",
    "image/",
    "audio/",
    "video/",
    "multipart/",
    "message/",
    "font/",
    "model/",
)


def _looks_like_path_token(token: str) -> bool:
    """Heuristic check whether a shell token is likely a file path."""
    if not token or token.startswith("-"):
        return False
    lowered = token.lower()
    if lowered.startswith(("http://", "https://", "ftp://", "data:")):
        return False
    if lowered.startswith(_MIME_PREFIXES):
        return False
    if token.startswith(("~", "/", "./", "../")):
        return True
    if "/" in token:
        return True
    return False


def _extract_paths_from_shell_command(command: str) -> list[str]:
    """Extract candidate file paths from a shell command string."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        # Best-effort fallback when quotes are malformed.
        tokens = command.split()

    candidates: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]

        # Handle separated redirection operators: `cat a > out.txt`
        if token in _SHELL_REDIRECT_OPERATORS:
            if i + 1 < len(tokens):
                next_token = tokens[i + 1]
                if _looks_like_path_token(next_token):
                    candidates.append(next_token)
            i += 1
            continue

        # Handle attached redirection: `>out.txt`, `2>err.log`, `<in.txt`
        attached = False
        for op in _REDIRECT_OPS_BY_LEN:
            if token.startswith(op) and len(token) > len(op):
                possible_path = token[len(op) :]
                if _looks_like_path_token(possible_path):
                    candidates.append(possible_path)
                attached = True
                break
        if attached:
            i += 1
            continue

        if _looks_like_path_token(token):
            candidates.append(token)
        i += 1

    # Stable de-duplication.
    deduped: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        deduped.append(c)
    return deduped


class FilePathToolGuardian(BaseToolGuardian):
    """Guardian that blocks access to configured sensitive files."""

    def __init__(
        self,
        *,
        sensitive_files: Iterable[str] | None = None,
    ) -> None:
        super().__init__(name="file_path_tool_guardian", always_run=True)
        self._enabled: bool = _is_file_guard_enabled()
        self._sensitive_files: set[str] = set()
        self._sensitive_dirs: set[str] = set()
        self.set_sensitive_files(_load_sensitive_files_from_config())
        if sensitive_files is not None:
            for path in sensitive_files:
                self.add_sensitive_file(path)

    @property
    def sensitive_files(self) -> set[str]:
        """Return a copy of currently blocked absolute sensitive paths."""
        return set(self._sensitive_files | self._sensitive_dirs)

    def set_sensitive_files(self, paths: Iterable[str]) -> None:
        """Replace sensitive-file set with *paths*."""
        normalized_files: set[str] = set()
        normalized_dirs: set[str] = set()
        for path in paths:
            if not path:
                continue
            normalized = _normalize_path(path)
            p = Path(normalized)
            # Existing directories and explicit slash-terminated entries are
            # both treated as directory guards.
            if p.is_dir() or path.endswith(("/", "\\")):
                normalized_dirs.add(normalized)
            else:
                normalized_files.add(normalized)
        self._sensitive_files = normalized_files
        self._sensitive_dirs = normalized_dirs

    def add_sensitive_file(self, path: str) -> None:
        """Add one sensitive file path to block list."""
        normalized = _normalize_path(path)
        p = Path(normalized)
        if p.is_dir() or path.endswith(("/", "\\")):
            self._sensitive_dirs.add(normalized)
            return
        self._sensitive_files.add(normalized)

    def remove_sensitive_file(self, path: str) -> bool:
        """Remove one sensitive file path. Returns True if it existed."""
        normalized = _normalize_path(path)
        if normalized in self._sensitive_files:
            self._sensitive_files.remove(normalized)
            return True
        if normalized in self._sensitive_dirs:
            self._sensitive_dirs.remove(normalized)
            return True
        return False

    def reload(self) -> None:
        """Reload enabled state and sensitive-file set from config."""
        self._enabled = _is_file_guard_enabled()
        self.set_sensitive_files(_load_sensitive_files_from_config())

    def _is_sensitive(self, abs_path: str) -> bool:
        """Return True when *abs_path* hits sensitive file/dir constraints."""
        path_obj = Path(abs_path)
        if abs_path in self._sensitive_files:
            return True
        return any(
            path_obj.is_relative_to(Path(dir_path))
            for dir_path in self._sensitive_dirs
        )

    def _make_finding(
        self,
        tool_name: str,
        param_name: str,
        raw_value: str,
        abs_path: str,
        *,
        snippet: str | None = None,
    ) -> GuardFinding:
        return GuardFinding(
            id=f"GUARD-{uuid.uuid4().hex}",
            rule_id="SENSITIVE_FILE_BLOCK",
            category=GuardThreatCategory.SENSITIVE_FILE_ACCESS,
            severity=GuardSeverity.HIGH,
            title="[HIGH] Access to sensitive file is blocked",
            description=(
                f"Tool '{tool_name}' attempted to access sensitive "
                f"file via parameter '{param_name}'."
            ),
            tool_name=tool_name,
            param_name=param_name,
            matched_value=raw_value,
            matched_pattern=abs_path,
            snippet=snippet or abs_path,
            remediation=(
                "Use a non-sensitive file path, or remove this path "
                "from security.file_guard.sensitive_files if needed."
            ),
            guardian=self.name,
            metadata={"resolved_path": abs_path},
        )

    def _check_value(
        self,
        tool_name: str,
        param_name: str,
        raw_value: str,
        findings: list[GuardFinding],
        *,
        snippet: str | None = None,
    ) -> None:
        """Check a single string value against sensitive paths."""
        abs_path = _normalize_path(raw_value)
        if self._is_sensitive(abs_path):
            findings.append(
                self._make_finding(
                    tool_name,
                    param_name,
                    raw_value,
                    abs_path,
                    snippet=snippet,
                ),
            )

    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> list[GuardFinding]:
        """Block tool call when targeted file path is sensitive.

        Checks all tools: known file tools use specific param names,
        shell commands get path extraction, and all other tools have
        every string parameter scanned for sensitive paths.
        """
        if not self._enabled:
            return []
        if not self._sensitive_files and not self._sensitive_dirs:
            return []

        findings: list[GuardFinding] = []

        # Shell commands: extract paths from the command string.
        if tool_name == "execute_shell_command":
            command = params.get("command")
            if not isinstance(command, str) or not command.strip():
                return findings
            for raw_path in _extract_paths_from_shell_command(command):
                self._check_value(
                    tool_name,
                    "command",
                    raw_path,
                    findings,
                    snippet=command,
                )
            return findings

        # Known file tools: check only the file-path parameters.
        known_params = _TOOL_FILE_PARAMS.get(tool_name)
        if known_params:
            for param_name in known_params:
                raw_value = params.get(param_name)
                if not isinstance(raw_value, str) or not raw_value.strip():
                    continue
                self._check_value(tool_name, param_name, raw_value, findings)
            return findings

        # All other tools: scan every string parameter that looks like a path.
        for param_name, param_value in params.items():
            if not isinstance(param_value, str) or not param_value.strip():
                continue
            if not _looks_like_path_token(param_value):
                continue
            self._check_value(tool_name, param_name, param_value, findings)

        return findings
