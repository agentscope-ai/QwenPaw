# -*- coding: utf-8 -*-
"""HTTP timeout configuration follows the public config/card contract."""

from types import SimpleNamespace

from qwenpaw.app.mcp.schemas import MCPClientCreateRequest
from qwenpaw.config.config import MCPClientConfig
from qwenpaw.drivers.adapters.mcp_card_builder import (
    build_mcp_client_info_payload,
    build_mcp_driver_card,
)
from qwenpaw.drivers.adapters.mcp_legacy_config import (
    legacy_mcp_client_to_driver,
)

URL = "http://127.0.0.1:8080/mcp/sse"


def test_mcp_client_config_roundtrips_http_timeout() -> None:
    """Persist http_timeout on HTTP clients; omit it from stdio dumps."""
    cfg = MCPClientConfig(
        name="actions",
        transport="streamable_http",
        url=URL,
        http_timeout=1200.0,
    )
    dumped = cfg.model_dump()
    assert dumped["http_timeout"] == 1200.0
    restored = MCPClientConfig.model_validate(dumped)
    assert restored.http_timeout == 1200.0

    stdio = MCPClientConfig(name="local", command="python")
    assert stdio.http_timeout is None
    assert "http_timeout" not in stdio.model_dump(exclude_none=True)


def test_http_timeout_roundtrips_through_driver_card() -> None:
    """Store http_timeout on HTTP DriverCards and echo it in API payloads."""
    created = MCPClientCreateRequest(
        name="actions",
        transport="streamable_http",
        url=URL,
        http_timeout=1200.0,
    )
    card = build_mcp_driver_card("actions", created, "mcp/actions")
    assert card.endpoint["http_timeout"] == 1200.0
    assert build_mcp_client_info_payload(card, None)["http_timeout"] == 1200.0

    stdio_card = build_mcp_driver_card(
        "local",
        MCPClientCreateRequest(name="local", command="python"),
        "mcp/local",
    )
    assert "http_timeout" not in stdio_card.endpoint


def test_legacy_http_migration_copies_http_timeout() -> None:
    """Copy http_timeout from legacy HTTP MCP config onto the DriverCard."""
    card, _ = legacy_mcp_client_to_driver(
        "actions",
        SimpleNamespace(
            transport="streamable_http",
            url=URL,
            headers={},
            http_timeout=1200.0,
        ),
    )
    assert card.endpoint["http_timeout"] == 1200.0
