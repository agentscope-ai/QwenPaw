# -*- coding: utf-8 -*-
"""Legacy agent.json MCP migration helpers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .mcp_console import (
    mcp_credential_ref,
    mcp_oauth_credential_ref,
    normalize_secret_key,
    source_binding_from_split,
    split_mcp_binding,
)
from ..constants import (
    CAPABILITY_KIND_TOOL,
    CREDENTIAL_ALIAS_OAUTH,
    CREDENTIAL_ALIAS_STATIC,
    CREDENTIAL_KIND_OAUTH_AUTH_CODE,
    CREDENTIAL_KIND_STATIC,
    POLICY_EFFECT_ASK,
    POLICY_TARGET_WILDCARD,
    PROTOCOL_MCP,
)
from ..contracts import (
    CredentialRef,
    DriverCard,
    DriverPolicy,
    PolicyRule,
    PolicyTarget,
)
from ..credentials.types import CredentialRecord
from ..manager import DriverManager


@dataclass
class LegacyMCPMigratedClient:
    client_key: str
    card_path: str
    credential_ref: str


@dataclass
class LegacyMCPMigrationSkippedClient:
    client_key: str
    reason: str


@dataclass
class LegacyMCPMigrationWarning:
    client_key: str
    field: str
    reason: str


@dataclass
class LegacyMCPMigrationReport:
    migrated: list[LegacyMCPMigratedClient] = field(default_factory=list)
    skipped: list[LegacyMCPMigrationSkippedClient] = field(
        default_factory=list,
    )
    warnings: list[LegacyMCPMigrationWarning] = field(default_factory=list)


async def migrate_legacy_mcp_if_needed(
    ws: Any,
    driver_manager: DriverManager,
) -> LegacyMCPMigrationReport:
    """Migrate legacy agent.json mcp.clients into Driver storage."""
    report = LegacyMCPMigrationReport()
    legacy_mcp = getattr(getattr(ws, "_config", None), "mcp", None)
    clients = getattr(legacy_mcp, "clients", None)
    if not clients:
        return report

    for client_key, config in dict(clients).items():
        await _migrate_one_client(
            str(client_key),
            config,
            driver_manager,
            report,
        )

    await asyncio.to_thread(_write_report, driver_manager.cards_dir, report)
    return report


async def _migrate_one_client(
    client_key: str,
    config: Any,
    driver_manager: DriverManager,
    report: LegacyMCPMigrationReport,
) -> None:
    target = driver_manager.card_store.path_for(
        client_key,
        protocol=PROTOCOL_MCP,
    )
    if await asyncio.to_thread(target.is_file):
        report.skipped.append(
            LegacyMCPMigrationSkippedClient(
                client_key=client_key,
                reason="driver_card_exists",
            ),
        )
        return

    if _args_may_contain_secret(list(getattr(config, "args", []) or [])):
        report.warnings.append(
            LegacyMCPMigrationWarning(
                client_key=client_key,
                field="args",
                reason="args_may_contain_secret",
            ),
        )
        report.skipped.append(
            LegacyMCPMigrationSkippedClient(
                client_key=client_key,
                reason="unsafe_secret_in_args",
            ),
        )
        return

    card, credential = legacy_mcp_client_to_driver(client_key, config)
    if credential is not None:
        try:
            await driver_manager.credential_store.get(credential.ref)
        except Exception:
            await driver_manager.credential_store.put(credential)
    await driver_manager.card_store.save(card)
    report.migrated.append(
        LegacyMCPMigratedClient(
            client_key=client_key,
            card_path=str(target),
            credential_ref=credential.ref if credential else "",
        ),
    )


def legacy_mcp_client_to_driver(
    client_key: str,
    config: Any,
) -> tuple[DriverCard, CredentialRecord | None]:
    """Convert one legacy MCP config object into Driver contracts."""
    transport = str(getattr(config, "transport", "stdio") or "stdio")
    oauth = getattr(config, "oauth", None)
    credential_alias = (
        CREDENTIAL_ALIAS_OAUTH
        if oauth is not None
        else CREDENTIAL_ALIAS_STATIC
    )
    now = time.time()

    env_public, env_secrets = split_mcp_binding(
        "env",
        dict(getattr(config, "env", {}) or {}),
    )
    header_public, header_secrets = split_mcp_binding(
        "headers",
        dict(getattr(config, "headers", {}) or {}),
    )

    endpoint: dict[str, Any]
    if transport == "stdio":
        endpoint = {
            "transport": "stdio",
            "command": str(getattr(config, "command", "") or ""),
            "args": list(getattr(config, "args", []) or []),
            "env": source_binding_from_split(
                env_public,
                {key: key for key in env_secrets},
                credential_alias,
            ),
        }
        cwd = str(getattr(config, "cwd", "") or "")
        if cwd:
            endpoint["cwd"] = cwd
    else:
        used: set[str] = set()
        header_secret_refs: dict[str, str] = {}
        for header in header_secrets:
            secret_key = normalize_secret_key(header, used)
            used.add(secret_key)
            header_secret_refs[header] = secret_key
        endpoint = {
            "transport": transport,
            "url": str(getattr(config, "url", "") or ""),
            "headers": source_binding_from_split(
                header_public,
                header_secret_refs,
                credential_alias,
            ),
        }

    credential = _build_legacy_credential(
        client_key,
        oauth,
        env_secrets,
        header_secrets,
        endpoint,
        now,
    )
    card = DriverCard(
        name=client_key,
        protocol=PROTOCOL_MCP,
        endpoint=endpoint,
        credentials=_legacy_credential_refs(credential),
        config={
            "display_name": str(getattr(config, "name", "") or client_key),
            "description": str(getattr(config, "description", "") or ""),
        },
        enabled=bool(getattr(config, "enabled", True)),
        policy=DriverPolicy(
            rules=[
                PolicyRule(
                    subject=POLICY_TARGET_WILDCARD,
                    effect=POLICY_EFFECT_ASK,
                    target=PolicyTarget(
                        kind=CAPABILITY_KIND_TOOL,
                        name=POLICY_TARGET_WILDCARD,
                    ),
                ),
            ],
        ),
    )
    return card, credential


def _build_legacy_credential(
    client_key: str,
    oauth: Any,
    env_secrets: dict[str, str],
    header_secrets: dict[str, str],
    endpoint: dict[str, Any],
    now: float,
) -> CredentialRecord | None:
    secrets: dict[str, Any] = {}
    public: dict[str, Any] = {}
    kind = CREDENTIAL_KIND_STATIC
    ref = mcp_credential_ref(client_key)

    for key, value in env_secrets.items():
        secrets[key] = value

    headers = endpoint.get("headers") if isinstance(endpoint, dict) else None
    for header, value in header_secrets.items():
        secret_key = normalize_secret_key(header)
        if isinstance(headers, dict):
            spec = headers.get(header)
            if isinstance(spec, dict) and spec.get("source") == "credential":
                secret_key = str(spec.get("field") or secret_key)
        secrets[secret_key] = value

    if oauth is not None:
        kind = CREDENTIAL_KIND_OAUTH_AUTH_CODE
        ref = mcp_oauth_credential_ref(client_key)
        public.update(
            {
                "client_id": str(getattr(oauth, "client_id", "") or ""),
                "scope": str(getattr(oauth, "scope", "") or ""),
                "expires_at": float(getattr(oauth, "expires_at", 0.0) or 0.0),
                "token_endpoint": str(
                    getattr(oauth, "token_endpoint", "") or "",
                ),
                "auth_endpoint": str(
                    getattr(oauth, "auth_endpoint", "") or "",
                ),
            },
        )
        for key in ("access_token", "refresh_token", "client_secret"):
            value = getattr(oauth, key, "")
            if value:
                secrets[key] = value

    if not secrets and not public:
        return None
    return CredentialRecord(
        ref=ref,
        kind=kind,
        public=public,
        secrets=secrets,
        meta={
            "created_at": now,
            "updated_at": now,
            "source": "legacy_agent_json_mcp",
        },
    )


def _legacy_credential_refs(
    credential: CredentialRecord | None,
) -> dict[str, CredentialRef]:
    if credential is None:
        return {}
    alias = (
        CREDENTIAL_ALIAS_OAUTH
        if credential.kind == CREDENTIAL_KIND_OAUTH_AUTH_CODE
        else CREDENTIAL_ALIAS_STATIC
    )
    return {alias: CredentialRef(kind=credential.kind, ref=credential.ref)}


def _args_may_contain_secret(args: list[str]) -> bool:
    markers = ("api-key", "apikey", "token", "secret", "password", "auth")
    return any(
        any(marker in str(arg).lower() for marker in markers) for arg in args
    )


def _write_report(cards_dir: Path, report: LegacyMCPMigrationReport) -> None:
    if not (report.migrated or report.skipped or report.warnings):
        return
    cards_dir.mkdir(parents=True, exist_ok=True)
    path = cards_dir / ".legacy_mcp_migration_report.yaml"
    payload = asdict(report)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
