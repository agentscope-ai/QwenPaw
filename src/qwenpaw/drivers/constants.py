# -*- coding: utf-8 -*-
"""Shared Driver string constants."""

from __future__ import annotations

from typing import Final, Literal

CREDENTIAL_ALIAS_DEFAULT: Final = "default"
CREDENTIAL_ALIAS_STATIC: Final = "static"
CREDENTIAL_ALIAS_OAUTH: Final = "oauth"

CREDENTIAL_KIND_NONE: Final = "none"
CREDENTIAL_KIND_STATIC: Final = "static"
CREDENTIAL_KIND_OAUTH_AUTH_CODE: Final = "oauth2_auth_code"

POLICY_EFFECT_ALLOW: Final[Literal["allow"]] = "allow"
POLICY_EFFECT_ASK: Final[Literal["ask"]] = "ask"
POLICY_EFFECT_DENY: Final[Literal["deny"]] = "deny"
POLICY_EFFECTS: Final[frozenset[str]] = frozenset(
    {
        POLICY_EFFECT_ALLOW,
        POLICY_EFFECT_ASK,
        POLICY_EFFECT_DENY,
    },
)

PROTOCOL_MCP: Final = "mcp"
CAPABILITY_KIND_TOOL: Final[Literal["tool"]] = "tool"
DRIVER_OPERATION_INVOKE: Final = "invoke"

POLICY_TARGET_WILDCARD: Final = "*"
SUBJECT_UNKNOWN_USER: Final = "user:unknown"

PRINCIPAL_SOURCE_CHANNEL: Final = "channel"
PRINCIPAL_SUBJECT_ALL: Final = "all"
PRINCIPAL_SUBJECT_USER: Final = "user"
PRINCIPAL_SUBJECT_SESSION: Final = "session"
