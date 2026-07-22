# -*- coding: utf-8 -*-
"""Legacy agent.json MCP migration helpers."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .env_ref import env_ref
from .mcp_console import (
    mcp_credential_ref,
    mcp_oauth_credential_ref,
    normalize_secret_key,
    plan_env_ref_bindings,
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
from ..storage import load_card

# Schema version of the legacy-MCP -> DriverCard migration, persisted on
# ``MCPConfig.migration_version`` (agent.json) as a one-shot watermark that
# is independent of whether a DriverCard file happens to exist:
#   v1: legacy agent.json ``mcp.clients`` -> DriverCard storage
#   v2: single ``${VAR}`` literal -> ``env:`` credential ref (#6029 heal)
CURRENT_MCP_MIGRATION_VERSION = 2


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


@dataclass
class LegacyMCPUpgradedBinding:
    card_name: str
    container: str
    key: str
    var: str


@dataclass
class LegacyMCPUpgradeReport:
    upgraded: list[LegacyMCPUpgradedBinding] = field(default_factory=list)


async def migrate_legacy_mcp_if_needed(
    ws: Any,
    driver_manager: DriverManager,
) -> LegacyMCPMigrationReport:
    """Run the one-shot, versioned migration of legacy MCP config.

    The "already migrated?" judgement lives on the persisted
    ``MCPConfig.migration_version`` watermark, not on whether a DriverCard
    file exists.  Once a workspace reaches ``CURRENT_MCP_MIGRATION_VERSION``
    the migration is skipped entirely, so deleting a migrated client no
    longer makes the next start re-derive it from ``mcp.clients`` (#6130).
    """
    report = LegacyMCPMigrationReport()
    mcp = getattr(getattr(ws, "_config", None), "mcp", None)
    if mcp is None:
        return report

    current = int(getattr(mcp, "migration_version", 0) or 0)
    if current >= CURRENT_MCP_MIGRATION_VERSION:
        return report

    if current < 1:
        # v0 -> v1: move legacy mcp.clients into DriverCard storage.  The
        # per-client "card exists" guard in _migrate_one_client is now only
        # an in-run idempotency / crash-rerun guard, not the judgement.
        clients = dict(getattr(mcp, "clients", None) or {})
        for client_key, config in clients.items():
            await _migrate_one_client(
                str(client_key),
                config,
                driver_manager,
                report,
            )

    if current < 2:
        # v1 -> v2: fold the #6029 env: ref self-heal in as a one-shot step
        # instead of re-scanning every card on every start.  Safe because
        # bad literals are historical: post-fix migration never makes new.
        await upgrade_legacy_mcp_credentials(driver_manager)

    await asyncio.to_thread(_write_report, driver_manager.cards_dir, report)

    # Persist the watermark only after all steps succeed; on partial failure
    # the version stays put and the next start re-runs (idempotent).
    mcp.migration_version = CURRENT_MCP_MIGRATION_VERSION
    await asyncio.to_thread(_persist_mcp_migration_version, ws)
    return report


def _persist_mcp_migration_version(ws: Any) -> None:
    """Persist the bumped MCPConfig.migration_version back to agent.json."""
    from ...config.config import save_agent_config

    # pylint: disable=protected-access
    save_agent_config(ws.agent_id, ws._config)


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
    env_plan = plan_env_ref_bindings(env_secrets)
    header_plan = plan_env_ref_bindings(header_secrets)

    endpoint: dict[str, Any]
    if transport == "stdio":
        env_binding = source_binding_from_split(
            env_public,
            {key: key for key in env_plan.plain_secrets},
            credential_alias,
        )
        env_binding.update(env_plan.env_bindings)
        endpoint = {
            "transport": "stdio",
            "command": str(getattr(config, "command", "") or ""),
            "args": list(getattr(config, "args", []) or []),
            "env": env_binding,
        }
        cwd = str(getattr(config, "cwd", "") or "")
        if cwd:
            endpoint["cwd"] = cwd
    else:
        used: set[str] = set()
        header_secret_refs: dict[str, str] = {}
        for header in header_plan.plain_secrets:
            secret_key = normalize_secret_key(header, used)
            used.add(secret_key)
            header_secret_refs[header] = secret_key
        header_binding = source_binding_from_split(
            header_public,
            header_secret_refs,
            credential_alias,
        )
        header_binding.update(header_plan.env_bindings)
        endpoint = {
            "transport": transport,
            "url": str(getattr(config, "url", "") or ""),
            "headers": header_binding,
        }

    credential = _build_legacy_credential(
        client_key,
        oauth,
        env_plan.plain_secrets,
        header_plan.plain_secrets,
        endpoint,
        now,
    )
    credentials = _legacy_credential_refs(credential)
    for alias, var in {
        **env_plan.env_aliases,
        **header_plan.env_aliases,
    }.items():
        credentials[alias] = CredentialRef(
            kind=CREDENTIAL_KIND_STATIC,
            ref=env_ref(var),
        )
    card = DriverCard(
        name=client_key,
        protocol=PROTOCOL_MCP,
        endpoint=endpoint,
        credentials=credentials,
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


async def upgrade_legacy_mcp_credentials(
    driver_manager: DriverManager,
) -> LegacyMCPUpgradeReport:
    """Self-heal MCP cards migrated before the #6029 fix.

    Re-runs the ``env:`` conversion over already-migrated cards whose
    credential secrets still hold a literal single ``${VAR}``.  Uses the
    same ``plan_env_ref_bindings`` as fresh migration, so the decision
    boundary is identical: real secrets (no ``${WORD}``) are untouched.
    """
    report = LegacyMCPUpgradeReport()
    for path in await driver_manager.card_store.list_paths():
        card = await asyncio.to_thread(load_card, path)
        if card.protocol != PROTOCOL_MCP:
            continue
        await _upgrade_one_card(card, driver_manager, report)
    await asyncio.to_thread(
        _write_upgrade_report,
        driver_manager.cards_dir,
        report,
    )
    return report


async def _upgrade_one_card(
    card: DriverCard,
    driver_manager: DriverManager,
    report: LegacyMCPUpgradeReport,
) -> None:
    endpoint = card.endpoint
    if not isinstance(endpoint, dict):
        return
    to_clear: dict[str, set[str]] = {}
    changed = False
    for container_name in ("headers", "env"):
        container = endpoint.get(container_name)
        if not isinstance(container, dict):
            continue
        for key, spec in list(container.items()):
            planned = await _plan_binding_upgrade(
                spec,
                card,
                driver_manager,
            )
            if planned is None:
                continue
            new_spec, alias, var, store_ref, field_name = planned
            container[key] = new_spec
            card.credentials[alias] = CredentialRef(
                kind=CREDENTIAL_KIND_STATIC,
                ref=env_ref(var),
            )
            to_clear.setdefault(store_ref, set()).add(field_name)
            report.upgraded.append(
                LegacyMCPUpgradedBinding(
                    card_name=card.name,
                    container=container_name,
                    key=str(key),
                    var=var,
                ),
            )
            changed = True
    if not changed:
        return
    await _clear_upgraded_secrets(driver_manager, card, to_clear)
    await driver_manager.card_store.save(card)


def _credential_source_ref(
    spec: Any,
    card: DriverCard,
) -> tuple[str, str] | None:
    """Return (store_ref, field) for an upgradable credential binding."""
    if not isinstance(spec, dict) or spec.get("source") != "credential":
        return None
    alias = str(spec.get("credential") or "")
    field_name = str(spec.get("field") or "")
    if not alias or not field_name:
        return None
    cred_ref = card.credentials.get(alias)
    store_ref = str(getattr(cred_ref, "ref", "") or "")
    if not store_ref or store_ref.startswith("env:"):
        return None
    return store_ref, field_name


async def _plan_binding_upgrade(
    spec: Any,
    card: DriverCard,
    driver_manager: DriverManager,
) -> tuple[dict[str, str], str, str, str, str] | None:
    resolved = _credential_source_ref(spec, card)
    if resolved is None:
        return None
    store_ref, field_name = resolved
    try:
        record = await driver_manager.credential_store.get(store_ref)
    except Exception:
        return None
    literal = record.secrets.get(field_name)
    if not isinstance(literal, str):
        return None
    plan = plan_env_ref_bindings({field_name: literal})
    new_spec = plan.env_bindings.get(field_name)
    if new_spec is None:
        return None
    new_alias, var = next(iter(plan.env_aliases.items()))
    return new_spec, new_alias, var, store_ref, field_name


async def _clear_upgraded_secrets(
    driver_manager: DriverManager,
    card: DriverCard,
    to_clear: dict[str, set[str]],
) -> None:
    store = driver_manager.credential_store
    for store_ref, fields in to_clear.items():
        try:
            record = await store.get(store_ref)
        except Exception:
            continue
        remaining = {
            key: value
            for key, value in record.secrets.items()
            if key not in fields
        }
        if remaining:
            await store.put(
                CredentialRecord(
                    ref=record.ref,
                    kind=record.kind,
                    public=record.public,
                    secrets=remaining,
                    meta=record.meta,
                ),
            )
            continue
        await store.delete(store_ref)
        _prune_orphan_credential_aliases(card, store_ref)


def _prune_orphan_credential_aliases(
    card: DriverCard,
    store_ref: str,
) -> None:
    referenced = _referenced_aliases(card)
    orphans = [
        alias
        for alias, cred in dict(card.credentials).items()
        if str(getattr(cred, "ref", "") or "") == store_ref
        and alias not in referenced
    ]
    for alias in orphans:
        card.credentials.pop(alias, None)


def _referenced_aliases(card: DriverCard) -> set[str]:
    referenced: set[str] = set()
    endpoint = card.endpoint
    if not isinstance(endpoint, dict):
        return referenced
    for container_name in ("headers", "env"):
        container = endpoint.get(container_name)
        if not isinstance(container, dict):
            continue
        for spec in container.values():
            if isinstance(spec, dict) and spec.get("source") == "credential":
                alias = str(spec.get("credential") or "")
                if alias:
                    referenced.add(alias)
    return referenced


def _write_upgrade_report(
    cards_dir: Path,
    report: LegacyMCPUpgradeReport,
) -> None:
    if not report.upgraded:
        return
    cards_dir.mkdir(parents=True, exist_ok=True)
    path = cards_dir / ".legacy_mcp_upgrade_report.yaml"
    payload = asdict(report)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
