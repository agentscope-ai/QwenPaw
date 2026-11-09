# -*- coding: utf-8 -*-
"""Application service for Console-managed MCP Driver configuration."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from ...config.utils import get_config_path, load_config

from ..driver_config_service import (
    DriverConfigService,
    ensure_driver_active,
)
from .schemas import (
    MCPAccessPolicy,
    MCPAccessPrincipalOption,
    MCPAccessRule,
    MCPClientCreateRequest,
    MCPClientInfo,
    MCPClientUpdateRequest,
    MCPToolAccessOverride,
    MCPToolDefaultPolicy,
    MCPToolInfo,
)
from ...drivers.adapters.mcp_console import (
    build_mcp_client_info_payload,
    build_mcp_credential_record,
    build_mcp_driver_card,
    mcp_credential_ref,
    mcp_oauth_credential_ref,
)
from ...drivers.capabilities import mcp_tool_is_enabled, mcp_tool_whitelist
from ...drivers.constants import (
    CAPABILITY_KIND_TOOL,
    CREDENTIAL_ALIAS_OAUTH,
    CREDENTIAL_ALIAS_STATIC,
    CREDENTIAL_KIND_OAUTH_AUTH_CODE,
    CREDENTIAL_KIND_STATIC,
    POLICY_EFFECT_ALLOW,
    POLICY_EFFECT_ASK,
    POLICY_EFFECT_DENY,
    POLICY_TARGET_WILDCARD,
    PRINCIPAL_SOURCE_CHANNEL,
    PRINCIPAL_SUBJECT_ALL,
    PRINCIPAL_SUBJECT_USER,
    PROTOCOL_MCP,
)
from ...drivers.contracts import (
    CredentialRef,
    DriverCard,
    iter_credential_refs,
)
from ...drivers.credential_commit import (
    commit_credential_binding,
    cleanup_credential_candidates,
)
from ...drivers.errors import CredentialNotFoundError, DriverCardError
from ...plugins._drivers import workspace_is_current
from ...plugins.registry import PluginRegistry
from ...drivers.policy_types import (
    DriverPolicy,
    PolicyPrincipal,
    PolicyRule,
    PolicyTarget,
)

logger = logging.getLogger(__name__)
_CREDENTIAL_OWNER = "mcp-config-static"
_CREDENTIAL_TTL = 600

MCP_PROTOCOL = PROTOCOL_MCP
MCP_TOOL_KIND = CAPABILITY_KIND_TOOL

_RESERVED_KEY_PREFIXES = (
    "access-principals/",
    "tools/",
    "toggle/",
    "oauth/",
    "policy/",
)


class MCPConfigService:
    """Own MCP-specific DriverCard mapping and policy presentation logic."""

    def __init__(self, workspace: Any) -> None:
        self._workspace = workspace
        self._driver_config = DriverConfigService(workspace)

    async def load_card(self, client_key: str) -> DriverCard:
        return await self._driver_config.load_card(
            client_key,
            protocol=MCP_PROTOCOL,
        )

    async def list_cards(self) -> list[DriverCard]:
        return await self._driver_config.list_cards(protocol=MCP_PROTOCOL)

    async def build_info_from_card(self, card: DriverCard) -> MCPClientInfo:
        credentials = iter_credential_refs(card)
        static_ref = _credential_ref_by_alias_or_kind(
            credentials,
            alias=CREDENTIAL_ALIAS_STATIC,
            kind=CREDENTIAL_KIND_STATIC,
        )
        credential = (
            await self._driver_config.load_optional_credential(static_ref.ref)
            if static_ref is not None
            else None
        )
        oauth_ref = _credential_ref_by_alias_or_kind(
            credentials,
            alias=CREDENTIAL_ALIAS_OAUTH,
            kind=CREDENTIAL_KIND_OAUTH_AUTH_CODE,
        )
        oauth_credential = await self._driver_config.load_optional_credential(
            (
                oauth_ref.ref
                if oauth_ref is not None
                else mcp_oauth_credential_ref(card.name)
            ),
        )
        return MCPClientInfo.model_validate(
            build_mcp_client_info_payload(card, credential, oauth_credential),
        )

    async def list_clients(self) -> list[MCPClientInfo]:
        return list(
            await asyncio.gather(
                *[
                    self.build_info_from_card(card)
                    for card in await self.list_cards()
                ],
            ),
        )

    async def list_tools(self, client_key: str) -> list[MCPToolInfo]:
        card = await self.load_card(client_key)
        if not card.enabled:
            return []
        try:
            capabilities = await self._driver_config.list_driver_capabilities(
                client_key,
                protocol=MCP_PROTOCOL,
                kind=MCP_TOOL_KIND,
                request_context={},
            )
        except Exception as exc:
            logger.warning(
                "Failed to list tools for MCP client '%s': %s",
                client_key,
                exc,
            )
            raise HTTPException(
                502,
                detail=f"Failed to query tools from MCP server: {exc}",
            ) from exc

        # Disk card is source of truth; in-memory capability.enabled may lag.
        whitelist = mcp_tool_whitelist(card.config.get("tools"))
        return [
            MCPToolInfo(
                name=capability.name,
                description=capability.description,
                enabled=mcp_tool_is_enabled(whitelist, capability.name),
                input_schema=capability.input_schema,
            )
            for capability in capabilities
        ]

    async def update_tool_whitelist(
        self,
        client_key: str,
        tools: list[str] | None,
    ) -> list[MCPToolInfo]:
        """Update tool whitelist and return full tool list with enabled status.

        Args:
            client_key: The MCP client identifier.
            tools: List of tool names to whitelist, or None to remove.
        """
        previous = await self.load_card(client_key)
        card = replace(previous, config={**previous.config, "tools": tools})
        await self._commit_client(
            card,
            None,
            previous=previous,
            expected={},
            reload_driver=False,
        )
        manager = getattr(self._workspace, "driver_manager", None)
        if manager is not None:
            try:
                await manager.refresh_driver(client_key)
            except Exception as exc:
                raise HTTPException(
                    502,
                    detail=(
                        f"MCP tool whitelist saved but failed to apply to "
                        f"the active runtime: {exc}"
                    ),
                ) from exc
        try:
            return await self.list_tools(client_key)
        except HTTPException:
            return []

    async def get_policy(self, client_key: str) -> MCPAccessPolicy:
        return mcp_access_policy_from_card(await self.load_card(client_key))

    async def list_access_principals(
        self,
        *,
        limit: int = 100,
    ) -> list[MCPAccessPrincipalOption]:
        """Return recent source-scoped users for Console policy editing."""
        chat_manager = getattr(self._workspace, "chat_manager", None)
        if chat_manager is None:
            return []
        try:
            chats = await chat_manager.list_chats()
        except Exception:
            logger.warning(
                "Failed to list chat identities for MCP access policy",
                exc_info=True,
            )
            return []

        by_identity: dict[
            tuple[str, str, str],
            MCPAccessPrincipalOption,
        ] = {}
        for chat in chats:
            source_value = str(getattr(chat, "channel", "") or "").strip()
            subject_value = str(getattr(chat, "user_id", "") or "").strip()
            if not source_value or not subject_value:
                continue
            key = (
                PRINCIPAL_SOURCE_CHANNEL,
                source_value,
                subject_value,
            )
            option = MCPAccessPrincipalOption(
                source_type=PRINCIPAL_SOURCE_CHANNEL,
                source_value=source_value,
                subject_type=PRINCIPAL_SUBJECT_USER,
                subject_value=subject_value,
                label=_principal_option_label(
                    source_value,
                    subject_value,
                    str(getattr(chat, "name", "") or ""),
                ),
                chat_id=str(getattr(chat, "id", "") or ""),
                chat_name=str(getattr(chat, "name", "") or ""),
                session_id=str(getattr(chat, "session_id", "") or ""),
                updated_at=getattr(chat, "updated_at", None),
            )
            existing = by_identity.get(key)
            if existing is None or _principal_updated_at(option) >= (
                _principal_updated_at(existing)
            ):
                by_identity[key] = option

        return sorted(
            by_identity.values(),
            key=_principal_updated_at,
            reverse=True,
        )[:limit]

    async def update_policy(
        self,
        client_key: str,
        access: MCPAccessPolicy,
    ) -> MCPAccessPolicy:
        previous = await self.load_card(client_key)
        card = replace(
            previous,
            policy=driver_policy_from_mcp_access_update(
                previous.policy,
                access,
            ),
        )
        await self._commit_client(
            card,
            None,
            previous=previous,
            expected={},
            reload_driver=False,
        )
        manager = getattr(self._workspace, "driver_manager", None)
        if manager is not None:
            await manager.sync_driver_policy(card, persist=False)
        return mcp_access_policy_from_card(card)

    async def create_client(
        self,
        client_key: str,
        client: MCPClientCreateRequest,
    ) -> MCPClientInfo:
        await self._cleanup_credentials()
        validate_client_key(client_key)
        path = self._driver_config.card_path(
            client_key,
            protocol=MCP_PROTOCOL,
        )
        if await asyncio.to_thread(path.is_file):
            raise HTTPException(
                400,
                detail=f"MCP client '{client_key}' already exists. Use PUT to "
                f"update.",
            )
        await ensure_mcp_display_name_unique(
            self,
            normalize_mcp_display_name(client.name, fallback=client_key),
            client_key=client_key,
        )

        credential = build_mcp_credential_record(client_key, client)
        credential = (
            self._versioned_credential(credential, client_key)
            if credential.secrets
            else None
        )
        card = build_mcp_driver_card(
            client_key,
            client,
            credential.ref if credential else "",
            credential_record=credential,
        )
        await self._commit_client(card, credential, previous=None, expected={})
        return await self.build_info_from_card(card)

    async def update_client(
        self,
        client_key: str,
        updates: MCPClientUpdateRequest,
    ) -> MCPClientInfo:
        await self._cleanup_credentials()
        existing_card = await self.load_card(client_key)
        binding = _credential_ref_by_alias_or_kind(
            iter_credential_refs(existing_card),
            alias=CREDENTIAL_ALIAS_STATIC,
            kind=CREDENTIAL_KIND_STATIC,
        )
        existing_credential, expected = None, {}
        if binding is not None and not binding.ref.startswith("env:"):
            try:
                (
                    existing_credential,
                    revision,
                ) = await self._driver_config.credential_store.get_versioned(
                    binding.ref,
                )
            except CredentialNotFoundError:
                revision = None
            expected[binding.ref] = revision
        existing_info = await self.build_info_from_card(existing_card)
        merged_client = merge_update_with_existing(existing_info, updates)
        await ensure_mcp_display_name_unique(
            self,
            normalize_mcp_display_name(
                merged_client.name,
                fallback=client_key,
            ),
            client_key=client_key,
        )
        credential = build_mcp_credential_record(
            client_key,
            merged_client,
            existing=existing_credential,
        )
        if existing_credential is not None and not (
            {"headers", "env", "transport"} & updates.model_fields_set
        ):
            # OAuth can hide a static fallback from the masked response.
            credential = replace(
                credential,
                public=dict(existing_credential.public),
                secrets=dict(existing_credential.secrets),
            )
        card = build_mcp_driver_card(
            client_key,
            merged_client,
            (
                binding.ref
                if existing_credential
                else mcp_credential_ref(client_key)
            ),
            credential_record=credential,
            existing=existing_card,
        )
        if credential.secrets and (
            existing_credential is None
            or credential.secrets != existing_credential.secrets
            or credential.public != existing_credential.public
            or _credential_context(card) != _credential_context(existing_card)
        ):
            credential = self._versioned_credential(credential, client_key)
            card = replace(
                card,
                credentials={
                    **card.credentials,
                    CREDENTIAL_ALIAS_STATIC: CredentialRef(
                        credential.kind,
                        credential.ref,
                    ),
                },
            )
        else:
            credential = None
        await self._commit_client(
            card,
            credential,
            previous=existing_card,
            expected=expected,
        )
        return await self.build_info_from_card(card)

    @staticmethod
    def _versioned_credential(record, client_key):
        return replace(
            record,
            ref=f"{mcp_credential_ref(client_key)}/static/{uuid4().hex}",
            meta={
                **record.meta,
                "candidate_owner": _CREDENTIAL_OWNER,
                "candidate_source": client_key,
                "candidate_expires_at": time.time() + _CREDENTIAL_TTL,
            },
        )

    async def _commit_client(
        self,
        card,
        record,
        *,
        previous,
        expected,
        reload_driver=True,
    ):
        from .oauth_bridge import _workspace_commit_lock

        registry = PluginRegistry()
        manager = registry.get_workspace_manager()

        def guard():
            if manager is not None and (
                getattr(manager, "_closing", False)
                or (
                    hasattr(self._workspace, "driver_manager")
                    and not workspace_is_current(registry, self._workspace)
                )
            ):
                raise DriverCardError("MCP workspace changed")
            profile = load_config().agents.profiles.get(
                self._workspace.agent_id,
            )
            if profile is None or not profile.enabled:
                raise DriverCardError("MCP workspace is unavailable")
            directory = Path(profile.workspace_dir).expanduser()
            if not directory.is_absolute():
                directory = get_config_path().parent / directory
            if directory.resolve() != self._workspace.workspace_dir.resolve():
                raise DriverCardError("MCP workspace directory changed")

        async with _workspace_commit_lock(manager):
            try:
                await commit_credential_binding(
                    self._driver_config.card_store,
                    self._driver_config.credential_store,
                    expected_card=previous,
                    expected_credentials=expected,
                    candidate_card=card,
                    candidate_record=record,
                    guard=guard,
                )
            except DriverCardError as exc:
                raise HTTPException(
                    409,
                    "MCP configuration changed; retry the update",
                ) from exc
        try:
            await self._driver_config._request_monitoring(card.protocol)
            if reload_driver:
                await self._driver_config.reload_driver_best_effort(card.name)
        except Exception:
            logger.warning("MCP configuration saved; runtime refresh deferred")

    async def _cleanup_credentials(self, discarded_refs=()):
        store = self._driver_config.credential_store
        retained = {
            ref.ref
            for descriptor in PluginRegistry()._driver_protocols.values()
            for handler in tuple(descriptor.handlers)
            if handler.manager.credential_store is store
            for ref in iter_credential_refs(handler.card).values()
        }
        try:
            await cleanup_credential_candidates(
                self._driver_config.card_store,
                store,
                owner=_CREDENTIAL_OWNER,
                now=time.time(),
                retained_refs=retained,
                discarded_refs=discarded_refs,
            )
        except Exception:
            logger.warning("Deferred MCP credential cleanup")

    async def toggle_client(self, client_key: str) -> MCPClientInfo:
        previous = await self.load_card(client_key)
        card = replace(previous, enabled=not previous.enabled)
        await self._commit_client(card, None, previous=previous, expected={})
        return await self.build_info_from_card(card)

    async def delete_client(self, client_key: str) -> dict[str, str]:
        card = await self.load_card(client_key)
        await self._driver_config.delete_driver_best_effort(client_key)
        await self._cleanup_credentials(
            {
                *(ref.ref for ref in iter_credential_refs(card).values()),
                mcp_credential_ref(client_key),
                mcp_oauth_credential_ref(client_key),
            },
        )

        return {
            "message": f"MCP client '{client_key}' deleted successfully",
        }


def _credential_context(card):
    return (
        {
            key: card.endpoint.get(key)
            for key in ("transport", "url", "command", "args", "cwd")
        },
        {
            section: {
                name: spec
                for name, spec in (card.endpoint.get(section) or {}).items()
                if isinstance(spec, dict)
                and spec.get("source") == "credential"
            }
            for section in ("headers", "env")
        },
        card.credentials,
    )


def validate_client_key(client_key: str) -> None:
    """Raise 400 if the key collides with reserved route prefixes."""
    lower = client_key.lower()
    for prefix in _RESERVED_KEY_PREFIXES:
        if lower == prefix.rstrip("/") or lower.startswith(prefix):
            raise HTTPException(
                400,
                detail=f"MCP client key must not start with reserved "
                f"prefix '{prefix}'. Please choose a different key.",
            )


def normalize_mcp_display_name(name: str, *, fallback: str) -> str:
    value = str(name or "").strip()
    return value or fallback


async def ensure_mcp_display_name_unique(
    service: MCPConfigService,
    display_name: str,
    *,
    client_key: str,
) -> None:
    """Ensure display names are unambiguous user-facing MCP identifiers."""
    desired = _display_name_key(display_name)
    for card in await service.list_cards():
        if card.name == client_key:
            continue
        if desired == _display_name_key(card.name):
            raise HTTPException(
                400,
                detail=(
                    f"MCP client name '{display_name}' conflicts with "
                    f"existing MCP client key '{card.name}'."
                ),
            )
        existing_display = _card_display_name(card)
        if desired == _display_name_key(existing_display):
            raise HTTPException(
                400,
                detail=(
                    f"MCP client name '{display_name}' already exists "
                    f"for MCP client '{card.name}'."
                ),
            )


def merge_update_with_existing(
    existing_info: MCPClientInfo,
    updates: MCPClientUpdateRequest,
) -> MCPClientCreateRequest:
    data = existing_info.model_dump(mode="json")
    data.pop("key", None)
    data.pop("oauth_status", None)
    data.pop("access_summary", None)
    update_data = updates.model_dump(exclude_unset=True)
    data.update(
        {
            key: value
            for key, value in update_data.items()
            if value is not None
        },
    )
    return MCPClientCreateRequest.model_validate(data)


def mcp_access_policy_from_card(card: DriverCard) -> MCPAccessPolicy:
    client_overrides = [
        override
        for rule in card.policy.rules
        if (override := _mcp_client_override_from_rule(rule)) is not None
    ]
    tool_defaults = [
        default
        for rule in card.policy.rules
        if (default := _mcp_tool_default_from_rule(rule)) is not None
    ]
    tool_overrides = [
        override
        for rule in card.policy.rules
        if (override := _mcp_tool_override_from_rule(rule)) is not None
    ]
    unmanaged_rules_count = sum(
        1
        for rule in card.policy.rules
        if not _is_console_managed_mcp_policy_rule(rule)
    )
    return MCPAccessPolicy(
        default_effect=card.policy.default_effect,
        client_overrides=client_overrides,
        tool_defaults=tool_defaults,
        tool_overrides=tool_overrides,
        unmanaged_rules_count=unmanaged_rules_count,
    )


def driver_policy_from_mcp_access_update(
    existing: DriverPolicy,
    access: MCPAccessPolicy,
) -> DriverPolicy:
    unmanaged_rules = [
        rule
        for rule in existing.rules
        if not _is_console_managed_mcp_policy_rule(rule)
    ]
    seen_rules: set[tuple[str, str, str, str, str]] = set()
    seen_defaults: set[str] = set()
    managed_rules: list[PolicyRule] = []
    for default in access.tool_defaults:
        tool_name = default.tool_name.strip()
        if not tool_name or tool_name == POLICY_TARGET_WILDCARD:
            raise HTTPException(400, detail="MCP tool default name is empty")
        if tool_name in seen_defaults:
            continue
        seen_defaults.add(tool_name)
        managed_rules.append(
            PolicyRule(
                subject=POLICY_TARGET_WILDCARD,
                effect=default.effect,
                target=PolicyTarget(kind=CAPABILITY_KIND_TOOL, name=tool_name),
                principal=PolicyPrincipal(),
            ),
        )
    for target_name, override in [
        (POLICY_TARGET_WILDCARD, override)
        for override in access.client_overrides
    ] + [
        (override.tool_name.strip(), override)
        for override in access.tool_overrides
    ]:
        if not target_name:
            raise HTTPException(400, detail="MCP tool override name is empty")
        source_value = override.source_value.strip()
        subject_value = override.subject_value.strip()
        if not source_value:
            raise HTTPException(400, detail="MCP policy source value is empty")
        if (
            override.subject_type == PRINCIPAL_SUBJECT_USER
            and not subject_value
        ):
            raise HTTPException(400, detail="MCP policy user value is empty")
        if override.subject_type == PRINCIPAL_SUBJECT_ALL:
            subject_value = ""
        key = (
            target_name,
            override.source_type,
            source_value,
            override.subject_type,
            subject_value,
        )
        if key in seen_rules:
            continue
        seen_rules.add(key)
        managed_rules.append(
            PolicyRule(
                subject=POLICY_TARGET_WILDCARD,
                effect=override.effect,
                target=PolicyTarget(
                    kind=CAPABILITY_KIND_TOOL,
                    name=target_name,
                ),
                principal=PolicyPrincipal(
                    source_type=override.source_type,
                    source_value=source_value,
                    subject_type=override.subject_type,
                    subject_value=subject_value,
                ),
            ),
        )
    return DriverPolicy(
        default_effect=access.default_effect,
        rules=[*unmanaged_rules, *managed_rules],
    )


async def ensure_mcp_driver_active(manager: Any, client_key: str) -> None:
    await ensure_driver_active(manager, client_key, protocol=MCP_PROTOCOL)


def _display_name_key(value: str) -> str:
    return str(value or "").strip().casefold()


def _card_display_name(card: DriverCard) -> str:
    return normalize_mcp_display_name(
        str(card.config.get("display_name") or ""),
        fallback=card.name,
    )


def _principal_option_label(
    source_value: str,
    subject_value: str,
    chat_name: str,
) -> str:
    base = f"{source_value} / {subject_value}"
    return f"{base} ({chat_name})" if chat_name else base


def _principal_updated_at(option: MCPAccessPrincipalOption) -> float:
    if option.updated_at is None:
        return 0.0
    return option.updated_at.timestamp()


def _credential_ref_by_alias_or_kind(
    credentials: dict[str, Any],
    *,
    alias: str,
    kind: str,
) -> Any | None:
    direct = credentials.get(alias)
    if direct is not None:
        return direct
    return next(
        (
            credential
            for credential in credentials.values()
            if getattr(credential, "kind", "") == kind
        ),
        None,
    )


def _mcp_access_rule_from_rule(
    rule: PolicyRule,
) -> MCPAccessRule | None:
    if (
        rule.condition is not None
        or rule.target.kind != CAPABILITY_KIND_TOOL
        or not rule.target.name
        or rule.effect
        not in {POLICY_EFFECT_ALLOW, POLICY_EFFECT_ASK, POLICY_EFFECT_DENY}
    ):
        return None

    principal = rule.principal
    source_type = principal.source_type.strip().lower()
    source_value = principal.source_value.strip()
    subject_type = principal.subject_type.strip().lower()
    subject_value = principal.subject_value.strip()
    if source_type == PRINCIPAL_SOURCE_CHANNEL and subject_type in {
        PRINCIPAL_SUBJECT_ALL,
        PRINCIPAL_SUBJECT_USER,
    }:
        return MCPAccessRule(
            source_type=source_type,  # type: ignore[arg-type]
            source_value=source_value,
            subject_type=subject_type,  # type: ignore[arg-type]
            subject_value=(
                "" if subject_type == PRINCIPAL_SUBJECT_ALL else subject_value
            ),
            effect=rule.effect,
        )

    return _legacy_subject_access_rule(rule)


def _legacy_subject_access_rule(
    rule: PolicyRule,
) -> MCPAccessRule | None:
    subject = rule.subject.strip()
    if not subject:
        return None
    if subject == POLICY_TARGET_WILDCARD:
        return MCPAccessRule(
            source_type=PRINCIPAL_SOURCE_CHANNEL,
            source_value="console",
            subject_type=PRINCIPAL_SUBJECT_ALL,
            subject_value="",
            effect=rule.effect,
        )
    if subject.startswith("channel:"):
        return MCPAccessRule(
            source_type=PRINCIPAL_SOURCE_CHANNEL,
            source_value=(
                subject.removeprefix("channel:") or POLICY_TARGET_WILDCARD
            ),
            subject_type=PRINCIPAL_SUBJECT_ALL,
            subject_value="",
            effect=rule.effect,
        )
    if subject.startswith("user:"):
        user = subject.removeprefix("user:")
        return MCPAccessRule(
            source_type=PRINCIPAL_SOURCE_CHANNEL,
            source_value="console",
            subject_type=(
                PRINCIPAL_SUBJECT_ALL
                if user == POLICY_TARGET_WILDCARD
                else PRINCIPAL_SUBJECT_USER
            ),
            subject_value="" if user == POLICY_TARGET_WILDCARD else user,
            effect=rule.effect,
        )
    return None


def _is_mcp_tool_default_rule(rule: PolicyRule) -> bool:
    if (
        rule.condition is not None
        or rule.target.kind != CAPABILITY_KIND_TOOL
        or rule.target.name in {"", POLICY_TARGET_WILDCARD}
        or rule.effect
        not in {POLICY_EFFECT_ALLOW, POLICY_EFFECT_ASK, POLICY_EFFECT_DENY}
        or rule.subject != POLICY_TARGET_WILDCARD
    ):
        return False
    principal = rule.principal
    return (
        principal.source_type in {"", POLICY_TARGET_WILDCARD}
        and principal.source_value in {"", POLICY_TARGET_WILDCARD}
        and principal.subject_type in {"", POLICY_TARGET_WILDCARD}
        and principal.subject_value in {"", POLICY_TARGET_WILDCARD}
    )


def _mcp_client_override_from_rule(rule: PolicyRule) -> MCPAccessRule | None:
    if (
        rule.target.kind == POLICY_TARGET_WILDCARD
        and rule.target.name == POLICY_TARGET_WILDCARD
    ):
        if rule.condition is not None or rule.effect not in {
            POLICY_EFFECT_ALLOW,
            POLICY_EFFECT_ASK,
            POLICY_EFFECT_DENY,
        }:
            return None
        return _legacy_subject_access_rule(rule)
    if (
        rule.target.kind != CAPABILITY_KIND_TOOL
        or rule.target.name != POLICY_TARGET_WILDCARD
    ):
        return None
    return _mcp_access_rule_from_rule(rule)


def _mcp_tool_default_from_rule(
    rule: PolicyRule,
) -> MCPToolDefaultPolicy | None:
    if not _is_mcp_tool_default_rule(rule):
        return None
    return MCPToolDefaultPolicy(
        tool_name=rule.target.name,
        effect=rule.effect,
    )


def _mcp_tool_override_from_rule(
    rule: PolicyRule,
) -> MCPToolAccessOverride | None:
    if (
        rule.target.kind != CAPABILITY_KIND_TOOL
        or rule.target.name in {"", POLICY_TARGET_WILDCARD}
        or _is_mcp_tool_default_rule(rule)
    ):
        return None
    access_rule = _mcp_access_rule_from_rule(rule)
    if access_rule is None:
        return None
    return MCPToolAccessOverride(
        tool_name=rule.target.name,
        **access_rule.model_dump(mode="json"),
    )


def _is_console_managed_mcp_policy_rule(rule: PolicyRule) -> bool:
    return (
        _mcp_client_override_from_rule(rule) is not None
        or _mcp_tool_default_from_rule(rule) is not None
        or _mcp_tool_override_from_rule(rule) is not None
    )
