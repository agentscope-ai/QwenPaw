# -*- coding: utf-8 -*-
"""用户级频道绑定持久化，不修改 Agent 的文件配置。"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..persistence.database import database_session
from ..security.secret_store import decrypt, encrypt
from .agent_repository import _SAFE_SCHEMA, agent_database_id

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True, slots=True)
class ChannelBindingRecord:
    """一个用户在指定 Agent 下拥有的频道绑定。"""

    id: UUID
    agent_key: str
    owner_user_id: UUID
    channel_type: str
    display_name: str
    enabled: bool
    config: dict[str, Any]
    configured_secret_fields: tuple[str, ...] = ()


class PostgresChannelBindingRepository:
    """在 PostgreSQL 中按用户隔离频道绑定控制面事实。"""

    def __init__(
        self,
        *,
        schema: str = "qwenpaw",
        session_factory: SessionFactory = database_session,
    ) -> None:
        normalized_schema = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized_schema):
            raise ValueError("invalid_database_schema")
        prefix = f'"{normalized_schema}".'
        self._bindings_table = f"{prefix}channel_bindings"
        self._credentials_table = f"{prefix}credential_records"
        self._external_identities_table = (
            f"{prefix}channel_external_identities"
        )
        self._access_rules_table = f"{prefix}channel_access_rules"
        self._session_factory = session_factory

    @staticmethod
    def _decode_secrets(value: bytes | None) -> dict[str, str]:
        if not value:
            return {}
        decoded = decrypt(value.decode("utf-8"))
        try:
            payload = json.loads(decoded)
        except (TypeError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): str(secret)
            for key, secret in payload.items()
            if secret is not None
        }

    @classmethod
    def _record(cls, row, agent_key: str) -> ChannelBindingRecord:
        secrets = cls._decode_secrets(row.get("encrypted_value"))
        return ChannelBindingRecord(
            id=row["id"],
            agent_key=agent_key,
            owner_user_id=row["owner_user_id"],
            channel_type=row["channel_type"],
            display_name=row["display_name"],
            enabled=row["status"] == "enabled",
            config=dict(row["config"] or {}),
            configured_secret_fields=tuple(sorted(secrets)),
        )

    async def list_for_user(
        self,
        *,
        agent_key: str,
        owner_user_id: UUID,
    ) -> list[ChannelBindingRecord]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT cb.id, cb.owner_user_id, cb.channel_type, "
                        "cb.display_name, cb.status, cb.config, "
                        "cr.encrypted_value "
                        f"FROM {self._bindings_table} cb "
                        f"LEFT JOIN {self._credentials_table} cr "
                        "ON cr.id = cb.credential_ref "
                        "WHERE agent_id = :agent_id "
                        "AND owner_user_id = :owner_user_id "
                        "ORDER BY channel_type, cb.id"
                    ),
                    {
                        "agent_id": agent_database_id(agent_key),
                        "owner_user_id": owner_user_id,
                    },
                )
            ).mappings().all()
        return [self._record(row, agent_key) for row in rows]

    async def list_enabled(
        self,
        *,
        agent_keys: list[str],
    ) -> list[ChannelBindingRecord]:
        if not agent_keys:
            return []
        key_by_id = {agent_database_id(key): key for key in agent_keys}
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT cb.id, cb.agent_id, cb.owner_user_id, "
                        "cb.channel_type, cb.display_name, cb.status, "
                        "cb.config, cr.encrypted_value "
                        f"FROM {self._bindings_table} cb "
                        f"LEFT JOIN {self._credentials_table} cr "
                        "ON cr.id = cb.credential_ref "
                        "WHERE cb.status = 'enabled' "
                        "AND cb.agent_id = ANY(CAST(:agent_ids AS uuid[])) "
                        "ORDER BY cb.created_at, cb.id"
                    ),
                    {"agent_ids": list(key_by_id)},
                )
            ).mappings().all()
        return [
            self._record(row, key_by_id[row["agent_id"]])
            for row in rows
            if row["agent_id"] in key_by_id
        ]

    async def list_enabled_runtime_configs(
        self,
        *,
        channel_type: str,
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT cb.agent_id, cb.owner_user_id, cb.config, "
                        "cr.encrypted_value "
                        f"FROM {self._bindings_table} cb "
                        f"LEFT JOIN {self._credentials_table} cr "
                        "ON cr.id = cb.credential_ref "
                        "WHERE cb.status = 'enabled' "
                        "AND cb.channel_type = :channel_type"
                    ),
                    {"channel_type": channel_type},
                )
            ).mappings().all()
        return [
            {
                "agent_id": row["agent_id"],
                "owner_user_id": row["owner_user_id"],
                "config": {
                    **dict(row["config"] or {}),
                    **self._decode_secrets(row["encrypted_value"]),
                },
            }
            for row in rows
        ]

    async def upsert(
        self,
        *,
        agent_key: str,
        owner_user_id: UUID,
        channel_type: str,
        display_name: str,
        enabled: bool,
        config: dict[str, Any],
        secrets: dict[str, str],
    ) -> ChannelBindingRecord:
        binding_id = uuid4()
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        f"INSERT INTO {self._bindings_table} "
                        "(id, agent_id, owner_user_id, channel_type, "
                        "display_name, status, config, created_by, updated_by) "
                        "VALUES (:id, :agent_id, :owner_user_id, :channel_type, "
                        ":display_name, :status, CAST(:config AS jsonb), "
                        ":owner_user_id, :owner_user_id) "
                        "ON CONFLICT (agent_id, owner_user_id, channel_type) "
                        "DO UPDATE SET display_name = EXCLUDED.display_name, "
                        "status = EXCLUDED.status, config = EXCLUDED.config, "
                        "updated_by = EXCLUDED.updated_by, updated_at = now() "
                        "RETURNING id, owner_user_id, channel_type, "
                        "display_name, status, config, credential_ref"
                    ),
                    {
                        "id": binding_id,
                        "agent_id": agent_database_id(agent_key),
                        "owner_user_id": owner_user_id,
                        "channel_type": channel_type,
                        "display_name": display_name,
                        "status": "enabled" if enabled else "disabled",
                        "config": json.dumps(config),
                    },
                )
            ).mappings().one()
            credential_ref = row["credential_ref"]
            encrypted_value = None
            if secrets:
                encrypted_value = encrypt(
                    json.dumps(secrets, ensure_ascii=False)
                ).encode("utf-8")
                if credential_ref is None:
                    credential_ref = uuid4()
                    await session.execute(
                        text(
                            f"INSERT INTO {self._credentials_table} "
                            "(id, scope_type, scope_id, secret_type, "
                            "encrypted_value, key_version, status, created_by) "
                            "VALUES (:id, 'channel', :binding_id, "
                            "'channel-config', :encrypted_value, "
                            "'fernet-v1', 'active', :created_by)"
                        ),
                        {
                            "id": credential_ref,
                            "binding_id": row["id"],
                            "encrypted_value": encrypted_value,
                            "created_by": owner_user_id,
                        },
                    )
                    await session.execute(
                        text(
                            f"UPDATE {self._bindings_table} "
                            "SET credential_ref = :credential_ref "
                            "WHERE id = :binding_id"
                        ),
                        {
                            "credential_ref": credential_ref,
                            "binding_id": row["id"],
                        },
                    )
                else:
                    await session.execute(
                        text(
                            f"UPDATE {self._credentials_table} "
                            "SET encrypted_value = :encrypted_value, "
                            "key_version = 'fernet-v1', status = 'active', "
                            "rotated_at = now(), revoked_at = NULL "
                            "WHERE id = :credential_ref"
                        ),
                        {
                            "credential_ref": credential_ref,
                            "encrypted_value": encrypted_value,
                        },
                    )
            elif credential_ref is not None:
                encrypted_value = await session.scalar(
                    text(
                        f"SELECT encrypted_value FROM {self._credentials_table} "
                        "WHERE id = :credential_ref"
                    ),
                    {"credential_ref": credential_ref},
                )
        return self._record(
            {**row, "encrypted_value": encrypted_value},
            agent_key,
        )

    async def get_runtime_config(
        self,
        *,
        binding_id: UUID,
        owner_user_id: UUID,
    ) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT cb.config, cr.encrypted_value "
                        f"FROM {self._bindings_table} cb "
                        f"LEFT JOIN {self._credentials_table} cr "
                        "ON cr.id = cb.credential_ref "
                        "WHERE cb.id = :binding_id "
                        "AND cb.owner_user_id = :owner_user_id"
                    ),
                    {
                        "binding_id": binding_id,
                        "owner_user_id": owner_user_id,
                    },
                )
            ).mappings().one_or_none()
        if row is None:
            return None
        return {
            **dict(row["config"] or {}),
            **self._decode_secrets(row["encrypted_value"]),
        }

    async def upsert_external_identity(
        self,
        *,
        binding_id: UUID,
        external_subject_id: str,
        platform_user_id: UUID,
        metadata: dict[str, Any],
    ) -> None:
        """记录个人频道看到的外部主体及其平台归属。"""
        normalized_subject = external_subject_id.strip()[:512]
        if not normalized_subject:
            return
        async with self._session_factory() as session:
            await session.execute(
                text(
                    f"INSERT INTO {self._external_identities_table} "
                    "(id, channel_binding_id, external_subject_id, "
                    "platform_user_id, binding_status, metadata) "
                    "SELECT :id, cb.id, :external_subject_id, "
                    ":platform_user_id, 'active', CAST(:metadata AS jsonb) "
                    f"FROM {self._bindings_table} cb "
                    "WHERE cb.id = :binding_id "
                    "AND cb.owner_user_id = :platform_user_id "
                    "ON CONFLICT (channel_binding_id, external_subject_id) "
                    "DO UPDATE SET platform_user_id = EXCLUDED.platform_user_id, "
                    "binding_status = 'active', metadata = EXCLUDED.metadata"
                ),
                {
                    "id": uuid4(),
                    "binding_id": binding_id,
                    "external_subject_id": normalized_subject,
                    "platform_user_id": platform_user_id,
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                },
            )

    async def delete(
        self,
        *,
        agent_key: str,
        owner_user_id: UUID,
        channel_type: str,
    ) -> bool:
        async with self._session_factory() as session:
            binding = (
                await session.execute(
                    text(
                        "SELECT id, credential_ref "
                        f"FROM {self._bindings_table} "
                        "WHERE agent_id = :agent_id "
                        "AND owner_user_id = :owner_user_id "
                        "AND channel_type = :channel_type"
                    ),
                    {
                        "agent_id": agent_database_id(agent_key),
                        "owner_user_id": owner_user_id,
                        "channel_type": channel_type,
                    },
                )
            ).mappings().one_or_none()
            if binding is None:
                return False
            await session.execute(
                text(
                    f"DELETE FROM {self._access_rules_table} "
                    "WHERE channel_binding_id = :binding_id"
                ),
                {"binding_id": binding["id"]},
            )
            await session.execute(
                text(
                    f"DELETE FROM {self._external_identities_table} "
                    "WHERE channel_binding_id = :binding_id"
                ),
                {"binding_id": binding["id"]},
            )
            await session.execute(
                text(
                    f"DELETE FROM {self._bindings_table} "
                    "WHERE id = :binding_id"
                ),
                {"binding_id": binding["id"]},
            )
            if binding["credential_ref"] is not None:
                await session.execute(
                    text(
                        f"DELETE FROM {self._credentials_table} "
                        "WHERE id = :credential_ref"
                    ),
                    {"credential_ref": binding["credential_ref"]},
                )
        return True


class ChannelBindingDeniedError(RuntimeError):
    """当前主体无权在目标 Agent 下管理自己的频道绑定。"""

    def __init__(self) -> None:
        super().__init__("channel_binding_forbidden")


class ChannelBindingService:
    """把可信 Web 主体和 Agent 使用权绑定到个人频道 CRUD。"""

    def __init__(self, *, binding_repository, agent_repository) -> None:
        self._bindings = binding_repository
        self._agents = agent_repository

    async def _require_access(self, *, actor, agent_key: str) -> UUID:
        if actor.user_id is None:
            raise ChannelBindingDeniedError()
        access = await self._agents.get_accessible(
            agent_key=agent_key,
            user_id=actor.user_id,
        )
        if access is None or access.status != "active":
            raise ChannelBindingDeniedError()
        return actor.user_id

    async def list_bindings(self, *, actor, agent_key: str):
        owner_user_id = await self._require_access(
            actor=actor,
            agent_key=agent_key,
        )
        return await self._bindings.list_for_user(
            agent_key=agent_key,
            owner_user_id=owner_user_id,
        )

    async def upsert(
        self,
        *,
        actor,
        agent_key: str,
        channel_type: str,
        display_name: str,
        enabled: bool,
        config: dict[str, Any],
        secrets: dict[str, str],
    ):
        owner_user_id = await self._require_access(
            actor=actor,
            agent_key=agent_key,
        )
        normalized_type = channel_type.strip().lower()
        if not normalized_type:
            raise ValueError("channel_type_required")
        return await self._bindings.upsert(
            agent_key=agent_key,
            owner_user_id=owner_user_id,
            channel_type=normalized_type,
            display_name=display_name.strip() or normalized_type,
            enabled=enabled,
            config=config,
            secrets=secrets,
        )

    async def has_bot_conflict(
        self,
        *,
        actor,
        agent_key: str,
        channel_type: str,
        config: dict[str, Any],
    ) -> bool:
        owner_user_id = await self._require_access(
            actor=actor,
            agent_key=agent_key,
        )
        normalized_type = channel_type.strip().lower()
        from ..app.channels.conflict import get_channel_bot_identity

        proposed = get_channel_bot_identity(normalized_type, config)
        if proposed is None:
            return False
        current_agent_id = agent_database_id(agent_key)
        candidates = await self._bindings.list_enabled_runtime_configs(
            channel_type=normalized_type,
        )
        for candidate in candidates:
            if (
                candidate["agent_id"] == current_agent_id
                and candidate["owner_user_id"] == owner_user_id
            ):
                continue
            if get_channel_bot_identity(
                normalized_type,
                candidate["config"],
            ) == proposed:
                return True
        return False

    async def delete(
        self,
        *,
        actor,
        agent_key: str,
        channel_type: str,
    ) -> bool:
        owner_user_id = await self._require_access(
            actor=actor,
            agent_key=agent_key,
        )
        normalized_type = channel_type.strip().lower()
        if not normalized_type:
            raise ValueError("channel_type_required")
        return await self._bindings.delete(
            agent_key=agent_key,
            owner_user_id=owner_user_id,
            channel_type=normalized_type,
        )
