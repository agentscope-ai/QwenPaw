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
    _CLIENT_CAPABILITIES_META_KEY,
    _CLIENT_INFO_META_KEY,
    _JSONRPC_HEADER_MISMATCH,
    _LIST_TOOLS_MAX_PAGES,
    _MCP_METHOD_HEADER,
    _MCP_NAME_HEADER,
    _MCP_PARAM_HEADER_PREFIX,
    _MCP_PROTOCOL_VERSION_HEADER,
    _MCP_SESSION_ID_HEADER,
    _MODERN_PROTOCOL_VERSION,
    _PROTOCOL_VERSION_META_KEY,
    _JsonRpcError,
    _LegacyProtocolError,
    _build_mcp_param_headers,
    _collect_tool_header_bindings,
    _normalize_call_tool_result,
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


def _transport_error(exc_type: type[httpx.TransportError]):
    req = httpx.Request("POST", "http://x")

    def make(_rid: Any) -> httpx.Response:
        raise exc_type("x", request=req)

    return make


def _fake_stateful(
    monkeypatch: pytest.MonkeyPatch,
    connected: list[str],
) -> None:
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


def _patch_slow_stateless(
    monkeypatch: pytest.MonkeyPatch,
    started: asyncio.Event,
    release: asyncio.Event,
    *,
    connects: list[str] | None = None,
    closed: list[str] | None = None,
) -> None:
    class Slow(HttpStatelessClient):
        async def connect(self, timeout=30.0):
            del timeout
            if connects is not None:
                connects.append("modern")
            started.set()
            await release.wait()
            self.is_connected = True
            self._http = object()

        async def close(self, ignore_errors=True):
            del ignore_errors
            if closed is not None:
                closed.append("modern")
            self.is_connected = False
            self._http = None

    monkeypatch.setattr(http_mod, "HttpStatelessClient", Slow)


# ---------------------------------------------------------------------------
# Version parsing / x-mcp-header helpers
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


def test_build_mcp_param_headers_types_and_omit():
    headers = _build_mcp_param_headers(
        [
            (("region",), "Region", "string"),
            (("count",), "Count", "integer"),
            (("note",), "Note", "string"),
        ],
        {"region": "us-west1", "count": 42, "note": None},
    )
    assert headers[f"{_MCP_PARAM_HEADER_PREFIX}Region"] == "us-west1"
    assert headers[f"{_MCP_PARAM_HEADER_PREFIX}Count"] == "42"
    assert f"{_MCP_PARAM_HEADER_PREFIX}Note" not in headers


def test_normalize_call_tool_result_snake_case_aliases():
    out = _normalize_call_tool_result(
        {"structured_content": {"ok": True}, "is_error": True},
    )
    assert out["structuredContent"] == {"ok": True}
    assert out["isError"] is True
    assert out["content"] == []


# ---------------------------------------------------------------------------
# HttpAutoClient fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "make",
    [
        lambda r: httpx.Response(400, text=""),
        lambda r: httpx.Response(404, text=""),
        lambda r: httpx.Response(405, text=""),
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


@pytest.mark.parametrize(
    ("make", "exc_type", "match"),
    [
        (lambda r: httpx.Response(401, text="u"), RuntimeError, "OAuth"),
        (_transport_error(httpx.ReadTimeout), httpx.ReadTimeout, None),
        (
            lambda r: _err(r, -32020, "header mismatch", status=400),
            RuntimeError,
            "server/discover",
        ),
        (lambda r: _err(r, -32022, "bad", {}), RuntimeError, "incompatible"),
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


async def test_auto_timeout_skips_legacy_fallback(monkeypatch):
    connected: list[str] = []
    _fake_stateful(monkeypatch, connected)

    class SlowLegacy(HttpStatelessClient):
        async def connect(self, timeout=30.0):
            await asyncio.sleep(0.05)
            raise _LegacyProtocolError("slow legacy")

        async def close(self, ignore_errors=True):
            del ignore_errors
            self._http = None

    monkeypatch.setattr(http_mod, "HttpStatelessClient", SlowLegacy)
    c = HttpAutoClient("auto", "streamable_http", "http://mcp.test/mcp")
    with pytest.raises(TimeoutError, match="before legacy fallback"):
        await c.connect(timeout=0.01)
    assert not connected
    assert c._impl is None


async def test_auto_stays_modern():
    def handler(req):
        body = json.loads(req.content)
        if body["method"] == "server/discover":
            return _disc(body["id"])
        if body["method"] == "tools/list":
            return _ok(
                body["id"],
                {"tools": [{"name": "modern", "inputSchema": {}}]},
            )
        return _err(body["id"], -32601, "x")

    c = _cli(HttpAutoClient, "auto", handler)
    await c.connect()
    try:
        assert not c.is_stateful
        assert isinstance(c._impl, HttpStatelessClient)
        assert (await c.list_tools())[0].name == "modern"
    finally:
        await c.close()
    assert c._impl is None


# ---------------------------------------------------------------------------
# HttpAutoClient lifecycle
# ---------------------------------------------------------------------------


async def test_auto_cancel_during_modern_connect_cleans_up(monkeypatch):
    closed: list[str] = []

    class Hang(HttpStatelessClient):
        async def connect(self, timeout=30.0):
            del timeout
            self._http = object()
            try:
                await asyncio.Event().wait()
            except BaseException:
                closed.append("modern")
                self._http = None
                raise

    monkeypatch.setattr(http_mod, "HttpStatelessClient", Hang)
    c = HttpAutoClient("auto", "streamable_http", "http://mcp.test/mcp")
    task = asyncio.create_task(c.connect())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == ["modern"]
    assert c._impl is None


async def test_auto_serializes_concurrent_connect(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    connects: list[str] = []
    _patch_slow_stateless(monkeypatch, started, release, connects=connects)
    c = HttpAutoClient("auto", "streamable_http", "http://mcp.test/mcp")
    first = asyncio.create_task(c.connect())
    await started.wait()
    second = asyncio.create_task(c.connect())
    await asyncio.sleep(0)
    assert connects == ["modern"]
    release.set()
    await first
    with pytest.raises(RuntimeError, match="already connected"):
        await second
    await c.close()
    assert c._impl is None


async def test_auto_close_waits_for_in_flight_connect(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    closed: list[str] = []
    _patch_slow_stateless(monkeypatch, started, release, closed=closed)
    c = HttpAutoClient("auto", "streamable_http", "http://mcp.test/mcp")
    first = asyncio.create_task(c.connect())
    await started.wait()
    closer = asyncio.create_task(c.close())
    await asyncio.sleep(0)
    assert not closer.done()
    release.set()
    await first
    await closer
    assert closed == ["modern"]
    assert c._impl is None


async def test_close_keeps_handle_until_cleanup_succeeds():
    class BoomHttp:
        def __init__(self):
            self.n = 0

        async def aclose(self):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("boom")

    http = BoomHttp()
    stateless = HttpStatelessClient(
        "modern",
        "streamable_http",
        "http://mcp.test/mcp",
    )
    stateless._http = http
    stateless.is_connected = True
    with pytest.raises(RuntimeError, match="boom"):
        await stateless.close(ignore_errors=False)
    assert stateless._http is http
    await stateless.close(ignore_errors=False)
    assert stateless._http is None

    class BoomImpl:
        def __init__(self):
            self.n = 0

        async def close(self, ignore_errors=True):
            del ignore_errors
            self.n += 1
            if self.n == 1:
                raise asyncio.CancelledError

    impl = BoomImpl()
    auto = HttpAutoClient("auto", "streamable_http", "http://mcp.test/mcp")
    auto._impl = impl
    auto.is_connected = True
    with pytest.raises(asyncio.CancelledError):
        await auto.close(ignore_errors=False)
    assert auto._impl is impl
    await auto.close(ignore_errors=False)
    assert auto._impl is None


# ---------------------------------------------------------------------------
# HttpStatelessClient wire
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
            if body["params"]["name"] == "ok":
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
            if body["params"]["name"] == "empty":
                return _sse(
                    {"jsonrpc": "2.0", "method": "notifications/progress"},
                )
            return _ok(
                rid,
                {
                    "content": [{"type": "text", "text": "hi"}],
                    "isError": False,
                },
            )
        return _err(rid, -32601, method)

    c = _cli(
        HttpStatelessClient,
        "modern",
        handler,
        headers={"Mcp-Session-Id": "legacy-session"},
    )
    await c.connect()
    try:
        assert c.headers["Mcp-Session-Id"] == "legacy-session"
        assert [t.name for t in await c.list_tools()] == ["echo"]
        assert (await c.call_tool("echo", {})).content[0].text == "hi"
        assert (await c.call_tool("ok", {})).content[0].text == "matched"
        with pytest.raises(RuntimeError, match="Empty SSE"):
            await c.call_tool("empty", {})
    finally:
        await c.close()

    discover, _tools_list, echo_call = seen[:3]
    meta = json.loads(discover.content)["params"]["_meta"]
    assert meta[_PROTOCOL_VERSION_META_KEY] == _MODERN_PROTOCOL_VERSION
    assert meta[_CLIENT_CAPABILITIES_META_KEY] == {}
    assert meta[_CLIENT_INFO_META_KEY]["name"] == "qwenpaw"
    assert discover.headers[_MCP_METHOD_HEADER] == "server/discover"
    assert _MCP_SESSION_ID_HEADER not in {
        key.casefold() for key in discover.headers
    }
    assert echo_call.headers[_MCP_PROTOCOL_VERSION_HEADER] == (
        _MODERN_PROTOCOL_VERSION
    )
    assert echo_call.headers[_MCP_NAME_HEADER] == "echo"


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"id": 1, "result": {"tools": []}}, "non-JSON-RPC"),
        (
            {"jsonrpc": "2.0", "id": 99, "result": {"tools": []}},
            "id mismatch",
        ),
    ],
)
async def test_stateless_rejects_malformed_jsonrpc(payload, match):
    def handler(req):
        body = json.loads(req.content)
        if body["method"] == "server/discover":
            return _disc(body["id"])
        out = dict(payload)
        out["id"] = body["id"] + 1 if match == "id mismatch" else body["id"]
        return httpx.Response(
            200,
            json=out,
            headers={"content-type": "application/json"},
        )

    c = _cli(HttpStatelessClient, "modern", handler)
    await c.connect()
    try:
        with pytest.raises(RuntimeError, match=match):
            await c.list_tools()
    finally:
        await c.close()


async def test_stateless_post_discover_401_is_oauth():
    def handler(req):
        body = json.loads(req.content)
        if body["method"] == "server/discover":
            return _disc(body["id"])
        return httpx.Response(401, text="u")

    c = _cli(HttpStatelessClient, "modern", handler)
    await c.connect()
    try:
        with pytest.raises(RuntimeError, match="OAuth"):
            await c.list_tools()
    finally:
        await c.close()


@pytest.mark.parametrize("second_ok", [True, False])
async def test_call_tool_header_mismatch_retry(second_ok, caplog):
    listed = {"n": 0}

    def handler(req):
        body = json.loads(req.content)
        rid = body["id"]
        if body["method"] == "server/discover":
            return _disc(rid)
        if body["method"] == "tools/list":
            listed["n"] += 1
            header = "Region" if listed["n"] == 1 else "Location"
            tools = [
                {
                    "name": "sql",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "region": {
                                "type": "string",
                                "x-mcp-header": header,
                            },
                        },
                    },
                },
            ]
            if listed["n"] == 1:
                tools.append(
                    {
                        "name": "bad_number",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "n": {
                                    "type": "number",
                                    "x-mcp-header": "N",
                                },
                            },
                        },
                    },
                )
            return _ok(rid, {"tools": tools})
        if body["method"] == "tools/call":
            if listed["n"] == 1 or not second_ok:
                return _err(rid, -32020, "header mismatch", status=400)
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
        assert "from 'modern'" in caplog.text
        if second_ok:
            captured: list[dict[str, str]] = []
            orig = c._http.stream

            def wrapped(method, url, **kwargs):
                captured.append(kwargs.get("headers") or {})
                return orig(method, url, **kwargs)

            c._http.stream = wrapped  # type: ignore[method-assign]
            await c.call_tool("sql", {"region": "us-west1"})
            assert captured[-1][f"{_MCP_PARAM_HEADER_PREFIX}Location"] == (
                "us-west1"
            )
        else:
            with pytest.raises(_JsonRpcError) as caught:
                await c.call_tool("sql", {"region": "us"})
            assert caught.value.code == _JSONRPC_HEADER_MISMATCH
        assert listed["n"] == 2
    finally:
        await c.close()


async def test_list_tools_max_pages_exceeded():
    n = {"v": 0}

    def handler(req):
        body = json.loads(req.content)
        rid = body["id"]
        if body["method"] == "server/discover":
            return _disc(rid)
        n["v"] += 1
        return _ok(
            rid,
            {
                "tools": [{"name": f"t{n['v']}", "inputSchema": {}}],
                "nextCursor": f"p{n['v']}",
            },
        )

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
# Driver routing / constructor
# ---------------------------------------------------------------------------


async def test_driver_routes_streamable_http_to_auto_and_sse_to_stateful(
    monkeypatch,
):
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


def test_streamable_http_ctor_type_guards():
    with pytest.raises(TypeError, match="name must be str"):
        HttpAutoClient(123, "streamable_http", "http://x")
    with pytest.raises(ValueError, match="streamable_http"):
        HttpStatelessClient("x", "sse", "http://x")
