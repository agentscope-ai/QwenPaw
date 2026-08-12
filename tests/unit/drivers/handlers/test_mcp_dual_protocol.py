# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for MCP 2026-07-28 dual-protocol Streamable-HTTP clients.

Intent
------
Cover modern ``HttpStatelessClient`` wire behavior and ``HttpAutoClient``
modern-first fallback without a live MCP server.  Keep cases focused on
protocol decisions that would regress dual-era routing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

import httpx
import pytest

import qwenpaw.drivers.handlers.mcp_stateful_client as mod
import qwenpaw.drivers.handlers.mcp_streamable_http as http_mod
from qwenpaw.drivers.handlers.mcp_stateful_client import HttpStatefulClient
from qwenpaw.drivers.handlers.mcp_streamable_http import (
    HttpAutoClient,
    HttpStatelessClient,
    _LIST_TOOLS_MAX_PAGES,
    _MCP_METHOD_HEADER,
    _MCP_NAME_HEADER,
    _MCP_PARAM_HEADER_PREFIX,
    _MCP_PROTOCOL_VERSION_HEADER,
    _MODERN_PROTOCOL_VERSION,
    _build_mcp_param_headers,
    _collect_tool_header_bindings,
    _encode_mcp_header_value,
    _supported_versions_from_payload,
)


def _ok(rid: Any, result: Any) -> httpx.Response:
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": rid, "result": result},
        headers={"content-type": "application/json"},
    )


def _err(
    rid: Any,
    code: int,
    msg: str,
    data: Any = None,
    *,
    status: int = 200,
) -> httpx.Response:
    err: dict[str, Any] = {"code": code, "message": msg}
    if data is not None:
        err["data"] = data
    return httpx.Response(
        status,
        json={"jsonrpc": "2.0", "id": rid, "error": err},
        headers={"content-type": "application/json"},
    )


def _disc(rid: Any) -> httpx.Response:
    return _ok(rid, {"supportedVersions": [_MODERN_PROTOCOL_VERSION]})


def _rid(req: httpx.Request) -> Any:
    return json.loads(req.content or b"{}").get("id", 1)


def _cli(cls: type, name: str, handler: Callable, **kw: Any) -> Any:
    """Build a client wired to ``httpx.MockTransport(handler)``."""
    return cls(
        name,
        "streamable_http",
        "http://mcp.test/mcp",
        http_transport=httpx.MockTransport(handler),
        **kw,
    )


def _sse(*events: Any) -> httpx.Response:
    parts = []
    for event in events:
        parts.extend(
            f"data: {line}\n"
            for line in json.dumps(event, indent=2).splitlines()
        )
        parts.append("\n")
    return httpx.Response(
        200,
        content="".join(parts).encode(),
        headers={"content-type": "text/event-stream"},
    )


def _fake_stateful(
    monkeypatch: pytest.MonkeyPatch,
    connected: list[str],
) -> None:
    """Replace ``HttpStatefulClient`` with a no-I/O fake for fallback tests."""

    class Fake(HttpStatefulClient):
        async def connect(self, timeout=30.0):
            del timeout
            connected.append(self.name)
            self.is_connected = True

        async def close(self, ignore_errors=True):
            del ignore_errors
            self.is_connected = False

        async def list_tools(self):
            return ["legacy-tool"]

    monkeypatch.setattr(mod, "HttpStatefulClient", Fake)


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"supportedVersions": ["2026-07-28"]}, ["2026-07-28"]),
        (
            {"protocolVersions": ["2026-07-28", "2025-11-25"]},
            ["2026-07-28", "2025-11-25"],
        ),
        ({"capabilities": {}}, None),
    ],
)
def test_supported_versions_from_payload(payload, expected):
    assert _supported_versions_from_payload(payload) == expected


# ---------------------------------------------------------------------------
# AutoClient fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "make",
    [
        lambda r: httpx.Response(404, text=""),
        lambda r: _ok(r, {"supportedVersions": ["2025-11-25"]}),
        lambda r: _err(r, -32601, "Method not found: server/discover"),
        lambda r: _err(r, -32022, "bad", {"supported": ["2025-11-25"]}),
    ],
)
async def test_auto_falls_back_once(monkeypatch, make):
    connected: list[str] = []
    _fake_stateful(monkeypatch, connected)
    c = _cli(HttpAutoClient, "auto", lambda r: make(_rid(r)))
    await c.connect()
    try:
        assert c.is_stateful
        assert connected == ["auto"]
        assert await c.list_tools() == ["legacy-tool"]
    finally:
        await c.close()
    assert c._impl is None
    assert not c.is_connected


@pytest.mark.parametrize(
    ("make", "exc_type", "match"),
    [
        (lambda r: httpx.Response(401, text="u"), RuntimeError, "OAuth"),
        (
            lambda r: (_ for _ in ()).throw(
                httpx.ConnectError(
                    "x",
                    request=httpx.Request("POST", "http://x"),
                ),
            ),
            httpx.ConnectError,
            None,
        ),
        (
            lambda r: (_ for _ in ()).throw(
                httpx.ReadTimeout(
                    "discover timed out",
                    request=httpx.Request("POST", "http://x"),
                ),
            ),
            httpx.ReadTimeout,
            None,
        ),
        (
            lambda r: _err(r, -32021, "missing cap", status=400),
            RuntimeError,
            "server/discover",
        ),
        (
            lambda r: _err(r, -32022, "bad", {"supported": ["2099-01-01"]}),
            RuntimeError,
            "incompatible",
        ),
    ],
)
async def test_auto_does_not_fallback(monkeypatch, make, exc_type, match):
    connected: list[str] = []
    _fake_stateful(monkeypatch, connected)
    c = _cli(HttpAutoClient, "auto", lambda r: make(_rid(r)))
    with pytest.raises(exc_type, match=match):
        await c.connect()
    assert not connected
    assert c._impl is None


async def test_auto_cancel_during_modern_connect_cleans_up(monkeypatch):
    closed: list[str] = []

    class HangStateless(HttpStatelessClient):
        async def connect(self, timeout=30.0):
            del timeout
            self._http = object()
            try:
                await asyncio.Event().wait()
            except BaseException:
                closed.append("modern")
                self._http = None
                raise

    monkeypatch.setattr(http_mod, "HttpStatelessClient", HangStateless)
    c = HttpAutoClient("auto", "streamable_http", "http://mcp.test/mcp")
    task = asyncio.create_task(c.connect(timeout=30.0))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == ["modern"]
    assert c._impl is None
    assert not c.is_connected


# ---------------------------------------------------------------------------
# Stateless wire path
# ---------------------------------------------------------------------------


async def test_stateless_discover_list_call_and_headers():
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        body = json.loads(req.content)
        method, rid = body["method"], body["id"]
        if method == "server/discover":
            return _disc(rid)
        if method == "tools/list":
            return _ok(rid, {"tools": [{"name": "echo", "inputSchema": {}}]})
        if method == "tools/call":
            name = body["params"]["name"]
            if name == "alias":
                return _ok(
                    rid,
                    {"structured_content": {"ok": True}, "is_error": True},
                )
            if name == "ok":
                return _sse(
                    {"jsonrpc": "2.0", "method": "notifications/progress"},
                    {
                        "jsonrpc": "2.0",
                        "id": rid + 99,
                        "result": {
                            "content": [{"type": "text", "text": "wrong"}],
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "result": {
                            "content": [{"type": "text", "text": "matched"}],
                        },
                    },
                )
            return _ok(
                rid,
                {
                    "content": [{"type": "text", "text": "hi"}],
                    "isError": False,
                },
            )
        return _err(rid, -32601, method)

    c = _cli(HttpStatelessClient, "modern", handler)
    await c.connect()
    try:
        assert [t.name for t in await c.list_tools()] == ["echo"]
        result = await c.call_tool("echo", {"text": "hi"})
        assert result.content[0].text == "hi"
        alias = await c.call_tool("alias", {})
        assert bool(
            getattr(alias, "is_error", False)
            or getattr(alias, "isError", False),
        )
        structured = getattr(alias, "structured_content", None) or getattr(
            alias,
            "structuredContent",
            None,
        )
        assert structured == {"ok": True}
        assert (await c.call_tool("ok", {})).content[0].text == "matched"
        await c.call_tool("café", {})
    finally:
        await c.close()

    discover, tools_list, echo_call = seen[:3]
    for req, method in (
        (discover, "server/discover"),
        (tools_list, "tools/list"),
        (echo_call, "tools/call"),
    ):
        assert req.headers[_MCP_PROTOCOL_VERSION_HEADER] == (
            _MODERN_PROTOCOL_VERSION
        )
        assert req.headers[_MCP_METHOD_HEADER] == method
    assert _MCP_NAME_HEADER not in discover.headers
    assert echo_call.headers[_MCP_NAME_HEADER] == "echo"
    cafe_req = next(
        r
        for r in seen
        if json.loads(r.content).get("params", {}).get("name") == "café"
    )
    assert cafe_req.headers[_MCP_NAME_HEADER].startswith("=?base64?")
    assert _encode_mcp_header_value("café").startswith("=?base64?")


async def test_stateless_rejects_non_jsonrpc_and_id_mismatch():
    def bad_result(req):
        body = json.loads(req.content)
        rid = body["id"]
        if body["method"] == "server/discover":
            return _disc(rid)
        return httpx.Response(
            200,
            json={"id": rid, "result": {"tools": []}},
            headers={"content-type": "application/json"},
        )

    c = _cli(HttpStatelessClient, "modern", bad_result)
    await c.connect()
    try:
        with pytest.raises(RuntimeError, match="non-JSON-RPC"):
            await c.list_tools()
    finally:
        await c.close()

    def wrong_id(req):
        body = json.loads(req.content)
        if body["method"] == "server/discover":
            return _disc(body["id"])
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"] + 1,
                "result": {"tools": []},
            },
            headers={"content-type": "application/json"},
        )

    c = _cli(HttpStatelessClient, "modern", wrong_id)
    await c.connect()
    try:
        with pytest.raises(RuntimeError, match="id mismatch"):
            await c.list_tools()
    finally:
        await c.close()


async def test_auto_stays_modern_and_driver_routing(monkeypatch):
    def modern_handler(req):
        body = json.loads(req.content)
        if body["method"] == "server/discover":
            return _disc(body["id"])
        if body["method"] == "tools/list":
            return _ok(
                body["id"],
                {"tools": [{"name": "modern", "inputSchema": {}}]},
            )
        return _err(body["id"], -32601, "x")

    c = _cli(HttpAutoClient, "auto", modern_handler)
    await c.connect()
    try:
        assert not c.is_stateful
        assert isinstance(c._impl, HttpStatelessClient)
        assert (await c.list_tools())[0].name == "modern"
    finally:
        await c.close()
    assert c._impl is None

    from qwenpaw.drivers.contracts import DriverCard
    from qwenpaw.drivers.credentials.providers import NoneProvider
    from qwenpaw.drivers.handlers import mcp as mcp_mod

    built: list[str] = []

    class Track:
        def __init__(self, **kw):
            del kw
            built.append(self.kind)
            self.is_connected = False

        async def connect(self):
            self.is_connected = True

        async def close(self, ignore_errors=True):
            del ignore_errors
            self.is_connected = False

    class Auto(Track):
        kind = "auto"

    class Stateful(Track):
        kind = "stateful"

    monkeypatch.setattr(mcp_mod, "HttpAutoClient", Auto)
    monkeypatch.setattr(mcp_mod, "HttpStatefulClient", Stateful)
    provider = NoneProvider()
    for transport in ("streamable_http", "sse"):
        card = DriverCard(
            name=f"mcp-{transport.replace('_', '-')}",
            protocol="mcp",
            endpoint={"transport": transport, "url": "http://mcp.test/mcp"},
        )
        handler = mcp_mod.MCPDriverHandler(card, provider)
        await handler._setup()
        await handler._teardown()
    assert built == ["auto", "stateful"]


# ---------------------------------------------------------------------------
# x-mcp-header
# ---------------------------------------------------------------------------


def test_collect_tool_header_bindings_core_rules():
    ok, err = _collect_tool_header_bindings(
        {
            "type": "object",
            "properties": {
                "region": {"type": "string", "x-mcp-header": "Region"},
            },
            "example": {"region": "us", "x-mcp-header": "noise"},
        },
    )
    assert err is None
    assert ok == [(("region",), "Region", "string")]

    _, err = _collect_tool_header_bindings(
        {
            "type": "object",
            "properties": {
                "n": {"type": "number", "x-mcp-header": "N"},
            },
        },
    )
    assert err and "string/integer/boolean" in err

    _, err = _collect_tool_header_bindings(
        {
            "type": "object",
            "properties": {
                "r": {"type": ["string", "null"], "x-mcp-header": "R"},
            },
        },
    )
    assert err and "string/integer/boolean" in err

    _, err = _collect_tool_header_bindings(
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string", "x-mcp-header": "Bad"},
                },
            },
        },
    )
    assert err and "statically reachable" in err


def test_build_mcp_param_headers_types_and_omit():
    headers = _build_mcp_param_headers(
        [
            (("region",), "Region", "string"),
            (("count",), "Count", "integer"),
            (("ok",), "Ok", "boolean"),
            (("note",), "Note", "string"),
        ],
        {"region": "us-west1", "count": 42, "ok": True, "note": None},
    )
    assert headers[f"{_MCP_PARAM_HEADER_PREFIX}Region"] == "us-west1"
    assert headers[f"{_MCP_PARAM_HEADER_PREFIX}Count"] == "42"
    assert headers[f"{_MCP_PARAM_HEADER_PREFIX}Ok"] == "true"
    assert f"{_MCP_PARAM_HEADER_PREFIX}Note" not in headers


async def test_list_tools_applies_x_mcp_header_and_pagination_cap(caplog):
    pages = {
        None: {
            "tools": [
                {
                    "name": "sql",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "region": {
                                "type": "string",
                                "x-mcp-header": "Region",
                            },
                        },
                    },
                },
                {
                    "name": "bad_number",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "n": {"type": "number", "x-mcp-header": "N"},
                        },
                    },
                },
            ],
            "nextCursor": "page-2",
        },
        "page-2": {"tools": []},
    }

    def handler(req):
        body = json.loads(req.content)
        rid = body["id"]
        if body["method"] == "server/discover":
            return _disc(rid)
        if body["method"] == "tools/list":
            cursor = body.get("params", {}).get("cursor")
            return _ok(rid, pages[cursor])
        if body["method"] == "tools/call":
            return _ok(
                rid,
                {
                    "content": [{"type": "text", "text": "ok"}],
                    "isError": False,
                },
            )
        return _err(rid, -32601, body["method"])

    c = _cli(HttpStatelessClient, "modern", handler)
    await c.connect()
    try:
        with caplog.at_level("WARNING"):
            tools = await c.list_tools()
        assert [t.name for t in tools] == ["sql"]
        assert "bad_number" in caplog.text

        captured: list[dict[str, str]] = []
        orig = c._http.stream

        def wrapped(method, url, **kwargs):
            captured.append(kwargs.get("headers") or {})
            return orig(method, url, **kwargs)

        c._http.stream = wrapped  # type: ignore[method-assign]
        await c.call_tool("sql", {"region": "us-west1"})
        assert captured[-1][f"{_MCP_PARAM_HEADER_PREFIX}Region"] == "us-west1"
    finally:
        await c.close()


async def test_list_tools_max_pages_exceeded():
    n = {"v": 0}

    def handler(req):
        body = json.loads(req.content)
        rid = body["id"]
        if body["method"] == "server/discover":
            return _disc(rid)
        if body["method"] == "tools/list":
            n["v"] += 1
            return _ok(
                rid,
                {
                    "tools": [{"name": f"t{n['v']}", "inputSchema": {}}],
                    "nextCursor": f"p{n['v']}",
                },
            )
        return _err(rid, -32601, body["method"])

    c = _cli(HttpStatelessClient, "modern", handler)
    await c.connect()
    try:
        with pytest.raises(
            RuntimeError,
            match=rf"tools/list pagination exceeded {_LIST_TOOLS_MAX_PAGES}",
        ):
            await c.list_tools()
        assert n["v"] == _LIST_TOOLS_MAX_PAGES
    finally:
        await c.close()


# ---------------------------------------------------------------------------
# Constructor guards
# ---------------------------------------------------------------------------


def test_streamable_http_ctor_type_guards():
    with pytest.raises(TypeError, match="name must be str"):
        HttpAutoClient(123, "streamable_http", "http://x")
    with pytest.raises(TypeError, match="url must be str"):
        HttpAutoClient("auto", "streamable_http", 123)
    with pytest.raises(ValueError, match="streamable_http"):
        HttpStatelessClient("x", "sse", "http://x")
