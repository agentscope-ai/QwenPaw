# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for MCP 2026-07-28 dual-protocol Streamable-HTTP clients."""

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
    _is_https_upgrade,
    _normalize_call_tool_result,
    _same_origin,
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


def _sse(*events: Any, status: int = 200) -> httpx.Response:
    parts = []
    for event in events:
        parts.extend(
            f"data: {line}\n"
            for line in json.dumps(event, indent=2).splitlines()
        )
        parts.append("\n")
    return httpx.Response(
        status,
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


def _stub_stateless(monkeypatch, connect, closed=None):
    class Stub(HttpStatelessClient):
        async def connect(self, timeout=30.0):
            return await connect(self, timeout)

        async def close(self, ignore_errors=True):
            del ignore_errors
            if closed is not None:
                closed.append("modern")
            self._http = None

    monkeypatch.setattr(http_mod, "HttpStatelessClient", Stub)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"supportedVersions": ["2026-07-28"]}, ["2026-07-28"]),
        (
            {"supported": ["2026-07-28", "2025-11-25"]},
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
            "properties": {
                "region": {"type": "string", "x-mcp-header": "Region"},
            },
            "example": {"region": "us", "x-mcp-header": "noise"},
        },
    )
    assert err is None
    assert ok == [(("region",), "Region", "string")]
    rejects = (
        ({"n": {"type": "number", "x-mcp-header": "N"}}, "string/integer"),
        (
            {"r": {"$ref": "#/x", "x-mcp-header": "R", "type": "string"}},
            "reachable",
        ),
        (
            {
                "a": {"type": "string", "x-mcp-header": "X"},
                "b": {"type": "string", "x-mcp-header": "x"},
            },
            "duplicate",
        ),
    )
    for props, part in rejects:
        _, err = _collect_tool_header_bindings({"properties": props})
        assert err and part in err
    allof = {"r": {"type": "string", "x-mcp-header": "R"}}
    _, err = _collect_tool_header_bindings({"allOf": [{"properties": allof}]})
    assert err and "reachable" in err


def test_build_mcp_param_headers_types_and_omit():
    headers = _build_mcp_param_headers(
        [
            (("region",), "Region", "string"),
            (("count",), "Count", "integer"),
            (("ok",), "Ok", "boolean"),
            (("note",), "Note", "string"),
            (("n",), "N", "integer"),
        ],
        {
            "region": "us-west1",
            "count": "42",
            "ok": "true",
            "note": None,
            "n": 42.0,
        },
    )
    assert headers[f"{_MCP_PARAM_HEADER_PREFIX}Region"] == "us-west1"
    assert headers[f"{_MCP_PARAM_HEADER_PREFIX}Count"] == "42"
    assert headers[f"{_MCP_PARAM_HEADER_PREFIX}Ok"] == "true"
    assert headers[f"{_MCP_PARAM_HEADER_PREFIX}N"] == "42"
    assert f"{_MCP_PARAM_HEADER_PREFIX}Note" not in headers
    for value in ("1.5", "--1"):
        with pytest.raises(RuntimeError, match="Cannot encode"):
            _build_mcp_param_headers(
                [(("bad",), "Bad", "integer")],
                {"bad": value},
            )


def test_normalize_call_tool_result_snake_case_aliases():
    out = _normalize_call_tool_result(
        {
            "structured_content": {"ok": True},
            "is_error": True,
            "result_type": "input_required",
        },
    )
    assert out["structuredContent"] == {"ok": True}
    assert out["isError"] is True
    assert out["resultType"] == "input_required"
    assert out["content"] == []


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
    c = _cli(
        HttpAutoClient,
        "auto",
        lambda r: make(_rid(r)),
        headers={"Mcp-Session-Id": "stale"},
    )
    await c.connect()
    try:
        assert c.is_stateful
        assert connected == ["auto"]
        assert not any(
            key.casefold() == _MCP_SESSION_ID_HEADER
            for key in (c._impl.headers or {})
        )
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
        (
            lambda r: _err(
                r,
                -32601,
                "Method not found: server/discover",
                status=404,
            ),
            RuntimeError,
            "server/discover",
        ),
        (
            lambda _r: _sse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32022, "message": "bad"},
                },
                status=400,
            ),
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


async def test_auto_timeout_skips_legacy_fallback(monkeypatch):
    connected: list[str] = []
    _fake_stateful(monkeypatch, connected)

    async def slow(_self, timeout=30.0):
        del timeout
        await asyncio.sleep(0.05)
        raise _LegacyProtocolError("slow legacy")

    _stub_stateless(monkeypatch, slow)
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


async def test_auto_cancel_during_modern_connect_cleans_up(monkeypatch):
    closed: list[str] = []

    async def hang(self, timeout=30.0):
        del timeout
        self._http = object()
        try:
            await asyncio.Event().wait()
        except BaseException:
            closed.append("modern")
            raise

    _stub_stateless(monkeypatch, hang)
    c = HttpAutoClient("auto", "streamable_http", "http://mcp.test/mcp")
    task = asyncio.create_task(c.connect())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == ["modern"]
    assert c._impl is None


async def test_auto_close_waits_for_in_flight_connect(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    closed: list[str] = []

    async def slow(_self, timeout=30.0):
        del _self, timeout
        started.set()
        await release.wait()

    _stub_stateless(monkeypatch, slow, closed=closed)
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


async def test_stateless_discover_list_call_and_headers():
    seen: list[httpx.Request] = []

    def handler(req):
        seen.append(req)
        body = json.loads(req.content)
        method, rid = body["method"], body["id"]
        if method == "server/discover":
            return _disc(rid)
        if method == "tools/list":
            return _ok(
                rid,
                {
                    "tools": [{"name": "echo", "inputSchema": {}}],
                    "nextCursor": "",
                    "next_cursor": "should-not-follow",
                },
            )
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
            if body["params"]["name"] == "need_input":
                payload = {
                    "resultType": "input_required",
                    "inputRequests": {},
                }
            else:
                payload = {
                    "content": [{"type": "text", "text": "hi"}],
                    "isError": False,
                }
            return _ok(rid, payload)
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
        with pytest.raises(RuntimeError, match="MRTR"):
            await c.call_tool("need_input", {})
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
    rpc_ids = [json.loads(req.content)["id"] for req in seen]
    assert rpc_ids == list(range(1, len(rpc_ids) + 1))


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


@pytest.mark.parametrize("second_ok", [True, False])
async def test_call_tool_header_mismatch_retry(second_ok):
    listed = {"n": 0}

    def handler(req):
        body = json.loads(req.content)
        rid = body["id"]
        if body["method"] == "server/discover":
            return _disc(rid)
        if body["method"] == "tools/list":
            listed["n"] += 1
            header = "Region" if listed["n"] == 1 else "Location"
            return _ok(
                rid,
                {
                    "tools": [
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
                    ],
                },
            )
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
        assert [t.name for t in await c.list_tools()] == ["sql"]
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


async def test_stateless_close_keeps_http_until_aclose_succeeds():
    c = _cli(HttpStatelessClient, "modern", lambda r: _disc(_rid(r)))
    await c.connect()
    http = c._http
    n = {"v": 0}

    async def boom():
        n["v"] += 1
        if n["v"] == 1:
            raise RuntimeError("aclose failed")

    c._http.aclose = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="aclose failed"):
        await c.close(ignore_errors=False)
    assert c._http is http
    await c.close(ignore_errors=False)
    assert c._http is None
    await c.connect()

    async def cancelled():
        raise asyncio.CancelledError

    c._http.aclose = cancelled  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await c.close()
    assert c._http is None


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

        async def connect(self):
            return None

        async def close(self, ignore_errors=True):
            del ignore_errors

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


def _modern_rpc(call_result: Any):
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        method, rid = body["method"], body["id"]
        if method == "server/discover":
            return _disc(rid)
        if method == "tools/list":
            return _ok(
                rid,
                {"tools": [{"name": "echo", "inputSchema": {}}]},
            )
        if method == "tools/call":
            return _ok(rid, call_result)
        return _err(rid, -32601, method)

    return handler


@pytest.mark.parametrize(
    "structured",
    (
        {"id": "1"},
        [{"id": "1", "name": "Alice"}],
        "alice",
        42,
        True,
        None,
    ),
)
async def test_call_tool_structured_content_any_json_type(structured):
    payload = {
        "resultType": "complete",
        "content": [],
        "structuredContent": structured,
    }
    c = _cli(HttpStatelessClient, "modern", _modern_rpc(payload))
    await c.connect()
    try:
        result = await c.call_tool("echo", {})
        assert result.structuredContent == structured
    finally:
        await c.close()


async def test_call_tool_rejects_unknown_result_type():
    c = _cli(
        HttpStatelessClient,
        "modern",
        _modern_rpc({"resultType": "streaming", "content": []}),
    )
    await c.connect()
    try:
        with pytest.raises(RuntimeError, match="unsupported resultType"):
            await c.call_tool("echo", {})
    finally:
        await c.close()


def test_origin_helpers_use_scheme_host_and_port():
    http80 = httpx.URL("http://mcp.test/mcp")
    http80_explicit = httpx.URL("http://mcp.test:80/mcp")
    http8000 = httpx.URL("http://mcp.test:8000/mcp")
    http9000 = httpx.URL("http://mcp.test:9000/mcp")
    other = httpx.URL("http://other.test/mcp")
    https443 = httpx.URL("https://mcp.test/mcp")
    https8080 = httpx.URL("https://mcp.test:8080/mcp")
    assert _same_origin(http80, http80_explicit)
    assert not _same_origin(http8000, http9000)
    assert not _same_origin(http80, other)
    assert not _same_origin(http80, https443)
    assert _is_https_upgrade(http80, https443)
    assert not _is_https_upgrade(https443, http80)
    assert not _is_https_upgrade(http8000, https8080)


@pytest.mark.parametrize("kwargs", ({}, {"follow_redirects": True}))
async def test_connect_follows_same_origin_redirect(kwargs):
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.path == "/mcp":
            return httpx.Response(
                307,
                headers={"location": "http://mcp.test/mcp/"},
            )
        return _disc(_rid(req))

    c = _cli(HttpStatelessClient, "modern", handler, **kwargs)
    await c.connect()
    try:
        assert c.is_connected
        assert "http://mcp.test/mcp/" in seen
    finally:
        await c.close()


async def test_connect_blocks_cross_origin_redirect():
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.host)
        if req.url.host == "mcp.test":
            return httpx.Response(
                307,
                headers={"location": "http://other.test/mcp/"},
            )
        return _disc(_rid(req))

    c = _cli(
        HttpStatelessClient,
        "modern",
        handler,
        headers={"X-Auth-Token": "secret", "Api-Key": "k"},
    )
    with pytest.raises(RuntimeError, match="cross-origin redirect"):
        await c.connect()
    assert seen == ["mcp.test"]


async def test_connect_blocks_cross_port_redirect():
    seen: list[int | None] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.port)
        if req.url.port == 8000:
            return httpx.Response(
                307,
                headers={"location": "http://mcp.test:9000/mcp"},
            )
        return _disc(_rid(req))

    c = HttpStatelessClient(
        "modern",
        "streamable_http",
        "http://mcp.test:8000/mcp",
        http_transport=httpx.MockTransport(handler),
        headers={"X-Api-Key": "k"},
    )
    with pytest.raises(RuntimeError, match="cross-origin redirect"):
        await c.connect()
    assert seen == [8000]


async def test_connect_allows_http_to_https_upgrade():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.scheme == "http":
            return httpx.Response(
                307,
                headers={"location": "https://mcp.test/mcp"},
            )
        return _disc(_rid(req))

    c = _cli(
        HttpStatelessClient,
        "modern",
        handler,
        headers={"X-Auth-Token": "secret"},
    )
    await c.connect()
    try:
        assert c.is_connected
        https_reqs = [req for req in seen if req.url.scheme == "https"]
        assert https_reqs
        assert https_reqs[0].headers["X-Auth-Token"] == "secret"
    finally:
        await c.close()


async def test_connect_blocks_https_to_http_downgrade():
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.scheme)
        if req.url.scheme == "https":
            return httpx.Response(
                307,
                headers={"location": "http://mcp.test/mcp"},
            )
        return _disc(_rid(req))

    c = HttpStatelessClient(
        "modern",
        "streamable_http",
        "https://mcp.test/mcp",
        http_transport=httpx.MockTransport(handler),
        headers={"X-Auth-Token": "secret"},
    )
    with pytest.raises(RuntimeError, match="cross-origin redirect"):
        await c.connect()
    assert seen == ["https"]


async def test_connect_blocks_http_to_https_non_default_port():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.scheme == "http":
            return httpx.Response(
                307,
                headers={"location": "https://mcp.test:8080/mcp"},
            )
        return _disc(_rid(req))

    c = HttpStatelessClient(
        "modern",
        "streamable_http",
        "http://mcp.test:8080/mcp",
        http_transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match="cross-origin redirect"):
        await c.connect()


@pytest.mark.parametrize(
    "kwargs",
    ({}, {"follow_redirects": True}, {"follow_redirects": False}),
)
async def test_follow_redirects_kwarg_does_not_duplicate(kwargs):
    c = _cli(
        HttpStatelessClient,
        "modern",
        lambda r: _disc(_rid(r)),
        **kwargs,
    )
    await c.connect()
    await c.close()


async def test_follow_redirects_kwarg_override():
    def handler(req: httpx.Request) -> httpx.Response:
        del req
        return httpx.Response(
            307,
            headers={"location": "http://mcp.test/mcp/"},
        )

    c = _cli(
        HttpStatelessClient,
        "modern",
        handler,
        follow_redirects=False,
    )
    with pytest.raises(RuntimeError, match="non-JSON-RPC"):
        await c.connect()


@pytest.mark.parametrize(
    "kwargs",
    ({}, {"follow_redirects": True}, {"follow_redirects": False}),
)
async def test_auto_follow_redirects_kwarg_does_not_duplicate(
    monkeypatch,
    kwargs,
):
    connected: list[str] = []
    _fake_stateful(monkeypatch, connected)
    c = _cli(
        HttpAutoClient,
        "auto",
        lambda r: httpx.Response(405, text=""),
        **kwargs,
    )
    await c.connect()
    try:
        assert c.is_stateful
        assert "follow_redirects" not in c._impl.client_kwargs
    finally:
        await c.close()


async def test_auto_client_strict_close_retains_impl_on_failure():
    fails = [True]

    class Impl:
        async def close(self, ignore_errors=True):
            del ignore_errors
            if fails[0]:
                fails[0] = False
                raise RuntimeError("close failed")

    c = HttpAutoClient("auto", "streamable_http", "http://mcp.test/mcp")
    c._impl = Impl()
    c.is_connected = True
    with pytest.raises(RuntimeError, match="close failed"):
        await c.close(ignore_errors=False)
    assert c._impl is not None
    await c.close(ignore_errors=False)
    assert c._impl is None


async def test_auto_client_close_propagates_cancellation():
    class Impl:
        async def close(self, ignore_errors=True):
            del ignore_errors
            raise asyncio.CancelledError

    c = HttpAutoClient("auto", "streamable_http", "http://mcp.test/mcp")
    c._impl = Impl()
    c.is_connected = True
    with pytest.raises(asyncio.CancelledError):
        await c.close(ignore_errors=True)
    assert c._impl is not None
