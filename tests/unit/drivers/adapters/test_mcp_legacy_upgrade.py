# -*- coding: utf-8 -*-
"""Tests for legacy MCP credential upgrade (self-heal of #6029 bad cards).

Cards migrated *before* the #6029 fix stored ``${VAR}`` header values as
literals in the credential store, so migration's "card already exists" gate
never repairs them.  ``upgrade_legacy_mcp_credentials`` re-runs the same
``env:`` conversion over already-migrated cards, and must:

* rewrite only credential secret values that hold a single ``${WORD}``,
* leave real secrets (no ``${WORD}``) byte-for-byte untouched,
* be idempotent (skip credentials already resolved via ``env:``).
"""
from pathlib import Path

import pytest

from qwenpaw.drivers.adapters.mcp_legacy_config import (
    upgrade_legacy_mcp_credentials,
)
from qwenpaw.drivers.contracts import CredentialRef, DriverCard, PolicyRule
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import card_path, dump_card, load_card


def _write_card(
    cards_dir: Path,
    *,
    headers: dict,
    credentials: dict,
) -> None:
    dump_card(
        DriverCard(
            name="wind",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "https://mcp.example.com/api/",
                "headers": headers,
            },
            credentials=credentials,
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(cards_dir, "wind", protocol="mcp"),
    )


@pytest.mark.asyncio
async def test_upgrade_rewrites_single_env_ref_literal(
    tmp_path: Path,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/wind",
            kind="static",
            secrets={"authorization": "Bearer ${API_KEY}"},
        ),
    )
    cards_dir = tmp_path / "drivers"
    _write_card(
        cards_dir,
        headers={
            "Authorization": {
                "source": "credential",
                "credential": "static",
                "field": "authorization",
            },
        },
        credentials={"static": CredentialRef("static", "mcp/wind")},
    )
    manager = DriverManager(cards_dir, store)

    report = await upgrade_legacy_mcp_credentials(manager)

    card = load_card(card_path(cards_dir, "wind", protocol="mcp"))
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
    assert "mcp/wind" not in await store.list_refs()
    assert len(report.upgraded) == 1


@pytest.mark.asyncio
async def test_upgrade_leaves_real_secret_untouched(
    tmp_path: Path,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/wind",
            kind="static",
            secrets={"authorization": "Bearer sk-real-key-123"},
        ),
    )
    cards_dir = tmp_path / "drivers"
    _write_card(
        cards_dir,
        headers={
            "Authorization": {
                "source": "credential",
                "credential": "static",
                "field": "authorization",
            },
        },
        credentials={"static": CredentialRef("static", "mcp/wind")},
    )
    manager = DriverManager(cards_dir, store)

    report = await upgrade_legacy_mcp_credentials(manager)

    card = load_card(card_path(cards_dir, "wind", protocol="mcp"))
    assert card.endpoint["headers"]["Authorization"] == {
        "source": "credential",
        "credential": "static",
        "field": "authorization",
    }
    assert card.credentials["static"] == CredentialRef("static", "mcp/wind")
    record = await store.get("mcp/wind")
    assert record.secrets["authorization"] == "Bearer sk-real-key-123"
    assert report.upgraded == []


@pytest.mark.asyncio
async def test_upgrade_is_idempotent_for_env_refs(
    tmp_path: Path,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    cards_dir = tmp_path / "drivers"
    _write_card(
        cards_dir,
        headers={
            "Authorization": {
                "source": "credential",
                "credential": "env_api_key",
                "field": "value",
                "format": "Bearer {value}",
            },
        },
        credentials={"env_api_key": CredentialRef("static", "env:API_KEY")},
    )
    manager = DriverManager(cards_dir, store)

    report = await upgrade_legacy_mcp_credentials(manager)

    assert report.upgraded == []
    card = load_card(card_path(cards_dir, "wind", protocol="mcp"))
    assert card.credentials["env_api_key"] == CredentialRef(
        "static",
        "env:API_KEY",
    )


@pytest.mark.asyncio
async def test_upgrade_mixed_credential_preserves_real_secret(
    tmp_path: Path,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/wind",
            kind="static",
            secrets={
                "authorization": "Bearer ${API_KEY}",
                "x_tenant": "acme-prod-1234",
            },
        ),
    )
    cards_dir = tmp_path / "drivers"
    _write_card(
        cards_dir,
        headers={
            "Authorization": {
                "source": "credential",
                "credential": "static",
                "field": "authorization",
            },
            "X-Tenant": {
                "source": "credential",
                "credential": "static",
                "field": "x_tenant",
            },
        },
        credentials={"static": CredentialRef("static", "mcp/wind")},
    )
    manager = DriverManager(cards_dir, store)

    report = await upgrade_legacy_mcp_credentials(manager)

    card = load_card(card_path(cards_dir, "wind", protocol="mcp"))
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
    assert card.endpoint["headers"]["X-Tenant"] == {
        "source": "credential",
        "credential": "static",
        "field": "x_tenant",
    }
    assert card.credentials["static"] == CredentialRef("static", "mcp/wind")
    record = await store.get("mcp/wind")
    assert record.secrets == {"x_tenant": "acme-prod-1234"}
    assert len(report.upgraded) == 1
