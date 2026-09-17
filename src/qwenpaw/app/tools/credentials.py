# -*- coding: utf-8 -*-
"""Credential Binding service for Agent tool password fields."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from ...access.agent_repository import agent_database_id
from ...drivers.credentials.types import CredentialRecord
from ...drivers.errors import CredentialNotFoundError
from .runtime_credentials import (
    TOOL_CREDENTIAL_CACHE,
    ToolCredentialRuntimeCache,
)

_CONSUMER_TYPE = "agent_tool"
_PURPOSE_PREFIX = "config:"


async def load_agent_tool_credentials(
    *,
    agent_key: str,
    tool_fields: dict[str, list[str]],
    service: "ToolCredentialService",
) -> None:
    """Load declared password fields into one Agent's runtime cache."""
    service.clear_agent(agent_key)
    for tool_name, password_fields in tool_fields.items():
        await service.load_tool(
            agent_id=agent_key,
            tool_name=tool_name,
            password_fields=password_fields,
        )


def declared_tool_password_fields(
    tool_names: list[str],
) -> dict[str, list[str]]:
    """Read password field declarations from installed plugin manifests."""
    from ...plugins.registry import PluginRegistry

    registry = PluginRegistry()
    result: dict[str, list[str]] = {}
    for tool_name in tool_names:
        plugin_id = registry.get_plugin_id_for_tool(tool_name)
        manifest = registry.get_plugin_manifest(plugin_id) if plugin_id else None
        if not manifest or "meta" not in manifest:
            continue
        meta = manifest["meta"]
        fields = list(meta.get("config_fields", []))
        for tool in meta.get("tools", []):
            if isinstance(tool, dict) and tool.get("name") == tool_name:
                fields = list(tool.get("config_fields", []))
                break
        password_fields = [
            str(field["name"])
            for field in fields
            if field.get("type") == "password" and field.get("name")
        ]
        if password_fields:
            result[tool_name] = password_fields
    return result


def _agent_id(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else agent_database_id(value)


def tool_credential_consumer_id(agent_id: UUID, tool_name: str) -> UUID:
    """Derive a stable consumer without adding a tool configuration table."""
    return uuid5(agent_id, f"tool:{tool_name}")


class ToolCredentialService:
    """Manage one Agent tool's bound password fields."""

    def __init__(
        self,
        *,
        store: Any,
        cache: ToolCredentialRuntimeCache = TOOL_CREDENTIAL_CACHE,
    ) -> None:
        self._store = store
        self._cache = cache

    def clear_agent(self, agent_id: UUID | str) -> None:
        """Remove all runtime-only credentials for one Agent."""
        self._cache.clear_agent(str(agent_id))

    @staticmethod
    def _purpose(field_name: str) -> str:
        return f"{_PURPOSE_PREFIX}{field_name}"

    async def replace(
        self,
        *,
        agent_id: UUID | str,
        tool_name: str,
        field_name: str,
        value: str,
        actor_user_id: UUID,
    ) -> UUID:
        database_id = _agent_id(agent_id)
        credential_id = await self._store.create_and_bind(
            record=CredentialRecord(
                ref="",
                kind="tool-config",
                public={"field": field_name},
                secrets={field_name: value},
            ),
            scope_type="agent",
            scope_id=database_id,
            consumer_type=_CONSUMER_TYPE,
            consumer_id=tool_credential_consumer_id(database_id, tool_name),
            purpose=self._purpose(field_name),
            created_by=actor_user_id,
        )
        self._cache.set_field(str(agent_id), tool_name, field_name, value)
        return credential_id

    async def _resolve(
        self,
        *,
        agent_id: UUID | str,
        tool_name: str,
        field_name: str,
    ) -> str:
        database_id = _agent_id(agent_id)
        record = await self._store.resolve(
            consumer_type=_CONSUMER_TYPE,
            consumer_id=tool_credential_consumer_id(database_id, tool_name),
            purpose=self._purpose(field_name),
            scope_type="agent",
            scope_id=database_id,
        )
        value = record.secrets.get(field_name)
        if not isinstance(value, str) or not value:
            raise CredentialNotFoundError(
                f"{tool_name}:{field_name}",
            )
        return value

    async def status(
        self,
        *,
        agent_id: UUID | str,
        tool_name: str,
        field_name: str,
    ) -> str:
        try:
            await self._resolve(
                agent_id=agent_id,
                tool_name=tool_name,
                field_name=field_name,
            )
        except CredentialNotFoundError:
            return "missing"
        return "configured"

    async def delete(
        self,
        *,
        agent_id: UUID | str,
        tool_name: str,
        field_name: str,
    ) -> bool:
        database_id = _agent_id(agent_id)
        deleted = await self._store.revoke_binding(
            consumer_type=_CONSUMER_TYPE,
            consumer_id=tool_credential_consumer_id(database_id, tool_name),
            purpose=self._purpose(field_name),
            scope_type="agent",
            scope_id=database_id,
        )
        self._cache.remove_field(str(agent_id), tool_name, field_name)
        return deleted

    async def load_tool(
        self,
        *,
        agent_id: UUID | str,
        tool_name: str,
        password_fields: list[str],
    ) -> dict[str, str]:
        loaded: dict[str, str] = {}
        for field_name in password_fields:
            try:
                loaded[field_name] = await self._resolve(
                    agent_id=agent_id,
                    tool_name=tool_name,
                    field_name=field_name,
                )
            except CredentialNotFoundError:
                continue
        self._cache.replace(str(agent_id), tool_name, loaded)
        return loaded

    async def apply_actions(
        self,
        *,
        agent_id: UUID | str,
        tool_name: str,
        actions: dict[str, tuple[str, str | None]],
        actor_user_id: UUID,
    ) -> None:
        """Apply all password mutations in one database transaction."""
        database_id = _agent_id(agent_id)
        consumer_id = tool_credential_consumer_id(database_id, tool_name)
        cache_values = self._cache.get(str(agent_id), tool_name)
        async with self._store.transaction() as session:
            for field_name, (action, value) in actions.items():
                if action == "keep":
                    continue
                if action == "replace" and isinstance(value, str) and value:
                    await self._store.create_and_bind(
                        record=CredentialRecord(
                            ref="",
                            kind="tool-config",
                            public={"field": field_name},
                            secrets={field_name: value},
                        ),
                        scope_type="agent",
                        scope_id=database_id,
                        consumer_type=_CONSUMER_TYPE,
                        consumer_id=consumer_id,
                        purpose=self._purpose(field_name),
                        created_by=actor_user_id,
                        session=session,
                    )
                    cache_values[field_name] = value
                elif action == "delete":
                    await self._store.revoke_binding(
                        consumer_type=_CONSUMER_TYPE,
                        consumer_id=consumer_id,
                        purpose=self._purpose(field_name),
                        scope_type="agent",
                        scope_id=database_id,
                        session=session,
                    )
                    cache_values.pop(field_name, None)
                else:
                    raise ValueError("invalid credential action")
        self._cache.replace(str(agent_id), tool_name, cache_values)
