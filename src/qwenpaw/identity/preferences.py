# -*- coding: utf-8 -*-
"""用户语言和时区偏好 PostgreSQL Repository。"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.database import database_session

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class UserPreferences:
    user_id: UUID
    language: str
    timezone: str


class PostgresPreferenceRepository:
    def __init__(
        self,
        *,
        schema: str = "qwenpaw",
        session_factory: SessionFactory = database_session,
    ) -> None:
        normalized = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized):
            raise ValueError("invalid_database_schema")
        self._table = f'"{normalized}".user_preferences'
        self._session_factory = session_factory

    async def get_or_create(self, user_id: UUID) -> UserPreferences:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"INSERT INTO {self._table} (user_id) VALUES (:user_id) "
                    "ON CONFLICT (user_id) DO UPDATE SET user_id = EXCLUDED.user_id "
                    "RETURNING user_id, language, timezone"
                ),
                {"user_id": user_id},
            )
            return _preferences_from_row(result.mappings().one())

    async def update(
        self,
        user_id: UUID,
        *,
        language: str,
        timezone: str,
    ) -> UserPreferences:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    f"INSERT INTO {self._table} "
                    "(user_id, language, timezone) VALUES "
                    "(:user_id, :language, :timezone) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "language = EXCLUDED.language, "
                    "timezone = EXCLUDED.timezone, updated_at = now() "
                    "RETURNING user_id, language, timezone"
                ),
                {
                    "user_id": user_id,
                    "language": language,
                    "timezone": timezone,
                },
            )
            return _preferences_from_row(result.mappings().one())


def _preferences_from_row(row) -> UserPreferences:
    return UserPreferences(
        user_id=row["user_id"],
        language=row["language"],
        timezone=row["timezone"],
    )
