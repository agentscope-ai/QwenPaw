# -*- coding: utf-8 -*-
"""Tests for browser CDP (Chrome DevTools Protocol) cloud mode integration."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers – import browser_control lazily so patches take effect
# ---------------------------------------------------------------------------

def _import_browser_control():
    """Import browser_control module (isolated from other tests)."""
    from copaw.agents.tools import browser_control
    return browser_control


# ---------------------------------------------------------------------------
# CDP endpoint setter / getter / clear
# ---------------------------------------------------------------------------

class TestCdpEndpointManagement:
    """Test set/get/clear CDP endpoint functions."""

    def setup_method(self):
        self.mod = _import_browser_control()
        # Save original and reset
        self._orig = self.mod._cdp_endpoint_url
        self.mod._cdp_endpoint_url = None

    def teardown_method(self):
        self.mod._cdp_endpoint_url = self._orig

    def test_set_and_get(self):
        assert self.mod.get_cdp_endpoint() is None
        self.mod.set_cdp_endpoint("http://localhost:9222")
        assert self.mod.get_cdp_endpoint() == "http://localhost:9222"

    def test_clear(self):
        self.mod.set_cdp_endpoint("http://localhost:9222")
        self.mod.clear_cdp_endpoint()
        assert self.mod.get_cdp_endpoint() is None


# ---------------------------------------------------------------------------
# _action_start with CDP
# ---------------------------------------------------------------------------

class TestActionStartCdp:
    """Test that _action_start uses connect_over_cdp when CDP endpoint is set."""

    def setup_method(self):
        self.mod = _import_browser_control()
        self._orig_url = self.mod._cdp_endpoint_url
        self._orig_state = {k: v for k, v in self.mod._state.items()}

    def teardown_method(self):
        self.mod._cdp_endpoint_url = self._orig_url
        # Restore state
        self.mod._state.update(self._orig_state)
        self.mod._state["pages"] = {}
        self.mod._state["refs"] = {}
        self.mod._state["refs_frame"] = {}
        self.mod._state["console_logs"] = {}
        self.mod._state["network_requests"] = {}
        self.mod._state["pending_dialogs"] = {}
        self.mod._state["pending_file_choosers"] = {}
        self.mod._state["_cdp_mode"] = False

    @pytest.mark.asyncio
    async def test_start_uses_cdp_when_endpoint_set(self):
        """When CDP endpoint is set, _action_start should connect_over_cdp."""
        self.mod.set_cdp_endpoint("http://remote:9222")

        mock_context = MagicMock()
        mock_context.on = MagicMock()

        mock_browser = MagicMock()
        mock_browser.contexts = [mock_context]

        mock_pw = MagicMock()
        mock_pw.chromium = MagicMock()
        mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

        mock_async_pw_instance = AsyncMock()
        mock_async_pw_instance.start = AsyncMock(return_value=mock_pw)

        with patch.object(
            self.mod,
            '_ensure_playwright_async',
            return_value=lambda: mock_async_pw_instance,
        ):
            result = await self.mod._action_start(headed=False)

        # Verify connect_over_cdp was called with correct URL
        mock_pw.chromium.connect_over_cdp.assert_awaited_once_with(
            "http://remote:9222",
        )
        # Verify state
        assert self.mod._state["_cdp_mode"] is True
        assert self.mod._state["browser"] is mock_browser
        assert self.mod._state["context"] is mock_context
        # Verify response
        data = json.loads(result.content[0]["text"])
        assert data["ok"] is True
        assert "CDP" in data["message"]

    @pytest.mark.asyncio
    async def test_start_falls_back_on_cdp_failure(self):
        """When CDP connection fails, _action_start should return error."""
        self.mod.set_cdp_endpoint("http://bad-host:9222")

        mock_pw = MagicMock()
        mock_pw.chromium = MagicMock()
        mock_pw.chromium.connect_over_cdp = AsyncMock(
            side_effect=Exception("Connection refused"),
        )

        mock_async_pw_instance = AsyncMock()
        mock_async_pw_instance.start = AsyncMock(return_value=mock_pw)

        with patch.object(
            self.mod,
            '_ensure_playwright_async',
            return_value=lambda: mock_async_pw_instance,
        ):
            result = await self.mod._action_start(headed=False)

        data = json.loads(result.content[0]["text"])
        assert data["ok"] is False
        assert "Connection refused" in data["error"]


# ---------------------------------------------------------------------------
# _ensure_browser with CDP
# ---------------------------------------------------------------------------

class TestEnsureBrowserCdp:
    """Test that _ensure_browser uses CDP when endpoint is set."""

    def setup_method(self):
        self.mod = _import_browser_control()
        self._orig_url = self.mod._cdp_endpoint_url
        self._orig_state = {k: v for k, v in self.mod._state.items()}

    def teardown_method(self):
        self.mod._cdp_endpoint_url = self._orig_url
        self.mod._state.update(self._orig_state)
        self.mod._state["pages"] = {}
        self.mod._state["refs"] = {}
        self.mod._state["refs_frame"] = {}
        self.mod._state["console_logs"] = {}
        self.mod._state["network_requests"] = {}
        self.mod._state["pending_dialogs"] = {}
        self.mod._state["pending_file_choosers"] = {}
        self.mod._state["_cdp_mode"] = False

    @pytest.mark.asyncio
    async def test_ensure_browser_cdp(self):
        """_ensure_browser should connect via CDP when endpoint is set."""
        self.mod.set_cdp_endpoint("http://remote:9222")
        # Reset browser state so _ensure_browser tries to start
        self.mod._state["browser"] = None
        self.mod._state["context"] = None

        mock_context = MagicMock()
        mock_context.on = MagicMock()

        mock_browser = MagicMock()
        mock_browser.contexts = [mock_context]

        mock_pw = MagicMock()
        mock_pw.chromium = MagicMock()
        mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

        mock_async_pw_instance = AsyncMock()
        mock_async_pw_instance.start = AsyncMock(return_value=mock_pw)

        with patch.object(
            self.mod,
            '_ensure_playwright_async',
            return_value=lambda: mock_async_pw_instance,
        ):
            result = await self.mod._ensure_browser()

        assert result is True
        assert self.mod._state["_cdp_mode"] is True
        mock_pw.chromium.connect_over_cdp.assert_awaited_once_with(
            "http://remote:9222",
        )

    @pytest.mark.asyncio
    async def test_ensure_browser_skips_if_already_running(self):
        """_ensure_browser should skip if browser is already connected."""
        self.mod._state["browser"] = MagicMock()
        self.mod._state["context"] = MagicMock()

        result = await self.mod._ensure_browser()
        assert result is True


# ---------------------------------------------------------------------------
# _reset_browser_state clears CDP mode
# ---------------------------------------------------------------------------

class TestResetBrowserStateCdp:
    """Test that _reset_browser_state clears _cdp_mode."""

    def test_reset_clears_cdp_mode(self):
        mod = _import_browser_control()
        mod._state["_cdp_mode"] = True
        mod._reset_browser_state()
        assert mod._state["_cdp_mode"] is False
