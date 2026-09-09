# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Configurable HTTP MCP timeout."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from qwenpaw.app.mcp.schemas import MCPClientCreateRequest
from qwenpaw.config.config import MCPClientConfig
from qwenpaw.drivers.adapters.mcp_card_builder import (
    build_mcp_client_info_payload,
    build_mcp_driver_card,
)
from qwenpaw.drivers.adapters.mcp_legacy_config import (
    legacy_mcp_client_to_driver,
)
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.credentials.providers import NoneProvider
from qwenpaw.drivers.handlers import mcp as mcp_handler
from qwenpaw.drivers.handlers.mcp_stateful_client import HttpStatefulClient
from qwenpaw.drivers.handlers.mcp_streamable_http import HttpStatelessClient

URL = "http://127.0.0.1:8080/mcp/sse"


def _http_payload(**overrides: object) -> dict:
    """Base streamable_http config payload with per-test overrides."""
    return {
        "name": "actions",
        "transport": "streamable_http",
        "url": URL,
        **overrides,
    }


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


@pytest.mark.parametrize(
    ("transport", "client_attr"),
    [
        ("streamable_http", "HttpAutoClient"),
        ("sse", "HttpStatefulClient"),
    ],
)
async def test_driver_handler_passes_http_timeout(
    transport: str,
    client_attr: str,
    monkeypatch,
) -> None:
    """Pass configured http_timeout through as the HTTP client timeout."""
    instances: list[object] = []

    class FakeClient:
        """Capture constructor kwargs for the driver handler."""

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            instances.append(self)

        async def connect(self) -> None:
            return None

        async def close(self, ignore_errors: bool = True) -> None:
            del ignore_errors

    monkeypatch.setattr(mcp_handler, client_attr, FakeClient)

    handler = mcp_handler.MCPDriverHandler(
        DriverCard(
            name="actions",
            protocol="mcp",
            endpoint={
                "transport": transport,
                "url": URL,
                "http_timeout": 1200.0,
            },
        ),
        NoneProvider(),
    )
    try:
        await handler._setup()
        assert instances[0].kwargs["timeout"] == 1200.0
    finally:
        await handler._teardown()


@pytest.mark.parametrize(
    "client_cls",
    [HttpStatefulClient, HttpStatelessClient],
)
@pytest.mark.parametrize(
    ("timeout", "expected_timeout", "expected_read"),
    [
        (1200, 1200.0, 1200.0),
        (timedelta(seconds=60), 60.0, 300.0),
        (None, 30.0, 300.0),
    ],
)
def test_http_client_timeout_normalization(
    client_cls,
    timeout,
    expected_timeout: float,
    expected_read: float,
) -> None:
    """Normalize timeout to seconds; raise read budget to at least it."""
    kwargs = {} if timeout is None else {"timeout": timeout}
    client = client_cls("actions", "streamable_http", URL, **kwargs)
    assert client.timeout == expected_timeout
    assert client.sse_read_timeout == expected_read


def test_http_timeout_rejects_non_positive_values() -> None:
    """Reject non-positive http_timeout values at the config schema."""
    with pytest.raises(ValidationError):
        MCPClientConfig(
            name="actions",
            transport="streamable_http",
            url=URL,
            http_timeout=0,
        )


def test_timeout_alias_maps_to_http_timeout() -> None:
    """Map a bare timeout field onto http_timeout when the latter is absent."""
    cfg = MCPClientConfig.model_validate(_http_payload(timeout=1200))
    assert cfg.http_timeout == 1200.0

    preferred = MCPClientConfig.model_validate(
        _http_payload(timeout=30, http_timeout=1200),
    )
    assert preferred.http_timeout == 1200.0
