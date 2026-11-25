# -*- coding: utf-8 -*-
"""Non-sensitive credential fingerprint for active Antigravity CLI logins."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

_KEYRING_SERVICE = "gemini"
_KEYRING_ACCOUNT = "antigravity"
_LOGIN_COLLECTION_PATH = "/org/freedesktop/secrets/collection/login"
_SSH_ENV_VARS = ("SSH_TTY", "SSH_CLIENT", "SSH_CONNECTION")
_GO_KEYRING_B64_PREFIX = "go-keyring-base64:"
_FINGERPRINT_TIMEOUT_SECONDS = 3.0
_CACHE_TTL_SECONDS = 2.0

_cached_fingerprint = ""
_cached_at = 0.0
_cache_epoch = 0


def reset_auth_fingerprint_cache() -> None:
    """Clear the cached active-account fingerprint."""
    global _cached_fingerprint, _cached_at, _cache_epoch
    _cached_fingerprint = ""
    _cached_at = 0.0
    _cache_epoch += 1


def _parse_credential_fingerprint(raw: str) -> str:
    """Hash stable account identity fields, ignoring short-lived tokens."""
    text = raw.strip()
    if not text:
        return ""
    if text.startswith(_GO_KEYRING_B64_PREFIX):
        encoded = text[len(_GO_KEYRING_B64_PREFIX) :].strip()
        if not encoded:
            return ""
        encoded += "=" * (-len(encoded) % 4)
        try:
            text = base64.b64decode(encoded).decode("utf-8")
        except Exception:  # pylint: disable=broad-except
            return ""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""

    auth_method = str(data.get("auth_method") or "").strip().lower()
    email = str(data.get("id_token_email") or "").strip().lower()
    token = data.get("token")
    refresh_token = (
        str(token.get("refresh_token") or "").strip()
        if isinstance(token, dict)
        else ""
    )
    if not (auth_method or email or refresh_token):
        return ""

    payload = f"{auth_method}\0{email}\0{refresh_token}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"agy:{digest}"


def _read_ssh_token_file(env: Mapping[str, str]) -> str:
    app_dir_raw = (env.get("ANTIGRAVITY_APP_DATA_DIR") or "").strip()
    if app_dir_raw:
        app_dir = Path(app_dir_raw).expanduser()
    else:
        home_raw = (env.get("HOME") or "").strip()
        home_dir = Path(home_raw).expanduser() if home_raw else Path.home()
        app_dir = home_dir / ".gemini" / "antigravity-cli"
    token_path = app_dir / "antigravity-oauth-token"
    try:
        raw = token_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "logged-out"
    except OSError:
        return ""
    return _parse_credential_fingerprint(raw)


def _read_darwin_keychain() -> str:
    proc = subprocess.run(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-a",
            _KEYRING_ACCOUNT,
            "-w",
            "-s",
            _KEYRING_SERVICE,
        ],
        capture_output=True,
        text=True,
        timeout=2.5,
        check=False,
    )
    if proc.returncode == 44:
        return "logged-out"
    if proc.returncode != 0:
        return ""
    return _parse_credential_fingerprint(proc.stdout)


def _resolve_dbus_address(env: Mapping[str, str]) -> str | None:
    explicit = (env.get("DBUS_SESSION_BUS_ADDRESS") or "").strip()
    if explicit:
        return explicit

    xdg_runtime = (env.get("XDG_RUNTIME_DIR") or "").strip()
    if xdg_runtime:
        bus_path = Path(xdg_runtime) / "bus"
        try:
            if bus_path.is_socket():
                return f"unix:path={bus_path}"
        except OSError:
            pass

    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None:
        bus_path = Path(f"/run/user/{geteuid()}/bus")
        try:
            if bus_path.is_socket():
                return f"unix:path={bus_path}"
        except OSError:
            pass

    return None


def _open_secret_service_connection(
    secretstorage: Any,
    env: Mapping[str, str],
) -> Any:
    bus_addr = _resolve_dbus_address(env)
    if bus_addr:
        conn = secretstorage.open_dbus_connection(bus=bus_addr)
        secretstorage.add_match_rules(conn)
        return conn
    return secretstorage.dbus_init()


def _read_linux_secret_service(env: Mapping[str, str]) -> str:
    import secretstorage

    conn = _open_secret_service_connection(secretstorage, env)
    attrs = {"service": _KEYRING_SERVICE, "username": _KEYRING_ACCOUNT}
    with closing(conn):
        try:
            collection = secretstorage.Collection(conn, _LOGIN_COLLECTION_PATH)
            locked = collection.is_locked()
        except secretstorage.exceptions.ItemNotFoundException:
            collection = secretstorage.get_default_collection(conn)
            locked = collection.is_locked()
        if locked:
            return ""

        items = list(collection.search_items(attrs))
        if not items:
            return "logged-out"

        exact = [item for item in items if item.get_attributes() == attrs]
        candidates = exact or items
        for item in candidates:
            if item.is_locked():
                return ""
            secret_bytes = item.get_secret()
            return _parse_credential_fingerprint(secret_bytes.decode("utf-8"))
    return ""


def read_active_agy_auth_fingerprint(
    env: Mapping[str, str] | None = None,
) -> str:
    """Return a non-sensitive fingerprint for the active Antigravity login.

    Returns ``"agy:<16-hex>"`` when logged in, ``"logged-out"`` when the
    credential store is explicitly empty, or ``""`` when status cannot be
    safely determined (fail-open).
    """
    try:
        effective_env = env if env is not None else os.environ
        if (effective_env.get("AGY_ADC_AUTH") or "").strip().lower() == "true":
            return ""
        if (effective_env.get("ANTIGRAVITY_GEMINI_DIR") or "").strip():
            return ""
        if any(
            (effective_env.get(name) or "").strip() for name in _SSH_ENV_VARS
        ):
            return _read_ssh_token_file(effective_env)
        if sys.platform == "darwin":
            return _read_darwin_keychain()
        if sys.platform.startswith(("linux", "freebsd", "openbsd", "netbsd")):
            return _read_linux_secret_service(effective_env)
    except Exception:  # pylint: disable=broad-except
        return ""
    return ""


async def async_agy_auth_fingerprint(
    reader: Callable[[], str] = read_active_agy_auth_fingerprint,
    *,
    timeout: float = _FINGERPRINT_TIMEOUT_SECONDS,
) -> str:
    """Run ``reader`` off the event loop with a short timeout and cache."""
    global _cached_fingerprint, _cached_at
    use_cache = reader is read_active_agy_auth_fingerprint
    if (
        use_cache
        and _cached_fingerprint
        and (time.monotonic() - _cached_at) < _CACHE_TTL_SECONDS
    ):
        return _cached_fingerprint

    epoch = _cache_epoch
    try:
        async with asyncio.timeout(timeout):
            result = str(await asyncio.to_thread(reader) or "")
    except Exception:  # pylint: disable=broad-except
        return ""

    if use_cache and result and _cache_epoch == epoch:
        _cached_fingerprint = result
        _cached_at = time.monotonic()
    return result


__all__ = [
    "async_agy_auth_fingerprint",
    "read_active_agy_auth_fingerprint",
    "reset_auth_fingerprint_cache",
]
