# -*- coding: utf-8 -*-
"""MCP env/header binding classification and presentation helpers."""

from __future__ import annotations

import re
from typing import Any

from ..credentials.types import CredentialRecord

_SAFE_KEY_PATTERN = re.compile(r"[^a-z0-9_]+")

PUBLIC_HEADER_KEYS = {
    "accept",
    "content-type",
    "user-agent",
    "x-client-name",
}
SECRET_HEADER_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
}
PUBLIC_ENV_KEYS = {
    "NODE_ENV",
    "LOG_LEVEL",
    "DEBUG",
    "MCP_MODE",
}
SECRET_ENV_KEY_PARTS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "AUTH",
)


def normalize_secret_key(name: str, existing: set[str] | None = None) -> str:
    """Return a lowercase credential secret key for an env/header name."""
    base = _SAFE_KEY_PATTERN.sub("_", name.strip().lower()).strip("_")
    if not base:
        base = "secret"
    if existing is None or base not in existing:
        return base
    index = 2
    while f"{base}_{index}" in existing:
        index += 1
    return f"{base}_{index}"


# pylint: disable-next=too-many-return-statements
def classify_mcp_binding(
    *,
    section: str,
    key: str,
    value: str,
) -> str:
    """Classify one Console MCP env/header value as public or secret."""
    del value
    if section == "headers":
        lowered = key.strip().lower()
        if lowered in SECRET_HEADER_KEYS:
            return "secret"
        if lowered in PUBLIC_HEADER_KEYS:
            return "public"
        return "secret"

    if section == "env":
        stripped = key.strip()
        upper = stripped.upper()
        if any(part in upper for part in SECRET_ENV_KEY_PARTS):
            return "secret"
        if stripped in PUBLIC_ENV_KEYS or upper in PUBLIC_ENV_KEYS:
            return "public"
        return "secret"

    return "secret"


def split_mcp_binding(
    section: str,
    values: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Split env/header maps into public literals and secret values."""
    public: dict[str, str] = {}
    secrets: dict[str, str] = {}
    for key, value in dict(values or {}).items():
        target = classify_mcp_binding(
            section=section,
            key=str(key),
            value=str(value),
        )
        if target == "public":
            public[str(key)] = str(value)
        else:
            secrets[str(key)] = str(value)
    return public, secrets


def source_binding_from_split(
    public: dict[str, str],
    secret_refs: dict[str, str],
    credential_alias: str,
) -> dict[str, dict[str, str]]:
    """Build canonical source/credential/field binding entries."""
    binding: dict[str, dict[str, str]] = {}
    for key, value in public.items():
        binding[str(key)] = {"source": "literal", "value": str(value)}
    for key, secret_key in secret_refs.items():
        binding[str(key)] = {
            "source": "credential",
            "credential": credential_alias,
            "field": str(secret_key),
        }
    return binding


def binding_to_response(
    binding: Any,
    credential: CredentialRecord | None,
    *,
    credential_alias: str,
) -> dict[str, str]:
    """Return masked Console response values from a Driver endpoint binding."""
    if not isinstance(binding, dict):
        return {}
    if "public" not in binding and "secret_refs" not in binding:
        result: dict[str, str] = {}
        secrets = credential.secrets if credential else {}
        for key, spec in binding.items():
            if isinstance(spec, dict) and spec.get("source") == "literal":
                result[str(key)] = str(spec.get("value") or "")
            elif (
                isinstance(spec, dict)
                and spec.get("source") == "credential"
                and spec.get("credential") == credential_alias
            ):
                value = secrets.get(str(spec.get("field") or ""), "")
                result[str(key)] = mask_mcp_secret_value(str(value))
            elif not isinstance(spec, dict):
                result[str(key)] = str(spec)
        return result
    result = {
        str(key): str(value)
        for key, value in dict(binding.get("public") or {}).items()
    }
    secrets = credential.secrets if credential else {}
    for output_name, secret_key in dict(
        binding.get("secret_refs") or {},
    ).items():
        value = secrets.get(str(secret_key), "")
        result[str(output_name)] = mask_mcp_secret_value(str(value))
    return result


def binding_plain_keys(
    binding: Any,
    *,
    credential_alias: str,
) -> dict[str, str]:
    """Return unmasked public values and blank placeholders for secret keys."""
    if not isinstance(binding, dict):
        return {}
    if "public" not in binding and "secret_refs" not in binding:
        result: dict[str, str] = {}
        for key, spec in binding.items():
            if isinstance(spec, dict) and spec.get("source") == "literal":
                result[str(key)] = str(spec.get("value") or "")
            elif (
                isinstance(spec, dict)
                and spec.get("source") == "credential"
                and spec.get("credential") == credential_alias
            ):
                result[str(key)] = ""
            elif not isinstance(spec, dict):
                result[str(key)] = str(spec)
        return result
    result = {
        str(key): str(value)
        for key, value in dict(binding.get("public") or {}).items()
    }
    for key in dict(binding.get("secret_refs") or {}):
        result[str(key)] = ""
    return result


def restore_masked_value(incoming: str, existing: str) -> str:
    """Return the existing secret when incoming equals its masked display."""
    if existing and incoming == mask_mcp_secret_value(existing):
        return existing
    return incoming


def mask_mcp_secret_value(value: str) -> str:
    """Mask a secret value for Console display."""
    if not value:
        return value
    length = len(value)
    if length <= 8:
        return "*" * length
    if length <= 12:
        return f"{value[:1]}{'*' * max(length - 2, 4)}{value[-1:]}"
    prefix_len = 3 if length > 2 and value[2] == "-" else 2
    prefix = value[:prefix_len]
    suffix_len = 4 if length >= 16 else 2
    suffix = value[-suffix_len:]
    masked_len = max(length - prefix_len - suffix_len, 4)
    return f"{prefix}{'*' * masked_len}{suffix}"
