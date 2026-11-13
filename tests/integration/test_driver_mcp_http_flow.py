# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from qwenpaw.drivers.capabilities import DriverInvocation
from qwenpaw.drivers.contracts import CredentialRef, DriverCard, PolicyRule
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import card_path, dump_card
from tests.integration.driver_mcp_fakes import (
    FakeHttpClient,
    patch_mcp_runtime_clients,
)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.p1
async def test_driver_mcp_http_header_secret_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/http_echo",
            kind="static",
            secrets={"authorization": "Bearer static-token"},
        ),
    )
    dump_card(
        DriverCard(
            name="http_echo",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "http://127.0.0.1:18080/mcp",
                "headers": {
                    "public": {"X-Client-Name": "qwenpaw-test"},
                    "secret_refs": {"Authorization": "authorization"},
                },
            },
            credentials={
                "default": CredentialRef("static", "mcp/http_echo"),
            },
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(tmp_path / "drivers", "http_echo", protocol="mcp"),
    )
    manager = DriverManager(tmp_path / "drivers", store)
    manager.register_handler_type("mcp", MCPDriverHandler)

    await manager.build_drivers()
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "inspect_headers"
    )
    result = await manager.invoke_capability(
        DriverInvocation(capability.capability_id, {}),
    )

    assert result.ok is True
    assert result.value["headers"]["Authorization"] == "Bearer static-token"
    assert result.value["headers"]["X-Client-Name"] == "qwenpaw-test"
    assert (
        FakeHttpClient.instances[0].kwargs["headers"]
        == result.value["headers"]
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.p1
async def test_driver_mcp_anysearch_default_config_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test purpose:
    - Verify the default MCP config ships an anysearch streamable_http
      template that migrates to a buildable DriverCard.

    Test flow:
    1. Build MCPConfig() and grab the anysearch client entry.
    2. Convert it to a DriverCard via the legacy migration helper.
    3. Register the card and build the driver handler (HTTP faked).
    4. Assert the exposed tool names match AnySearch's server.

    API endpoints:
    - none (driver layer, no app subprocess).
    """
    from qwenpaw.config.config import MCPConfig
    from qwenpaw.drivers.adapters.mcp_legacy_config import (
        legacy_mcp_client_to_driver,
    )

    patch_mcp_runtime_clients(monkeypatch)

    cfg = MCPConfig()
    assert "anysearch" in cfg.clients
    client = cfg.clients["anysearch"]
    assert client.enabled is False
    assert client.transport == "streamable_http"
    assert client.url == "https://api.anysearch.com/mcp"
    assert client.headers == {
        "Authorization": "Bearer ${ANYSEARCH_API_KEY}",
    }

    card, credential = legacy_mcp_client_to_driver("anysearch", client)
    assert card.protocol == "mcp"
    assert card.endpoint["transport"] == "streamable_http"
    assert card.endpoint["url"] == "https://api.anysearch.com/mcp"
    assert card.enabled is False
    assert card.policy.rules[0].effect == "ask"

    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    if credential is not None:
        await store.put(credential)
    card.enabled = True
    dump_card(
        card,
        card_path(tmp_path / "drivers", "anysearch", protocol="mcp"),
    )
    manager = DriverManager(tmp_path / "drivers", store)
    manager.register_handler_type("mcp", MCPDriverHandler)

    await manager.build_drivers()
    names = sorted(
        item.name for item in await manager.list_capabilities(kind="tool")
    )
    assert names == [
        "echo_http",
        "inspect_headers",
        "oauth_echo",
    ]
    assert "tavily_search" not in cfg.clients
