# -*- coding: utf-8 -*-
"""Tests for Driver credential binding resolution (bindings.py)."""

from __future__ import annotations

from qwenpaw.drivers.adapters.mcp_binding import (
    binding_plain_keys,
    binding_to_response,
)
from qwenpaw.drivers.credentials.bindings import resolve_binding
from qwenpaw.drivers.credentials.types import ResolvedCredential


def _env_credential(value: str) -> ResolvedCredential:
    return ResolvedCredential(kind="env", secrets={"value": value})


def test_resolve_binding_skips_empty_env_value() -> None:
    """A ${VAR} credential whose environment variable is unset must not
    produce a header (the empty value would otherwise yield an illegal
    header like 'Authorization: Bearer ' and break the connection).
    """
    binding = {
        "Authorization": {
            "source": "credential",
            "credential": "env_anysearch_api_key",
            "field": "value",
            "format": "Bearer {value}",
        },
    }
    resolved = resolve_binding(
        binding,
        {"env_anysearch_api_key": _env_credential("")},
    )
    assert resolved == {}


def test_resolve_binding_injects_populated_env_value() -> None:
    """A populated environment variable is formatted and injected."""
    binding = {
        "Authorization": {
            "source": "credential",
            "credential": "env_anysearch_api_key",
            "field": "value",
            "format": "Bearer {value}",
        },
    }
    resolved = resolve_binding(
        binding,
        {"env_anysearch_api_key": _env_credential("secret-token")},
    )
    assert resolved == {"Authorization": "Bearer secret-token"}


def test_resolve_binding_skips_empty_format_result() -> None:
    """A format template that resolves to an empty string is dropped."""
    binding = {
        "X-Token": {
            "source": "credential",
            "credential": "env_empty",
            "field": "value",
            "format": "{value}",
        },
    }
    resolved = resolve_binding(
        binding,
        {"env_empty": _env_credential("")},
    )
    assert resolved == {}


def test_resolve_binding_keeps_public_literal() -> None:
    """Public literal headers pass through unchanged."""
    binding = {"X-Client-Name": {"source": "literal", "value": "qwenpaw"}}
    resolved = resolve_binding(binding, {})
    assert resolved == {"X-Client-Name": "qwenpaw"}


_ENV_REF_BINDING = {
    "Authorization": {
        "source": "credential",
        "credential": "env_anysearch_api_key",
        "field": "value",
        "format": "Bearer {value}",
    },
}


def test_binding_to_response_shows_env_ref_template() -> None:
    """B2: env-backed headers must be visible in the Console response
    (previously silently dropped because the alias is not 'static').
    """
    assert binding_to_response(
        _ENV_REF_BINDING,
        None,
        credential_alias="static",
        env_aliases={"env_anysearch_api_key": "ANYSEARCH_API_KEY"},
    ) == {"Authorization": "Bearer ${ANYSEARCH_API_KEY}"}


def test_binding_plain_keys_preserves_env_ref_template() -> None:
    """B3: UI edit round-trip must preserve env-backed headers
    (previously dropped, so saving the client silently deleted them).
    """
    assert binding_plain_keys(
        _ENV_REF_BINDING,
        credential_alias="static",
        env_aliases={"env_anysearch_api_key": "ANYSEARCH_API_KEY"},
    ) == {"Authorization": "Bearer ${ANYSEARCH_API_KEY}"}


def test_static_alias_starting_with_env_is_not_misclassified() -> None:
    """A static credential alias like ``env_custom`` must not be treated
    as env-backed (regression from rayrayraykk: identification must come
    from the env: credential refs, not the alias naming convention)."""
    static_binding = {
        "X-K": {
            "source": "credential",
            "credential": "env_custom",
            "field": "value",
        },
    }
    assert (
        binding_to_response(
            static_binding,
            None,
            credential_alias="static",
            env_aliases={"env_anysearch_api_key": "ANYSEARCH_API_KEY"},
        )
        == {}
    )


def test_resolve_binding_keeps_falsey_nonempty_values() -> None:
    """Zero and False are legitimate credential values and must survive
    the empty-value guard (regression: `if not value` dropped them)."""
    binding = {
        "X-Num": {
            "source": "credential",
            "credential": "env_num",
            "field": "value",
        },
        "X-Bool": {
            "source": "credential",
            "credential": "env_bool",
            "field": "value",
        },
    }
    resolved = resolve_binding(
        binding,
        {
            "env_num": ResolvedCredential(kind="env", secrets={"value": 0}),
            "env_bool": ResolvedCredential(
                kind="env",
                secrets={"value": False},
            ),
        },
    )
    assert resolved == {"X-Num": "0", "X-Bool": "False"}


def test_resolve_binding_skips_none_and_empty() -> None:
    """None and empty-string credential values are omitted entirely."""
    binding = {
        "X-A": {
            "source": "credential",
            "credential": "env_a",
            "field": "value",
        },
        "X-B": {
            "source": "credential",
            "credential": "env_b",
            "field": "value",
        },
    }
    resolved = resolve_binding(
        binding,
        {
            "env_a": ResolvedCredential(kind="env", secrets={"value": None}),
            "env_b": ResolvedCredential(kind="env", secrets={"value": ""}),
        },
    )
    assert resolved == {}


def test_resolve_binding_skips_unknown_source() -> None:
    """An unrecognized binding source must not produce a header value.

    ``resolve_binding`` lives in the protocol-agnostic credentials layer
    shared by all Driver handlers, not just MCP — this guards the empty
    env-value / unknown-source behavior that MCP header bindings rely on.
    """
    binding = {
        "X-K": {"source": "oauth", "credential": "tok", "field": "value"},
    }
    resolved = resolve_binding(binding, {})
    assert resolved == {}


def test_resolve_value_source_direct_contract() -> None:
    """Direct contract of the shared resolver: literal passthrough, unknown
    source -> None, empty credential value -> None (no empty headers)."""
    from qwenpaw.drivers.credentials.bindings import _resolve_value_source

    assert (
        _resolve_value_source({"source": "literal", "value": "v"}, {}) == "v"
    )
    assert _resolve_value_source({"source": "weird"}, {}) is None
    assert (
        _resolve_value_source(
            {"source": "credential", "credential": "c", "field": "missing"},
            {},
        )
        is None
    )
