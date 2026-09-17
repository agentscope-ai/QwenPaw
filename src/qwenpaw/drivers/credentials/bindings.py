# -*- coding: utf-8 -*-
"""Credential-to-runtime binding helpers for Driver handlers."""

from __future__ import annotations

import base64
import logging
from typing import Any

from ..constants import (
    CREDENTIAL_ALIAS_DEFAULT,
    CREDENTIAL_ALIAS_OAUTH,
    CREDENTIAL_ALIAS_STATIC,
)
from .providers import CredentialProvider
from .types import ResolvedCredential

logger = logging.getLogger(__name__)


async def resolve_credentials(
    providers: dict[str, CredentialProvider],
) -> dict[str, ResolvedCredential]:
    """Resolve all credential aliases declared on one DriverCard."""
    credentials: dict[str, ResolvedCredential] = {}
    for alias, provider in providers.items():
        credentials[alias] = await provider.resolve()
    if CREDENTIAL_ALIAS_DEFAULT not in credentials and len(credentials) == 1:
        credentials[CREDENTIAL_ALIAS_DEFAULT] = next(
            iter(credentials.values()),
        )
    return credentials


def resolve_binding(
    binding: dict[str, Any],
    credentials: dict[str, ResolvedCredential],
) -> dict[str, str]:
    """Resolve an env/header binding into runtime string values."""
    if not isinstance(binding, dict):
        return {}
    if "public" not in binding and "secret_refs" not in binding:
        result: dict[str, str] = {}
        for output_name, spec in binding.items():
            value = _resolve_value_source(spec, credentials)
            if value is not None:
                result[str(output_name)] = value
        return result

    logger.warning(
        "Driver endpoint binding uses legacy public/secret_refs shape; "
        "prefer source=literal or source=credential entries.",
    )
    result = {
        str(key): str(value)
        for key, value in dict(binding.get("public") or {}).items()
    }
    for output_name, secret_key in dict(
        binding.get("secret_refs") or {},
    ).items():
        value = lookup_credential_value(credentials, str(secret_key))
        if value is not None:
            result[str(output_name)] = str(value)
    return result


def implicit_auth_headers(
    credentials: dict[str, ResolvedCredential],
    existing_headers: dict[str, str],
) -> dict[str, str]:
    """Return protocol-neutral auth headers inferred from credentials."""
    if any(key.lower() == "authorization" for key in existing_headers):
        return {}

    credential = credentials.get(CREDENTIAL_ALIAS_OAUTH)
    if credential is None:
        credential = credentials.get(CREDENTIAL_ALIAS_DEFAULT) or next(
            iter(credentials.values()),
            ResolvedCredential.EMPTY,
        )
    values = credential.values
    if not values:
        return {}

    headers = values.get("headers")
    if isinstance(headers, dict):
        return {str(key): str(value) for key, value in headers.items()}

    access_token = values.get("access_token") or values.get("token")
    if access_token:
        return {"Authorization": f"Bearer {access_token}"}

    username = values.get("username")
    password = values.get("password")
    if username is not None and password is not None:
        raw = f"{username}:{password}".encode("utf-8")
        encoded = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}

    return {}


def lookup_credential_value(
    credentials: dict[str, ResolvedCredential],
    reference: str,
) -> Any:
    """Look up ``alias.field`` or a bare field in resolved credentials."""
    alias = ""
    field = reference
    if "." in reference:
        alias, field = reference.split(".", 1)

    candidates: list[ResolvedCredential] = []
    if alias:
        credential = credentials.get(alias)
        if credential is not None:
            candidates.append(credential)
    else:
        for preferred in (CREDENTIAL_ALIAS_STATIC, CREDENTIAL_ALIAS_DEFAULT):
            credential = credentials.get(preferred)
            if credential is not None:
                candidates.append(credential)
        candidates.extend(
            credential
            for key, credential in credentials.items()
            if key not in {CREDENTIAL_ALIAS_STATIC, CREDENTIAL_ALIAS_DEFAULT}
        )

    for credential in candidates:
        if field in credential.secrets:
            return credential.secrets[field]
        if field in credential.values:
            return credential.values[field]
    return None


def _resolve_value_source(
    spec: Any,
    credentials: dict[str, ResolvedCredential],
) -> str | None:
    if not isinstance(spec, dict) or "source" not in spec:
        return str(spec)

    source = str(spec.get("source") or "")
    if source == "literal":
        return str(spec.get("value") or "")
    if source != "credential":
        return None

    alias = str(spec.get("credential") or CREDENTIAL_ALIAS_DEFAULT)
    field = str(spec.get("field") or "")
    value = (
        lookup_credential_value(credentials, f"{alias}.{field}")
        if field
        else None
    )
    if value is None:
        return None

    text = str(value)
    fmt = spec.get("format")
    if isinstance(fmt, str) and fmt:
        return fmt.replace("{value}", text)
    return text
