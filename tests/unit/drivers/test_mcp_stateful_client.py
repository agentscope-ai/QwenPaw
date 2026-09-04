# -*- coding: utf-8 -*-
"""Unit tests for HttpStatefulClient transport selection in _setup_transport.

Verifies that:
- transport="streamable_http" calls streamable_http_client
- transport="sse" calls sse_client
- Invalid transport raises ValueError in __init__
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import qwenpaw.drivers.handlers.mcp_stateful_client as mcp_mod
from qwenpaw.drivers.handlers.mcp_stateful_client import HttpStatefulClient


@pytest.mark.asyncio
async def test_streamable_http_calls_streamable_http_client() -> None:
    """When transport='streamable_http', streamable_http_client is called
    with the url and an httpx.AsyncClient, and sse_client is NOT called."""
    with (
        patch.object(mcp_mod, "streamable_http_client") as mock_streamable,
        patch.object(mcp_mod, "sse_client") as mock_sse,
    ):
        mock_streamable.return_value = AsyncMock()

        client = HttpStatefulClient(
            name="jin10_mcp",
            transport="streamable_http",
            url="https://mcp.example.com/api/",
            headers={"Authorization": "Bearer secret"},
            timeout=20,
            sse_read_timeout=200,
        )
        mock_stack = AsyncMock()
        mock_stack.enter_async_context = AsyncMock(
            return_value=(MagicMock(), MagicMock()),
        )

        read, write = await client._setup_transport(mock_stack)

        # streamable_http_client was called exactly once
        mock_streamable.assert_called_once()
        call_kwargs = mock_streamable.call_args.kwargs
        assert call_kwargs["url"] == "https://mcp.example.com/api/"
        http_client: httpx.AsyncClient = call_kwargs["http_client"]
        assert isinstance(http_client, httpx.AsyncClient)
        assert http_client.headers["authorization"] == "Bearer secret"

        # sse_client was NOT called
        mock_sse.assert_not_called()

        # enter_async_context called twice: httpx.AsyncClient + streamable_http_client
        assert mock_stack.enter_async_context.call_count == 2

        # _setup_transport returns the (read, write) tuple from enter_async_context
        assert read is not None
        assert write is not None


@pytest.mark.asyncio
async def test_sse_calls_sse_client() -> None:
    """When transport='sse', sse_client is called with correct args."""
    with (
        patch.object(mcp_mod, "sse_client") as mock_sse,
        patch.object(mcp_mod, "streamable_http_client") as mock_streamable,
    ):
        mock_sse.return_value = AsyncMock()

        client = HttpStatefulClient(
            name="sse_mcp",
            transport="sse",
            url="https://mcp.example.com/sse",
            headers={"X-Custom": "value"},
            timeout=15,
            sse_read_timeout=120,
            extra_arg="extra_val",
        )
        mock_stack = AsyncMock()
        mock_stack.enter_async_context = AsyncMock(
            return_value=(MagicMock(), MagicMock()),
        )

        await client._setup_transport(mock_stack)

        # sse_client was called exactly once
        mock_sse.assert_called_once()
        call_kwargs = mock_sse.call_args.kwargs
        assert call_kwargs["url"] == "https://mcp.example.com/sse"
        assert call_kwargs["headers"] == {"X-Custom": "value"}
        assert call_kwargs["timeout"] == 15
        assert call_kwargs["sse_read_timeout"] == 120
        assert call_kwargs.get("extra_arg") == "extra_val"

        # streamable_http_client was NOT called
        mock_streamable.assert_not_called()

        # enter_async_context called once (sse_client only, no extra httpx.AsyncClient)
        assert mock_stack.enter_async_context.call_count == 1


def test_invalid_transport_raises_value_error() -> None:
    """__init__ raises ValueError when transport is not 'streamable_http' or 'sse'."""
    with pytest.raises(ValueError, match="transport must be"):
        HttpStatefulClient(
            name="bad",
            transport="stdio",
            url="http://localhost",
        )


def test_invalid_transport_raises_value_error_unknown() -> None:
    """__init__ raises ValueError for any unrecognized transport string."""
    with pytest.raises(ValueError, match="transport must be"):
        HttpStatefulClient(
            name="bad",
            transport="websocket",
            url="http://localhost",
        )


def test_transport_type_error_on_non_string() -> None:
    """__init__ raises TypeError when transport is not a string."""
    with pytest.raises(TypeError, match="transport must be str"):
        HttpStatefulClient(
            name="bad",
            transport=123,  # type: ignore[arg-type]
            url="http://localhost",
        )


def test_name_type_error_on_non_string() -> None:
    """__init__ raises TypeError when name is not a string."""
    with pytest.raises(TypeError, match="name must be str"):
        HttpStatefulClient(
            name=None,  # type: ignore[arg-type]
            transport="sse",
            url="http://localhost",
        )


def test_url_type_error_on_non_string() -> None:
    """__init__ raises TypeError when url is not a string."""
    with pytest.raises(TypeError, match="url must be str"):
        HttpStatefulClient(
            name="bad",
            transport="sse",
            url=42,  # type: ignore[arg-type]
        )


def test_valid_transports_accepted() -> None:
    """Both 'streamable_http' and 'sse' are accepted as valid transports."""
    for transport in ("streamable_http", "sse"):
        client = HttpStatefulClient(
            name="valid",
            transport=transport,
            url="http://localhost",
        )
        assert client.transport == transport
        assert client.is_stateful is True


@pytest.mark.asyncio
async def test_sse_with_minimal_args() -> None:
    """sse_client path works with only required args (no headers, no extra kwargs)."""
    with patch.object(mcp_mod, "sse_client") as mock_sse:
        mock_sse.return_value = AsyncMock()

        client = HttpStatefulClient(
            name="minimal",
            transport="sse",
            url="http://localhost:3000/sse",
        )
        mock_stack = AsyncMock()
        mock_stack.enter_async_context = AsyncMock(
            return_value=(MagicMock(), MagicMock()),
        )

        await client._setup_transport(mock_stack)

        mock_sse.assert_called_once()
        call_kwargs = mock_sse.call_args.kwargs
        assert call_kwargs["url"] == "http://localhost:3000/sse"
        assert call_kwargs["headers"] is None
        assert call_kwargs["timeout"] == 30  # default
        assert call_kwargs["sse_read_timeout"] == 300  # default (60*5)


@pytest.mark.asyncio
async def test_streamable_http_with_minimal_args() -> None:
    """streamable_http path works with only required args (no headers, no extra kwargs)."""
    with patch.object(mcp_mod, "streamable_http_client") as mock_streamable:
        mock_streamable.return_value = AsyncMock()

        client = HttpStatefulClient(
            name="minimal_http",
            transport="streamable_http",
            url="http://localhost:3000/mcp",
        )
        mock_stack = AsyncMock()
        mock_stack.enter_async_context = AsyncMock(
            return_value=(MagicMock(), MagicMock()),
        )

        await client._setup_transport(mock_stack)

        mock_streamable.assert_called_once()
        call_kwargs = mock_streamable.call_args.kwargs
        assert call_kwargs["url"] == "http://localhost:3000/mcp"
        http_client = call_kwargs["http_client"]
        assert isinstance(http_client, httpx.AsyncClient)
        # No custom headers should be supplied by the client configuration.
        # httpx still installs its own standard default headers.
        assert "authorization" not in http_client.headers
