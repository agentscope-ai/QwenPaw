# -*- coding: utf-8 -*-
"""Helpers for serving downloaded local media back to the web console."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlparse

from ..constant import WORKING_DIR
from .channels.utils import file_url_to_local_path

MEDIA_ROUTE_PREFIX = "/api/media"


def _build_media_roots() -> tuple[tuple[str, Path], ...]:
    """Build the set of local media roots that the web console may serve."""
    roots: list[tuple[str, Path]] = [
        ("workspace", (WORKING_DIR / "media").resolve()),
    ]
    home_root = (Path("~/.copaw").expanduser().resolve() / "media").resolve()
    if home_root != roots[0][1]:
        roots.append(("home", home_root))
    return tuple(roots)


MEDIA_ROOTS = _build_media_roots()
MEDIA_ROOT = MEDIA_ROOTS[0][1]


def _resolve_relative_to_media_root(
    path: Path,
) -> Optional[tuple[str, Path, Path]]:
    """Return (alias, root, relative_path) for the matching media root."""
    for alias, root in MEDIA_ROOTS:
        try:
            relative_path = path.relative_to(root)
        except ValueError:
            continue
        return alias, root, relative_path
    return None


def _resolve_under_root(root: Path, relative_path: str) -> Optional[Path]:
    """Resolve a relative path under a root, rejecting traversal."""
    try:
        candidate = (root / relative_path).resolve()
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None

    if not candidate.is_file():
        return None

    return candidate


def to_public_media_url(url_or_path: Optional[str]) -> Optional[str]:
    """Map a local media path under a known media root to a same-origin URL."""
    if not isinstance(url_or_path, str):
        return None

    value = url_or_path.strip()
    if not value:
        return None

    parsed = urlparse(value)
    if parsed.scheme in ("http", "https", "data"):
        return value

    local_path = file_url_to_local_path(value)
    if not local_path:
        return value

    try:
        resolved = Path(local_path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return value

    match = _resolve_relative_to_media_root(resolved)
    if match is None:
        return value

    alias, _, relative_path = match
    quoted = quote(relative_path.as_posix(), safe="/")
    return f"{MEDIA_ROUTE_PREFIX}/{alias}/{quoted}"


def resolve_public_media_path(media_path: str) -> Optional[Path]:
    """Resolve a request path under a known media root, rejecting traversal."""
    if not media_path:
        return None

    normalized = media_path.strip().lstrip("/")
    if not normalized:
        return None

    first, _, remainder = normalized.partition("/")
    for alias, root in MEDIA_ROOTS:
        if first == alias:
            if not remainder:
                return None
            return _resolve_under_root(root, remainder)

    for _, root in MEDIA_ROOTS:
        candidate = _resolve_under_root(root, normalized)
        if candidate is not None:
            return candidate

    return None
