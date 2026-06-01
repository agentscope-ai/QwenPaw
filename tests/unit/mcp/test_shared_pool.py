# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for SharedMCPPool (#4842).

Verifies that MCP clients with identical configurations are shared
across agents via reference counting, and that cleanup happens
correctly when all references are released.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.app.mcp.pool import SharedMCPPool, _config_fingerprint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    """Create a mock MCPClientConfig with sensible defaults."""
    cfg = MagicMock()
    cfg.name = overrides.get("name", "test-server")
    cfg.transport = overrides.get("transport", "stdio")
    cfg.command = overrides.get("command", "npx")
    cfg.args = overrides.get("args", ["-y", "test-mcp-server"])
    cfg.env = overrides.get("env", {"KEY": "val"})
    cfg.cwd = overrides.get("cwd", "")
    cfg.url = overrides.get("url", "")
    cfg.headers = overrides.get("headers", {})
    cfg.enabled = True
    cfg.oauth = None
    return cfg


def _make_builder():
    """Create a mock builder that returns mock clients."""
    clients = []

    def builder(config):
        client = MagicMock()
        client.connect = AsyncMock()
        client.close = AsyncMock()
        client.name = config.name
        clients.append(client)
        return client

    return builder, clients


# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------


class TestConfigFingerprint:
    """Tests for _config_fingerprint determinism and sensitivity."""

    def test_same_config_same_fingerprint(self):
        config_a = _make_config(command="npx", args=["-y", "srv"])
        config_b = _make_config(command="npx", args=["-y", "srv"])
        assert _config_fingerprint(config_a) == _config_fingerprint(config_b)

    def test_different_command_different_fingerprint(self):
        config_a = _make_config(command="npx")
        config_b = _make_config(command="node")
        assert _config_fingerprint(config_a) != _config_fingerprint(config_b)

    def test_different_args_different_fingerprint(self):
        config_a = _make_config(args=["-y", "srv-a"])
        config_b = _make_config(args=["-y", "srv-b"])
        assert _config_fingerprint(config_a) != _config_fingerprint(config_b)

    def test_name_does_not_affect_fingerprint(self):
        """name is cosmetic — two configs with different names but same
        transport params should share the same server process."""
        config_a = _make_config(name="agent-1-server")
        config_b = _make_config(name="agent-2-server")
        assert _config_fingerprint(config_a) == _config_fingerprint(config_b)


# ---------------------------------------------------------------------------
# Pool tests
# ---------------------------------------------------------------------------


class TestSharedMCPPool:
    """Tests for SharedMCPPool acquire/release/refcount."""

    @pytest.fixture(autouse=True)
    def _reset_pool(self):
        SharedMCPPool.reset()
        yield
        SharedMCPPool.reset()

    @pytest.mark.asyncio
    async def test_acquire_creates_client(self):
        pool = SharedMCPPool.instance()
        builder, clients = _make_builder()
        config = _make_config()

        client = await pool.acquire(config, builder=builder)

        assert client is clients[0]
        assert len(clients) == 1
        clients[0].connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acquire_same_config_reuses_client(self):
        """Two acquires with the same config should return the same
        client and only spawn one process."""
        pool = SharedMCPPool.instance()
        builder, clients = _make_builder()
        config_a = _make_config(name="agent-1")
        config_b = _make_config(name="agent-2")

        client_a = await pool.acquire(config_a, builder=builder)
        client_b = await pool.acquire(config_b, builder=builder)

        assert client_a is client_b
        assert len(clients) == 1  # only one process spawned

    @pytest.mark.asyncio
    async def test_acquire_different_config_creates_separate(self):
        pool = SharedMCPPool.instance()
        builder, clients = _make_builder()
        config_a = _make_config(command="npx")
        config_b = _make_config(command="node")

        client_a = await pool.acquire(config_a, builder=builder)
        client_b = await pool.acquire(config_b, builder=builder)

        assert client_a is not client_b
        assert len(clients) == 2

    @pytest.mark.asyncio
    async def test_release_decrements_refcount(self):
        pool = SharedMCPPool.instance()
        builder, clients = _make_builder()
        config = _make_config()

        await pool.acquire(config, builder=builder)
        await pool.acquire(config, builder=builder)

        # refcount = 2, release once → refcount = 1, client stays alive
        await pool.release(config)
        clients[0].close.assert_not_awaited()

        stats = pool.stats()
        assert stats["total_clients"] == 1
        assert stats["total_refs"] == 1

    @pytest.mark.asyncio
    async def test_release_closes_at_zero(self):
        pool = SharedMCPPool.instance()
        builder, clients = _make_builder()
        config = _make_config()

        await pool.acquire(config, builder=builder)
        await pool.release(config)

        # refcount reached 0 → client should be closed
        clients[0].close.assert_awaited_once()
        assert pool.stats()["total_clients"] == 0

    @pytest.mark.asyncio
    async def test_close_all(self):
        pool = SharedMCPPool.instance()
        builder, clients = _make_builder()

        await pool.acquire(_make_config(command="a"), builder=builder)
        await pool.acquire(_make_config(command="b"), builder=builder)

        await pool.close_all()

        for client in clients:
            client.close.assert_awaited_once()
        assert pool.stats()["total_clients"] == 0

    @pytest.mark.asyncio
    async def test_singleton(self):
        pool_a = SharedMCPPool.instance()
        pool_b = SharedMCPPool.instance()
        assert pool_a is pool_b

    @pytest.mark.asyncio
    async def test_connect_failure_does_not_leak(self):
        """If connect() fails, the client should be cleaned up and
        not left in the pool."""
        pool = SharedMCPPool.instance()
        config = _make_config()

        def failing_builder(_cfg):
            client = MagicMock()
            client.connect = AsyncMock(
                side_effect=ConnectionError("refused"),
            )
            client.close = AsyncMock()
            return client

        with pytest.raises(ConnectionError):
            await pool.acquire(config, builder=failing_builder)

        assert pool.stats()["total_clients"] == 0


# ---------------------------------------------------------------------------
# MCPClientManager integration with pool
# ---------------------------------------------------------------------------


class TestMCPClientManagerPoolIntegration:
    """Verify MCPClientManager delegates to SharedMCPPool."""

    @pytest.fixture(autouse=True)
    def _reset_pool(self):
        SharedMCPPool.reset()
        yield
        SharedMCPPool.reset()

    @pytest.mark.asyncio
    async def test_add_client_uses_pool(self):
        from qwenpaw.app.mcp.manager import MCPClientManager

        manager = MCPClientManager()
        config = _make_config()
        builder, clients = _make_builder()

        with patch.object(
            MCPClientManager,
            "_build_client",
            side_effect=builder,
        ):
            await manager._add_client("test-key", config)

        pool = SharedMCPPool.instance()
        assert pool.stats()["total_clients"] == 1
        assert pool.stats()["total_refs"] == 1

        client_list = await manager.get_clients()
        assert len(client_list) == 1
        assert client_list[0] is clients[0]

    @pytest.mark.asyncio
    async def test_close_all_releases_to_pool(self):
        from qwenpaw.app.mcp.manager import MCPClientManager

        manager = MCPClientManager()
        config = _make_config()
        builder, clients = _make_builder()

        with patch.object(
            MCPClientManager,
            "_build_client",
            side_effect=builder,
        ):
            await manager._add_client("test-key", config)

        await manager.close_all()

        pool = SharedMCPPool.instance()
        assert pool.stats()["total_clients"] == 0
        clients[0].close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_two_managers_share_client(self):
        """Two MCPClientManagers (simulating two agents) with the same
        MCP config should share a single server process."""
        from qwenpaw.app.mcp.manager import MCPClientManager

        manager_a = MCPClientManager()
        manager_b = MCPClientManager()
        config = _make_config()
        builder, clients = _make_builder()

        with patch.object(
            MCPClientManager,
            "_build_client",
            side_effect=builder,
        ):
            await manager_a._add_client("srv", config)
            await manager_b._add_client("srv", config)

        # Only one client was actually created
        assert len(clients) == 1

        pool = SharedMCPPool.instance()
        assert pool.stats()["total_refs"] == 2

        # Close manager_a — client stays alive (refcount=1)
        await manager_a.close_all()
        clients[0].close.assert_not_awaited()

        # Close manager_b — client is closed (refcount=0)
        await manager_b.close_all()
        clients[0].close.assert_awaited_once()
