# -*- coding: utf-8 -*-
"""Migration tests: legacy ${VAR} header/env values -> env: credential refs."""
from types import SimpleNamespace

from qwenpaw.drivers.adapters.mcp_binding import (
    EnvRefPlan,
    plan_env_ref_bindings,
)
from qwenpaw.drivers.adapters.mcp_legacy_config import (
    legacy_mcp_client_to_driver,
)
from qwenpaw.drivers.contracts import CredentialRef


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
