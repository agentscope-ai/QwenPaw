# -*- coding: utf-8 -*-
"""MCP env/header binding classification and presentation helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .env_ref import env_alias, parse_env_template
from ..credentials.types import CredentialRecord
from ...security.secret_store import (  # pylint: disable=unused-import
    mask_secret_value as mask_mcp_secret_value,
    restore_masked_secret_value as restore_masked_value,
)

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


@dataclass
class EnvRefPlan:
    """Split of secret values into single ${VAR} bindings vs. the rest."""

    env_bindings: dict[str, dict[str, str]] = field(default_factory=dict)
    env_aliases: dict[str, str] = field(default_factory=dict)
    plain_secrets: dict[str, str] = field(default_factory=dict)
    multi_ref_keys: list[str] = field(default_factory=list)


def plan_env_ref_bindings(secrets: dict[str, str]) -> EnvRefPlan:
    """Route each secret value: single ${VAR} -> env: binding, else plain.

    A value holding exactly one ${VAR} reference becomes a credential
    binding against an ``env:``-backed alias, resolved from os.environ at
    runtime so the real value is never persisted.  Plain values and values
    with multiple references are returned untouched for the caller's
    existing static-secret path; multi-reference keys are recorded so the
    migration can warn about them.
    """
    plan = EnvRefPlan()
    used_aliases: set[str] = set()
    for raw_key, raw_value in dict(secrets or {}).items():
        key = str(raw_key)
        value = str(raw_value)
        template = parse_env_template(value)
        if template is not None and template.is_single:
            var = template.var_names[0]
            alias = env_alias(var)
            if alias in used_aliases:
                index = 2
                while f"{alias}_{index}" in used_aliases:
                    index += 1
                alias = f"{alias}_{index}"
            used_aliases.add(alias)
            plan.env_aliases[alias] = var
            spec: dict[str, str] = {
                "source": "credential",
                "credential": alias,
                "field": "value",
            }
            if template.format != "{value}":
                spec["format"] = template.format
            plan.env_bindings[key] = spec
            continue
        plan.plain_secrets[key] = value
        if template is not None:
            plan.multi_ref_keys.append(key)
    return plan


def _env_ref_template(
    spec: dict[str, Any],
    env_aliases: dict[str, str] | None = None,
) -> str | None:
    """Render an env-backed credential binding as its ${VAR} template.

    Returns e.g. ``Bearer ${ANYSEARCH_API_KEY}`` for a binding whose
    ``credential`` alias is ``env_<var>`` with a ``format`` of
    ``Bearer {value}``.  ``None`` when the binding is not env-backed.

    The original variable name (preserving case) is taken from
    ``env_aliases`` (alias -> var name, derived from the card's
    ``env:`` credential refs); when absent the alias is uppercased as a
    fallback.
    """
    credential = str(spec.get("credential") or "")
    if not credential.startswith("env_"):
        return None
    var_name = ""
    if env_aliases:
        var_name = env_aliases.get(credential, "")
    if not var_name:
        var_name = credential[len("env_") :].upper()
    fmt = str(spec.get("format") or "{value}")
    return fmt.replace("{value}", "${" + var_name + "}")


def _is_env_ref_spec(
    spec: Any,
    env_aliases: dict[str, str] | None = None,
) -> bool:
    """Whether a binding is env-backed, decided by the env: credential
    refs (via env_aliases) rather than the alias naming convention — a
    static alias like ``env_custom`` must not be misclassified."""
    if not (isinstance(spec, dict) and spec.get("source") == "credential"):
        return False
    if not env_aliases:
        return False
    return str(spec.get("credential") or "") in env_aliases


def binding_to_response(
    binding: Any,
    credential: CredentialRecord | None,
    *,
    credential_alias: str,
    env_aliases: dict[str, str] | None = None,
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
            elif _is_env_ref_spec(spec, env_aliases):
                template = _env_ref_template(spec, env_aliases)
                if template:
                    result[str(key)] = template
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
    env_aliases: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return unmasked public values and blank placeholders for secret keys."""
    if not isinstance(binding, dict):
        return {}
    if "public" not in binding and "secret_refs" not in binding:
        result: dict[str, str] = {}
        for key, spec in binding.items():
            if isinstance(spec, dict) and spec.get("source") == "literal":
                result[str(key)] = str(spec.get("value") or "")
            elif _is_env_ref_spec(spec, env_aliases):
                template = _env_ref_template(spec, env_aliases)
                if template:
                    result[str(key)] = template
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
