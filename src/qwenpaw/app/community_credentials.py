# -*- coding: utf-8 -*-
"""Private encrypted community credentials, never process environment values."""

import json
import os

from ..constant import SECRET_DIR
from ..security.secret_store import decrypt, encrypt, is_encrypted
from ..utils.io_utils import get_sync_path_lock, read_json, write_json_atomic

_CREDENTIAL_PATH = SECRET_DIR / "community_credentials.json"
_STATES = {"active", "paused", "rejected", "cleared"}


def _empty(state: str = "cleared") -> dict:
    return {"account": "", "password": "", "state": state}


def _check_file() -> None:
    if _CREDENTIAL_PATH.is_symlink():
        raise OSError("Community credential file must not be a symlink")


def _validate(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("state") not in _STATES:
        raise ValueError("Invalid community credential state")
    if not all(
        isinstance(data.get(key), str) for key in ("account", "password")
    ):
        raise ValueError("Invalid community credentials")
    return {key: data[key] for key in ("account", "password", "state")}


def _write(data: dict) -> None:
    _check_file()
    data = _validate(data)
    _CREDENTIAL_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        _CREDENTIAL_PATH.parent.chmod(0o700)
        if _CREDENTIAL_PATH.exists():
            _CREDENTIAL_PATH.chmod(0o600)
    # Encrypt the whole payload, including the account and reconnect state.
    write_json_atomic(
        _CREDENTIAL_PATH,
        {"version": 1, "payload": encrypt(json.dumps(data))},
        new_file_mode=0o600,
    )


def _load() -> dict:
    _check_file()
    if not _CREDENTIAL_PATH.exists():
        return _empty()
    raw = read_json(_CREDENTIAL_PATH)
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise ValueError("Invalid community credential document")
    ciphertext = raw.get("payload")
    if not isinstance(ciphertext, str) or not is_encrypted(ciphertext):
        raise ValueError("Community credentials must be encrypted")
    plaintext = decrypt(ciphertext)
    if plaintext == ciphertext:
        raise ValueError("Cannot decrypt community credentials")
    return _validate(json.loads(plaintext))


def load() -> dict:
    """Internal only: no caller may serialize this dict into an API response."""
    with get_sync_path_lock(_CREDENTIAL_PATH):
        try:
            return _load()
        except (OSError, ValueError):
            return _empty("unreadable")


def save(account: str, password: str) -> None:
    with get_sync_path_lock(_CREDENTIAL_PATH):
        _write({"account": account, "password": password, "state": "active"})


def pause(*, rejected: bool = False) -> None:
    with get_sync_path_lock(_CREDENTIAL_PATH):
        data = _load()
        data["state"] = "rejected" if rejected else "paused"
        _write(data)


def clear() -> None:
    with get_sync_path_lock(_CREDENTIAL_PATH):
        _write(_empty())
