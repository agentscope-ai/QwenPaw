# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from qwenpaw.drivers.capabilities import DriverInvocation
from qwenpaw.drivers.contracts import CredentialRef, DriverCard, PolicyRule
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.handlers.mcp import MCPDriverHandler
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import card_path, dump_card
from tests.integration.driver_mcp_fakes import patch_mcp_runtime_clients


@pytest.mark.asyncio
async def test_env_ref_header_resolves_from_environment_at_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    monkeypatch.setenv("WIND_API_KEY", "ak_real_key_123")
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    dump_card(
        DriverCard(
            name="wind",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "http://127.0.0.1:18080/mcp",
                "headers": {
                    "Authorization": {
                        "source": "credential",
                        "credential": "env_wind_api_key",
                        "field": "value",
                        "format": "Bearer {value}",
                    },
                },
            },
            credentials={
                "env_wind_api_key": CredentialRef(
                    "static",
                    "env:WIND_API_KEY",
                ),
            },
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(tmp_path / "drivers", "wind", protocol="mcp"),
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
    assert result.value["headers"]["Authorization"] == "Bearer ak_real_key_123"
    # A rotated env value is reflected without any persisted credential.
    credentials_file = tmp_path / "credentials.yaml"
    on_disk = (
        credentials_file.read_text(encoding="utf-8")
        if credentials_file.is_file()
        else ""
    )
    assert "ak_real_key_123" not in on_disk
