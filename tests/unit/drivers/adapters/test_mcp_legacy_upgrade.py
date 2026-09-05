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
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from qwenpaw.app.mcp.schemas import (
    MCPClientCreateRequest,
    MCPClientInfo,
    MCPClientUpdateRequest,
)
from qwenpaw.config.config import MCPClientConfig
from qwenpaw.mcp_timeout import (
    DEFAULT_MCP_TOOL_CALL_TIMEOUT_SECONDS,
    MAX_MCP_TOOL_CALL_TIMEOUT_SECONDS,
    MCP_TOOL_CALL_TIMEOUT_DESCRIPTION,
    parse_mcp_tool_call_timeout,
)
from qwenpaw.drivers.adapters.mcp_card_builder import (
    build_mcp_client_info_payload,
    build_mcp_driver_card,
)
from qwenpaw.drivers.adapters.mcp_legacy_config import (
    legacy_mcp_client_to_driver,
    upgrade_legacy_mcp_credentials,
)
from qwenpaw.drivers.contracts import CredentialRef, DriverCard, PolicyRule
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import card_path, dump_card, load_card


def test_mcp_timeout_roundtrips_through_config_and_driver_card() -> None:
    legacy = MCPClientConfig(
        name="slow-server",
        command="python",
        tool_call_timeout=5.0,
    )
    assert legacy.tool_call_timeout == 5.0

    migrated, _ = legacy_mcp_client_to_driver("slow-server", legacy)
    assert migrated.endpoint["tool_call_timeout"] == 5.0

    assert (
        MCPClientConfig(
            name="default-server",
            command="python",
        ).tool_call_timeout
        == DEFAULT_MCP_TOOL_CALL_TIMEOUT_SECONDS
    )

    created = MCPClientCreateRequest(
        name="slow-server",
        command="python",
        tool_call_timeout=7.0,
    )
    card = build_mcp_driver_card(
        "slow-server",
        created,
        "mcp/slow-server",
    )
    assert card.endpoint["tool_call_timeout"] == 7.0
    assert (
        build_mcp_client_info_payload(card, None)["tool_call_timeout"] == 7.0
    )

    updated = build_mcp_driver_card(
        "slow-server",
        MCPClientUpdateRequest(tool_call_timeout=9.0),
        "mcp/slow-server",
        existing=card,
    )
    assert updated.endpoint["tool_call_timeout"] == 9.0


@pytest.mark.parametrize(
    "model",
    [
        MCPClientInfo,
        MCPClientCreateRequest,
        MCPClientUpdateRequest,
        MCPClientConfig,
    ],
)
def test_mcp_timeout_schema_uses_shared_description(model) -> None:
    timeout_schema = model.model_json_schema()["properties"][
        "tool_call_timeout"
    ]

    assert timeout_schema["description"] == MCP_TOOL_CALL_TIMEOUT_DESCRIPTION


def test_legacy_timeout_name_is_not_coerced_to_tool_call_timeout() -> None:
    assert (
        MCPClientConfig(
            name="http-server",
            transport="streamable_http",
            url="https://mcp.example.com",
            timeout=6.0,
        ).tool_call_timeout
        == DEFAULT_MCP_TOOL_CALL_TIMEOUT_SECONDS
    )
    assert (
        MCPClientCreateRequest(
            name="http-server",
            transport="streamable_http",
            url="https://mcp.example.com",
            timeout=6.5,
        ).tool_call_timeout
        == DEFAULT_MCP_TOOL_CALL_TIMEOUT_SECONDS
    )
    assert MCPClientUpdateRequest(timeout=10.0).tool_call_timeout is None


def test_legacy_stdio_config_accepts_timeout_alias() -> None:
    config = MCPClientConfig(
        name="stdio-server",
        command="python",
        timeout=6.0,
    )

    assert config.tool_call_timeout == 6.0


@pytest.mark.parametrize(
    "config",
    [
        {
            "name": "stdio-server",
            "command": "python",
            "tool_call_timeout": None,
        },
        {
            "name": "http-server",
            "transport": "streamable_http",
            "url": "https://mcp.example.com",
            "tool_call_timeout": None,
            "timeout": 6.0,
        },
    ],
)
def test_legacy_config_treats_none_timeout_as_unset(config) -> None:
    assert (
        MCPClientConfig(**config).tool_call_timeout
        == DEFAULT_MCP_TOOL_CALL_TIMEOUT_SECONDS
    )


def test_legacy_http_migration_ignores_transport_timeout() -> None:
    config = SimpleNamespace(
        transport="streamable_http",
        url="https://mcp.example.com",
        headers={},
        oauth=None,
        tools=None,
        tool_call_timeout=None,
        timeout=6.0,
    )

    migrated, _ = legacy_mcp_client_to_driver("legacy-http", config)

    assert (
        migrated.endpoint["tool_call_timeout"]
        == DEFAULT_MCP_TOOL_CALL_TIMEOUT_SECONDS
    )


def test_legacy_stdio_migration_falls_back_from_none_to_timeout() -> None:
    config = SimpleNamespace(
        transport="stdio",
        command="python",
        args=[],
        env={},
        oauth=None,
        tools=None,
        tool_call_timeout=None,
        timeout=6.0,
    )

    migrated, _ = legacy_mcp_client_to_driver("legacy-stdio", config)

    assert migrated.endpoint["tool_call_timeout"] == 6.0


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 0, -1])
def test_mcp_tool_call_timeout_rejects_non_finite_or_non_positive_values(
    value,
) -> None:
    with pytest.raises(ValueError):
        parse_mcp_tool_call_timeout(value)

    with pytest.raises(ValidationError):
        MCPClientConfig(
            name="bad-server",
            command="python",
            tool_call_timeout=value,
        )

    with pytest.raises(ValidationError):
        MCPClientCreateRequest(
            name="bad-server",
            command="python",
            tool_call_timeout=value,
        )

    with pytest.raises(ValidationError):
        MCPClientUpdateRequest(tool_call_timeout=value)


@pytest.mark.parametrize("value", [True, False])
def test_mcp_tool_call_timeout_rejects_boolean_values(value) -> None:
    with pytest.raises(ValueError):
        parse_mcp_tool_call_timeout(value)

    with pytest.raises(ValidationError):
        MCPClientConfig(
            name="bad-server",
            command="python",
            tool_call_timeout=value,
        )

    with pytest.raises(ValidationError):
        MCPClientCreateRequest(
            name="bad-server",
            command="python",
            tool_call_timeout=value,
        )

    with pytest.raises(ValidationError):
        MCPClientUpdateRequest(tool_call_timeout=value)


def test_parse_mcp_tool_call_timeout_requires_a_value() -> None:
    parameter = inspect.signature(parse_mcp_tool_call_timeout).parameters[
        "value"
    ]
    assert parameter.default is inspect.Parameter.empty


def test_mcp_tool_call_timeout_rejects_values_above_maximum() -> None:
    too_large = MAX_MCP_TOOL_CALL_TIMEOUT_SECONDS + 1

    with pytest.raises(ValueError):
        parse_mcp_tool_call_timeout(too_large)

    with pytest.raises(ValidationError):
        MCPClientConfig(
            name="bad-server",
            command="python",
            tool_call_timeout=too_large,
        )

    with pytest.raises(ValidationError):
        MCPClientCreateRequest(
            name="bad-server",
            command="python",
            tool_call_timeout=too_large,
        )

    with pytest.raises(ValidationError):
        MCPClientUpdateRequest(tool_call_timeout=too_large)


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
