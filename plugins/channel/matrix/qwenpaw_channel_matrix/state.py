# -*- coding: utf-8 -*-
"""Instance-owned files and a non-copying reader for legacy Matrix state."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile

from qwenpaw.plugins.install_lock import plugin_install_lock
from qwenpaw.plugins.matrix_legacy import (
    MatrixLegacyError,
    load_matrix_legacy,
    verify_matrix_legacy,
)

logger = logging.getLogger(__name__)


class MatrixStateError(RuntimeError):
    """An ambiguous identity or live owner prevents state reuse."""


def _read_json(path):
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise MatrixStateError("MATRIX_STATE_UNREADABLE") from exc
    if not isinstance(value, dict):
        raise MatrixStateError("MATRIX_STATE_INVALID")
    return value


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class MatrixStateStore:
    """Hold OS claims until every SDK resource has stopped.

    Legacy files contain no homeserver metadata. Reading an auth hint is not
    ownership proof. A host capture or an explicitly supplied, verified token
    must establish the homeserver/workspace, after real account/device login.
    """

    def __init__(self, config):
        workspace = config.get("workspace_dir")
        if not workspace:
            raise MatrixStateError("MATRIX_WORKSPACE_REQUIRED")
        self.workspace = Path(workspace).expanduser().resolve()
        self.root = self.workspace / "channel_state" / "matrix"
        self.homeserver = str(config.get("homeserver") or "").rstrip("/")
        self.legacy = (
            Path(config["legacy_state_dir"]).expanduser().resolve()
            if config.get("legacy_state_dir")
            else None
        )
        self.owner = None
        self.directory = None
        self.crypto_dir = None
        self._claims = ExitStack()
        self._begun = False
        self._legacy_adopted = False
        self.has_legacy_authorization = "legacy_state_owner" in config
        self._legacy_authorization = config.get("legacy_state_owner")

    def begin(self):
        if self._begun:
            raise MatrixStateError("MATRIX_STATE_ALREADY_OWNED")
        try:
            self._claims.enter_context(
                plugin_install_lock(self.root / ".active.lock", timeout=0),
            )
        except Exception as exc:
            raise MatrixStateError("MATRIX_STATE_ALREADY_OWNED") from exc
        self._begun = True

    def auth_hint(self):
        current = _read_json(self.root / "current.json")
        if current and current.get("homeserver") == self.homeserver:
            scope = current.get("scope", "")
            if len(scope) != 64 or any(
                c not in "0123456789abcdef" for c in scope
            ):
                raise MatrixStateError("MATRIX_STATE_INVALID")
            return _read_json(self.root / scope / "auth.json")
        return self.legacy_auth()

    def legacy_auth(self):
        return (
            _read_json(self.legacy / "matrix_auth_state.json")
            if self.legacy
            else None
        )

    def legacy_owner(self):
        return (
            _read_json(self.legacy / "matrix_plugin_owner.json")
            if self.legacy
            else None
        )

    def has_legacy_state(self):
        return bool(
            self.legacy
            and any(
                (self.legacy / name).exists()
                for name in (
                    "matrix_auth_state.json",
                    "matrix_sync_token",
                    "matrix_crypto_store",
                )
            ),
        )

    def captured_legacy_verified(self, user_id, device_id):
        if not self.has_legacy_authorization:
            return False
        if self.legacy is None:
            raise MatrixStateError("MATRIX_LEGACY_CAPTURE_INVALID")
        try:
            capture = load_matrix_legacy(legacy_state_dir=self.legacy)
            return verify_matrix_legacy(
                capture,
                self._legacy_authorization,
                {
                    "homeserver": self.homeserver,
                    "user_id": user_id,
                    "device_id": device_id,
                    "workspace_dir": str(self.workspace),
                },
                legacy_state_dir=self.legacy,
            )
        except MatrixLegacyError as exc:
            raise MatrixStateError(str(exc)) from None

    def bind(
        self,
        user_id,
        device_id,
        *,
        legacy_verified=False,
        encryption_enabled=False,
    ):
        if not self._begun or not user_id:
            raise MatrixStateError("MATRIX_STATE_IDENTITY_REQUIRED")
        owner = {
            "homeserver": self.homeserver,
            "user_id": user_id,
            "device_id": device_id,
            "workspace_dir": str(self.workspace),
        }
        if self.owner:
            if self.owner != owner:
                raise MatrixStateError("MATRIX_STATE_IDENTITY_CONFLICT")
            return
        scope = hashlib.sha256(
            json.dumps([self.homeserver, user_id, device_id]).encode(),
        ).hexdigest()
        directory = self.root / scope
        if not directory.resolve().is_relative_to(self.root.resolve()):
            raise MatrixStateError("MATRIX_STATE_PATH_UNSAFE")
        database_name = f"{user_id}_{device_id}.db"
        needs_crypto = encryption_enabled or (
            self.legacy and (self.legacy / "matrix_crypto_store").exists()
        )
        if needs_crypto and (
            Path(database_name).name != database_name or "\\" in database_name
        ):
            raise MatrixStateError("MATRIX_CRYPTO_FILENAME_UNSAFE")
        # Across workspaces, the same account/device must not acquire two key
        # stores concurrently. OS locks release on crash; files are never used
        # as a PID/existence-only lock or deleted while another process owns it.
        claim_root = (
            self.legacy / "matrix_plugin_claims"
            if self.legacy
            else Path(tempfile.gettempdir()) / "qwenpaw-matrix-device-claims"
        )
        device_claim = claim_root / scope
        self._claims.enter_context(
            plugin_install_lock(device_claim.with_suffix(".lock"), timeout=0),
        )
        device_owner = _read_json(device_claim.with_suffix(".json"))
        if device_owner is not None and device_owner != owner:
            raise MatrixStateError("MATRIX_DEVICE_WORKSPACE_CONFLICT")
        previous = _read_json(directory / "owner.json")
        if previous is not None and previous != owner:
            raise MatrixStateError("MATRIX_STATE_IDENTITY_CONFLICT")
        crypto = directory / "crypto_store"
        if self.has_legacy_state():
            legacy = self.legacy_auth()
            if (
                not legacy_verified
                or not legacy
                or any(
                    legacy.get(k, "") != owner[k]
                    for k in ("user_id", "device_id")
                )
            ):
                raise MatrixStateError("MATRIX_LEGACY_IDENTITY_CONFLICT")
            self._claims.enter_context(
                plugin_install_lock(
                    self.legacy / ".matrix-plugin.lock",
                    timeout=0,
                ),
            )
            legacy_owner = _read_json(self.legacy / "matrix_plugin_owner.json")
            if legacy_owner is not None and legacy_owner != owner:
                raise MatrixStateError("MATRIX_LEGACY_OWNER_CONFLICT")
            if (
                legacy_owner is None
                and self.has_legacy_authorization
                and not self.captured_legacy_verified(user_id, device_id)
            ):
                raise MatrixStateError("MATRIX_LEGACY_OWNER_UNVERIFIED")
            # Durable claim is intentional: another workspace cannot later
            # silently take over this device's Olm/Megolm database.
            legacy_crypto = self.legacy / "matrix_crypto_store"
            if legacy_crypto.exists():
                expected = database_name
                foreign = [
                    p for p in legacy_crypto.glob("*.db") if p.name != expected
                ]
                if foreign and not (legacy_crypto / expected).is_file():
                    raise MatrixStateError(
                        "MATRIX_LEGACY_CRYPTO_IDENTITY_CONFLICT",
                    )
                if any(crypto.glob("*.db")):
                    raise MatrixStateError("MATRIX_CRYPTO_STORE_CONFLICT")
                crypto = legacy_crypto
            _atomic_json(self.legacy / "matrix_plugin_owner.json", owner)
            self._legacy_adopted = True
        _atomic_json(device_claim.with_suffix(".json"), owner)
        _atomic_json(directory / "owner.json", owner)
        _atomic_json(
            self.root / "current.json",
            {"homeserver": self.homeserver, "scope": scope},
        )
        self.owner, self.directory, self.crypto_dir = owner, directory, crypto

    def save_auth(self, token, user_id, device_id):
        if (
            not self.directory
            or self.owner["user_id"] != user_id
            or self.owner["device_id"] != device_id
        ):
            raise MatrixStateError("MATRIX_STATE_IDENTITY_CONFLICT")
        _atomic_json(
            self.directory / "auth.json",
            {
                "access_token": token,
                "user_id": user_id,
                "device_id": device_id,
            },
        )

    def load_sync(self):
        if self.directory is None:
            raise MatrixStateError("MATRIX_STATE_IDENTITY_REQUIRED")
        path = self.directory / "sync_token"
        if not path.exists() and self._legacy_adopted:
            path = self.legacy / "matrix_sync_token"
        try:
            return (
                path.read_text("utf-8").strip() or None
                if path.exists()
                else None
            )
        except OSError as exc:
            logger.warning("Matrix sync token could not be read: %s", exc)
            return None

    def save_sync(self, token):
        if not self.directory:
            raise MatrixStateError("MATRIX_STATE_IDENTITY_REQUIRED")
        path = self.directory / "sync_token"
        fd, temporary = tempfile.mkstemp(prefix=".sync-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(token)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def close(self):
        self._claims.close()
        self._begun = False
