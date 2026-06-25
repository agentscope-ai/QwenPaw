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
async def test_driver_mcp_oauth_access_token_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/oauth_echo/oauth",
            kind="oauth2_auth_code",
            public={"expires_at": 0.0, "scope": "tools:read tools:call"},
            secrets={"access_token": "oauth-token"},
        ),
    )
    dump_card(
        DriverCard(
            name="oauth_echo",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "http://127.0.0.1:18081/mcp",
                "headers": {"public": {}, "secret_refs": {}},
            },
            credentials={
                "oauth": CredentialRef(
                    "oauth2_auth_code",
                    "mcp/oauth_echo/oauth",
                ),
            },
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(tmp_path / "drivers", "oauth_echo", protocol="mcp"),
    )
    manager = DriverManager(tmp_path / "drivers", store)
    manager.register_handler_type("mcp", MCPDriverHandler)

    await manager.build_drivers()
    capability = next(
        item
        for item in await manager.list_capabilities(kind="tool")
        if item.name == "oauth_echo"
    )
    result = await manager.invoke_capability(
        DriverInvocation(capability.capability_id, {"text": "hello"}),
    )

    assert result.ok is True
    assert FakeHttpClient.instances[0].kwargs["headers"] == {
        "Authorization": "Bearer oauth-token",
    }


@pytest.mark.asyncio
async def test_driver_mcp_http_combines_oauth_and_static_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/composite/oauth",
            kind="oauth2_auth_code",
            public={"expires_at": 0.0},
            secrets={"access_token": "oauth-token"},
        ),
    )
    await store.put(
        CredentialRecord(
            ref="mcp/composite/static",
            kind="static",
            secrets={"api_key": "static-key"},
        ),
    )
    dump_card(
        DriverCard(
            name="composite",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "http://127.0.0.1:18081/mcp",
                "headers": {
                    "Authorization": {
                        "source": "credential",
                        "credential": "oauth",
                        "field": "access_token",
                        "format": "Bearer {value}",
                    },
                    "X-API-Key": {
                        "source": "credential",
                        "credential": "static",
                        "field": "api_key",
                    },
                    "X-Client-Name": {
                        "source": "literal",
                        "value": "qwenpaw-test",
                    },
                },
            },
            credentials={
                "oauth": CredentialRef(
                    "oauth2_auth_code",
                    "mcp/composite/oauth",
                ),
                "static": CredentialRef("static", "mcp/composite/static"),
            },
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(tmp_path / "drivers", "composite", protocol="mcp"),
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
    assert result.value["headers"] == {
        "Authorization": "Bearer oauth-token",
        "X-API-Key": "static-key",
        "X-Client-Name": "qwenpaw-test",
    }
