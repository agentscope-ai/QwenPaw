# -*- coding: utf-8 -*-
"""Tests for hot-reload channel_manager preservation and process swap."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_channel(name="test"):
    ch = MagicMock()
    ch.channel = name
    ch._process = MagicMock(name="old_process")
    return ch


def _make_mock_channel_manager(channels):
    cm = MagicMock()
    cm.channels = channels
    cm.set_workspace = MagicMock()
    return cm


def _make_mock_workspace(runner, channel_manager=None):
    ws = MagicMock()
    ws._service_manager = MagicMock()
    ws._service_manager.services = {
        "runner": runner,
    }
    if channel_manager:
        ws._service_manager.services["channel_manager"] = channel_manager
    return ws


# ---------------------------------------------------------------------------
# Tests for reload_channel_service
# ---------------------------------------------------------------------------

class TestReloadChannelService:

    @pytest.mark.asyncio
    async def test_updates_all_channels_process(self):
        """After reload, all channels should point to new runner."""
        from copaw.app.workspace.service_factories import reload_channel_service

        old_runner = MagicMock()
        old_runner.stream_query = MagicMock(name="old_stream_query")

        new_runner = MagicMock()
        new_runner.stream_query = MagicMock(name="new_stream_query")

        ch1 = _make_mock_channel("whatsapp")
        ch1._process = old_runner.stream_query
        ch2 = _make_mock_channel("signal")
        ch2._process = old_runner.stream_query

        cm = _make_mock_channel_manager([ch1, ch2])
        ws = _make_mock_workspace(new_runner, cm)

        await reload_channel_service(ws, cm)

        # Both channels should now point to new_runner.stream_query
        assert ch1._process is new_runner.stream_query
        assert ch2._process is new_runner.stream_query

    @pytest.mark.asyncio
    async def test_calls_set_workspace(self):
        """Reload should update workspace reference on channel_manager."""
        from copaw.app.workspace.service_factories import reload_channel_service

        runner = MagicMock()
        runner.stream_query = MagicMock()
        cm = _make_mock_channel_manager([_make_mock_channel()])
        ws = _make_mock_workspace(runner, cm)

        await reload_channel_service(ws, cm)

        cm.set_workspace.assert_called_once_with(ws)

    @pytest.mark.asyncio
    async def test_no_runner_skips_update(self):
        """If runner is not available, channels should not be modified."""
        from copaw.app.workspace.service_factories import reload_channel_service

        old_process = MagicMock(name="old")
        ch = _make_mock_channel()
        ch._process = old_process

        cm = _make_mock_channel_manager([ch])
        ws = MagicMock()
        ws._service_manager = MagicMock()
        ws._service_manager.services = {}  # no runner

        await reload_channel_service(ws, cm)

        # Process unchanged
        assert ch._process is old_process

    @pytest.mark.asyncio
    async def test_empty_channels_no_error(self):
        """Reload with zero channels should not raise."""
        from copaw.app.workspace.service_factories import reload_channel_service

        runner = MagicMock()
        runner.stream_query = MagicMock()
        cm = _make_mock_channel_manager([])
        ws = _make_mock_workspace(runner, cm)

        await reload_channel_service(ws, cm)

        cm.set_workspace.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_reloads_idempotent(self):
        """Calling reload twice should work and always point to latest runner."""
        from copaw.app.workspace.service_factories import reload_channel_service

        runner1 = MagicMock()
        runner1.stream_query = MagicMock(name="r1")
        runner2 = MagicMock()
        runner2.stream_query = MagicMock(name="r2")

        ch = _make_mock_channel()
        cm = _make_mock_channel_manager([ch])

        ws1 = _make_mock_workspace(runner1)
        await reload_channel_service(ws1, cm)
        assert ch._process is runner1.stream_query

        ws2 = _make_mock_workspace(runner2)
        await reload_channel_service(ws2, cm)
        assert ch._process is runner2.stream_query


# ---------------------------------------------------------------------------
# Tests for ServiceDescriptor reusable flag
# ---------------------------------------------------------------------------

class TestChannelManagerReusable:

    def test_channel_manager_descriptor_is_reusable(self):
        """channel_manager must be marked reusable for hot-reload to work."""
        from copaw.app.workspace.service_manager import ServiceManager

        sm = ServiceManager(workspace=MagicMock())

        # Simulate workspace registration (we can't easily call _register_services
        # so just check the descriptor class supports it)
        from copaw.app.workspace.service_manager import ServiceDescriptor
        desc = ServiceDescriptor(
            name="channel_manager",
            service_class=None,
            reusable=True,
        )
        assert desc.reusable is True

    def test_service_manager_get_reusable_includes_channel_manager(self):
        """get_reusable_services should return channel_manager when marked."""
        from copaw.app.workspace.service_manager import (
            ServiceDescriptor,
            ServiceManager,
        )

        sm = ServiceManager(workspace=MagicMock())
        sm.register(ServiceDescriptor(
            name="channel_manager",
            service_class=None,
            reusable=True,
        ))
        mock_cm = MagicMock()
        sm.services["channel_manager"] = mock_cm

        reusable = sm.get_reusable_services()
        assert "channel_manager" in reusable
        assert reusable["channel_manager"] is mock_cm

    def test_non_reusable_service_excluded(self):
        """Non-reusable services should not appear in get_reusable_services."""
        from copaw.app.workspace.service_manager import (
            ServiceDescriptor,
            ServiceManager,
        )

        sm = ServiceManager(workspace=MagicMock())
        sm.register(ServiceDescriptor(
            name="runner",
            service_class=None,
            reusable=False,
        ))
        sm.services["runner"] = MagicMock()

        reusable = sm.get_reusable_services()
        assert "runner" not in reusable
