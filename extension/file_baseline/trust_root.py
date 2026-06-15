# -*- coding: utf-8
"""Block Agent writes to integrity-protection state (trust root) paths."""
from __future__ import annotations

import re
from pathlib import Path

from .paths import integrity_protection_root, resolve_under_working_dir
from .write_context import is_file_baseline_maintenance

_INTEGRITY_SEGMENT = "integrity-protection"

_WRITE_INTENT = re.compile(
    r"(?:"
    r">>|>>|>|"
    r"Set-Content|Add-Content|Out-File|WriteAllText|WriteAllBytes|"
    r"Remove-Item|Clear-Content|"
    r"Copy-Item|Move-Item|Rename-Item|"
    r"\battrib\b|\bdel\b|\berase\b|\bfsutil\b|"
    r"\btee\b|\bcp\b|\bmv\b|\bcopy\b|\bmove\b|\bren\b|"
    r"\.write_text\s*\(|\.write_bytes\s*\(|"
    r"open\s*\([^)]*['\"](?:[wa]|r[bt]?\+|[rwab]?\+)|"
    r"os\.open\s*\([^)]*(?:O_WRONLY|O_RDWR|O_APPEND|O_TRUNC|O_CREAT)|"
    r"os\.writev?\s*\(|os\.truncate\s*\(|os\.ftruncate\s*\(|"
    r"os\.remove\s*\(|os\.unlink\s*\(|"
    r"SetFileAttributes[AW]?\s*\(|CreateFile[AW]?\s*\(|WriteFile\s*\(|"
    r"DeleteFile[AW]?\s*\(|MoveFileEx[AW]?\s*\(|ReplaceFile[AW]?\s*\(|"
    r"CopyFile[AW]?\s*\(|SetEndOfFile\s*\("
    r")",
    re.IGNORECASE,
)

_QUOTED_PATH = re.compile(r"""['"]([^'"]+)['"]""")
_INTEGRITY_PATH_FRAGMENT = re.compile(
    r"([A-Za-z0-9._~:/\\-]*integrity-protection[^\s'\"),;]*)",
    re.IGNORECASE,
)


def is_under_integrity_protection(working_dir: Path, absolute: Path) -> bool:
    rel = resolve_under_working_dir(working_dir, absolute)
    if rel is None:
        return False
    parts = rel.parts
    return bool(parts) and parts[0] == _INTEGRITY_SEGMENT


def agent_integrity_write_blocked(
    working_dir: Path,
    absolute_path: str | Path,
    *,
    cwd: Path | None = None,
) -> str | None:
    """Return an error message when Agent must not write this path, else None."""
    if is_file_baseline_maintenance():
        return None
    resolved = _resolve_absolute(working_dir, absolute_path, cwd=cwd)
    if resolved is None:
        return None
    if is_under_integrity_protection(working_dir, resolved):
        rel = resolve_under_working_dir(working_dir, resolved)
        return (
            "Agent cannot modify integrity-protection state "
            f"({rel or resolved}). Baseline metadata is operator-maintained only."
        )
    return None


_INTEGRITY_WRITE_SIGNAL = re.compile(
    r"(?:"
    r"\.write\s*\(|\.write_text\s*\(|\.write_bytes\s*\(|"
    r">>|>>|>|WriteAllText|WriteAllBytes|Remove-Item|Clear-Content|"
    r"\battrib\b|\bdel\b|\berase\b|\bfsutil\b|"
    r"open\s*\([^)]*,\s*['\"](?:[wa]|r[bt]?\+|[rwab]?\+)|"
    r"os\.open\s*\([^)]*(?:O_WRONLY|O_RDWR|O_APPEND|O_TRUNC|O_CREAT)|"
    r"os\.writev?\s*\(|os\.truncate\s*\(|os\.ftruncate\s*\(|"
    r"os\.remove\s*\(|os\.unlink\s*\(|"
    r"SetFileAttributes[AW]?\s*\(|CreateFile[AW]?\s*\(|WriteFile\s*\(|"
    r"DeleteFile[AW]?\s*\(|MoveFileEx[AW]?\s*\(|ReplaceFile[AW]?\s*\(|"
    r"CopyFile[AW]?\s*\(|SetEndOfFile\s*\("
    r")",
    re.IGNORECASE,
)


def detect_integrity_state_write_in_text(
    working_dir: Path,
    text: str,
    *,
    cwd: Path | None = None,
) -> list[str]:
    """Return working-dir-relative integrity-protection paths targeted for writes."""
    if not text.strip():
        return []
    if _INTEGRITY_SEGMENT not in text.lower():
        return []
    if not _INTEGRITY_WRITE_SIGNAL.search(text):
        return []

    hits: list[str] = []
    seen: set[str] = set()
    base = cwd or working_dir

    if _INTEGRITY_SEGMENT in text.lower():
        for match in _QUOTED_PATH.finditer(text):
            candidate = _maybe_integrity_rel(working_dir, match.group(1), base=base)
            if candidate and candidate not in seen:
                seen.add(candidate)
                hits.append(candidate)
        for match in _INTEGRITY_PATH_FRAGMENT.finditer(text):
            candidate = _maybe_integrity_rel(working_dir, match.group(1), base=base)
            if candidate and candidate not in seen:
                seen.add(candidate)
                hits.append(candidate)

    for token in re.split(r"[\s|&;]+", text):
        token = token.strip().strip("'\"")
        if not token or _INTEGRITY_SEGMENT not in token.lower():
            continue
        candidate = _maybe_integrity_rel(working_dir, token, base=base)
        if candidate and candidate not in seen:
            seen.add(candidate)
            hits.append(candidate)

    if not hits:
        hits = ["integrity-protection/"]

    return hits


def _resolve_absolute(
    working_dir: Path,
    path: str | Path,
    *,
    cwd: Path | None = None,
) -> Path | None:
    raw = Path(path).expanduser()
    try:
        if raw.is_absolute():
            return raw.resolve(strict=False)
        base = (cwd or working_dir).resolve(strict=False)
        return (base / raw).resolve(strict=False)
    except OSError:
        return None


def _maybe_integrity_rel(
    working_dir: Path,
    raw_path: str,
    *,
    base: Path,
) -> str | None:
    cleaned = raw_path.strip().strip("'\"")
    if not cleaned or _INTEGRITY_SEGMENT not in cleaned.lower():
        return None
    absolute = _resolve_absolute(working_dir, cleaned, cwd=base)
    if absolute is None:
        return None
    if not is_under_integrity_protection(working_dir, absolute):
        return None
    rel = resolve_under_working_dir(working_dir, absolute)
    return rel.as_posix() if rel is not None else None
