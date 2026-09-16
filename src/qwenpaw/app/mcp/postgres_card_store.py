# -*- coding: utf-8 -*-
"""Database-backed DriverCard reads with disposable YAML materialization."""

from __future__ import annotations

from pathlib import Path

from ...drivers.credentials.providers import CredentialProvider
from ...drivers.errors import DriverNotFoundError
from ...drivers.storage import AsyncDriverCardStore

REVISION_KEY = "_postgres_revision"


class _RevisionGuardedProvider(CredentialProvider):
    def __init__(self, store, card, provider):
        self._store, self._card, self._provider = store, card, provider

    async def resolve(self):
        if not await self._store.is_current(self._card):
            raise DriverNotFoundError(self._card.name)
        return await self._provider.resolve()

    async def close(self):
        await self._provider.close()

    def on_secrets_changed(self, secrets=None):
        self._provider.on_secrets_changed(secrets)


class PostgresMCPCardStore(AsyncDriverCardStore):
    """PG is authoritative even if a YAML cache is missing or altered."""

    authoritative = True

    def __init__(self, cards_dir: Path, *, agent_key: str, repository):
        super().__init__(cards_dir)
        self._agent_key, self._repository = agent_key, repository

    @staticmethod
    def _project(record):
        from .config_service import _card_from_postgres

        card = _card_from_postgres(record)
        card.config[REVISION_KEY] = record.revision
        return card

    async def load(self, name: str, *, protocol: str):
        if protocol != "mcp":
            raise DriverNotFoundError(name)
        record = await self._repository.get_driver(
            agent_key=self._agent_key,
            client_key=name,
        )
        if record is None:
            raise DriverNotFoundError(name)
        return self._project(record)

    async def load_path(self, path: Path):
        for record in await self._repository.list_drivers(agent_key=self._agent_key):
            if self.path_for(record.client_key, protocol="mcp") == path:
                return self._project(record)
        raise DriverNotFoundError(path.stem)

    async def list_paths(self):
        return [
            self.path_for(record.client_key, protocol="mcp")
            for record in await self._repository.list_drivers(agent_key=self._agent_key)
        ]

    async def stored_path(self, name: str):
        record = await self._repository.get_driver(
            agent_key=self._agent_key, client_key=name
        )
        return self.path_for(name, protocol="mcp") if record is not None else None

    async def save(self, card):
        # Ignore supplied runtime mutations; project the committed revision.
        current = await self.load(card.name, protocol=card.protocol)
        return await super().save(current)

    async def delete(self, name: str):
        # Logical deletion belongs to the repository transaction. Retaining
        # cache files cannot resurrect a Driver because reads never scan them.
        if await self.stored_path(name) is not None:
            raise ValueError("MCP deletion must commit before runtime removal")

    async def is_current(self, card):
        record = await self._repository.get_driver(
            agent_key=self._agent_key, client_key=card.name
        )
        return bool(
            record
            and record.enabled
            and record.revision == card.config.get(REVISION_KEY)
        )

    def guard_provider(self, card, provider):
        return _RevisionGuardedProvider(self, card, provider)
