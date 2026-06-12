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
