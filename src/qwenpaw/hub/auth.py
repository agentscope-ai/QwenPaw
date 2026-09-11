# -*- coding: utf-8 -*-
"""Authentication and account storage for QwenPaw Hub."""

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
from pathlib import Path

from .credentials import TenantCredentialVault
from .database import (
    connect_hub_database,
    ensure_tenant,
    initialize_hub_database,
    utc_now,
)

_PASSWORD_ITERATIONS = 600_000
_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class HubUser:
    """Authenticated QwenPaw Hub identity."""

    user_id: str
    username: str
    role: str
    disabled: bool
    token_version: int
    profile: dict[str, object]
    preferences: dict[str, object]
    metadata: dict[str, object]
    revision: int
    last_login_at: str | None
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
            "profile": self.profile,
            "preferences": self.preferences,
            "metadata": self.metadata,
            "revision": self.revision,
            "last_login_at": self.last_login_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class HubAuthService:
    """Persist users and issue versioned HMAC bearer tokens."""

    def __init__(
        self,
        database_path: Path,
        credential_vault: TenantCredentialVault,
    ) -> None:
        self.database_path = database_path
        self.credential_vault = credential_vault
        self._registration_lock = threading.Lock()
        initialize_hub_database(database_path)
        self._token_secret = self.credential_vault.get_or_create_system_secret(
            "TOKEN_SIGNING_SECRET",
        ).encode("ascii")

    def _connect(self) -> sqlite3.Connection:
        return connect_hub_database(self.database_path)

    def status(self) -> dict[str, object]:
        """Return public bootstrap and registration state."""
        has_users = self.user_count() > 0
        return {
            "enabled": True,
            "has_users": has_users,
            "bootstrap_required": not has_users,
            "registration_enabled": self.registration_enabled(),
            "mode": "hub",
        }

    def user_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM hub_users "
                "WHERE deleted_at IS NULL",
            ).fetchone()
        return int(row["count"])

    def has_enabled_admin(self) -> bool:
        """Return whether public startup has an initialized administrator."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM hub_users "
                "WHERE role = 'admin' AND disabled = 0 "
                "AND deleted_at IS NULL LIMIT 1",
            ).fetchone()
        return row is not None

    def registration_enabled(self) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM hub_settings WHERE key = ?",
                ("registration_enabled",),
            ).fetchone()
        return row is not None and bool(json.loads(str(row["value_json"])))

    def register(self, username: str, password: str) -> tuple[HubUser, str]:
        """Bootstrap the first admin or register a user when enabled."""
        with self._registration_lock:
            first_user = self.user_count() == 0
            if not first_user and not self.registration_enabled():
                raise PermissionError("Registration is disabled.")
            user = self.create_user(
                username=username,
                password=password,
                role=(
                    "admin"
                    if first_user
                    else self._registration_default_role()
                ),
            )
            return user, self.create_token(user)

    def _registration_default_role(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM hub_settings WHERE key = ?",
                ("registration_default_role",),
            ).fetchone()
        if row is None:
            return "user"
        return str(json.loads(str(row["value_json"])))

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: str = "user",
    ) -> HubUser:
        """Create an account with a stable ID and PBKDF2 password hash."""
        normalized_username = username.strip()
        self._validate_credentials(normalized_username, password)
        if role not in {"admin", "user"}:
            raise ValueError(f"Invalid role: {role}")
        salt = secrets.token_bytes(16)
        password_hash = self._hash_password(password, salt)
        now = utc_now()
        user_id = uuid.uuid4().hex
        try:
            with self._connect() as connection:
                tenant_id = f"personal-{user_id}"
                ensure_tenant(
                    connection,
                    tenant_id,
                    tenant_type="personal",
                    display_name=normalized_username,
                )
                connection.execute(
                    """
                    INSERT INTO hub_users(
                        user_id, username, password_hash, password_salt,
                        role, disabled, token_version, profile_json,
                        preferences_json, metadata_json, revision,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        user_id,
                        normalized_username,
                        password_hash,
                        salt.hex(),
                        role,
                        '{"schema_version":1}',
                        '{"schema_version":1}',
                        '{"schema_version":1}',
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
    ) -> tuple[HubUser, str]:
        """Verify credentials and return a fresh bearer token."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM hub_users WHERE username = ? COLLATE NOCASE "
                "AND deleted_at IS NULL",
                (username.strip(),),
            ).fetchone()
        if row is None or bool(row["disabled"]):
            raise PermissionError("Invalid username or password.")
        salt = bytes.fromhex(str(row["password_salt"]))
        actual_hash = self._hash_password(password, salt)
        if not hmac.compare_digest(actual_hash, str(row["password_hash"])):
            raise PermissionError("Invalid username or password.")
        user = self._user_from_row(row)
        login_time = utc_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE hub_users SET last_login_at = ?, updated_at = ?, "
                "revision = revision + 1 WHERE user_id = ?",
                (login_time, login_time, user.user_id),
            )
        refreshed = self.get_user(user.user_id)
        if refreshed is not None:
            user = refreshed
        return user, self.create_token(user)

    def create_token(self, user: HubUser) -> str:
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

    def verify_token(self, token: str) -> HubUser | None:
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

    def list_users(self) -> list[HubUser]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM hub_users WHERE deleted_at IS NULL "
                "ORDER BY created_at, username",
            ).fetchall()
        return [self._user_from_row(row) for row in rows]

    def list_users_page(
        self,
        *,
        page: int,
        page_size: int,
        query: str | None = None,
        role: str | None = None,
        disabled: bool | None = None,
    ) -> tuple[list[HubUser], int]:
        """Return one filtered account page and the matching total."""
        clauses: list[str] = ["deleted_at IS NULL"]
        parameters: list[object] = []
        if query:
            clauses.append("(username LIKE ? OR user_id LIKE ?)")
            pattern = f"%{query}%"
            parameters.extend([pattern, pattern])
        if role:
            if role not in {"admin", "user"}:
                raise ValueError(f"Invalid role: {role}")
            clauses.append("role = ?")
            parameters.append(role)
        if disabled is not None:
            clauses.append("disabled = ?")
            parameters.append(int(disabled))
        where = f" WHERE {' AND '.join(clauses)}"
        with self._connect() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS count FROM hub_users{where}",
                parameters,
            ).fetchone()
            rows = connection.execute(
                f"SELECT * FROM hub_users{where} "
                "ORDER BY created_at DESC, username "
                "LIMIT ? OFFSET ?",
                (*parameters, page_size, (page - 1) * page_size),
            ).fetchall()
        return (
            [self._user_from_row(row) for row in rows],
            int(total_row["count"]),
        )

    def get_user(self, user_id: str) -> HubUser | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM hub_users WHERE user_id = ? "
                "AND deleted_at IS NULL",
                (user_id,),
            ).fetchone()
        return self._user_from_row(row) if row is not None else None

    def get_usernames(self, user_ids: set[str]) -> dict[str, str]:
        """Return active usernames for a batch of user identifiers."""
        if not user_ids:
            return {}
        ordered_ids = sorted(user_ids)
        placeholders = ", ".join("?" for _ in ordered_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT user_id, username FROM hub_users "
                f"WHERE user_id IN ({placeholders}) "
                f"AND deleted_at IS NULL",
                ordered_ids,
            ).fetchall()
        return {str(row["user_id"]): str(row["username"]) for row in rows}

    def update_user(
        self,
        user_id: str,
        *,
        role: str | None = None,
        disabled: bool | None = None,
        actor_user_id: str | None = None,
    ) -> HubUser:
        """Update authorization state and invalidate all existing tokens."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM hub_users WHERE user_id = ? "
                "AND deleted_at IS NULL",
                (user_id,),
            ).fetchone()
            if row is None:
                raise KeyError(user_id)
            current = self._user_from_row(row)
            next_role = role if role is not None else current.role
            next_disabled = (
                disabled if disabled is not None else current.disabled
            )
            if next_role not in {"admin", "user"}:
                raise ValueError(f"Invalid role: {next_role}")
            authorization_changed = (
                next_role != current.role or next_disabled != current.disabled
            )
            if actor_user_id == user_id and authorization_changed:
                raise ValueError(
                    "Administrators cannot change their own role or "
                    "account status.",
                )
            if current.is_admin and (next_role != "admin" or next_disabled):
                count_row = connection.execute(
                    "SELECT COUNT(*) AS count FROM hub_users "
                    "WHERE role = 'admin' AND disabled = 0 "
                    "AND deleted_at IS NULL",
                ).fetchone()
                if int(count_row["count"]) <= 1:
                    raise ValueError(
                        "The last active administrator cannot be disabled "
                        "or demoted.",
                    )
            connection.execute(
                """
                UPDATE hub_users SET role = ?, disabled = ?,
                    token_version = token_version + 1,
                    revision = revision + 1, updated_at = ?
                WHERE user_id = ?
                """,
                (next_role, int(next_disabled), utc_now(), user_id),
            )
            updated_row = connection.execute(
                "SELECT * FROM hub_users WHERE user_id = ? "
                "AND deleted_at IS NULL",
                (user_id,),
            ).fetchone()
            if updated_row is None:
                raise KeyError(user_id)
            return self._user_from_row(updated_row)

    def change_password(self, user_id: str, password: str) -> HubUser:
        """Replace a user's password and invalidate existing sessions."""
        current = self.get_user(user_id)
        if current is None:
            raise KeyError(user_id)
        self._validate_credentials(current.username, password)
        salt = secrets.token_bytes(16)
        password_hash = self._hash_password(password, salt)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE hub_users SET password_hash = ?, password_salt = ?,
                    token_version = token_version + 1,
                    revision = revision + 1, updated_at = ?
                WHERE user_id = ? AND deleted_at IS NULL
                """,
                (
                    password_hash,
                    salt.hex(),
                    utc_now(),
                    user_id,
                ),
            )
        updated = self.get_user(user_id)
        if updated is None:
            raise KeyError(user_id)
        return updated

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
    def _user_from_row(row: sqlite3.Row) -> HubUser:
        return HubUser(
            user_id=str(row["user_id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            disabled=bool(row["disabled"]),
            token_version=int(row["token_version"]),
            profile=json.loads(str(row["profile_json"])),
            preferences=json.loads(str(row["preferences_json"])),
            metadata=json.loads(str(row["metadata_json"])),
            revision=int(row["revision"]),
            last_login_at=(
                str(row["last_login_at"])
                if row["last_login_at"] is not None
                else None
            ),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
