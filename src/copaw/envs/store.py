# -*- coding: utf-8 -*-
"""Reading and writing environment variables.

Persistence strategy (two layers):

1. **envs.json** – canonical store, survives process restarts.
2. **os.environ** – injected into the current Python process so that
   ``os.getenv()`` and child subprocesses (``subprocess.run``, etc.)
   can read them immediately.
"""
from __future__ import annotations

import json
import os
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)
from typing import Optional

from ..constant import WORKING_DIR


def _resolve_envs_json_path() -> Path:
    raw = os.environ.get("COPAW_ENVS_FILE", "envs.json").strip() or "envs.json"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (WORKING_DIR / path).expanduser()
    return path.resolve()


_ENVS_JSON = _resolve_envs_json_path()
_LEGACY_ENVS_JSON = Path(__file__).resolve().parent / "envs.json"


def _migrate_legacy_envs(path: Path) -> None:
    """Migrate legacy envs.json from package dir to working dir once."""
    if path.is_file():
        return
    if _LEGACY_ENVS_JSON.resolve() == path.resolve():
        return
    if not _LEGACY_ENVS_JSON.is_file():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(_LEGACY_ENVS_JSON, path)
        path.chmod(0o600)
    except OSError:
        logger.warning("Failed to migrate legacy envs.json to %s", path)


def get_envs_json_path() -> Path:
    """Return the default envs.json path."""
    return _ENVS_JSON


# ------------------------------------------------------------------
# os.environ helpers
# ------------------------------------------------------------------


def _apply_to_environ(envs: dict[str, str]) -> None:
    """Set every key/value into ``os.environ``."""
    for key, value in envs.items():
        os.environ[key] = value


def _remove_from_environ(key: str) -> None:
    """Remove *key* from ``os.environ`` if present."""
    os.environ.pop(key, None)


def _sync_environ(
    old: dict[str, str],
    new: dict[str, str],
) -> None:
    """Synchronise ``os.environ``: set *new*, remove stale *old*."""
    for key in old:
        if key not in new:
            _remove_from_environ(key)
    _apply_to_environ(new)


# ------------------------------------------------------------------
# JSON persistence
# ------------------------------------------------------------------


def load_envs(
    path: Optional[Path] = None,
) -> dict[str, str]:
    """Load env vars from envs.json."""
    if path is None:
        path = get_envs_json_path()
    _migrate_legacy_envs(path)
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items()}
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


def save_envs(
    envs: dict[str, str],
    path: Optional[Path] = None,
) -> None:
    """Write env vars to envs.json and sync to ``os.environ``."""
    old = load_envs(path)

    if path is None:
        path = get_envs_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(envs, fh, indent=2, ensure_ascii=False)

    _sync_environ(old, envs)


def set_env_var(
    key: str,
    value: str,
) -> dict[str, str]:
    """Set a single env var. Returns updated dict."""
    envs = load_envs()
    envs[key] = value
    save_envs(envs)
    return envs


def delete_env_var(key: str) -> dict[str, str]:
    """Delete a single env var. Returns updated dict."""
    envs = load_envs()
    envs.pop(key, None)
    save_envs(envs)
    return envs


def load_envs_into_environ() -> dict[str, str]:
    """Load envs.json and apply all entries to ``os.environ``.

    Call this once at application startup so that environment
    variables persisted from a previous session are available
    immediately.
    """
    envs = load_envs()
    _apply_to_environ(envs)
    return envs
