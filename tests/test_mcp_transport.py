# -*- coding: utf-8 -*-
"""Tests for MCP multi-transport support (stdio, sse, streamable_http)."""

import pytest
from copaw.config.config import MCPClientConfig, Config
from copaw.app.mcp.manager import MCPClientManager, _VALID_TRANSPORTS


class TestMCPClientConfig:
    """Config model tests."""

    def test_stdio_backward_compat(self):
        """Existing stdio configs without transport field still work."""
        cfg = MCPClientConfig(name="test", command="npx", args=["-y", "pkg"])
        assert cfg.transport == "stdio"
        assert cfg.url == ""
        assert cfg.headers == {}

    def test_sse_config(self):
        cfg = MCPClientConfig(
            name="sse",
            transport="sse",
            url="http://localhost:8080/sse",
            headers={"Authorization": "Bearer tok"},
        )
        assert cfg.transport == "sse"
        assert cfg.url == "http://localhost:8080/sse"
        assert cfg.headers["Authorization"] == "Bearer tok"

    def test_streamable_http_config(self):
        cfg = MCPClientConfig(
            name="http",
            transport="streamable_http",
            url="http://localhost:8080/mcp",
        )
        assert cfg.transport == "streamable_http"

    def test_json_roundtrip(self):
        original = MCPClientConfig(
            name="rt",
            transport="sse",
            url="http://x:9000/sse",
            headers={"X-Key": "val"},
        )
        data = original.model_dump()
        restored = MCPClientConfig(**data)
        assert restored.transport == "sse"
        assert restored.url == original.url
        assert restored.headers == original.headers

    def test_full_config_roundtrip(self):
        config = Config()
        config.mcp.clients["remote"] = MCPClientConfig(
            name="r",
            transport="sse",
            url="http://a/sse",
        )
        config.mcp.clients["local"] = MCPClientConfig(
            name="l",
            command="echo",
        )
        dump = config.model_dump(mode="json")
        restored = Config(**dump)
        assert restored.mcp.clients["remote"].transport == "sse"
        assert restored.mcp.clients["local"].transport == "stdio"


class TestMCPClientManager:  # pylint: disable=protected-access
    """Manager _create_client factory tests."""

    def test_create_stdio_client(self):
        from agentscope.mcp import StdIOStatefulClient

        cfg = MCPClientConfig(name="s", command="echo", args=["hi"])
        client = MCPClientManager._create_client(cfg)
        assert isinstance(client, StdIOStatefulClient)

    def test_create_sse_client(self):
        from agentscope.mcp import HttpStatefulClient

        cfg = MCPClientConfig(
            name="e",
            transport="sse",
            url="http://localhost/sse",
        )
        client = MCPClientManager._create_client(cfg)
        assert isinstance(client, HttpStatefulClient)

    def test_create_streamable_http_client(self):
        from agentscope.mcp import HttpStatefulClient

        cfg = MCPClientConfig(
            name="h",
            transport="streamable_http",
            url="http://localhost/mcp",
        )
        client = MCPClientManager._create_client(cfg)
        assert isinstance(client, HttpStatefulClient)

    def test_invalid_transport_raises(self):
        cfg = MCPClientConfig(
            name="bad",
            transport="websocket",
            url="ws://localhost",
        )
        with pytest.raises(ValueError, match="websocket"):
            MCPClientManager._create_client(cfg)

    def test_stdio_missing_command_raises(self):
        cfg = MCPClientConfig(name="bad", transport="stdio")
        with pytest.raises(ValueError, match="command"):
            MCPClientManager._create_client(cfg)

    def test_sse_missing_url_raises(self):
        cfg = MCPClientConfig(name="bad", transport="sse")
        with pytest.raises(ValueError, match="url"):
            MCPClientManager._create_client(cfg)

    def test_valid_transports_constant(self):
        assert _VALID_TRANSPORTS == ("stdio", "sse", "streamable_http")
