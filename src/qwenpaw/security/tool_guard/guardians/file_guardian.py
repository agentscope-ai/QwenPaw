# -*- coding: utf-8 -*-
"""Path-based sensitive file guardian.

Blocks tool calls that target files explicitly listed in a sensitive-file set.
"""
from __future__ import annotations

import ntpath
import os
import re
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

_SECRET_DIR_CURRENT_NAME = ".qwenpaw.secret"
_SECRET_DIR_LEGACY_NAME = ".copaw.secret"


def _with_platform_trailing_sep(path: str | Path) -> str:
    """Return path string with a trailing separator for current platform."""
    raw = str(path)
    if raw.endswith(("/", "\\")):
        return raw
    return raw + ("\\" if os.name == "nt" else "/")


_COMPAT_SECRET_DIRS: tuple[str, ...] = (
    _with_platform_trailing_sep(SECRET_DIR),
    _with_platform_trailing_sep(Path.home() / _SECRET_DIR_LEGACY_NAME),
    _with_platform_trailing_sep(Path.home() / _SECRET_DIR_CURRENT_NAME),
)


def ensure_file_guard_paths(paths: Iterable[str]) -> list[str]:
    """Return *paths* plus compatibility secret dirs, de-duplicated."""
    merged = [p for p in paths if p]
    merged.extend(_COMPAT_SECRET_DIRS)
    # Keep order stable while removing duplicates.
    return list(dict.fromkeys(merged))


def _default_deny_dirs() -> list[str]:
    """Default sensitive dirs with legacy/current compatibility."""
    return ensure_file_guard_paths([])


_DEFAULT_DENY_DIRS: list[str] = _default_deny_dirs()

_SHELL_REDIRECT_OPERATORS = frozenset(
    {">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>", "<", "<<", "<<<"},
)
# Longest-first for startswith: avoids `>` matching before `>>`.
_REDIRECT_OPS_BY_LEN = tuple(
    sorted(_SHELL_REDIRECT_OPERATORS, key=len, reverse=True),
)
_NESTED_SHELL_COMMANDS = frozenset(
    {
        "bash",
        "sh",
        "zsh",
        "fish",
        "cmd",
        "cmd.exe",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
    },
)
_POWERSHELL_COMMAND_FLAGS = frozenset(
    {
        "-command",
        "-c",
        "/command",
        "/c",
    },
)
_INLINE_FILE_ACCESS_PATTERNS = (
    re.compile(r"\bopen\(\s*(['\"])(?P<path>.+?)\1"),
    re.compile(r"\bPath\(\s*(['\"])(?P<path>.+?)\1"),
    re.compile(r"\breadFileSync\(\s*(['\"])(?P<path>.+?)\1"),
    re.compile(r"\bwriteFileSync\(\s*(['\"])(?P<path>.+?)\1"),
)
_WINDOWS_PERCENT_ENV_RE = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")
_POWERSHELL_ENV_RE = re.compile(r"\$env:([A-Za-z_][A-Za-z0-9_]*)")
_MAX_NESTED_SHELL_DEPTH = 3


def _workspace_root() -> Path:
    """Return current workspace root for resolving relative paths."""
    return Path(get_current_workspace_dir() or WORKING_DIR)


# Windows path recognition helpers --------------------------------------------
# Drive-letter absolute path, e.g. C:\foo, D:/bar
_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
# Drive-letter only (no separator), e.g. C:foo – treated as relative on drive C
_WIN_DRIVE_ONLY_RE = re.compile(r"^[A-Za-z]:")
# UNC path, e.g. \\server\share\...
_WIN_UNC_RE = re.compile(r"^\\\\[^\\/?%*:|\"<>]+[\\/][^\\/?%*:|\"<>]+")


def _is_windows_style_path(raw: str) -> bool:
    """Heuristic check: does *raw* look like a Windows-style path string?"""
    if not raw:
        return False
    if _WIN_DRIVE_RE.match(raw):
        return True
    if _WIN_UNC_RE.match(raw):
        return True
    # Leading .\ / ..\ / \ (root of current drive)
    if raw.startswith((".\\", "..\\", "\\")):
        return True
    # Any backslash acting as a segment separator is a reasonable signal.
    # Note: this can false-positive on POSIX shell escapes, but those tokens
    # are rarely meaningful as real filesystem paths anyway.
    if "\\" in raw:
        return True
    return False


def _canonicalize_windows_path(raw: str) -> str:
    """Normalize a Windows-style path to a canonical lowercase forward-slash
    string that is comparable across call sites.

    Uses :mod:`ntpath` so it works on POSIX hosts too (important for tests
    and for mixed environments).
    """
    expanded = os.path.expanduser(raw) if raw.startswith("~") else raw
    if not ntpath.isabs(expanded):
        root = str(_workspace_root())
        expanded = ntpath.join(root, expanded)
    normalized = ntpath.normpath(expanded)
    # Canonical form: forward slashes + lowercase (NTFS is case-insensitive).
    return normalized.replace("\\", "/").lower()


def _expand_shell_path_vars(raw: str) -> str:
    """Expand common shell path variables before path normalization.

    ``os.path.expandvars`` handles POSIX ``$HOME`` / ``${HOME}`` on all
    platforms.  File guard also needs to reason about Windows shell forms while
    running tests or servers on POSIX, so expand ``%USERPROFILE%`` and
    PowerShell ``$env:USERPROFILE`` explicitly.
    """

    def replace_percent(match: re.Match[str]) -> str:
        name = match.group(1)
        return os.environ.get(name, match.group(0))

    def replace_powershell(match: re.Match[str]) -> str:
        name = match.group(1)
        return os.environ.get(name, match.group(0))

    expanded = _WINDOWS_PERCENT_ENV_RE.sub(replace_percent, raw)
    expanded = _POWERSHELL_ENV_RE.sub(replace_powershell, expanded)
    return os.path.expandvars(expanded)


def _normalize_path(raw_path: str) -> str:
    """Normalize *raw_path* to a canonical absolute path string.

    Supports both POSIX and Windows-style paths. When running on Windows
    or when *raw_path* clearly looks like a Windows path, the result uses
    forward slashes and is lowercased to reflect NTFS case-insensitivity.
    """
    if not isinstance(raw_path, str):
        return ""
    raw = raw_path.strip()
    if not raw:
        return ""

    if os.name == "nt" or _is_windows_style_path(raw):
        return _canonicalize_windows_path(raw)

    p = Path(raw).expanduser()
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
        return ensure_file_guard_paths(configured)
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
    """Heuristic check whether a shell token is likely a file path.

    Recognizes POSIX-style paths (``/``, ``./``, ``../``, ``~``) as well as
    Windows-style paths (drive-letter, UNC, ``.\\``/``..\\``, or
    backslash-containing tokens).
    """
    if not token or token.startswith("-"):
        return False
    lowered = token.lower()
    if lowered.startswith(("http://", "https://", "ftp://", "data:")):
        return False
    if lowered.startswith(_MIME_PREFIXES):
        return False

    posix_signal = token.startswith(("~", "/", "./", "../")) or "/" in token
    windows_signal = any(
        (
            _WIN_DRIVE_RE.match(token),
            _WIN_DRIVE_ONLY_RE.match(token),
            _WIN_UNC_RE.match(token),
            token.startswith((".\\", "..\\", "\\")),
            "\\" in token,
        ),
    )
    return bool(posix_signal or windows_signal)


def _strip_surrounding_quotes(token: str) -> str:
    """Strip a single matching pair of ASCII quotes around *token*."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token


def _sanitize_path_candidate(raw: str) -> str:
    """Normalize shell/param quoting artifacts around a path candidate."""
    candidate = raw.strip()
    # Handle escaped boundary quotes such as: \"C:\\Users\\x\"
    if len(candidate) >= 4 and (
        (candidate.startswith('\\"') and candidate.endswith('\\"'))
        or (candidate.startswith("\\'") and candidate.endswith("\\'"))
    ):
        candidate = candidate[2:-2]
    return _strip_surrounding_quotes(candidate)


def _extract_attached_redirect_path(token: str) -> str | None:
    """Return redirected path for attached forms like ``2>err.log``."""
    for op in _REDIRECT_OPS_BY_LEN:
        if token.startswith(op) and len(token) > len(op):
            possible_path = token[len(op) :]
            if _looks_like_path_token(possible_path):
                return possible_path
            return None
    return None


def _shell_token_streams(command: str) -> list[list[str]]:
    """Return token streams using POSIX and Windows-friendly shlex modes."""
    streams: list[list[str]] = []
    for use_posix in (os.name != "nt", os.name == "nt"):
        try:
            tokens = shlex.split(command, posix=use_posix)
        except ValueError:
            continue
        if not use_posix:
            tokens = [_strip_surrounding_quotes(t) for t in tokens]
        streams.append(tokens)

    # Always include the opposite mode too.  This lets POSIX hosts correctly
    # inspect Windows paths with backslashes, and Windows hosts inspect POSIX
    # shell snippets in tests or copied commands.
    for use_posix in (True, False):
        try:
            tokens = shlex.split(command, posix=use_posix)
        except ValueError:
            continue
        if not use_posix:
            tokens = [_strip_surrounding_quotes(t) for t in tokens]
        if tokens not in streams:
            streams.append(tokens)

    if not streams:
        streams.append(command.split())
    return streams


def _dedupe(values: Iterable[str]) -> list[str]:
    """Return values with stable de-duplication."""
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _looks_like_shell_c_flag(token: str) -> bool:
    """Return True for shell flags that make the next token executable code."""
    lowered = token.lower()
    if lowered in _POWERSHELL_COMMAND_FLAGS:
        return True
    if not lowered.startswith("-"):
        return False
    # bash/sh/zsh accept compact combinations such as -c, -lc, -exc.
    return "c" in lowered[1:]


def _extract_nested_shell_commands(tokens: list[str]) -> list[str]:
    """Extract command strings passed to nested shell interpreters."""
    if not tokens:
        return []
    executable = Path(tokens[0].lower()).name
    executable = ntpath.basename(executable)
    if executable not in _NESTED_SHELL_COMMANDS:
        return []

    nested: list[str] = []
    for i, token in enumerate(tokens[1:], start=1):
        if _looks_like_shell_c_flag(_sanitize_path_candidate(token)):
            if i + 1 < len(tokens):
                nested.append(
                    " ".join(
                        _sanitize_path_candidate(part)
                        for part in tokens[i + 1 :]
                    ),
                )
            break
    return nested


def _extract_inline_file_access_paths(command: str) -> list[str]:
    """Extract paths from common inline interpreter file APIs."""
    candidates: list[str] = []
    for pattern in _INLINE_FILE_ACCESS_PATTERNS:
        for match in pattern.finditer(command):
            path = match.group("path")
            if path:
                candidates.append(_sanitize_path_candidate(path))
    return candidates


def _extract_paths_from_shell_command(
    command: str,
    *,
    _depth: int = 0,
) -> list[str]:
    """Extract candidate file paths from a shell command string.

    On Windows, :func:`shlex.split` is invoked with ``posix=False`` so that
    backslashes in paths like ``C:\\Users\\foo`` are not interpreted as POSIX
    escape characters and dropped from the token stream.
    """
    candidates: list[str] = _extract_inline_file_access_paths(command)

    for tokens in _shell_token_streams(command):
        if _depth < _MAX_NESTED_SHELL_DEPTH:
            for nested_command in _extract_nested_shell_commands(tokens):
                candidates.extend(
                    _extract_paths_from_shell_command(
                        nested_command,
                        _depth=_depth + 1,
                    ),
                )

        i = 0
        while i < len(tokens):
            token = _sanitize_path_candidate(tokens[i])

            # Handle separated redirection operators: `cat a > out.txt`
            if token in _SHELL_REDIRECT_OPERATORS:
                if i + 1 < len(tokens):
                    next_token = tokens[i + 1]
                    next_token = _sanitize_path_candidate(next_token)
                    if _looks_like_path_token(next_token):
                        candidates.append(next_token)
                i += 1
                continue

            # Handle attached redirection: `>out.txt`, `2>err.log`, `<in.txt`
            attached_path = _extract_attached_redirect_path(token)
            if attached_path is not None:
                candidates.append(_sanitize_path_candidate(attached_path))
                i += 1
                continue

            if _looks_like_path_token(token):
                candidates.append(token)
            i += 1

    return _dedupe(candidates)


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
        """Return True when *abs_path* hits sensitive file/dir constraints.

        Uses string prefix matching on the canonical normalized paths so the
        check behaves consistently for both POSIX and Windows-style paths
        (including on hosts where :class:`pathlib.Path` cannot parse the
        target's native separators).
        """
        if not abs_path:
            return False
        if abs_path in self._sensitive_files:
            return True
        for dir_path in self._sensitive_dirs:
            if not dir_path:
                continue
            # Normalize both sides to have no trailing separator, then test
            # for either exact equality or a proper segment-boundary prefix.
            trimmed = dir_path.rstrip("/\\")
            if not trimmed:
                continue
            if abs_path == trimmed:
                return True
            if abs_path.startswith(trimmed + "/"):
                return True
            if abs_path.startswith(trimmed + "\\"):
                return True
        return False

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
        normalized_input = _sanitize_path_candidate(raw_value)
        normalized_input = _expand_shell_path_vars(normalized_input)
        abs_path = _normalize_path(normalized_input)
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
