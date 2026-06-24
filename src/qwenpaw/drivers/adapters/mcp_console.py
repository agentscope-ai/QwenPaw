# -*- coding: utf-8 -*-
"""Console MCP adapter compatibility facade."""

from __future__ import annotations

from .mcp_binding import (
    binding_plain_keys,
    binding_to_response,
    classify_mcp_binding,
    mask_mcp_secret_value,
    normalize_secret_key,
    restore_masked_value,
    source_binding_from_split,
    split_mcp_binding,
)
from .mcp_card_builder import (
    OAUTH_CREDENTIAL_ALIAS,
    STATIC_CREDENTIAL_ALIAS,
    attach_mcp_oauth_credential,
    build_mcp_client_info_payload,
    build_mcp_credential_record,
    build_mcp_driver_card,
    detach_mcp_oauth_credential,
    mcp_credential_ref,
    mcp_oauth_credential_ref,
    update_oauth_credential_ref,
)

__all__ = [
    "OAUTH_CREDENTIAL_ALIAS",
    "STATIC_CREDENTIAL_ALIAS",
    "attach_mcp_oauth_credential",
    "binding_plain_keys",
    "binding_to_response",
    "build_mcp_client_info_payload",
    "build_mcp_credential_record",
    "build_mcp_driver_card",
    "classify_mcp_binding",
    "detach_mcp_oauth_credential",
    "mask_mcp_secret_value",
    "mcp_credential_ref",
    "mcp_oauth_credential_ref",
    "normalize_secret_key",
    "restore_masked_value",
    "source_binding_from_split",
    "split_mcp_binding",
    "update_oauth_credential_ref",
]
