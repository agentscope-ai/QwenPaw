# -*- coding: utf-8 -*-
"""WebSocket bridge for Chrome Extension browser takeover.

Manages bidirectional JSON-RPC 2.0 communication between
QwenPaw backend and the QwenPaw Browser Bridge Chrome
Extension.  Each workspace gets its own bridge instance.
"""

import asyncio
import logging
import time
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Global bridge registry: workspace_id -> bridge
_bridges: dict[str, "BrowserTakeoverBridge"] = {}


def get_or_create_bridge(
    workspace_id: str,
) -> "BrowserTakeoverBridge":
    """Return an existing bridge or create a new one."""
    if workspace_id not in _bridges:
        _bridges[workspace_id] = BrowserTakeoverBridge(
            workspace_id,
        )
    return _bridges[workspace_id]


def get_bridge(
    workspace_id: str,
) -> "BrowserTakeoverBridge | None":
    """Return an existing bridge or None."""
    return _bridges.get(workspace_id)


class BrowserTakeoverBridge:  # pylint: disable=R0904
    """WebSocket bridge for Chrome Extension takeover."""

    def __init__(self, workspace_id: str) -> None:
        self._workspace_id = workspace_id
        self._ws: WebSocket | None = None
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._connected = asyncio.Event()
        self._paused = asyncio.Event()
        self._paused.set()
        self._managed_tabs: dict[int, dict[str, Any]] = {}
        self._request_counter = 0

    # ------ connection lifecycle ------

    async def accept(self, ws: WebSocket) -> None:
        """Accept and run the extension WebSocket loop."""
        if self._ws is not None:
            logger.warning(
                (
                    "Replacing existing extension"
                    " connection for workspace %s"
                ),
                self._workspace_id,
            )
            await self._close_existing()

        self._ws = ws
        self._connected.set()
        logger.info(
            "Extension connected (workspace=%s)",
            self._workspace_id,
        )

        try:
            while True:
                data = await ws.receive_json()
                await self._handle_message(data)
        except Exception:
            logger.info(
                "Extension disconnected (workspace=%s)",
                self._workspace_id,
            )
        finally:
            self._on_disconnect()

    async def _close_existing(self) -> None:
        """Close a previously connected WebSocket."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._on_disconnect()

    def _on_disconnect(self) -> None:
        """Clean up after WebSocket disconnection."""
        self._ws = None
        self._connected.clear()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(
                    ConnectionError("Extension disconnected"),
                )
        self._pending.clear()

    # ------ message handling ------

    async def _handle_message(
        self,
        data: dict[str, Any],
    ) -> None:
        """Route incoming JSON-RPC messages."""
        if "id" in data and "result" in data:
            self._handle_response(data)
        elif "id" in data and "error" in data:
            self._handle_error_response(data)
        elif "method" in data and "id" not in data:
            self._handle_event(data)
        else:
            logger.warning(
                "Unknown message format: %s",
                str(data)[:200],
            )

    def _handle_response(
        self,
        data: dict[str, Any],
    ) -> None:
        """Handle a JSON-RPC response."""
        req_id = str(data["id"])
        fut = self._pending.pop(req_id, None)
        if fut and not fut.done():
            fut.set_result(data["result"])

    def _handle_error_response(
        self,
        data: dict[str, Any],
    ) -> None:
        """Handle a JSON-RPC error response."""
        req_id = str(data["id"])
        fut = self._pending.pop(req_id, None)
        err = data.get("error", {})
        msg = err.get("message", "Unknown error")
        if fut and not fut.done():
            fut.set_exception(RuntimeError(msg))

    def _handle_event(
        self,
        data: dict[str, Any],
    ) -> None:
        """Handle a JSON-RPC notification (no id)."""
        method = data.get("method", "")
        params = data.get("params", {})

        if method == "hitl.paused":
            self._paused.clear()
            logger.info("HITL paused by user")
        elif method == "hitl.resumed":
            self._paused.set()
            logger.info("HITL resumed by user")
        elif method == "tab.closed":
            tab_id = params.get("tabId")
            self._managed_tabs.pop(tab_id, None)
            logger.info("Tab %s closed by user", tab_id)
        elif method == "tab.navigated":
            tab_id = params.get("tabId")
            if tab_id in self._managed_tabs:
                self._managed_tabs[tab_id]["url"] = params.get("url", "")

    # ------ command sending ------

    async def send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for response."""
        if not self._ws:
            raise ConnectionError(
                "Extension not connected. Install the "
                "QwenPaw Browser Bridge Chrome Extension "
                "and ensure it is connected.",
            )

        await self._paused.wait()

        self._request_counter += 1
        req_id = f"r{self._request_counter:04d}"
        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params:
            msg["params"] = params

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[dict] = loop.create_future()
        self._pending[req_id] = fut

        try:
            await self._ws.send_json(msg)
            return await asyncio.wait_for(
                fut,
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(
                f"Extension did not respond to " f"{method} within {timeout}s",
            ) from None

    # ------ high-level helpers ------

    async def wait_for_connection(
        self,
        timeout: float = 60.0,
    ) -> bool:
        """Wait until an extension connects."""
        try:
            await asyncio.wait_for(
                self._connected.wait(),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def discover_tabs(self) -> list[dict]:
        """List user's open Chrome tabs."""
        result = await self.send_command("tabs.list")
        tabs = result.get("tabs", [])
        return tabs

    async def claim_tab(
        self,
        tab_id: int,
    ) -> dict[str, Any]:
        """Attach debugger and inject banner on a tab."""
        result = await self.send_command(
            "tab.claim",
            {"tabId": tab_id, "showBanner": True},
        )
        self._managed_tabs[tab_id] = {
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "claimed_at": time.time(),
        }
        return result

    async def release_tab(
        self,
        tab_id: int,
    ) -> dict[str, Any]:
        """Detach debugger and remove banner."""
        result = await self.send_command(
            "tab.release",
            {"tabId": tab_id},
        )
        self._managed_tabs.pop(tab_id, None)
        return result

    async def create_tab(
        self,
        url: str,
    ) -> dict[str, Any]:
        """Create a new tab and claim it."""
        result = await self.send_command(
            "tab.create",
            {"url": url, "groupName": "QwenPaw"},
        )
        tab_id = result.get("tabId")
        if tab_id is not None:
            self._managed_tabs[tab_id] = {
                "title": result.get("title", ""),
                "url": url,
                "claimed_at": time.time(),
            }
        return result

    async def get_accessibility_tree(
        self,
        tab_id: int,
    ) -> dict[str, Any]:
        """Get AX tree from a claimed tab."""
        return await self.send_command(
            "page.accessibilityTree",
            {"tabId": tab_id},
        )

    async def take_screenshot(
        self,
        tab_id: int,
        full_page: bool = False,
    ) -> dict[str, Any]:
        """Capture screenshot from a claimed tab."""
        return await self.send_command(
            "page.screenshot",
            {"tabId": tab_id, "fullPage": full_page},
        )

    async def navigate(
        self,
        tab_id: int,
        url: str,
    ) -> dict[str, Any]:
        """Navigate a claimed tab to a URL."""
        return await self.send_command(
            "page.navigate",
            {"tabId": tab_id, "url": url},
        )

    async def click(
        self,
        tab_id: int,
        x: int,
        y: int,
        button: str = "left",
        click_count: int = 1,
    ) -> dict[str, Any]:
        """Click at coordinates in a claimed tab."""
        return await self.send_command(
            "input.click",
            {
                "tabId": tab_id,
                "x": x,
                "y": y,
                "button": button,
                "clickCount": click_count,
            },
        )

    async def click_node(
        self,
        tab_id: int,
        backend_node_id: int,
    ) -> dict[str, Any]:
        """Click an element by its AX backend node ID."""
        return await self.send_command(
            "input.clickNode",
            {
                "tabId": tab_id,
                "backendNodeId": backend_node_id,
            },
        )

    async def type_text(
        self,
        tab_id: int,
        text: str,
    ) -> dict[str, Any]:
        """Type text into the focused element."""
        return await self.send_command(
            "input.type",
            {"tabId": tab_id, "text": text},
        )

    async def press_key(
        self,
        tab_id: int,
        key: str,
    ) -> dict[str, Any]:
        """Press a keyboard key."""
        return await self.send_command(
            "input.pressKey",
            {"tabId": tab_id, "key": key},
        )

    async def evaluate(
        self,
        tab_id: int,
        expression: str,
    ) -> dict[str, Any]:
        """Evaluate JS in a claimed tab."""
        return await self.send_command(
            "runtime.evaluate",
            {
                "tabId": tab_id,
                "expression": expression,
            },
        )

    async def stop(self) -> None:
        """Disconnect and clean up."""
        for tab_id in list(self._managed_tabs):
            try:
                await self.release_tab(tab_id)
            except Exception:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._on_disconnect()
        _bridges.pop(self._workspace_id, None)

    # ------ properties ------

    @property
    def is_connected(self) -> bool:
        """Whether extension WS is connected."""
        return self._ws is not None

    @property
    def is_paused(self) -> bool:
        """Whether HITL pause is active."""
        return not self._paused.is_set()

    @property
    def managed_tabs(self) -> dict[int, dict]:
        """Currently managed tab metadata."""
        return dict(self._managed_tabs)

    def register_tab(
        self,
        tab_id: int,
        title: str = "",
        url: str = "",
    ) -> None:
        """Register a tab as managed."""
        self._managed_tabs[tab_id] = {
            "title": title,
            "url": url,
        }

    @property
    def workspace_id(self) -> str:
        """Workspace this bridge serves."""
        return self._workspace_id
