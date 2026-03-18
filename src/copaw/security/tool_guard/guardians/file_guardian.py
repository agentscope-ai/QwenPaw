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
from ....constant import WORKING_DIR
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

_TOOL_DENY_FILES: list[str] = ["/Users/gnip-tongyi/.copaw/test_file_access/"]

_SHELL_REDIRECT_OPERATORS = frozenset(
    {">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>", "<", "<<", "<<<"},
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


def _load_sensitive_files_from_config() -> list[str]:
    """Load ``security.tool_guard.sensitive_files`` from config.json."""
    try:
        from copaw.config import load_config

        cfg = load_config().security.tool_guard
        configured = list(getattr(cfg, "sensitive_files", []) or [])
        return [*list(_TOOL_DENY_FILES), *configured]
    except Exception:
        return list(_TOOL_DENY_FILES)


def _looks_like_path_token(token: str) -> bool:
    """Heuristic check whether a shell token is likely a path."""
    if not token or token.startswith("-"):
        return False
    lowered = token.lower()
    if lowered.startswith(("http://", "https://", "ftp://")):
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
        for op in _SHELL_REDIRECT_OPERATORS:
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
        super().__init__(name="file_path_tool_guardian")
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
        """Reload sensitive-file set from config."""
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

    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> list[GuardFinding]:
        """Block tool call when targeted file path is sensitive."""
        if not self._sensitive_files and not self._sensitive_dirs:
            return []

        findings: list[GuardFinding] = []

        if tool_name == "execute_shell_command":
            command = params.get("command")
            if not isinstance(command, str) or not command.strip():
                return findings
            for raw_path in _extract_paths_from_shell_command(command):
                abs_path = _normalize_path(raw_path)
                if not self._is_sensitive(abs_path):
                    continue
                findings.append(
                    GuardFinding(
                        id=f"GUARD-{uuid.uuid4().hex}",
                        rule_id="SENSITIVE_FILE_BLOCK",
                        category=GuardThreatCategory.SENSITIVE_FILE_ACCESS,
                        severity=GuardSeverity.HIGH,
                        title="[HIGH] Access to sensitive file is blocked",
                        description=(
                            f"Tool '{tool_name}' command contains a sensitive "
                            "file path."
                        ),
                        tool_name=tool_name,
                        param_name="command",
                        matched_value=raw_path,
                        matched_pattern=abs_path,
                        snippet=command,
                        remediation=(
                            "Use a non-sensitive file path, or remove this "
                            "path from security.tool_guard.sensitive_files "
                            "if needed."
                        ),
                        guardian=self.name,
                        metadata={"resolved_path": abs_path},
                    ),
                )
            return findings

        param_names = _TOOL_FILE_PARAMS.get(tool_name)
        if not param_names:
            return findings

        for param_name in param_names:
            raw_value = params.get(param_name)
            if not isinstance(raw_value, str) or not raw_value.strip():
                continue

            abs_path = _normalize_path(raw_value)
            if not self._is_sensitive(abs_path):
                continue

            findings.append(
                GuardFinding(
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
                    snippet=abs_path,
                    remediation=(
                        "Use a non-sensitive file path, or remove this path "
                        "from security.tool_guard.sensitive_files if needed."
                    ),
                    guardian=self.name,
                    metadata={"resolved_path": abs_path},
                ),
            )
        return findings
