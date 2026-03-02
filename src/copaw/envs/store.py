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
from pathlib import Path
from typing import Optional

_ENVS_DIR = Path(__file__).resolve().parent
_ENVS_JSON = _ENVS_DIR / "envs.json"
# Security-sensitive envs should come from process/system environment,
# not persisted envs.json.
_PROTECTED_BOOTSTRAP_KEYS = frozenset({"COPAW_WORKING_DIR"})


def get_envs_json_path() -> Path:
    """Return the default envs.json path."""
    return _ENVS_JSON


# ------------------------------------------------------------------
# os.environ helpers
# ------------------------------------------------------------------


def _apply_to_environ(
    envs: dict[str, str],
    *,
    overwrite: bool = True,
) -> None:
    """Set key/value pairs into ``os.environ``.

    Args:
        envs: Key-value mapping to inject.
        overwrite: When False, existing process env values take precedence.
    """
    for key, value in envs.items():
        if not overwrite and key in os.environ:
            continue
        os.environ[key] = value


def _remove_from_environ(key: str) -> None:
    """Remove *key* from ``os.environ`` if present."""
    os.environ.pop(key, None)


def _sync_environ(
    old: dict[str, str],
    new: dict[str, str],
) -> None:
    """Synchronise ``os.environ``: set *new*, remove stale *old*."""
    for key, old_value in old.items():
        if key not in new and os.environ.get(key) == old_value:
            _remove_from_environ(key)
    _apply_to_environ(new, overwrite=True)


# ------------------------------------------------------------------
# JSON persistence
# ------------------------------------------------------------------


def load_envs(
    path: Optional[Path] = None,
) -> dict[str, str]:
    """Load env vars from envs.json."""
    if path is None:
        path = get_envs_json_path()
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
    envs = {
        key: value
        for key, value in envs.items()
        if key not in _PROTECTED_BOOTSTRAP_KEYS
    }
    # Do not override explicit runtime/system env vars.
    _apply_to_environ(envs, overwrite=False)
    return envs
