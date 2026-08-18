# -*- coding: utf-8 -*-
"""Authentication and account storage for QwenPaw Pro."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .credentials import TenantCredentialVault

_PASSWORD_ITERATIONS = 600_000
_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ProUser:
    """Authenticated QwenPaw Pro identity."""

    user_id: str
    username: str
    role: str
    disabled: bool
    token_version: int
    created_at: str
    updated_at: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def to_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "disabled": self.disabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ProAuthService:
    """Persist users and issue versioned HMAC bearer tokens."""

    def __init__(
        self,
        database_path: Path,
        credential_vault: TenantCredentialVault,
    ) -> None:
        self.database_path = database_path
        self.credential_vault = credential_vault
        self._registration_lock = threading.Lock()
        self._initialize()
        self._token_secret = self.credential_vault.get_or_create_system_secret(
            "TOKEN_SIGNING_SECRET",
        ).encode("ascii")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pro_users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                    disabled INTEGER NOT NULL DEFAULT 0,
                    token_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """,
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pro_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """,
            )
            connection.execute(
                "INSERT OR IGNORE INTO pro_settings(key, value) "
                "VALUES ('registration_enabled', 'false')",
            )

    def status(self) -> dict[str, object]:
        """Return public bootstrap and registration state."""
        has_users = self.user_count() > 0
        return {
            "enabled": True,
            "has_users": has_users,
            "bootstrap_required": not has_users,
            "registration_enabled": self.registration_enabled(),
            "mode": "pro",
        }

    def user_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM pro_users",
            ).fetchone()
        return int(row["count"])

    def registration_enabled(self) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM pro_settings WHERE key = ?",
                ("registration_enabled",),
            ).fetchone()
        return row is not None and str(row["value"]).lower() == "true"

    def set_registration_enabled(self, enabled: bool) -> bool:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO pro_settings(key, value) "
                "VALUES (?, ?)",
                ("registration_enabled", "true" if enabled else "false"),
            )
        return enabled

    def register(self, username: str, password: str) -> tuple[ProUser, str]:
        """Bootstrap the first admin or register a user when enabled."""
        with self._registration_lock:
            first_user = self.user_count() == 0
            if not first_user and not self.registration_enabled():
                raise PermissionError("Registration is disabled.")
            user = self.create_user(
                username=username,
                password=password,
                role="admin" if first_user else "user",
            )
            return user, self.create_token(user)

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: str = "user",
    ) -> ProUser:
        """Create an account with a stable ID and PBKDF2 password hash."""
        normalized_username = username.strip()
        self._validate_credentials(normalized_username, password)
        if role not in {"admin", "user"}:
            raise ValueError(f"Invalid role: {role}")
        salt = secrets.token_bytes(16)
        password_hash = self._hash_password(password, salt)
        now = _now()
        user_id = uuid.uuid4().hex
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO pro_users(
                        user_id, username, password_hash, password_salt,
                        role, disabled, token_version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?)
                    """,
                    (
                        user_id,
                        normalized_username,
                        password_hash,
                        salt.hex(),
                        role,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"Username already exists: {normalized_username}",
            ) from exc
        user = self.get_user(user_id)
        if user is None:
            raise RuntimeError(f"Failed to load created user: {user_id}")
        return user

    def authenticate(
        self,
        username: str,
        password: str,
    ) -> tuple[ProUser, str]:
        """Verify credentials and return a fresh bearer token."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM pro_users WHERE username = ? COLLATE NOCASE",
                (username.strip(),),
            ).fetchone()
        if row is None or bool(row["disabled"]):
            raise PermissionError("Invalid username or password.")
        salt = bytes.fromhex(str(row["password_salt"]))
        actual_hash = self._hash_password(password, salt)
        if not hmac.compare_digest(actual_hash, str(row["password_hash"])):
            raise PermissionError("Invalid username or password.")
        user = self._user_from_row(row)
        return user, self.create_token(user)

    def create_token(self, user: ProUser) -> str:
        """Issue a signed token tied to the user's current token version."""
        now = int(time.time())
        payload = {
            "sub": user.user_id,
            "ver": user.token_version,
            "iat": now,
            "exp": now + _TOKEN_TTL_SECONDS,
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        ).decode("ascii")
        signature = hmac.new(
            self._signing_secret(),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return f"{encoded}.{signature}"

    def verify_token(self, token: str) -> ProUser | None:
        """Verify signature, expiry, disabled state, and token version."""
        try:
            encoded, signature = token.split(".", 1)
            expected = hmac.new(
                self._signing_secret(),
                encoded.encode("ascii"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(
                base64.urlsafe_b64decode(encoded.encode("ascii")),
            )
            if int(payload["exp"]) < int(time.time()):
                return None
            user = self.get_user(str(payload["sub"]))
            if user is None or user.disabled:
                return None
            if user.token_version != int(payload["ver"]):
                return None
            return user
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def list_users(self) -> list[ProUser]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM pro_users ORDER BY created_at, username",
            ).fetchall()
        return [self._user_from_row(row) for row in rows]

    def get_user(self, user_id: str) -> ProUser | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM pro_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return self._user_from_row(row) if row is not None else None

    def update_user(
        self,
        user_id: str,
        *,
        role: str | None = None,
        disabled: bool | None = None,
    ) -> ProUser:
        """Update authorization state and invalidate all existing tokens."""
        current = self.get_user(user_id)
        if current is None:
            raise KeyError(user_id)
        next_role = role if role is not None else current.role
        next_disabled = disabled if disabled is not None else current.disabled
        if next_role not in {"admin", "user"}:
            raise ValueError(f"Invalid role: {next_role}")
        if current.is_admin and (next_role != "admin" or next_disabled):
            if self._active_admin_count() <= 1:
                raise ValueError(
                    "The last active administrator cannot be disabled "
                    "or demoted.",
                )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE pro_users SET role = ?, disabled = ?,
                    token_version = token_version + 1, updated_at = ?
                WHERE user_id = ?
                """,
                (next_role, int(next_disabled), _now(), user_id),
            )
        updated = self.get_user(user_id)
        if updated is None:
            raise KeyError(user_id)
        return updated

    def _active_admin_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM pro_users "
                "WHERE role = 'admin' AND disabled = 0",
            ).fetchone()
        return int(row["count"])

    def _signing_secret(self) -> bytes:
        return self._token_secret

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            _PASSWORD_ITERATIONS,
        ).hex()

    @staticmethod
    def _validate_credentials(username: str, password: str) -> None:
        if not username or len(username) > 64:
            raise ValueError("Username must contain 1-64 characters.")
        if len(password) < 8:
            raise ValueError("Password must contain at least 8 characters.")

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> ProUser:
        return ProUser(
            user_id=str(row["user_id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            disabled=bool(row["disabled"]),
            token_version=int(row["token_version"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
