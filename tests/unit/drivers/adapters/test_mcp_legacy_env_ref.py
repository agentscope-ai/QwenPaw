# -*- coding: utf-8 -*-
"""Migration tests: legacy ${VAR} header/env values -> env: credential refs."""

from types import SimpleNamespace

from qwenpaw.drivers.adapters.mcp_binding import (
    EnvRefPlan,
    plan_env_ref_bindings,
)
from qwenpaw.drivers.adapters.mcp_card_builder import (
    build_mcp_client_info_payload,
    build_mcp_credential_record,
    build_mcp_driver_card,
    mcp_credential_ref,
)
from qwenpaw.drivers.adapters.mcp_legacy_config import (
    legacy_mcp_client_to_driver,
)
from qwenpaw.drivers.contracts import CredentialRef
from qwenpaw.drivers.credentials.bindings import resolve_binding
from qwenpaw.drivers.credentials.types import ResolvedCredential

# --- plan_env_ref_bindings unit behavior ---


def test_plan_links_single_env_ref_with_format() -> None:
    plan = plan_env_ref_bindings({"Authorization": "Bearer ${API_KEY}"})
    assert isinstance(plan, EnvRefPlan)
    assert plan.env_bindings == {
        "Authorization": {
            "source": "credential",
            "credential": "env_api_key",
            "field": "value",
            "format": "Bearer {value}",
        },
    }
    assert plan.env_aliases == {"env_api_key": "API_KEY"}
    assert not plan.plain_secrets
    assert not plan.multi_ref_keys


def test_plan_pure_ref_omits_format() -> None:
    plan = plan_env_ref_bindings({"X-Api-Key": "${API_KEY}"})
    assert plan.env_bindings["X-Api-Key"] == {
        "source": "credential",
        "credential": "env_api_key",
        "field": "value",
    }


def test_plan_keeps_plain_secret_untouched() -> None:
    plan = plan_env_ref_bindings({"Authorization": "Bearer static-token"})
    assert plan.plain_secrets == {"Authorization": "Bearer static-token"}
    assert not plan.env_bindings
    assert not plan.env_aliases


def test_plan_multi_ref_is_reported_and_kept_plain() -> None:
    plan = plan_env_ref_bindings({"Authorization": "${USER}:${PASS}"})
    assert plan.multi_ref_keys == ["Authorization"]
    assert not plan.env_aliases
    assert plan.plain_secrets == {"Authorization": "${USER}:${PASS}"}


# --- end-to-end migration behavior ---


def test_migration_links_header_env_ref_and_never_persists_key() -> None:
    card, credential = legacy_mcp_client_to_driver(
        "wind",
        SimpleNamespace(
            transport="streamable_http",
            url="https://mcp.example.com/api/",
            headers={"Authorization": "Bearer ${API_KEY}"},
        ),
    )
    assert card.endpoint["headers"]["Authorization"] == {
        "source": "credential",
        "credential": "env_api_key",
        "field": "value",
        "format": "Bearer {value}",
    }
    assert card.credentials["env_api_key"] == CredentialRef(
        "static",
        "env:API_KEY",
    )
    assert credential is None or "authorization" not in credential.secrets


def test_migration_mixed_static_and_env_ref_headers() -> None:
    card, credential = legacy_mcp_client_to_driver(
        "svc",
        SimpleNamespace(
            transport="streamable_http",
            url="https://x/api/",
            headers={
                "Authorization": "Bearer ${API_KEY}",
                "X-Api-Key": "literal-secret",
            },
        ),
    )
    assert card.credentials["env_api_key"] == CredentialRef(
        "static",
        "env:API_KEY",
    )
    assert credential is not None
    assert credential.secrets.get("x_api_key") == "literal-secret"
    assert "authorization" not in credential.secrets


def test_migration_stdio_env_ref() -> None:
    card, _credential = legacy_mcp_client_to_driver(
        "svc",
        SimpleNamespace(
            transport="stdio",
            command="run-server",
            args=[],
            env={"API_TOKEN": "${TOKEN}"},
        ),
    )
    assert card.endpoint["env"]["API_TOKEN"] == {
        "source": "credential",
        "credential": "env_token",
        "field": "value",
    }
    assert card.credentials["env_token"] == CredentialRef(
        "static",
        "env:TOKEN",
    )


# --- Console save round-trip regression (review #6817) ---


def _console_save_roundtrip(
    client_key: str,
    client: dict,
) -> tuple[dict, dict]:
    """Simulate: migrate -> API payload -> unchanged Console save -> resolve.

    Returns ``(saved_headers, resolved_headers)`` for assertions.
    """
    card, credential = legacy_mcp_client_to_driver(
        client_key,
        SimpleNamespace(
            transport=client.get("transport", "streamable_http"),
            url=client.get("url", ""),
            command=client.get("command", ""),
            args=client.get("args", []),
            headers=client.get("headers", {}),
            env=client.get("env", {}),
        ),
    )
    payload = build_mcp_client_info_payload(card, credential)

    static_record = build_mcp_credential_record(client_key, payload)
    saved = build_mcp_driver_card(
        client_key,
        payload,
        mcp_credential_ref(client_key),
        credential_record=static_record,
        existing=card,
    )

    resolved = resolve_binding(
        saved.endpoint["headers"],
        {
            "static": ResolvedCredential(
                kind="static",
                secrets=dict(static_record.secrets),
            ),
            **{
                alias: ResolvedCredential(
                    kind="env",
                    secrets={"value": "live-token"},
                )
                for alias, ref in saved.credentials.items()
                if ref.ref.startswith("env:")
            },
        },
    )
    return saved.endpoint["headers"], resolved


def test_console_save_preserves_header_env_ref_binding() -> None:
    """An unchanged Console save must keep the env binding, not degrade the
    ${VAR} template into a static literal secret."""
    saved_headers, resolved = _console_save_roundtrip(
        "anysearch",
        {
            "transport": "streamable_http",
            "url": "https://api.anysearch.com/mcp",
            "headers": {"Authorization": "Bearer ${ANYSEARCH_API_KEY}"},
        },
    )
    assert saved_headers["Authorization"] == {
        "source": "credential",
        "credential": "env_anysearch_api_key",
        "field": "value",
        "format": "Bearer {value}",
    }
    assert resolved == {"Authorization": "Bearer live-token"}


def test_console_save_preserves_stdio_env_ref_binding() -> None:
    """The same round-trip must hold for stdio env-backed values."""
    card, credential = legacy_mcp_client_to_driver(
        "svc",
        SimpleNamespace(
            transport="stdio",
            command="run-server",
            args=[],
            env={"API_TOKEN": "${TOKEN}"},
        ),
    )
    payload = build_mcp_client_info_payload(card, credential)
    static_record = build_mcp_credential_record("svc", payload)
    saved = build_mcp_driver_card(
        "svc",
        payload,
        mcp_credential_ref("svc"),
        credential_record=static_record,
        existing=card,
    )
    assert saved.endpoint["env"]["API_TOKEN"] == {
        "source": "credential",
        "credential": "env_token",
        "field": "value",
    }
    resolved = resolve_binding(
        saved.endpoint["env"],
        {
            "env_token": ResolvedCredential(
                kind="env",
                secrets={"value": "live-token"},
            ),
        },
    )
    assert resolved == {"API_TOKEN": "live-token"}


def test_console_save_keeps_static_secret_untouched() -> None:
    """A real static secret still lands in the static credential record.

    Mirrors the Console flow: the GET payload shows a masked value, and
    the user's unchanged save submits it; the save path restores the
    original when an existing secret matches, or stores the submitted
    literal for a fresh value.
    """
    card, credential = legacy_mcp_client_to_driver(
        "svc",
        SimpleNamespace(
            transport="streamable_http",
            url="https://x/api/",
            headers={"X-Api-Key": "literal-secret"},
        ),
    )
    payload = build_mcp_client_info_payload(card, credential)
    # Unchanged save submits the same payload; the masked static value is
    # restored against the existing credential on update.
    static_record = build_mcp_credential_record(
        "svc",
        payload,
        existing=credential,
    )
    saved = build_mcp_driver_card(
        "svc",
        payload,
        mcp_credential_ref("svc"),
        credential_record=static_record,
        existing=card,
    )
    assert saved.endpoint["headers"]["X-Api-Key"] == {
        "source": "credential",
        "credential": "static",
        "field": "x_api_key",
    }
    resolved = resolve_binding(
        saved.endpoint["headers"],
        {
            "static": ResolvedCredential(
                kind="static",
                secrets=dict(static_record.secrets),
            ),
        },
    )
    assert resolved == {"X-Api-Key": "literal-secret"}


def test_console_save_preserves_env_var_case() -> None:
    """Response serialization must preserve the original env var case from
    the card's env: ref instead of uppercasing the lowercased alias."""
    card, credential = legacy_mcp_client_to_driver(
        "svc",
        SimpleNamespace(
            transport="streamable_http",
            url="https://x/api/",
            headers={"Authorization": "Bearer ${ApiKey}"},
        ),
    )
    payload = build_mcp_client_info_payload(card, credential)
    assert payload["headers"] == {"Authorization": "Bearer ${ApiKey}"}


def test_console_save_drops_stale_env_ref_when_switched_to_static() -> None:
    """Switching a header from ${VAR} template to a static literal must
    remove the stale env: credential ref so runtime resolution no longer
    sees it."""
    card, _credential = legacy_mcp_client_to_driver(
        "svc",
        SimpleNamespace(
            transport="streamable_http",
            url="https://x/api/",
            headers={"Authorization": "Bearer ${API_KEY}"},
        ),
    )
    payload = SimpleNamespace(
        transport="streamable_http",
        url="https://x/api/",
        headers={"Authorization": "Bearer static-key"},
    )
    static_record = build_mcp_credential_record("svc", payload)
    saved = build_mcp_driver_card(
        "svc",
        payload,
        mcp_credential_ref("svc"),
        credential_record=static_record,
        existing=card,
    )
    assert "env_api_key" not in saved.credentials
    assert saved.credentials["static"].ref == mcp_credential_ref("svc")
    resolved = resolve_binding(
        saved.endpoint["headers"],
        {
            "static": ResolvedCredential(
                kind="static",
                secrets=dict(static_record.secrets),
            ),
        },
    )
    assert resolved == {"Authorization": "Bearer static-key"}


def test_console_save_treats_multi_env_ref_as_static() -> None:
    """A header embedding multiple ${VAR} refs (e.g. ${USER}:${PASS}) is not
    a supported single-env binding; it must be stored as a static literal
    instead of being silently dropped."""
    payload = SimpleNamespace(
        transport="streamable_http",
        url="https://x/api/",
        headers={"Authorization": "${USER}:${PASS}"},
    )
    static_record = build_mcp_credential_record("svc", payload)
    assert static_record.secrets.get("authorization") == "${USER}:${PASS}"

    saved = build_mcp_driver_card(
        "svc",
        payload,
        mcp_credential_ref("svc"),
        credential_record=static_record,
    )
    assert saved.endpoint["headers"]["Authorization"] == {
        "source": "credential",
        "credential": "static",
        "field": "authorization",
    }
    resolved = resolve_binding(
        saved.endpoint["headers"],
        {
            "static": ResolvedCredential(
                kind="static",
                secrets=dict(static_record.secrets),
            ),
        },
    )
    assert resolved == {"Authorization": "${USER}:${PASS}"}


def test_env_aliases_do_not_collide_on_case() -> None:
    """Two env vars differing only in case (${ApiKey} vs ${APIKEY}) must
    get distinct, collision-free credential aliases and resolve from their
    own environment variables on case-sensitive systems."""
    plan = plan_env_ref_bindings(
        {
            "X-First": "${ApiKey}",
            "X-Second": "${APIKEY}",
        },
    )
    assert len(plan.env_aliases) == 2
    assert plan.env_aliases["env_apikey"] == "ApiKey"
    assert plan.env_aliases["env_apikey_2"] == "APIKEY"

    card, _credential = legacy_mcp_client_to_driver(
        "svc",
        SimpleNamespace(
            transport="streamable_http",
            url="https://x/api/",
            headers={
                "X-First": "${ApiKey}",
                "X-Second": "${APIKEY}",
            },
        ),
    )
    refs = {v.ref for v in card.credentials.values()}
    assert "env:ApiKey" in refs
    assert "env:APIKEY" in refs

    resolved = resolve_binding(
        card.endpoint["headers"],
        {
            "env_apikey": ResolvedCredential(
                kind="env",
                secrets={"value": "first-token"},
            ),
            "env_apikey_2": ResolvedCredential(
                kind="env",
                secrets={"value": "second-token"},
            ),
        },
    )
    assert resolved == {
        "X-First": "first-token",
        "X-Second": "second-token",
    }
