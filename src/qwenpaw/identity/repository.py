# -*- coding: utf-8 -*-
"""用户凭据 Repository 契约与 PostgreSQL 实现。"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.database import database_session
from .governance import LastActiveAdminError, UserNotFoundError
from .models import (
    CredentialRecord,
    PlatformRole,
    UserProfileUpdate,
    UserRecord,
    UserStatus,
)

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_FIRST_USER_LOCK_KEY = 716_350_211_404
_PUBLIC_USER_COLUMNS = (
    "id, username, platform_role, status, display_name, email, phone, "
    "department, job_title, remark, created_at, updated_at, last_login_at"
)


class DuplicateUsernameError(RuntimeError):
    """用户名唯一约束冲突。"""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__("username_already_exists")


class UserRepository(Protocol):
    """用户服务所需的最小持久化接口。"""

    async def count_users(self) -> int: ...

    async def create_credential(
        self,
        *,
        username: str,
        password_hash: str,
        platform_role: PlatformRole,
    ) -> CredentialRecord: ...

    async def get_credential_by_username(
        self,
        username: str,
    ) -> CredentialRecord | None: ...

    async def get_credential_by_user_id(
        self,
        user_id: UUID,
    ) -> CredentialRecord | None: ...

    async def update_password_hash(
        self,
        user_id: UUID,
        password_hash: str,
    ) -> None: ...

    async def mark_login(self, user_id: UUID) -> None: ...

    async def update_profile(
        self,
        user_id: UUID,
        profile: UserProfileUpdate,
    ) -> UserRecord: ...

    async def create_legacy_admin_if_empty(
        self,
        *,
        username: str,
        password_hash: str,
    ) -> CredentialRecord | None: ...

    async def list_users(self) -> list[UserRecord]: ...

    async def get_user(self, user_id: UUID) -> UserRecord: ...

    async def update_status(
        self,
        user_id: UUID,
        status: UserStatus,
    ) -> UserRecord: ...

    async def update_role(
        self,
        user_id: UUID,
        role: PlatformRole,
    ) -> UserRecord: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class PostgresUserRepository:
    """使用 Schema 限定 SQL 的 PostgreSQL 用户 Repository。"""

    def __init__(
        self,
        *,
        schema: str = "qwenpaw",
        session_factory: SessionFactory = database_session,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        normalized_schema = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized_schema):
            raise ValueError("invalid_database_schema")
        self._users_table = f'"{normalized_schema}".users'
        self._session_factory = session_factory
        self._clock = clock

    async def count_users(self) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                text(f"SELECT count(*) FROM {self._users_table}")
            )
            return int(result.scalar_one())

    async def create_credential(
        self,
        *,
        username: str,
        password_hash: str,
        platform_role: PlatformRole,
    ) -> CredentialRecord:
        credential = await self._create_locked(
            username=username,
            password_hash=password_hash,
            platform_role=platform_role,
            only_if_empty=False,
        )
        if credential is None:  # pragma: no cover - guarded by flag
            raise RuntimeError("credential_creation_skipped")
        return credential

    async def create_legacy_admin_if_empty(
        self,
        *,
        username: str,
        password_hash: str,
    ) -> CredentialRecord | None:
        """在同一事务锁内确认空库并导入旧管理员。"""
        return await self._create_locked(
            username=username,
            password_hash=password_hash,
            platform_role=PlatformRole.ADMIN,
            only_if_empty=True,
        )

    async def _create_locked(
        self,
        *,
        username: str,
        password_hash: str,
        platform_role: PlatformRole,
        only_if_empty: bool,
    ) -> CredentialRecord | None:
        user_id = uuid4()
        try:
            async with self._session_factory() as session:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _FIRST_USER_LOCK_KEY},
                )
                existing_result = await session.execute(
                    text(f"SELECT EXISTS(SELECT 1 FROM {self._users_table})")
                )
                has_users = bool(existing_result.scalar_one())
                if only_if_empty and has_users:
                    return None
                effective_role = platform_role if has_users else PlatformRole.ADMIN
                result = await session.execute(
                    text(
                        f"INSERT INTO {self._users_table} "
                        "(id, username, password_hash, status, platform_role) "
                        "VALUES (:id, :username, :password_hash, "
                        "'active', :platform_role) "
                        f"RETURNING password_hash, {_PUBLIC_USER_COLUMNS}"
                    ),
                    {
                        "id": user_id,
                        "username": username,
                        "password_hash": password_hash,
                        "platform_role": effective_role.value,
                    },
                )
                return _credential_from_row(result.mappings().one())
        except IntegrityError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(
                exc.orig,
                "pgcode",
                None,
            )
            if sqlstate != "23505":
                raise
            raise DuplicateUsernameError(username) from exc

    async def get_credential_by_username(
        self,
        username: str,
    ) -> CredentialRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT password_hash, {_PUBLIC_USER_COLUMNS} "
                    f"FROM {self._users_table} WHERE username = :username"
                ),
                {"username": username},
            )
            row = result.mappings().one_or_none()
        return _credential_from_row(row) if row is not None else None

    async def get_credential_by_user_id(
        self,
        user_id: UUID,
    ) -> CredentialRecord | None:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT password_hash, {_PUBLIC_USER_COLUMNS} "
                    f"FROM {self._users_table} WHERE id = :user_id"
                ),
                {"user_id": user_id},
            )
            row = result.mappings().one_or_none()
        return _credential_from_row(row) if row is not None else None

    async def update_password_hash(
        self,
        user_id: UUID,
        password_hash: str,
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    f"UPDATE {self._users_table} "
                    "SET password_hash = :password_hash, updated_at = now() "
                    "WHERE id = :user_id"
                ),
                {"user_id": user_id, "password_hash": password_hash},
            )

    async def mark_login(self, user_id: UUID) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text(
                    f"UPDATE {self._users_table} "
                    "SET last_login_at = :logged_in_at, updated_at = now() "
                    "WHERE id = :user_id"
                ),
                {"user_id": user_id, "logged_in_at": self._clock()},
            )

    async def update_profile(
        self,
        user_id: UUID,
        profile: UserProfileUpdate,
    ) -> UserRecord:
        parameters = {
            "user_id": user_id,
            "username": profile.username,
            "display_name": profile.display_name,
            "email": profile.email,
            "phone": profile.phone,
            "department": profile.department,
            "job_title": profile.job_title,
            "remark": profile.remark,
        }
        try:
            async with self._session_factory() as session:
                result = await session.execute(
                    text(
                        f"UPDATE {self._users_table} SET "
                        "username = :username, display_name = :display_name, "
                        "email = :email, phone = :phone, department = :department, "
                        "job_title = :job_title, remark = :remark, updated_at = now() "
                        "WHERE id = :user_id "
                        f"RETURNING {_PUBLIC_USER_COLUMNS}"
                    ),
                    parameters,
                )
                row = result.mappings().one_or_none()
        except IntegrityError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(
                exc.orig, "pgcode", None
            )
            if sqlstate != "23505":
                raise
            raise DuplicateUsernameError(profile.username) from exc
        if row is None:
            raise UserNotFoundError()
        return _user_from_row(row)

    async def list_users(self) -> list[UserRecord]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT {_PUBLIC_USER_COLUMNS} "
                    f"FROM {self._users_table} ORDER BY username"
                )
            )
            return [_user_from_row(row) for row in result.mappings().all()]

    async def get_user(self, user_id: UUID) -> UserRecord:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"SELECT {_PUBLIC_USER_COLUMNS} "
                    f"FROM {self._users_table} WHERE id = :user_id"
                ),
                {"user_id": user_id},
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise UserNotFoundError()
        return _user_from_row(row)

    async def update_status(
        self,
        user_id: UUID,
        status: UserStatus,
    ) -> UserRecord:
        if status not in ("active", "disabled"):
            raise ValueError("invalid_user_status")
        return await self._update_governance_field(
            user_id=user_id,
            field="status",
            value=status,
        )

    async def update_role(
        self,
        user_id: UUID,
        role: PlatformRole,
    ) -> UserRecord:
        return await self._update_governance_field(
            user_id=user_id,
            field="platform_role",
            value=PlatformRole(role).value,
        )

    async def _update_governance_field(
        self,
        *,
        user_id: UUID,
        field: str,
        value: str,
    ) -> UserRecord:
        if field not in ("status", "platform_role"):
            raise ValueError("invalid_governance_field")
        async with self._session_factory() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _FIRST_USER_LOCK_KEY},
            )
            current_result = await session.execute(
                text(
                    f"SELECT {_PUBLIC_USER_COLUMNS} "
                    f"FROM {self._users_table} WHERE id = :user_id FOR UPDATE"
                ),
                {"user_id": user_id},
            )
            current_row = current_result.mappings().one_or_none()
            if current_row is None:
                raise UserNotFoundError()
            current = _user_from_row(current_row)
            removes_active_admin = (
                current.platform_role is PlatformRole.ADMIN
                and current.status == "active"
                and (
                    (field == "status" and value == "disabled")
                    or (field == "platform_role" and value == "member")
                )
            )
            if removes_active_admin:
                count_result = await session.execute(
                    text(
                        f"SELECT count(*) FROM {self._users_table} "
                        "WHERE platform_role = 'admin' AND status = 'active'"
                    )
                )
                if int(count_result.scalar_one()) <= 1:
                    raise LastActiveAdminError()
            result = await session.execute(
                text(
                    f"UPDATE {self._users_table} SET {field} = :value, "
                    "updated_at = now() WHERE id = :user_id "
                    f"RETURNING {_PUBLIC_USER_COLUMNS}"
                ),
                {"user_id": user_id, "value": value},
            )
            return _user_from_row(result.mappings().one())


def _credential_from_row(row) -> CredentialRecord:
    return CredentialRecord(
        user=_user_from_row(row),
        password_hash=row["password_hash"],
    )


def _user_from_row(row) -> UserRecord:
    status: UserStatus = "active" if row["status"] == "active" else "disabled"
    return UserRecord(
        id=row["id"],
        username=row["username"],
        platform_role=PlatformRole(row["platform_role"]),
        status=status,
        display_name=row.get("display_name"),
        email=row.get("email"),
        phone=row.get("phone"),
        department=row.get("department"),
        job_title=row.get("job_title"),
        remark=row.get("remark"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        last_login_at=row.get("last_login_at"),
    )
