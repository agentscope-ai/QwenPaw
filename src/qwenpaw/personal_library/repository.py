# -*- coding: utf-8 -*-
"""PostgreSQL metadata repository for isolated personal libraries."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.database import database_session, set_request_user
from .models import PersonalLibraryDocument

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class PostgresPersonalLibraryRepository:
    """Persist document metadata while applying the request owner to RLS."""

    def __init__(
        self,
        *,
        schema: str = "qwenpaw",
        session_factory: SessionFactory = database_session,
    ) -> None:
        normalized = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized):
            raise ValueError("invalid_database_schema")
        self._documents_table = f'"{normalized}".user_library_documents'
        self._session_factory = session_factory

    async def get_document(
        self,
        *,
        owner_user_id: UUID,
        agent_id: UUID,
        document_id: UUID,
    ) -> PersonalLibraryDocument | None:
        statement = text(
            f"SELECT id, owner_user_id, agent_id, relative_path, name, media_type, size, "
            f"sha256, created_at, updated_at FROM {self._documents_table} "
            "WHERE owner_user_id = :owner_user_id AND agent_id = :agent_id AND id = :document_id"
        )
        async with self._session_factory() as session:
            await set_request_user(session, owner_user_id)
            row = (
                await session.execute(
                    statement,
                    {"owner_user_id": owner_user_id, "agent_id": agent_id, "document_id": document_id},
                )
            ).mappings().one_or_none()
        return None if row is None else self._document_from_row(row)

    async def get_by_path(
        self,
        *,
        owner_user_id: UUID,
        agent_id: UUID,
        relative_path: str,
    ) -> PersonalLibraryDocument | None:
        statement = text(
            f"SELECT id, owner_user_id, agent_id, relative_path, name, media_type, size, "
            f"sha256, created_at, updated_at FROM {self._documents_table} "
            "WHERE owner_user_id = :owner_user_id AND agent_id = :agent_id AND relative_path = :relative_path"
        )
        async with self._session_factory() as session:
            await set_request_user(session, owner_user_id)
            row = (
                await session.execute(
                    statement,
                    {"owner_user_id": owner_user_id, "agent_id": agent_id, "relative_path": relative_path},
                )
            ).mappings().one_or_none()
        return None if row is None else self._document_from_row(row)

    async def list_documents(
        self,
        *,
        owner_user_id: UUID,
        agent_id: UUID,
    ) -> list[PersonalLibraryDocument]:
        statement = text(
            f"SELECT id, owner_user_id, agent_id, relative_path, name, media_type, size, "
            f"sha256, created_at, updated_at FROM {self._documents_table} "
            "WHERE owner_user_id = :owner_user_id AND agent_id = :agent_id "
            "ORDER BY relative_path ASC"
        )
        async with self._session_factory() as session:
            await set_request_user(session, owner_user_id)
            rows = (
                await session.execute(statement, {"owner_user_id": owner_user_id, "agent_id": agent_id})
            ).mappings().all()
        return [self._document_from_row(row) for row in rows]

    async def save_document(
        self,
        document: PersonalLibraryDocument,
    ) -> PersonalLibraryDocument:
        statement = text(
            f"INSERT INTO {self._documents_table} ("
            "id, owner_user_id, agent_id, relative_path, name, media_type, size, sha256, "
            "created_at, updated_at"
            ") VALUES ("
            ":id, :owner_user_id, :agent_id, :relative_path, :name, :media_type, :size, "
            ":sha256, :created_at, :updated_at"
            ") ON CONFLICT (id) DO UPDATE SET "
            "relative_path = EXCLUDED.relative_path, name = EXCLUDED.name, "
            "media_type = EXCLUDED.media_type, "
            "size = EXCLUDED.size, sha256 = EXCLUDED.sha256, "
            "updated_at = EXCLUDED.updated_at "
            "RETURNING id, owner_user_id, agent_id, relative_path, name, media_type, size, "
            "sha256, created_at, updated_at"
        )
        params = {
            "id": document.id,
            "owner_user_id": document.owner_user_id,
            "agent_id": document.agent_id,
            "relative_path": document.relative_path,
            "name": document.name,
            "media_type": document.media_type,
            "size": document.size,
            "sha256": document.sha256,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
        }
        async with self._session_factory() as session:
            await set_request_user(session, document.owner_user_id)
            row = (await session.execute(statement, params)).mappings().one()
        return self._document_from_row(row)

    async def delete_document(
        self,
        *,
        owner_user_id: UUID,
        agent_id: UUID,
        document_id: UUID,
    ) -> bool:
        statement = text(
            f"DELETE FROM {self._documents_table} "
            "WHERE owner_user_id = :owner_user_id AND agent_id = :agent_id AND id = :document_id"
        )
        async with self._session_factory() as session:
            await set_request_user(session, owner_user_id)
            result = await session.execute(
                statement,
                {"owner_user_id": owner_user_id, "agent_id": agent_id, "document_id": document_id},
            )
        return bool(result.rowcount)

    @staticmethod
    def _document_from_row(row) -> PersonalLibraryDocument:
        return PersonalLibraryDocument(
            id=row["id"],
            owner_user_id=row["owner_user_id"],
            agent_id=row["agent_id"],
            relative_path=row["relative_path"],
            name=row["name"],
            media_type=row["media_type"],
            size=row["size"],
            sha256=row["sha256"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
