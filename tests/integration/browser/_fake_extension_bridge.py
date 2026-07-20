# -*- coding: utf-8 -*-
"""In-memory extension double honoring the frozen wire protocol (tab.*)."""

from __future__ import annotations

from typing import Any, Mapping

from qwenpaw.browser.control_link.chrome.protocol import EXTENSION_COMMANDS

_CDP_FIXTURES: dict[str, dict[str, Any]] = {
    "Page.reload": {},
    "Page.navigate": {"frameId": "f1"},
    "Page.captureScreenshot": {"data": "aGVsbG8="},
    "Page.getNavigationHistory": {
        "currentIndex": 1,
        "entries": [
            {"id": 10, "url": "about:blank"},
            {"id": 11, "url": "https://a"},
        ],
    },
    "Accessibility.getFullAXTree": {
        "nodes": [
            {
                "nodeId": "1",
                "role": {"value": "button"},
                "name": {"value": "Save"},
                "childIds": [],
                "backendDOMNodeId": 42,
            },
            {
                "nodeId": "2",
                "role": {"value": "button"},
                "name": {"value": "Cancel"},
                "childIds": [],
                "backendDOMNodeId": 43,
            },
        ],
    },
    "DOMSnapshot.captureSnapshot": {"documents": [], "strings": []},
    "DOM.getDocument": {"root": {"nodeId": 1}},
    "DOM.querySelectorAll": {"nodeIds": [2]},
    "DOM.resolveNode": {"object": {"objectId": "obj-1"}},
    "Runtime.callFunctionOn": {"result": {"value": "Save"}},
    "DOM.getBoxModel": {"model": {"content": [0, 0, 10, 0, 10, 10, 0, 10]}},
    "Input.dispatchMouseEvent": {},
    "Input.dispatchKeyEvent": {},
}


class FakeExtensionBridge:
    """Minimal connected extension bridge for core contract coverage."""

    def __init__(self) -> None:
        self._tabs: dict[int, dict[str, Any]] = {}
        self._next_id = 1
        self._connected = True
        self._ready = True
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._event_handlers: dict[str, list[Any]] = {}
        self._ready_observers: list[Any] = []

    def add_event_listener(self, method: str, handler: Any):
        self._event_handlers.setdefault(method, []).append(handler)
        return lambda: self._event_handlers[method].remove(handler)

    def subscribe_ready(self, handler: Any):
        """Mirror the production bridge's post-ack observer contract."""
        self._ready_observers.append(handler)

        def unsubscribe() -> None:
            self._ready_observers.remove(handler)

        return unsubscribe

    def emit_event(self, method: str, params: dict[str, Any]) -> None:
        for handler in list(self._event_handlers.get(method, [])):
            handler(params)

    def is_connected(self) -> bool:
        return self._connected

    async def detach_websocket(
        self,
        websocket: Any | None = None,
        *,
        reason: str = "disconnected",
    ) -> None:
        """Model the bridge liveness transition used by reconnect coverage."""
        del websocket, reason
        self._connected = False

    async def request(  # pylint: disable=too-many-return-statements
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        del timeout
        payload = dict(params or {})
        self.calls.append((method, payload))
        assert method in EXTENSION_COMMANDS, f"unknown command {method}"
        if method == "tab.create":
            protocol_version = payload.get("protocolVersion", 2)
            owner_id = payload.get("ownerId")
            workspace_id = payload.get("workspaceId")
            if protocol_version == 2 and (not owner_id or not workspace_id):
                raise ValueError("ownerId and workspaceId are required")
            tab_id = self._next_id
            self._next_id += 1
            url = str(payload.get("url", "about:blank"))
            self._tabs[tab_id] = {
                "tabId": tab_id,
                "url": url,
                "title": "Fake Extension Page",
                "active": True,
                "createdByQwenPaw": True,
                "ownerId": str(owner_id),
                "workspaceId": str(workspace_id),
            }
            return {"tabId": tab_id, "url": url}
        if method == "tabs.list":
            return list(self._tabs.values())
        if method == "tab.close":
            self._tabs.pop(int(payload["tabId"]), None)
            return {"closed": payload.get("tabId")}
        if method == "tab.activate":
            tab_id = int(payload["tabId"])
            for tab in self._tabs.values():
                tab["active"] = tab["tabId"] == tab_id
            return {"active": tab_id}
        if method == "tab.ensure":
            return {"tabId": payload.get("tabId")}
        if method == "tab.attach":
            return {"attached": payload["tabId"]}
        if method == "cdp.send":
            if payload["method"] == "Page.navigate":
                tab_id = int(payload["tabId"])
                url = str(payload["params"]["url"])
                self._tabs[tab_id]["url"] = url
                self.emit_event(
                    "cdp.event",
                    {
                        "tabId": tab_id,
                        "method": "Page.frameNavigated",
                        "params": {"frame": {"url": url}},
                    },
                )
            return dict(_CDP_FIXTURES.get(str(payload["method"]), {}))
        raise AssertionError(f"fake: unhandled command {method}")
