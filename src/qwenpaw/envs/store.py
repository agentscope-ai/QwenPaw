# -*- coding: utf-8 -*-
"""Reading and writing environment variables.

Persistence strategy (two layers):

1. **envs.json** – canonical store, survives process restarts.
2. **os.environ** – injected into the current Python process so that
   ``os.getenv()`` and child subprocesses (``subprocess.run``, etc.)
   can read them immediately.

Community credentials are scoped exceptions: stored encrypted in envs.json,
but never exported to os.environ or returned by generic environment APIs.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..constant import SECRET_DIR, WORKING_DIR
from ..security.secret_store import decrypt, encrypt, is_encrypted
from ..utils.io_utils import get_sync_path_lock, write_json_atomic

from .registry import (
    env_key_identity,
    is_bootstrap_protected_env_key,
    is_internal_env_key,
    is_managed_control_key,
    is_private_env_key,
    validate_unique_env_keys,
)

logger = logging.getLogger(__name__)


_BOOTSTRAP_WORKING_DIR = WORKING_DIR
_BOOTSTRAP_SECRET_DIR = SECRET_DIR

_ENVS_JSON = _BOOTSTRAP_SECRET_DIR / "envs.json"
_LEGACY_ENVS_JSON_CANDIDATES = (
    Path(__file__).resolve().parent / "envs.json",
    _BOOTSTRAP_WORKING_DIR / "envs.json",
)
_HOST_ENV_VALUES: dict[str, str | None] = {}


class PrivateEnvDecryptionError(RuntimeError):
    """A service credential cannot be decrypted with the current key."""


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        # Some systems/filesystems may not support chmod semantics.
        pass


def _prepare_secret_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(path.parent, 0o700)


def _migrate_legacy_envs_json(path: Path) -> None:
    """Copy old envs.json into secret dir once (best effort)."""
    if os.environ.get("QWENPAW_RUNTIME_ID") or path.is_file():
        return
    if path.exists() and not path.is_file():
        logger.error(
            "envs.json path exists but is not a regular file: %s",
            path,
        )
        return

    for legacy in _LEGACY_ENVS_JSON_CANDIDATES:
        if not legacy.is_file() or _same_path(legacy, path):
            continue
        try:
            _prepare_secret_parent(path)
            shutil.copy2(legacy, path)
            _chmod_best_effort(path, 0o600)
            return
        except OSError as exc:
            logger.warning(
                "Failed to migrate legacy envs.json from %s: %s",
                legacy,
                exc,
            )
            continue


def get_envs_json_path() -> Path:
    """Return envs.json path under SECRET_DIR."""
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
    seen: set[str] = set()
    for key, value in envs.items():
        if (
            is_internal_env_key(key)
            or is_managed_control_key(key)
            or is_private_env_key(key)
        ):
            continue
        identity = env_key_identity(key)
        if identity in seen:
            logger.warning(
                f"Skipping case-conflicting environment variable: {key}",
            )
            continue
        seen.add(identity)
        host_key = identity if os.name == "nt" else key
        if host_key not in _HOST_ENV_VALUES:
            _HOST_ENV_VALUES[host_key] = os.environ.get(key)
        if not overwrite and key in os.environ:
            continue
        os.environ[key] = value


def _remove_from_environ(key: str) -> None:
    """Restore the inherited value for *key*, or remove it if absent."""
    if is_internal_env_key(key):
        return
    host_key = env_key_identity(key) if os.name == "nt" else key
    inherited = _HOST_ENV_VALUES.get(host_key)
    if inherited is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = inherited


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


def _resolve_envs_path(path: Optional[Path]) -> tuple[Path, bool]:
    if path is None:
        return get_envs_json_path(), True
    return path, False


def _quarantine_corrupt_envs(path: Path, exc: Exception) -> None:
    source = path.resolve(strict=False) if path.is_symlink() else path
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantined = source.with_name(
        f"{source.name}.corrupt-{timestamp}-{secrets.token_hex(4)}",
    )
    try:
        source.rename(quarantined)
        _chmod_best_effort(quarantined, 0o600)
    except OSError as quarantine_exc:
        logger.error(
            "Failed to quarantine corrupt envs.json at %s: %s",
            path,
            quarantine_exc,
        )
        raise

    logger.warning(
        "Failed to load envs.json from %s; quarantined it to %s: %s",
        path,
        quarantined,
        exc,
    )


def _load_envs_unlocked(
    path: Path,
    *,
    fail_on_os_error: bool = False,
    strict_private: bool = False,
) -> dict[str, str]:
    if path.exists() and not path.is_file():
        logger.error(
            "envs.json path exists but is not a regular file: %s",
            path,
        )
        return {}
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("envs.json root must be a JSON object")
        raw = {k: str(v) for k, v in data.items()}
        has_plaintext = any(v and not is_encrypted(v) for v in raw.values())
        decrypted = {k: decrypt(v) for k, v in raw.items()}
        if strict_private and any(
            is_private_env_key(k) and is_encrypted(v) and decrypted[k] == v
            for k, v in raw.items()
        ):
            raise PrivateEnvDecryptionError(
                "Cannot decrypt community credentials",
            )
        if has_plaintext:
            _rewrite_encrypted(path, decrypted)
        return decrypted
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        _quarantine_corrupt_envs(path, exc)
    except OSError as exc:
        logger.warning(
            "Failed to read envs.json from %s due to OS error: %s",
            path,
            exc,
        )
        if fail_on_os_error:
            raise
    return {}


def load_envs(
    path: Optional[Path] = None,
) -> dict[str, str]:
    """Load non-private env vars, decrypting values transparently.

    Legacy plaintext values are detected and re-encrypted on disk.
    """
    path, migrate_legacy = _resolve_envs_path(path)
    with get_sync_path_lock(path):
        if migrate_legacy:
            _migrate_legacy_envs_json(path)
        return _public_envs(_load_envs_unlocked(path))


def _public_envs(envs: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in envs.items() if not is_private_env_key(k)}


def load_private_envs() -> dict[str, str]:
    """Internal service access; excluded from generic APIs and tool exports."""
    path = get_envs_json_path()
    with get_sync_path_lock(path):
        envs = _load_envs_unlocked(
            path,
            fail_on_os_error=True,
            strict_private=True,
        )
        return {k: v for k, v in envs.items() if is_private_env_key(k)}


def update_private_envs(updates: dict[str, str | None]) -> None:
    """Atomically update service credentials without exporting them."""
    if any(not is_private_env_key(key) for key in updates):
        raise ValueError("Not a private environment key")
    path = get_envs_json_path()
    with get_sync_path_lock(path):
        _migrate_legacy_envs_json(path)
        old = _load_envs_unlocked(path, fail_on_os_error=True)
        envs = dict(old)
        for key, value in updates.items():
            if value is None:
                envs.pop(key, None)
            else:
                envs[key] = value
        _save_envs_unlocked(envs, path, old=old, plaintext_keys=set(updates))


def _reject_private_updates(keys) -> None:
    if any(is_private_env_key(key) for key in keys):
        raise ValueError("Community credentials must use community settings")


def _rewrite_encrypted(path: Path, envs: dict[str, str]) -> None:
    """Re-write *envs* with all values encrypted (migration helper)."""
    try:
        encrypted = {
            k: encrypt(v) if v and not is_encrypted(v) else v
            for k, v in envs.items()
        }
        _prepare_secret_parent(path)
        _chmod_best_effort(path, 0o600)
        write_json_atomic(path, encrypted)
    except Exception as exc:
        logger.warning("Failed to re-encrypt envs.json: %s", exc)


def _save_envs_unlocked(
    envs: dict[str, str],
    path: Path,
    *,
    old: dict[str, str],
    plaintext_keys: set[str] | None = None,
) -> None:
    validate_unique_env_keys(envs)
    for key, value in envs.items():
        if is_internal_env_key(key):
            # Preserve legacy data during unrelated edits without injecting it.
            if key not in old or old[key] != value:
                raise ValueError(f"Environment variable is managed: {key}")
        elif is_managed_control_key(key):
            raise ValueError(f"Environment variable is managed: {key}")
    if path.exists() and not path.is_file():
        raise IsADirectoryError(
            f"envs.json path exists but is not a regular file: {path}",
        )
    _prepare_secret_parent(path)
    encrypted = {
        k: encrypt(v)
        if v and (k in (plaintext_keys or set()) or not is_encrypted(v))
        else v
        for k, v in envs.items()
    }
    # Keep untouched scoped ciphertext, including values encrypted with a
    # temporarily unavailable key. Plaintext passwords may start with ENC: too.
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        for key, value in envs.items():
            if (
                is_private_env_key(key)
                and key not in (plaintext_keys or set())
                and key in raw
                and value == old.get(key)
            ):
                encrypted[key] = raw[key]
    _chmod_best_effort(path, 0o600)
    write_json_atomic(path, encrypted)
    _sync_environ(old, envs)


def save_envs(
    envs: dict[str, str],
    path: Optional[Path] = None,
) -> None:
    """Write env vars to envs.json (encrypted) and sync to ``os.environ``."""
    _reject_private_updates(envs)
    path, migrate_legacy = _resolve_envs_path(path)
    with get_sync_path_lock(path):
        if migrate_legacy:
            _migrate_legacy_envs_json(path)
        old = _load_envs_unlocked(path, fail_on_os_error=True)
        private = {k: v for k, v in old.items() if is_private_env_key(k)}
        _save_envs_unlocked({**envs, **private}, path, old=old)


def set_env_var(
    key: str,
    value: str,
) -> dict[str, str]:
    """Set a single env var. Returns updated dict."""
    _reject_private_updates([key])
    path = get_envs_json_path()
    with get_sync_path_lock(path):
        _migrate_legacy_envs_json(path)
        old = _load_envs_unlocked(path, fail_on_os_error=True)
        envs = dict(old)
        envs[key] = value
        _save_envs_unlocked(envs, path, old=old)
        return _public_envs(envs)


def update_env_vars(updates: dict[str, str]) -> dict[str, str]:
    """Merge multiple values atomically and return the persisted mapping."""
    _reject_private_updates(updates)
    path = get_envs_json_path()
    with get_sync_path_lock(path):
        _migrate_legacy_envs_json(path)
        old = _load_envs_unlocked(path, fail_on_os_error=True)
        envs = {**old, **updates}
        _save_envs_unlocked(envs, path, old=old)
        return _public_envs(envs)


def delete_env_var(key: str) -> dict[str, str]:
    """Delete a single env var. Returns updated dict."""
    _reject_private_updates([key])
    path = get_envs_json_path()
    with get_sync_path_lock(path):
        _migrate_legacy_envs_json(path)
        old = _load_envs_unlocked(path, fail_on_os_error=True)
        envs = dict(old)
        envs.pop(key, None)
        _save_envs_unlocked(envs, path, old=old)
        return _public_envs(envs)


def load_envs_into_environ() -> dict[str, str]:
    """Load envs.json and apply bootstrap-safe entries to ``os.environ``.

    Call this once at application startup so that environment
    variables persisted from a previous session are available
    immediately. Protected keys are excluded from injection, and
    persisted values override existing process/system values.

    Returns:
        Non-private mapping from envs.json, including protected keys
        that are intentionally not injected into ``os.environ``.
    """
    from qwenpaw.backup._utils.safe_swap import (
        cleanup_stale_restore_artifacts,
        restore_process_lock,
    )

    with restore_process_lock():
        cleanup_stale_restore_artifacts(_BOOTSTRAP_SECRET_DIR)
        envs = load_envs()
    blocked_internal = [key for key in envs if is_internal_env_key(key)]
    for key in blocked_internal:
        logger.warning(
            f"Ignoring internally managed environment variable from "
            f"{get_envs_json_path()}: {key}",
        )
    bootstrap_envs = {
        key: value
        for key, value in envs.items()
        if not is_bootstrap_protected_env_key(key)
    }
    # Console-managed values override the inherited process environment.
    _apply_to_environ(bootstrap_envs, overwrite=True)
    return envs
