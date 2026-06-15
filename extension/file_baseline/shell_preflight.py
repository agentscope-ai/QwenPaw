# -*- coding: utf-8
"""Lightweight detection of agent shell/python writes to file-baseline-protected paths."""
from __future__ import annotations

import logging
import os
import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from .agent_write import resolve_protected_relative_path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .service import FileBaselineService

_SHELL_REDIRECTS = frozenset({">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>"})

_POWERSHELL_WRAPPER = re.compile(
    r"(?:^|[\s|&;])(?:powershell(?:\.exe)?|pwsh(?:\.exe)?)\b",
    re.IGNORECASE,
)

_POWERSHELL_COMMAND_ARG = re.compile(
    r"-(?:Command|c)\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)

# Explicit write / mutate-then-write patterns (not plain reads like Get-Content).
_SHELL_WRITE_INTENT = re.compile(
    r"(?:"
    r">>|>>|>|"
    r"Set-Content|Add-Content|Out-File|Clear-Content|"
    r"Remove-Item|"
    r"WriteAllText|WriteAllBytes|WriteAllLines|"
    r"AppendAllText|AppendAllBytes|AppendAllLines|"
    r"FileStream|StreamWriter|OpenWrite|"
    r"\[System\.IO\.File\]|IO\.File\]::|"
    r"Copy-Item|Move-Item|Rename-Item|"
    r"\battrib\b|"
    r"\bdel\b|\berase\b|\bfsutil\b|"
    r"-replace\b|"
    r"\btee\b|\bcp\b|\bmv\b|\bcopy\b|\bmove\b|"
    r"\bren\b"
    r")",
    re.IGNORECASE,
)

_PYTHON_WRITE_SIGNAL = re.compile(
    r"(?:"
    r"\.write_text\s*\(|\.write_bytes\s*\(|\.open\s*\([^)]*['\"](?:[wa]|r[bt]?\+|[rwab]?\+)|"
    r"open\s*\([^)]*['\"](?:[wa]|r[bt]?\+|[rwab]?\+)|"
    r"\bos\.open\s*\([^)]*(?:O_WRONLY|O_RDWR|O_APPEND|O_TRUNC|O_CREAT)|"
    r"\bos\.writev?\s*\(|"
    r"\bos\.fdopen\s*\([^)]*['\"](?:[wa]|r[bt]?\+|[rwab]?\+)"
    r")",
    re.IGNORECASE,
)

_PYTHON_MUTATE_SIGNAL = re.compile(
    r"(?:"
    r"\bos\.rename\s*\(|"
    r"\bos\.replace\s*\(|"
    r"\bos\.chmod\s*\(|"
    r"\bos\.truncate\s*\(|"
    r"\bos\.ftruncate\s*\(|"
    r"\bos\.remove\s*\(|"
    r"\bos\.unlink\s*\(|"
    r"\bshutil\.move\s*\(|"
    r"\bshutil\.copy2?\s*\(|"
    r"\bshutil\.copyfile\s*\(|"
    r"\bSetFileAttributes[AW]?\s*\(|"
    r"\bCreateFile[AW]?\s*\(|"
    r"\bWriteFile\s*\(|"
    r"\bDeleteFile[AW]?\s*\(|"
    r"\bMoveFileEx[AW]?\s*\(|"
    r"\bReplaceFile[AW]?\s*\(|"
    r"\bCopyFile[AW]?\s*\(|"
    r"\bSetEndOfFile\s*\(|"
    r"\.rename\s*\(|"
    r"\.replace\s*\(|"
    r"\.chmod\s*\(|"
    r"\.unlink\s*\(|"
    r"\.truncate\s*\("
    r")",
    re.IGNORECASE,
)

_QUOTED_PATH = re.compile(r"""['"]([^'"]+)['"]""")

_PYTHON_EXE = re.compile(
    r"(?:^|[\s|&;])(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?\b",
    re.IGNORECASE,
)

_PYTHON_C_ARG = re.compile(
    r"-(?:c|C)\s+(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[^\s]+)",
    re.DOTALL,
)


def _extract_python_inline_code(command: str) -> list[str]:
    codes: list[str] = []
    for match in _PYTHON_C_ARG.finditer(command):
        snippet = _strip_outer_quotes(match.group(1).strip())
        if snippet:
            codes.append(snippet)
    return codes


def _is_python_executable_token(token: str) -> bool:
    lowered = token.lower().strip("\"'")
    return lowered in {
        "python",
        "python3",
        "py",
        "python.exe",
        "python3.exe",
        "py.exe",
    } or lowered.startswith("python3.")


def _extract_python_script_paths(command: str) -> list[str]:
    use_posix = os.name != "nt"
    try:
        tokens = shlex.split(command, posix=use_posix)
    except ValueError:
        tokens = command.split()
    if not use_posix:
        tokens = [t.strip("'\"") for t in tokens]

    scripts: list[str] = []
    idx = 0
    while idx < len(tokens):
        if not _is_python_executable_token(tokens[idx]):
            idx += 1
            continue
        j = idx + 1
        while j < len(tokens):
            token = tokens[j]
            lowered = token.lower()
            if lowered in {"-c", "-m"}:
                break
            if lowered.startswith("-") and not lowered.endswith(".py"):
                j += 1
                continue
            cleaned = token.strip("'\"")
            if cleaned.lower().endswith(".py"):
                scripts.append(cleaned)
                break
            if not lowered.startswith("-"):
                break
            j += 1
        idx += 1
    return scripts


def _read_python_script_content(
    raw_path: str,
    *,
    workspace: Path,
    cwd: Path | None,
) -> str | None:
    absolute = _resolve_command_path(raw_path, workspace=workspace, cwd=cwd)
    if not absolute.is_file() or absolute.suffix.lower() != ".py":
        return None
    try:
        return absolute.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _python_shell_write_targets(
    service: "FileBaselineService",
    *,
    agent_id: str,
    command: str,
    cwd: Path | None,
) -> list[str]:
    if not _PYTHON_EXE.search(command):
        return []

    workspace = service.settings_store.resolve_workspace(agent_id)
    hits: list[str] = []
    seen: set[str] = set()

    for fragment in _iter_shell_script_fragments(command):
        for code in _extract_python_inline_code(fragment):
            for rel in detect_python_protected_write_targets(
                service,
                agent_id=agent_id,
                code=code,
                cwd=cwd,
            ):
                if rel not in seen:
                    seen.add(rel)
                    hits.append(rel)

        for raw_script in _extract_python_script_paths(fragment):
            content = _read_python_script_content(
                raw_script,
                workspace=workspace,
                cwd=cwd,
            )
            if not content:
                continue
            for rel in detect_python_protected_write_targets(
                service,
                agent_id=agent_id,
                code=content,
                cwd=cwd,
            ):
                if rel not in seen:
                    seen.add(rel)
                    hits.append(rel)

    return hits


def _looks_like_filename(token: str) -> bool:
    cleaned = token.strip().strip("'\"")
    if not cleaned or cleaned.startswith("-"):
        return False
    return "." in cleaned or cleaned.upper().endswith(".MD")


def _extract_shell_write_paths(command: str) -> list[str]:
    from qwenpaw.security.tool_guard.guardians.file_guardian import (
        _extract_paths_from_shell_command,
    )

    candidates = list(_extract_paths_from_shell_command(command))
    use_posix = os.name != "nt"
    try:
        tokens = shlex.split(command, posix=use_posix)
    except ValueError:
        tokens = command.split()
    if not use_posix:
        tokens = [t.strip("'\"") for t in tokens]

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in _SHELL_REDIRECTS and i + 1 < len(tokens):
            nxt = tokens[i + 1].strip("'\"")
            if _looks_like_filename(nxt):
                candidates.append(nxt)
            i += 2
            continue
        lowered = token.lower()
        if lowered in {"set-content", "out-file", "add-content"} and i + 1 < len(tokens):
            for j in range(i + 1, min(i + 6, len(tokens))):
                maybe = tokens[j].strip("'\"")
                if maybe.lower() in {"-path", "-filepath", "-literalpath"}:
                    continue
                if _looks_like_filename(maybe):
                    candidates.append(maybe)
                    break
        i += 1

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _strip_outer_quotes(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        return cleaned[1:-1]
    return cleaned


def _iter_shell_script_fragments(command: str) -> list[str]:
    """Return command segments to scan, including nested PowerShell -Command scripts."""
    text = (command or "").strip()
    if not text:
        return []

    fragments: list[str] = [text]
    if not _POWERSHELL_WRAPPER.search(text):
        return fragments

    match = _POWERSHELL_COMMAND_ARG.search(text)
    if not match:
        return fragments

    inner = _strip_outer_quotes(match.group(1).strip())
    if inner and inner not in fragments:
        fragments.append(inner)
    return fragments


def _path_name_variants(relative_path: str) -> tuple[str, ...]:
    rel = relative_path.replace("\\", "/")
    base = Path(rel).name
    return tuple(
        dict.fromkeys(
            item
            for item in (rel, base, f"./{rel}", f".\\{rel}")
            if item
        ),
    )


def _mentions_protected_path(text: str, relative_path: str) -> bool:
    for variant in _path_name_variants(relative_path):
        pattern = rf"(?<![\w./\\-]){re.escape(variant)}(?![\w.-])"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _resolve_command_path(raw_path: str, *, workspace: Path, cwd: Path | None) -> Path:
    candidate = raw_path.strip()
    if not candidate:
        return Path()
    expanded = Path(candidate).expanduser()
    if expanded.is_absolute():
        return expanded.resolve(strict=False)
    base = cwd if cwd is not None else workspace
    return (base / expanded).resolve(strict=False)


def _protected_targets_from_paths(
    service: "FileBaselineService",
    *,
    agent_id: str,
    raw_paths: list[str],
    cwd: Path | None = None,
) -> list[str]:
    if not service.is_enabled():
        return []
    workspace = service.settings_store.resolve_workspace(agent_id)
    rel_paths: list[str] = []
    seen: set[str] = set()
    for raw in raw_paths:
        absolute = _resolve_command_path(raw, workspace=workspace, cwd=cwd)
        if not absolute:
            continue
        rel = resolve_protected_relative_path(
            service,
            agent_id=agent_id,
            absolute_path=absolute,
        )
        if rel and rel not in seen:
            seen.add(rel)
            rel_paths.append(rel)
    return rel_paths


def detect_shell_protected_write_targets(
    service: "FileBaselineService",
    *,
    agent_id: str,
    command: str,
    cwd: Path | None = None,
) -> list[str]:
    """Return protected relative paths the shell command may write, or []."""
    if not service.is_enabled():
        return []

    settings = service.settings_store.load()
    protected = service.settings_store.effective_paths(settings, agent_id)
    if not protected:
        return []

    hits: list[str] = []
    seen: set[str] = set()

    for fragment in _iter_shell_script_fragments(command):
        text = fragment.strip()
        if not text or not _SHELL_WRITE_INTENT.search(text):
            continue

        for rel in protected:
            if rel in seen:
                continue
            if not _mentions_protected_path(text, rel):
                continue
            seen.add(rel)
            hits.append(rel)

        raw_paths = _extract_shell_write_paths(text)
        for resolved in _protected_targets_from_paths(
            service,
            agent_id=agent_id,
            raw_paths=raw_paths,
            cwd=cwd,
        ):
            if resolved not in seen:
                seen.add(resolved)
                hits.append(resolved)

    for rel in _python_shell_write_targets(
        service,
        agent_id=agent_id,
        command=command,
        cwd=cwd,
    ):
        if rel not in seen:
            seen.add(rel)
            hits.append(rel)

    return hits


def detect_python_protected_write_targets(
    service: "FileBaselineService",
    *,
    agent_id: str,
    code: str,
    cwd: Path | None = None,
) -> list[str]:
    """Return protected relative paths python code may write or mutate, or []."""
    text = (code or "").strip()
    baseline_enabled = service.is_enabled()
    write_signal = bool(_PYTHON_WRITE_SIGNAL.search(text)) if text else False
    mutate_signal = bool(_PYTHON_MUTATE_SIGNAL.search(text)) if text else False
    if not text or (not write_signal and not mutate_signal):
        logger.info(
            "file_baseline_python_preflight agent_id=%s baseline_enabled=%s "
            "write_signal=%s mutate_signal=%s rel_paths=[] reason=%s",
            agent_id,
            baseline_enabled,
            write_signal,
            mutate_signal,
            "empty_code" if not text else "no_threat_signal",
        )
        return []

    settings = service.settings_store.load()
    protected = service.settings_store.effective_paths(settings, agent_id)
    rel_paths: list[str] = []
    seen: set[str] = set()

    if write_signal or mutate_signal:
        for raw in [match.group(1) for match in _QUOTED_PATH.finditer(text)]:
            for rel in _protected_targets_from_paths(
                service,
                agent_id=agent_id,
                raw_paths=[raw],
                cwd=cwd,
            ):
                if rel not in seen:
                    seen.add(rel)
                    rel_paths.append(rel)

    if mutate_signal and protected:
        for rel in protected:
            if rel in seen:
                continue
            if _mentions_protected_path(text, rel):
                seen.add(rel)
                rel_paths.append(rel)

    logger.info(
        "file_baseline_python_preflight agent_id=%s baseline_enabled=%s "
        "write_signal=%s mutate_signal=%s rel_paths=%s cwd=%s",
        agent_id,
        baseline_enabled,
        write_signal,
        mutate_signal,
        rel_paths,
        str(cwd) if cwd is not None else None,
    )
    return rel_paths


def absolute_paths_for_relative(
    service: "FileBaselineService",
    *,
    agent_id: str,
    relative_paths: list[str],
) -> list[Path]:
    workspace = service.settings_store.resolve_workspace(agent_id)
    return [workspace / rel for rel in relative_paths]
