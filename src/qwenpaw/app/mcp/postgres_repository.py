# -*- coding: utf-8 -*-
"""Transactional PostgreSQL source of truth for MCP driver configuration."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...access.agent_repository import agent_database_id
from ...drivers.credentials.postgres_store import PostgresCredentialStore
from ...drivers.constants import CREDENTIAL_KIND_OAUTH_AUTH_CODE
from ...drivers.credentials.types import CredentialRecord
from ...drivers.errors import CredentialNotFoundError
from ...persistence.database import database_session
from ...persistence.mode import StorageMode
from ...persistence.settings import load_database_settings

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_OAUTH_AUTHORIZATION = {
    "source": "credential",
    "credential": "oauth",
    "field": "access_token",
    "format": "Bearer {value}",
}


def _is_oauth_authorization(value: Any) -> bool:
    return isinstance(value, Mapping) and all(
        value.get(key) == expected
        for key, expected in _OAUTH_AUTHORIZATION.items()
    )


def _has_oauth_authorization_conflict(config: Mapping[str, Any]) -> bool:
    endpoint = config.get("endpoint") or {}
    if str(endpoint.get("transport") or "stdio") == "stdio":
        return False
    headers = endpoint.get("headers") or {}
    return any(
        name.lower() == "authorization"
        and (name != "Authorization" or not _is_oauth_authorization(value))
        for name, value in headers.items()
    )


def _attach_oauth_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if _has_oauth_authorization_conflict(config):
        raise ValueError("oauth_authorization_conflict")
    updated = dict(config)
    credentials = dict(updated.get("credentials") or {})
    credentials["oauth"] = {
        "kind": CREDENTIAL_KIND_OAUTH_AUTH_CODE,
        "purpose": "oauth",
    }
    endpoint = dict(updated.get("endpoint") or {})
    if str(endpoint.get("transport") or "stdio") != "stdio":
        headers = dict(endpoint.get("headers") or {})
        headers["Authorization"] = dict(_OAUTH_AUTHORIZATION)
        endpoint["headers"] = headers
    updated["credentials"] = credentials
    updated["endpoint"] = endpoint
    return updated


def _detach_oauth_config(config: Mapping[str, Any]) -> dict[str, Any]:
    updated = dict(config)
    credentials = dict(updated.get("credentials") or {})
    credentials.pop("oauth", None)
    endpoint = dict(updated.get("endpoint") or {})
    headers = dict(endpoint.get("headers") or {})
    authorization = headers.get("Authorization")
    if _is_oauth_authorization(authorization):
        headers.pop("Authorization", None)
    endpoint["headers"] = headers
    updated["credentials"] = credentials
    updated["endpoint"] = endpoint
    return updated


def is_postgres_mcp_enabled() -> bool:
    """Return whether PostgreSQL MCP persistence is available.

    Per-Agent cutover is decided separately: an Agent with legacy cards and
    no PostgreSQL drivers must remain on the legacy adapter.
    """
    return load_database_settings().storage_mode is StorageMode.POSTGRES


async def workspace_uses_postgres(
    workspace: Any,
    *,
    repository: "PostgresMCPRepository | None" = None,
) -> bool:
    """Apply the per-Agent cutover gate without hiding legacy cards."""
    if not is_postgres_mcp_enabled():
        return False
    if repository is None:
        from ...identity.runtime import get_identity_schema

        repository = PostgresMCPRepository(schema=get_identity_schema())
    if await repository.has_any_driver(agent_key=workspace.agent_id):
        return True
    from ...drivers.storage import AsyncDriverCardStore

    store = AsyncDriverCardStore(workspace.workspace_dir / "drivers")
    for path in await store.list_paths():
        try:
            card = await store.load_path(path)
        except Exception:
            continue
        if card.protocol == "mcp":
            return False
    return True


class MCPRevisionConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("mcp_revision_conflict")


@dataclass(frozen=True, slots=True)
class MCPDriverRecord:
    driver_id: UUID
    agent_id: UUID
    client_key: str
    enabled: bool
    revision: int
    config: dict[str, Any]
    tool_allowlist: list[str] | None
    policy: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MCPDriverTarget:
    driver_id: UUID
    agent_id: UUID
    client_key: str
    revision: int
    enabled: bool
    endpoint_url: str
    oauth_authorization_conflict: bool = False


@dataclass(frozen=True, slots=True)
class MCPBoundCredentialStatus:
    authorized: bool
    expires_at: float = 0.0
    scope: str = ""
    client_id: str = ""


@dataclass(frozen=True, slots=True)
class MCPPrincipalIdentity:
    user_id: UUID
    username: str


class PostgresMCPRepository:
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
        self._drivers = f"{prefix}agent_drivers"
        self._revisions = f"{prefix}driver_revisions"
        self._bindings = f"{prefix}credential_bindings"
        self._credential_records = f"{prefix}credential_records"
        self._agents = f"{prefix}agents"
        self._agent_members = f"{prefix}agent_members"
        self._users = f"{prefix}users"
        self._session_factory = session_factory
        self._credentials = PostgresCredentialStore(
            schema=normalized, session_factory=session_factory
        )

    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._session_factory()

    async def list_principal_identities(
        self, *, agent_key: str
    ) -> list[MCPPrincipalIdentity]:
        """Return active owner and active, unrevoked members for policy UI."""
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "WITH eligible_users AS ("
                    f"SELECT a.owner_user_id AS user_id FROM {self._agents} a "
                    "WHERE a.id=:agent_id "
                    "UNION "
                    f"SELECT am.user_id FROM {self._agent_members} am "
                    "WHERE am.agent_id=:agent_id AND am.revoked_at IS NULL) "
                    f"SELECT u.id AS user_id,u.username FROM {self._users} u "
                    "JOIN eligible_users e ON e.user_id=u.id "
                    "WHERE u.status='active' ORDER BY u.username,u.id"
                ),
                {"agent_id": agent_database_id(agent_key)},
            )
            rows = result.mappings().all()
        return [
            MCPPrincipalIdentity(user_id=row["user_id"], username=row["username"])
            for row in rows
        ]

    @staticmethod
    def _hash(
        config: Mapping[str, Any], tools: list[str] | None, policy: Mapping[str, Any]
    ) -> str:
        value = json.dumps(
            {"config": config, "tool_allowlist": tools, "policy": policy},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _record(row: Mapping[str, Any]) -> MCPDriverRecord:
        allowlist = row["tool_allowlist"]
        return MCPDriverRecord(
            driver_id=row["driver_id"],
            agent_id=row["agent_id"],
            client_key=row["client_key"],
            enabled=row["status"] == "enabled",
            revision=row["revision"],
            config=dict(row["config"] or {}),
            tool_allowlist=None if allowlist is None else list(allowlist),
            policy=dict(row["policy"] or {}),
        )

    async def create_driver(
        self,
        *,
        agent_key: str,
        client_key: str,
        created_by: UUID,
        config: Mapping[str, Any],
        tool_allowlist: list[str] | None,
        policy: Mapping[str, Any],
        session: AsyncSession | None = None,
    ) -> MCPDriverRecord:
        if session is None:
            async with self._session_factory() as owned:
                await self.create_driver(
                    agent_key=agent_key,
                    client_key=client_key,
                    created_by=created_by,
                    config=config,
                    tool_allowlist=tool_allowlist,
                    policy=policy,
                    session=owned,
                )
            result = await self.get_driver(agent_key=agent_key, client_key=client_key)
            assert result is not None
            return result
        driver_id, revision_id = uuid4(), uuid4()
        await session.execute(
            text(
                f"INSERT INTO {self._drivers} (id,agent_id,protocol,name,status,created_by) VALUES (:id,:agent,'mcp',:name,'enabled',:created_by)"
            ),
            {
                "id": driver_id,
                "agent": agent_database_id(agent_key),
                "name": client_key,
                "created_by": created_by,
            },
        )
        await self._insert_revision(
            session=session,
            revision_id=revision_id,
            driver_id=driver_id,
            revision=1,
            config=config,
            tool_allowlist=tool_allowlist,
            policy=policy,
            created_by=created_by,
        )
        await session.execute(
            text(
                f"UPDATE {self._drivers} SET current_revision_id=:revision_id WHERE id=:driver_id"
            ),
            {"revision_id": revision_id, "driver_id": driver_id},
        )
        return MCPDriverRecord(
            driver_id=driver_id,
            agent_id=agent_database_id(agent_key),
            client_key=client_key,
            enabled=True,
            revision=1,
            config=dict(config),
            tool_allowlist=tool_allowlist,
            policy=dict(policy),
        )

    async def _insert_revision(
        self,
        *,
        session: AsyncSession,
        revision_id: UUID,
        driver_id: UUID,
        revision: int,
        config: Mapping[str, Any],
        tool_allowlist: list[str] | None,
        policy: Mapping[str, Any],
        created_by: UUID,
    ) -> None:
        await session.execute(
            text(
                f"INSERT INTO {self._revisions} (id,driver_id,revision,config,tool_allowlist,policy,content_hash,created_by) VALUES (:id,:driver_id,:revision,CAST(:config AS jsonb),CAST(:tools AS jsonb),CAST(:policy AS jsonb),:hash,:created_by)"
            ),
            {
                "id": revision_id,
                "driver_id": driver_id,
                "revision": revision,
                "config": json.dumps(dict(config), ensure_ascii=False),
                "tools": json.dumps(tool_allowlist),
                "policy": json.dumps(dict(policy), ensure_ascii=False),
                "hash": self._hash(config, tool_allowlist, policy),
                "created_by": created_by,
            },
        )

    async def get_driver(
        self,
        *,
        agent_key: str,
        client_key: str,
        session: AsyncSession | None = None,
        for_update: bool = False,
    ) -> MCPDriverRecord | None:
        if session is None:
            async with self._session_factory() as owned:
                return await self.get_driver(
                    agent_key=agent_key,
                    client_key=client_key,
                    session=owned,
                    for_update=for_update,
                )
        suffix = " FOR UPDATE OF ad" if for_update else ""
        row = (
            (
                await session.execute(
                    text(
                        f"SELECT ad.id driver_id,ad.agent_id,ad.name client_key,ad.status,dr.revision,dr.config,dr.tool_allowlist,dr.policy FROM {self._drivers} ad JOIN {self._revisions} dr ON dr.id=ad.current_revision_id WHERE ad.agent_id=:agent AND ad.protocol='mcp' AND ad.name=:name AND ad.status<>'deleted'{suffix}"
                    ),
                    {"agent": agent_database_id(agent_key), "name": client_key},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._record(row)

    async def list_drivers(self, *, agent_key: str) -> list[MCPDriverRecord]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            f"SELECT ad.id driver_id,ad.agent_id,ad.name client_key,ad.status,dr.revision,dr.config,dr.tool_allowlist,dr.policy FROM {self._drivers} ad JOIN {self._revisions} dr ON dr.id=ad.current_revision_id WHERE ad.agent_id=:agent AND ad.protocol='mcp' AND ad.status<>'deleted' ORDER BY ad.name"
                        ),
                        {"agent": agent_database_id(agent_key)},
                    )
                )
                .mappings()
                .all()
            )
        return [self._record(row) for row in rows]

    async def has_any_driver(self, *, agent_key: str) -> bool:
        async with self._session_factory() as session:
            value = await session.scalar(
                text(
                    f"SELECT EXISTS(SELECT 1 FROM {self._drivers} WHERE agent_id=:agent AND protocol='mcp')"
                ),
                {"agent": agent_database_id(agent_key)},
            )
        return bool(value)

    async def update_driver(
        self,
        *,
        agent_key: str,
        client_key: str,
        expected_revision: int,
        updated_by: UUID,
        config: Mapping[str, Any],
        tool_allowlist: list[str] | None,
        policy: Mapping[str, Any],
        session: AsyncSession | None = None,
    ) -> MCPDriverRecord:
        if session is None:
            async with self._session_factory() as owned:
                await self.update_driver(
                    agent_key=agent_key,
                    client_key=client_key,
                    expected_revision=expected_revision,
                    updated_by=updated_by,
                    config=config,
                    tool_allowlist=tool_allowlist,
                    policy=policy,
                    session=owned,
                )
            result = await self.get_driver(agent_key=agent_key, client_key=client_key)
            assert result is not None
            return result
        current = await self.get_driver(
            agent_key=agent_key,
            client_key=client_key,
            session=session,
            for_update=True,
        )
        if current is None:
            raise CredentialNotFoundError(client_key)
        if current.revision != expected_revision:
            raise MCPRevisionConflict()
        revision_id = uuid4()
        await self._insert_revision(
            session=session,
            revision_id=revision_id,
            driver_id=current.driver_id,
            revision=current.revision + 1,
            config=config,
            tool_allowlist=tool_allowlist,
            policy=policy,
            created_by=updated_by,
        )
        await session.execute(
            text(
                f"UPDATE {self._drivers} SET current_revision_id=:revision_id WHERE id=:driver_id"
            ),
            {"revision_id": revision_id, "driver_id": current.driver_id},
        )
        return MCPDriverRecord(
            driver_id=current.driver_id,
            agent_id=current.agent_id,
            client_key=current.client_key,
            enabled=current.enabled,
            revision=current.revision + 1,
            config=dict(config),
            tool_allowlist=tool_allowlist,
            policy=dict(policy),
        )

    async def set_enabled(
        self,
        *,
        agent_key: str,
        client_key: str,
        expected_revision: int,
        updated_by: UUID,
        enabled: bool,
    ) -> MCPDriverRecord:
        current = await self.get_driver(agent_key=agent_key, client_key=client_key)
        if current is None:
            raise CredentialNotFoundError(client_key)
        async with self._session_factory() as session:
            locked = await self.get_driver(
                agent_key=agent_key,
                client_key=client_key,
                session=session,
                for_update=True,
            )
            if locked is None or locked.revision != expected_revision:
                raise MCPRevisionConflict()
            revision_id = uuid4()
            await self._insert_revision(
                session=session,
                revision_id=revision_id,
                driver_id=locked.driver_id,
                revision=locked.revision + 1,
                config=locked.config,
                tool_allowlist=locked.tool_allowlist,
                policy=locked.policy,
                created_by=updated_by,
            )
            await session.execute(
                text(
                    f"UPDATE {self._drivers} SET status=:status,current_revision_id=:revision_id WHERE id=:driver_id"
                ),
                {
                    "status": "enabled" if enabled else "disabled",
                    "revision_id": revision_id,
                    "driver_id": locked.driver_id,
                },
            )
        result = await self.get_driver(agent_key=agent_key, client_key=client_key)
        assert result is not None
        return result

    async def delete_driver(
        self, *, agent_key: str, client_key: str, expected_revision: int
    ) -> bool:
        async with self._session_factory() as session:
            current = await self.get_driver(
                agent_key=agent_key,
                client_key=client_key,
                session=session,
                for_update=True,
            )
            if current is None:
                return False
            if current.revision != expected_revision:
                raise MCPRevisionConflict()
            await session.execute(
                text(
                    f"UPDATE {self._credential_records} SET "
                    "status='revoked',revoked_at=now() WHERE status='active' "
                    f"AND id IN (SELECT credential_id FROM {self._bindings} "
                    "WHERE consumer_type='driver' AND consumer_id=:driver_id)"
                ),
                {"driver_id": current.driver_id},
            )
            await session.execute(
                text(
                    f"DELETE FROM {self._bindings} WHERE consumer_type='driver' "
                    "AND consumer_id=:driver_id"
                ),
                {"driver_id": current.driver_id},
            )
            await session.execute(
                text(
                    f"UPDATE {self._drivers} SET status='deleted' WHERE id=:driver_id"
                ),
                {"driver_id": current.driver_id},
            )
        return True

    async def get_oauth_target(
        self, *, session: AsyncSession, agent_key: str, client_key: str
    ) -> MCPDriverTarget | None:
        record = await self.get_driver(
            agent_key=agent_key, client_key=client_key, session=session, for_update=True
        )
        if record is None:
            return None
        endpoint = record.config.get("endpoint")
        endpoint_url = str(
            (endpoint.get("url") if isinstance(endpoint, dict) else None)
            or record.config.get("url")
            or ""
        )
        return MCPDriverTarget(
            record.driver_id,
            record.agent_id,
            record.client_key,
            record.revision,
            record.enabled,
            endpoint_url,
            _has_oauth_authorization_conflict(record.config),
        )

    async def replace_bound_credential(
        self,
        *,
        session: AsyncSession,
        target: MCPDriverTarget,
        actor_user_id: UUID,
        purpose: str,
        kind: str,
        public: Mapping[str, Any],
        secrets: Mapping[str, str],
    ) -> UUID:
        row = (
            (
                await session.execute(
                    text(
                        f"SELECT ad.id,ad.agent_id,ad.name,ad.status,dr.revision,dr.config,dr.tool_allowlist,dr.policy FROM {self._drivers} ad JOIN {self._revisions} dr ON dr.id=ad.current_revision_id WHERE ad.id=:driver_id AND ad.agent_id=:agent_id AND ad.protocol='mcp' AND ad.name=:name AND ad.status<>'deleted' FOR UPDATE OF ad"
                    ),
                    {
                        "driver_id": target.driver_id,
                        "agent_id": target.agent_id,
                        "name": target.client_key,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["revision"] != target.revision:
            raise MCPRevisionConflict()
        config = (
            _attach_oauth_config(row["config"] or {})
            if purpose == "oauth"
            else dict(row["config"] or {})
        )
        credential_id = await self._credentials.create_and_bind(
            record=CredentialRecord(
                ref="", kind=kind, public=dict(public), secrets=dict(secrets)
            ),
            scope_type="driver",
            scope_id=target.driver_id,
            consumer_type="driver",
            consumer_id=target.driver_id,
            purpose=purpose,
            created_by=actor_user_id,
            session=session,
        )
        revision_id = uuid4()
        allowlist = row["tool_allowlist"]
        await self._insert_revision(
            session=session,
            revision_id=revision_id,
            driver_id=target.driver_id,
            revision=target.revision + 1,
            config=config,
            tool_allowlist=None if allowlist is None else list(allowlist),
            policy=dict(row["policy"] or {}),
            created_by=actor_user_id,
        )
        await session.execute(
            text(
                f"UPDATE {self._drivers} SET current_revision_id=:revision_id WHERE id=:driver_id"
            ),
            {"revision_id": revision_id, "driver_id": target.driver_id},
        )
        return credential_id

    async def resolve_bound_credential(
        self, *, agent_key: str, client_key: str, purpose: str
    ) -> CredentialRecord:
        target_record = await self.get_driver(
            agent_key=agent_key, client_key=client_key
        )
        if target_record is None or not target_record.enabled:
            raise CredentialNotFoundError(client_key)
        return await self._credentials.resolve(
            consumer_type="driver",
            consumer_id=target_record.driver_id,
            purpose=purpose,
            scope_type="driver",
            scope_id=target_record.driver_id,
        )

    async def bound_credential_status(
        self, *, agent_key: str, client_key: str, purpose: str = "oauth"
    ) -> MCPBoundCredentialStatus:
        try:
            record = await self.resolve_bound_credential(
                agent_key=agent_key, client_key=client_key, purpose=purpose
            )
        except CredentialNotFoundError:
            return MCPBoundCredentialStatus(authorized=False)
        public = record.public
        expires = public.get("expires_at", 0.0)
        try:
            expires_at = float(expires or 0.0)
        except (TypeError, ValueError):
            expires_at = 0.0
        return MCPBoundCredentialStatus(
            authorized=bool(record.secrets.get("access_token")),
            expires_at=expires_at,
            scope=str(public.get("scope") or ""),
            client_id=str(public.get("client_id") or ""),
        )

    async def refresh_oauth_credential(
        self,
        *,
        agent_key: str,
        credential_id: UUID,
        record: CredentialRecord,
    ) -> None:
        """Replace one active OAuth token only while its binding remains valid."""
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"SELECT ad.id driver_id FROM {self._drivers} ad "
                            f"JOIN {self._bindings} cb ON cb.consumer_type='driver' "
                            "AND cb.consumer_id=ad.id AND cb.purpose='oauth' "
                            f"JOIN {self._credential_records} cr ON cr.id=cb.credential_id "
                            "WHERE ad.agent_id=:agent_id AND ad.protocol='mcp' "
                            "AND ad.status='enabled' AND cr.id=:credential_id "
                            "AND cr.status='active' AND cr.revoked_at IS NULL "
                            "FOR UPDATE OF ad,cr"
                        ),
                        {
                            "agent_id": agent_database_id(agent_key),
                            "credential_id": credential_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or record.kind != CREDENTIAL_KIND_OAUTH_AUTH_CODE:
                raise CredentialNotFoundError(str(credential_id))
            updated = await self._credentials.replace_active_value(
                session=session,
                credential_id=credential_id,
                scope_type="driver",
                scope_id=row["driver_id"],
                record=record,
            )
            if not updated:
                raise CredentialNotFoundError(str(credential_id))

    async def revoke_bound_credential(
        self,
        *,
        session: AsyncSession,
        target: MCPDriverTarget,
        actor_user_id: UUID,
        purpose: str = "oauth",
    ) -> bool:
        row = (
            (
                await session.execute(
                    text(
                        f"SELECT ad.id,dr.revision,dr.config,dr.tool_allowlist,dr.policy,cb.credential_id FROM {self._drivers} ad JOIN {self._revisions} dr ON dr.id=ad.current_revision_id LEFT JOIN {self._bindings} cb ON cb.consumer_type='driver' AND cb.consumer_id=ad.id AND cb.purpose=:purpose WHERE ad.id=:driver_id AND ad.agent_id=:agent_id AND ad.protocol='mcp' AND ad.name=:name AND ad.status<>'deleted' FOR UPDATE OF ad"
                    ),
                    {
                        "purpose": purpose,
                        "driver_id": target.driver_id,
                        "agent_id": target.agent_id,
                        "name": target.client_key,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["revision"] != target.revision:
            raise MCPRevisionConflict()
        credential_id = row["credential_id"]
        if credential_id is None:
            return False
        await self._credentials.revoke(
            credential_id=credential_id,
            scope_type="driver",
            scope_id=target.driver_id,
            session=session,
        )
        await session.execute(
            text(
                f"DELETE FROM {self._bindings} WHERE consumer_type='driver' AND consumer_id=:driver_id AND purpose=:purpose"
            ),
            {"driver_id": target.driver_id, "purpose": purpose},
        )
        revision_id = uuid4()
        allowlist = row["tool_allowlist"]
        await self._insert_revision(
            session=session,
            revision_id=revision_id,
            driver_id=target.driver_id,
            revision=target.revision + 1,
            config=(
                _detach_oauth_config(row["config"] or {})
                if purpose == "oauth"
                else dict(row["config"] or {})
            ),
            tool_allowlist=None if allowlist is None else list(allowlist),
            policy=dict(row["policy"] or {}),
            created_by=actor_user_id,
        )
        await session.execute(
            text(
                f"UPDATE {self._drivers} SET current_revision_id=:revision_id, credential_binding_id=NULL WHERE id=:driver_id"
            ),
            {"revision_id": revision_id, "driver_id": target.driver_id},
        )
        return True
