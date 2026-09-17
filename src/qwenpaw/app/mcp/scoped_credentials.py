# -*- coding: utf-8 -*-
"""Driver credential adapter bound to one PostgreSQL Agent scope."""

from __future__ import annotations

from uuid import UUID

from ...drivers.errors import CredentialNotFoundError, DriverCardError
from .postgres_repository import PostgresMCPRepository

_PREFIX = "pgmcp/"


def postgres_credential_ref(client_key: str, purpose: str) -> str:
    return f"{_PREFIX}{client_key}/{purpose}"


class ScopedPostgresMCPCredentialStore:
    """Expose runtime get without permitting an unscoped database read."""

    def __init__(self, *, agent_key: str, repository: PostgresMCPRepository) -> None:
        self._agent_key = agent_key
        self._repository = repository

    async def get(self, ref: str):
        if not ref.startswith(_PREFIX):
            raise CredentialNotFoundError(ref)
        client_key, separator, purpose = ref[len(_PREFIX) :].rpartition("/")
        if not separator or not client_key or not purpose:
            raise CredentialNotFoundError(ref)
        return await self._repository.resolve_bound_credential(
            agent_key=self._agent_key,
            client_key=client_key,
            purpose=purpose,
        )

    async def put(self, record) -> None:
        try:
            credential_id = UUID(record.ref)
        except (TypeError, ValueError) as exc:
            raise DriverCardError(
                "PostgreSQL credential refresh requires a resolved reference"
            ) from exc
        await self._repository.refresh_oauth_credential(
            agent_key=self._agent_key,
            credential_id=credential_id,
            record=record,
        )

    async def delete(self, _ref: str) -> None:
        raise DriverCardError("PostgreSQL credentials require a scoped transaction")

    async def list_refs(self) -> list[str]:
        return []
