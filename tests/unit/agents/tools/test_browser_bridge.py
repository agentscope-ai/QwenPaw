# -*- coding: utf-8 -*-
"""Tests for browser takeover bridge.

Covers:
- BrowserTakeoverBridge message routing & Future management
- HITL event handling (pause / resume / stop)
- _resolve_mode priority logic
- _parse_tab_id and _ref_to_node_id helpers
- _dispatch_takeover action routing
"""
# pylint: disable=protected-access

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from qwenpaw.agents.tools.browser_bridge import (
    BrowserTakeoverBridge,
    _bridges,
    get_bridge,
    get_or_create_bridge,
)
from qwenpaw.agents.tools.browser_control import (
    _parse_tab_id,
    _ref_to_node_id,
    _resolve_mode,
)


class TestBrowserTakeoverBridge:
    """Core bridge logic."""

    def setup_method(self):
        _bridges.clear()

    def test_initial_state(self):
        bridge = BrowserTakeoverBridge("ws1")
        assert not bridge.is_connected
        assert not bridge.is_paused
        assert not bridge.managed_tabs
        assert bridge.workspace_id == "ws1"

    def test_get_or_create_bridge_reuses(self):
        b1 = get_or_create_bridge("ws1")
        b2 = get_or_create_bridge("ws1")
        assert b1 is b2

    def test_get_or_create_bridge_different(self):
        b1 = get_or_create_bridge("ws1")
        b2 = get_or_create_bridge("ws2")
        assert b1 is not b2

    def test_get_bridge_returns_none(self):
        assert get_bridge("nonexistent") is None

    def test_get_bridge_returns_existing(self):
        b = get_or_create_bridge("ws1")
        assert get_bridge("ws1") is b

    @pytest.mark.asyncio
    async def test_handle_response(self):
        bridge = BrowserTakeoverBridge("ws1")
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        bridge._pending["r0001"] = fut

        await bridge._handle_message(
            {"id": "r0001", "result": {"ok": True}},
        )
        assert fut.done()
        assert fut.result() == {"ok": True}

    @pytest.mark.asyncio
    async def test_handle_error_response(self):
        bridge = BrowserTakeoverBridge("ws1")
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        bridge._pending["r0001"] = fut

        await bridge._handle_message(
            {
                "id": "r0001",
                "error": {"code": -1, "message": "fail"},
            },
        )
        assert fut.done()
        with pytest.raises(RuntimeError, match="fail"):
            fut.result()

    @pytest.mark.asyncio
    async def test_hitl_pause_resume(self):
        bridge = BrowserTakeoverBridge("ws1")
        assert not bridge.is_paused

        await bridge._handle_message(
            {"method": "hitl.paused", "params": {}},
        )
        assert bridge.is_paused

        await bridge._handle_message(
            {"method": "hitl.resumed", "params": {}},
        )
        assert not bridge.is_paused

    @pytest.mark.asyncio
    async def test_tab_closed_event(self):
        bridge = BrowserTakeoverBridge("ws1")
        bridge._managed_tabs[42] = {"url": "https://x.com"}

        await bridge._handle_message(
            {
                "method": "tab.closed",
                "params": {"tabId": 42},
            },
        )
        assert 42 not in bridge._managed_tabs

    @pytest.mark.asyncio
    async def test_tab_navigated_event(self):
        bridge = BrowserTakeoverBridge("ws1")
        bridge._managed_tabs[42] = {"url": "https://old.com"}

        await bridge._handle_message(
            {
                "method": "tab.navigated",
                "params": {"tabId": 42, "url": "https://new.com"},
            },
        )
        assert bridge._managed_tabs[42]["url"] == ("https://new.com")

    @pytest.mark.asyncio
    async def test_send_command_no_ws(self):
        bridge = BrowserTakeoverBridge("ws1")
        with pytest.raises(ConnectionError):
            await bridge.send_command("tabs.list")

    @pytest.mark.asyncio
    async def test_send_command_timeout(self):
        bridge = BrowserTakeoverBridge("ws1")
        bridge._ws = AsyncMock()
        bridge._ws.send_json = AsyncMock()

        with pytest.raises(TimeoutError):
            await bridge.send_command(
                "tabs.list",
                timeout=0.05,
            )

    @pytest.mark.asyncio
    async def test_send_command_success(self):
        bridge = BrowserTakeoverBridge("ws1")
        mock_ws = AsyncMock()

        async def fake_send_json(msg):
            req_id = msg["id"]
            await bridge._handle_message(
                {"id": req_id, "result": {"tabs": []}},
            )

        mock_ws.send_json = fake_send_json
        bridge._ws = mock_ws

        result = await bridge.send_command("tabs.list")
        assert result == {"tabs": []}

    @pytest.mark.asyncio
    async def test_on_disconnect_cancels_futures(self):
        bridge = BrowserTakeoverBridge("ws1")
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        bridge._pending["r0001"] = fut
        bridge._ws = AsyncMock()

        bridge._on_disconnect()

        assert not bridge.is_connected
        assert fut.done()
        with pytest.raises(ConnectionError):
            fut.result()

    @pytest.mark.asyncio
    async def test_wait_for_connection_timeout(self):
        bridge = BrowserTakeoverBridge("ws1")
        ok = await bridge.wait_for_connection(timeout=0.05)
        assert not ok

    @pytest.mark.asyncio
    async def test_wait_for_connection_success(self):
        bridge = BrowserTakeoverBridge("ws1")
        bridge._connected.set()
        ok = await bridge.wait_for_connection(timeout=0.1)
        assert ok


class TestResolveMode:
    """Test _resolve_mode priority logic."""

    def test_explicit_takeover(self):
        assert _resolve_mode("takeover", False) == "takeover"

    def test_explicit_headed(self):
        assert _resolve_mode("headed", False) == "headed"

    def test_explicit_headless(self):
        assert _resolve_mode("headless", False) == "headless"

    def test_headed_flag_fallback(self):
        assert _resolve_mode("", True) == "headed"

    def test_default_headless(self):
        assert _resolve_mode("", False) == "headless"

    def test_mode_overrides_headed_flag(self):
        assert _resolve_mode("takeover", True) == "takeover"

    def test_whitespace_stripped(self):
        assert _resolve_mode("  takeover  ", False) == "takeover"

    def test_case_insensitive(self):
        assert _resolve_mode("TAKEOVER", False) == "takeover"

    def test_config_default_takeover(self):
        assert _resolve_mode("", False, "takeover") == "takeover"

    def test_config_default_headed(self):
        assert _resolve_mode("", False, "headed") == "headed"

    def test_config_overrides_explicit_mode(self):
        assert _resolve_mode("headless", False, "takeover") == "takeover"

    def test_config_overrides_headed_flag(self):
        assert _resolve_mode("", True, "takeover") == "takeover"


class TestParseTabId:
    """Test _parse_tab_id helper."""

    def test_plain_int(self):
        assert _parse_tab_id("42") == 42

    def test_chrome_prefix(self):
        assert _parse_tab_id("chrome_42") == 42

    def test_invalid(self):
        assert _parse_tab_id("default") is None

    def test_empty(self):
        assert _parse_tab_id("") is None

    def test_whitespace(self):
        assert _parse_tab_id("  42  ") == 42


class TestRefToNodeId:
    """Test _ref_to_node_id helper."""

    def test_e_prefix(self):
        assert _ref_to_node_id("e42") == 42

    def test_plain_int(self):
        assert _ref_to_node_id("42") == 42

    def test_invalid(self):
        assert _ref_to_node_id("abc") is None

    def test_empty(self):
        assert _ref_to_node_id("") is None


class TestDispatchTakeover:
    """Test takeover dispatch routing."""

    @pytest.fixture
    def mock_bridge(self):
        bridge = BrowserTakeoverBridge("test")
        bridge._ws = AsyncMock()
        bridge._connected.set()
        return bridge

    @pytest.mark.asyncio
    async def test_start_creates_tab(self):
        from qwenpaw.agents.tools.browser_control import (
            _dispatch_takeover,
        )

        state = {"workspace_id": "test"}
        bridge = get_or_create_bridge("test")
        bridge._ws = AsyncMock()
        bridge._connected.set()
        bridge.send_command = AsyncMock(
            return_value={
                "tabId": 99,
                "title": "New Tab",
                "url": "about:blank",
            },
        )

        result = await _dispatch_takeover(
            "start",
            state,
            "",
            "default",
            "",
            "",
            "",
            False,
            -1,
            -1,
            "left",
            False,
        )
        data = json.loads(result.content[0]["text"])
        assert data["ok"] is True
        assert data["status"] == "connected"
        assert data["tab"]["tabId"] == 99
        bridge.send_command.assert_awaited_once_with(
            "tab.create",
            {"url": "about:blank"},
        )
        _bridges.clear()

    @pytest.mark.asyncio
    async def test_discover_tabs(self):
        from qwenpaw.agents.tools.browser_control import (
            _dispatch_takeover,
        )

        state = {"workspace_id": "test"}
        bridge = get_or_create_bridge("test")
        mock_ws = AsyncMock()
        tabs_data = [
            {"tabId": 1, "title": "A", "url": "https://a.com"},
        ]

        async def fake_send(msg):
            req_id = msg["id"]
            await bridge._handle_message(
                {"id": req_id, "result": {"tabs": tabs_data}},
            )

        mock_ws.send_json = fake_send
        bridge._ws = mock_ws
        bridge._connected.set()

        result = await _dispatch_takeover(
            "discover_tabs",
            state,
            "",
            "default",
            "",
            "",
            "",
            False,
            -1,
            -1,
            "left",
            False,
        )
        data = json.loads(result.content[0]["text"])
        assert data["ok"] is True
        assert len(data["tabs"]) == 1
        _bridges.clear()

    @pytest.mark.asyncio
    async def test_not_connected_error(self):
        from qwenpaw.agents.tools.browser_control import (
            _dispatch_takeover,
        )

        _bridges.clear()
        state = {"workspace_id": "noconn"}
        get_or_create_bridge("noconn")

        result = await _dispatch_takeover(
            "snapshot",
            state,
            "",
            "default",
            "",
            "",
            "",
            False,
            -1,
            -1,
            "left",
            False,
        )
        data = json.loads(result.content[0]["text"])
        assert data["ok"] is False
        assert "not connected" in data["error"].lower()
        _bridges.clear()

    @pytest.mark.asyncio
    async def test_unsupported_action(self):
        from qwenpaw.agents.tools.browser_control import (
            _dispatch_takeover,
        )

        state = {"workspace_id": "test"}
        bridge = get_or_create_bridge("test")
        bridge._ws = AsyncMock()
        bridge._connected.set()
        bridge._managed_tabs[1] = {"url": "https://x.com"}

        result = await _dispatch_takeover(
            "nonexistent_action",
            state,
            "",
            "1",
            "",
            "",
            "",
            False,
            -1,
            -1,
            "left",
            False,
        )
        data = json.loads(result.content[0]["text"])
        assert data["ok"] is False
        assert "not supported" in data["error"].lower()
        _bridges.clear()
