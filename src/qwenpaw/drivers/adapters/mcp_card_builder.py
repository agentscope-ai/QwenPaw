# -*- coding: utf-8 -*-
"""Build DriverCard and CredentialRecord objects for Console MCP clients."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from .mcp_binding import (
    binding_plain_keys,
    binding_to_response,
    classify_mcp_binding,
    normalize_secret_key,
    restore_masked_value,
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
    PROTOCOL_MCP,
    PRINCIPAL_SOURCE_CHANNEL,
    PRINCIPAL_SUBJECT_ALL,
    PRINCIPAL_SUBJECT_USER,
)
from ..contracts import CredentialRef, DriverCard
from ..credentials.types import CredentialRecord
from ..policy_types import DriverPolicy

STATIC_CREDENTIAL_ALIAS = CREDENTIAL_ALIAS_STATIC
OAUTH_CREDENTIAL_ALIAS = CREDENTIAL_ALIAS_OAUTH


def mcp_credential_ref(client_key: str) -> str:
    return f"mcp/{client_key}"


def mcp_oauth_credential_ref(client_key: str) -> str:
    return f"mcp/{client_key}/oauth"


def build_mcp_credential_record(
    client_key: str,
    client: Any,
    *,
    existing: CredentialRecord | None = None,
) -> CredentialRecord:
    """Build the static MCP credential record from console request data."""
    ref = mcp_credential_ref(client_key)
    incoming_env = dict(_read_field(client, "env", {}) or {})
    incoming_headers = dict(_read_field(client, "headers", {}) or {})
    existing_secrets = dict(existing.secrets) if existing else {}
    secrets: dict[str, str] = {}

    for key, value in incoming_env.items():
        if (
            classify_mcp_binding(section="env", key=str(key), value=str(value))
            == "public"
        ):
            continue
        secret_key = str(key)
        secrets[secret_key] = restore_masked_value(
            str(value),
            existing_secrets.get(secret_key, ""),
        )

    used = set(secrets)
    for header, value in incoming_headers.items():
        if (
            classify_mcp_binding(
                section="headers",
                key=str(header),
                value=str(value),
            )
            == "public"
        ):
            continue
        secret_key = normalize_secret_key(str(header), used)
        used.add(secret_key)
        old_value = existing_secrets.get(secret_key, "")
        secrets[secret_key] = restore_masked_value(str(value), old_value)

    now = time.time()
    meta = dict(existing.meta) if existing else {"created_at": now}
    meta["updated_at"] = now
    return CredentialRecord(
        ref=ref,
        kind=CREDENTIAL_KIND_STATIC,
        public={},
        secrets=secrets,
        meta=meta,
    )


def build_mcp_driver_card(
    client_key: str,
    client: Any,
    credential_ref: str,
    *,
    credential_record: CredentialRecord | None = None,
    existing: DriverCard | None = None,
) -> DriverCard:
    """Build a DriverCard from console MCP create/update request data."""
    current = _card_to_client_data(existing) if existing else {}
    updates = _model_dump(client)
    data = {**current, **{k: v for k, v in updates.items() if v is not None}}
    transport = str(data.get("transport") or "stdio")
    secrets = dict(credential_record.secrets) if credential_record else {}

    if transport == "stdio":
        env = dict(data.get("env") or {})
        public_env, secret_env = split_mcp_binding("env", env)
        endpoint: dict[str, Any] = {
            "transport": "stdio",
            "command": str(data.get("command") or ""),
            "args": list(data.get("args") or []),
            "env": source_binding_from_split(
                public_env,
                {str(key): str(key) for key in secret_env},
                STATIC_CREDENTIAL_ALIAS,
            ),
        }
        cwd = str(data.get("cwd") or "")
        if cwd:
            endpoint["cwd"] = cwd
    else:
        headers = dict(data.get("headers") or {})
        public_headers, secret_headers = split_mcp_binding("headers", headers)
        used: set[str] = set()
        secret_refs: dict[str, str] = {}
        for header in secret_headers:
            secret_key = normalize_secret_key(str(header), used)
            used.add(secret_key)
            secret_refs[str(header)] = secret_key
        endpoint = {
            "transport": transport,
            "url": str(data.get("url") or ""),
            "headers": source_binding_from_split(
                public_headers,
                secret_refs,
                STATIC_CREDENTIAL_ALIAS,
            ),
        }
        _preserve_oauth_authorization_binding(existing, endpoint)

    credentials = _credential_refs_from_existing(existing)
    if secrets:
        credentials[STATIC_CREDENTIAL_ALIAS] = CredentialRef(
            kind=CREDENTIAL_KIND_STATIC,
            ref=credential_ref,
        )
    else:
        credentials.pop(STATIC_CREDENTIAL_ALIAS, None)
    # Generic DriverPolicy defaults to deny as the low-level safe fallback.
    # Console-created MCP clients default to ask so a newly added external
    # server requires human approval instead of failing silently before the
    # user has configured detailed rules.
    policy = (
        existing.policy
        if existing
        else DriverPolicy(default_effect=POLICY_EFFECT_ASK, rules=[])
    )
    return DriverCard(
        name=client_key,
        protocol=PROTOCOL_MCP,
        endpoint=endpoint,
        credentials=credentials,
        config={
            "display_name": str(data.get("name") or "").strip() or client_key,
            "description": str(data.get("description") or ""),
            "tools": data.get("tools"),
        },
        enabled=bool(data.get("enabled", True)),
        policy=policy,
    )


def build_mcp_client_info_payload(
    card: DriverCard,
    credential: CredentialRecord | None,
    oauth_credential: CredentialRecord | None = None,
) -> dict[str, Any]:
    """Return the MCPClientInfo-compatible API response payload."""
    endpoint = card.endpoint
    transport = str(endpoint.get("transport") or "stdio")
    env = binding_to_response(
        endpoint.get("env") or {},
        credential,
        credential_alias=STATIC_CREDENTIAL_ALIAS,
    )
    headers = binding_to_response(
        endpoint.get("headers") or {},
        credential,
        credential_alias=STATIC_CREDENTIAL_ALIAS,
    )
    return {
        "key": card.name,
        "name": str(card.config.get("display_name") or card.name),
        "description": str(card.config.get("description") or ""),
        "enabled": card.enabled,
        "transport": transport,
        "url": str(endpoint.get("url") or ""),
        "headers": headers,
        "command": str(endpoint.get("command") or ""),
        "args": list(endpoint.get("args") or []),
        "env": env,
        "cwd": str(endpoint.get("cwd") or ""),
        "tools": card.config.get("tools"),
        "oauth_status": _oauth_status(oauth_credential),
        "access_summary": {
            "default_effect": card.policy.default_effect,
            "overrides_count": sum(
                1
                for rule in card.policy.rules
                if _is_tool_access_override(rule)
            ),
        },
    }


def attach_mcp_oauth_credential(card: DriverCard, ref: str) -> DriverCard:
    """Return a card with OAuth source and bearer header binding."""
    credentials = _credential_refs_from_existing(card)
    credentials[OAUTH_CREDENTIAL_ALIAS] = CredentialRef(
        CREDENTIAL_KIND_OAUTH_AUTH_CODE,
        ref,
    )
    endpoint = dict(card.endpoint)
    if str(endpoint.get("transport") or "stdio") != "stdio":
        headers = dict(endpoint.get("headers") or {})
        headers["Authorization"] = {
            "source": "credential",
            "credential": OAUTH_CREDENTIAL_ALIAS,
            "field": "access_token",
            "format": "Bearer {value}",
        }
        endpoint["headers"] = headers
    return replace(card, endpoint=endpoint, credentials=credentials)


def detach_mcp_oauth_credential(card: DriverCard) -> DriverCard:
    """Return a card with OAuth source and bearer binding removed."""
    credentials = _credential_refs_from_existing(card)
    credentials.pop(OAUTH_CREDENTIAL_ALIAS, None)
    endpoint = dict(card.endpoint)
    headers = endpoint.get("headers")
    if isinstance(headers, dict):
        updated_headers = dict(headers)
        auth_spec = updated_headers.get("Authorization")
        if (
            isinstance(auth_spec, dict)
            and auth_spec.get("source") == "credential"
            and auth_spec.get("credential") == OAUTH_CREDENTIAL_ALIAS
        ):
            updated_headers.pop("Authorization", None)
        endpoint["headers"] = updated_headers
    return replace(card, endpoint=endpoint, credentials=credentials)


def update_oauth_credential_ref(card: DriverCard, ref: str) -> DriverCard:
    """Return a copy of card pointing at an OAuth auth-code credential."""
    return attach_mcp_oauth_credential(card, ref)


def _is_tool_access_override(rule: Any) -> bool:
    if (
        rule.condition is not None
        or rule.target.kind != CAPABILITY_KIND_TOOL
        or not rule.target.name
        or rule.effect not in {"allow", "ask", "deny"}
    ):
        return False
    principal = rule.principal
    if (
        principal.source_type.strip().lower() == PRINCIPAL_SOURCE_CHANNEL
        and principal.subject_type.strip().lower()
        in {PRINCIPAL_SUBJECT_ALL, PRINCIPAL_SUBJECT_USER}
    ):
        return True
    subject = rule.subject.strip()
    return (
        subject == "*"
        or subject.startswith("channel:")
        or subject.startswith("user:")
    )


def _oauth_status(record: CredentialRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    access_token = str(record.secrets.get("access_token") or "")
    expires_at = float(record.public.get("expires_at") or 0.0)
    authorized = bool(access_token) and (
        expires_at <= 0 or expires_at > time.time()
    )
    return {
        "authorized": authorized,
        "expires_at": expires_at,
        "scope": str(record.public.get("scope") or ""),
        "client_id": str(record.public.get("client_id") or ""),
    }


def _card_to_client_data(card: DriverCard | None) -> dict[str, Any]:
    if card is None:
        return {}
    endpoint = card.endpoint
    return {
        "name": card.config.get("display_name") or card.name,
        "description": card.config.get("description") or "",
        "enabled": card.enabled,
        "transport": endpoint.get("transport") or "stdio",
        "url": endpoint.get("url") or "",
        "headers": binding_plain_keys(
            endpoint.get("headers") or {},
            credential_alias=STATIC_CREDENTIAL_ALIAS,
        ),
        "command": endpoint.get("command") or "",
        "args": list(endpoint.get("args") or []),
        "env": binding_plain_keys(
            endpoint.get("env") or {},
            credential_alias=STATIC_CREDENTIAL_ALIAS,
        ),
        "cwd": endpoint.get("cwd") or "",
    }


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_unset=True)
    if hasattr(value, "dict"):
        return value.dict(exclude_unset=True)
    if isinstance(value, dict):
        return dict(value)
    return dict(vars(value))


def _read_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def _credential_refs_from_existing(
    existing: DriverCard | None,
) -> dict[str, CredentialRef]:
    if existing is None:
        return {}
    return dict(existing.credentials)


def _preserve_oauth_authorization_binding(
    existing: DriverCard | None,
    endpoint: dict[str, Any],
) -> None:
    if existing is None:
        return
    if OAUTH_CREDENTIAL_ALIAS not in _credential_refs_from_existing(existing):
        return
    headers = dict(endpoint.get("headers") or {})
    if "Authorization" in headers:
        return
    existing_headers = existing.endpoint.get("headers")
    if not isinstance(existing_headers, dict):
        return
    existing_auth = existing_headers.get("Authorization")
    if (
        isinstance(existing_auth, dict)
        and existing_auth.get("source") == "credential"
        and existing_auth.get("credential") == OAUTH_CREDENTIAL_ALIAS
    ):
        headers["Authorization"] = dict(existing_auth)
        endpoint["headers"] = headers
