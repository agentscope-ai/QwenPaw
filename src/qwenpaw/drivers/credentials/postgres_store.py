# -*- coding: utf-8 -*-
"""PostgreSQL credential store with scoped, internal-only resolution."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...persistence.database import database_session
from ...security.secret_store import decrypt, encrypt
from ..errors import CredentialNotFoundError, DriverCardError
from .types import CredentialRecord

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_KEY_VERSION = "fernet-v1"


class PostgresCredentialStore:
    """Persist encrypted credentials and resolve only matching bindings."""

    def __init__(
        self,
        *,
        schema: str = "qwenpaw",
        session_factory: SessionFactory = database_session,
    ) -> None:
        normalized = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized):
            raise ValueError("invalid_database_schema")
        prefix = f'"{normalized}".'
        self._credentials = f"{prefix}credential_records"
        self._bindings = f"{prefix}credential_bindings"
        self._session_factory = session_factory

    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]:
        """Expose one transaction for a multi-field credential update."""
        return self._session_factory()

    @staticmethod
    def _encode(record: CredentialRecord) -> bytes:
        payload = {
            "public": dict(record.public),
            "secrets": dict(record.secrets),
            "meta": dict(record.meta),
        }
        for key, value in payload["secrets"].items():
            if not isinstance(key, str) or not key or not isinstance(value, str):
                raise DriverCardError(
                    "Credential secret keys and values must be strings"
                )
        return encrypt(json.dumps(payload, ensure_ascii=False)).encode("utf-8")

    @staticmethod
    def _decode(value: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(decrypt(value.decode("utf-8")))
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            raise DriverCardError("Credential payload is invalid") from exc
        if not isinstance(payload, dict):
            raise DriverCardError("Credential payload is invalid")
        return payload

    async def create_and_bind(
        self,
        *,
        record: CredentialRecord,
        scope_type: str,
        scope_id: UUID,
        consumer_type: str,
        consumer_id: UUID,
        purpose: str,
        created_by: UUID,
        session: AsyncSession | None = None,
    ) -> UUID:
        if session is None:
            async with self._session_factory() as owned:
                return await self.create_and_bind(
                    record=record,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    consumer_type=consumer_type,
                    consumer_id=consumer_id,
                    purpose=purpose,
                    created_by=created_by,
                    session=owned,
                )
        credential_id = uuid4()
        old_id = await session.scalar(
            text(
                f"SELECT credential_id FROM {self._bindings} WHERE consumer_type=:ct AND consumer_id=:cid AND purpose=:purpose FOR UPDATE"
            ),
            {"ct": consumer_type, "cid": consumer_id, "purpose": purpose},
        )
        await session.execute(
            text(
                f"INSERT INTO {self._credentials} (id, scope_type, scope_id, secret_type, encrypted_value, key_version, status, created_by) VALUES (:id,:scope_type,:scope_id,:kind,:value,:version,'active',:created_by)"
            ),
            {
                "id": credential_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "kind": record.kind,
                "value": self._encode(record),
                "version": _KEY_VERSION,
                "created_by": created_by,
            },
        )
        if old_id is None:
            await session.execute(
                text(
                    f"INSERT INTO {self._bindings} (id, credential_id, consumer_type, consumer_id, purpose, created_by) VALUES (:id,:credential_id,:ct,:cid,:purpose,:created_by)"
                ),
                {
                    "id": uuid4(),
                    "credential_id": credential_id,
                    "ct": consumer_type,
                    "cid": consumer_id,
                    "purpose": purpose,
                    "created_by": created_by,
                },
            )
        else:
            await session.execute(
                text(
                    f"UPDATE {self._bindings} SET credential_id=:new_id, created_by=:created_by, created_at=now() WHERE consumer_type=:ct AND consumer_id=:cid AND purpose=:purpose"
                ),
                {
                    "new_id": credential_id,
                    "created_by": created_by,
                    "ct": consumer_type,
                    "cid": consumer_id,
                    "purpose": purpose,
                },
            )
            await session.execute(
                text(
                    f"UPDATE {self._credentials} SET status='revoked', revoked_at=now() WHERE id=:old_id AND status='active'"
                ),
                {"old_id": old_id},
            )
        return credential_id

    async def resolve(
        self,
        *,
        consumer_type: str,
        consumer_id: UUID,
        purpose: str,
        scope_type: str,
        scope_id: UUID,
    ) -> CredentialRecord:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"SELECT cr.id, cr.secret_type, cr.encrypted_value FROM {self._bindings} cb JOIN {self._credentials} cr ON cr.id=cb.credential_id WHERE cb.consumer_type=:ct AND cb.consumer_id=:cid AND cb.purpose=:purpose AND cr.scope_type=:scope_type AND cr.scope_id=:scope_id AND cr.status='active' AND cr.revoked_at IS NULL"
                        ),
                        {
                            "ct": consumer_type,
                            "cid": consumer_id,
                            "purpose": purpose,
                            "scope_type": scope_type,
                            "scope_id": scope_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise CredentialNotFoundError(f"{consumer_type}:{consumer_id}:{purpose}")
        payload = self._decode(row["encrypted_value"])
        return CredentialRecord(
            ref=str(row["id"]),
            kind=row["secret_type"],
            public=dict(payload.get("public") or {}),
            secrets=dict(payload.get("secrets") or {}),
            meta=dict(payload.get("meta") or {}),
        )

    async def revoke(
        self,
        *,
        credential_id: UUID,
        scope_type: str,
        scope_id: UUID,
        session: AsyncSession | None = None,
    ) -> bool:
        if session is None:
            async with self._session_factory() as owned:
                return await self.revoke(
                    credential_id=credential_id,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    session=owned,
                )
        result = await session.execute(
            text(
                f"UPDATE {self._credentials} SET status='revoked', revoked_at=now() WHERE id=:id AND scope_type=:scope_type AND scope_id=:scope_id AND status='active'"
            ),
            {"id": credential_id, "scope_type": scope_type, "scope_id": scope_id},
        )
        return bool(result.rowcount)

    async def revoke_binding(
        self,
        *,
        consumer_type: str,
        consumer_id: UUID,
        purpose: str,
        scope_type: str,
        scope_id: UUID,
        session: AsyncSession | None = None,
    ) -> bool:
        """Revoke and remove one binding only within its declared scope."""
        if session is None:
            async with self._session_factory() as owned:
                return await self.revoke_binding(
                    consumer_type=consumer_type,
                    consumer_id=consumer_id,
                    purpose=purpose,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    session=owned,
                )
        credential_id = await session.scalar(
            text(
                f"SELECT cb.credential_id FROM {self._bindings} cb "
                f"JOIN {self._credentials} cr ON cr.id=cb.credential_id "
                "WHERE cb.consumer_type=:ct AND cb.consumer_id=:cid "
                "AND cb.purpose=:purpose AND cr.scope_type=:scope_type "
                "AND cr.scope_id=:scope_id FOR UPDATE OF cb,cr"
            ),
            {
                "ct": consumer_type,
                "cid": consumer_id,
                "purpose": purpose,
                "scope_type": scope_type,
                "scope_id": scope_id,
            },
        )
        if credential_id is None:
            return False
        await self.revoke(
            credential_id=credential_id,
            scope_type=scope_type,
            scope_id=scope_id,
            session=session,
        )
        await session.execute(
            text(
                f"DELETE FROM {self._bindings} WHERE consumer_type=:ct "
                "AND consumer_id=:cid AND purpose=:purpose "
                "AND credential_id=:credential_id"
            ),
            {
                "ct": consumer_type,
                "cid": consumer_id,
                "purpose": purpose,
                "credential_id": credential_id,
            },
        )
        return True

    async def replace_active_value(
        self,
        *,
        session: AsyncSession,
        credential_id: UUID,
        scope_type: str,
        scope_id: UUID,
        record: CredentialRecord,
    ) -> bool:
        result = await session.execute(
            text(
                f"UPDATE {self._credentials} SET encrypted_value=:value, "
                "key_version=:version,rotated_at=now() WHERE id=:id "
                "AND scope_type=:scope_type AND scope_id=:scope_id "
                "AND status='active' AND revoked_at IS NULL"
            ),
            {
                "id": credential_id,
                "scope_type": scope_type,
                "scope_id": scope_id,
                "value": self._encode(record),
                "version": _KEY_VERSION,
            },
        )
        return bool(result.rowcount)
