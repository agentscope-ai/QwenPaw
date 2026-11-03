# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression coverage for CLI access to managed runtime APIs."""

import asyncio
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import httpx
import pytest
from click.testing import CliRunner
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.agents.tools import agent_management
from qwenpaw.agents.memory.proactive.proactive_responder import (
    send_proactive_message_via_http,
)
from qwenpaw.app.auth import RuntimeBoundaryMiddleware
from qwenpaw.cli import http as cli_http
from qwenpaw.cli import doctor_cmd, plugin_commands, update_cmd
from qwenpaw.utils.runtime_api import async_api_client
from qwenpaw.cli.main import cli

_RUNTIME_URL = "http://127.0.0.1:9001"
_TOKEN_HEADER = "X-QwenPaw-Runtime-Token"


@pytest.fixture(autouse=True)
def managed_runtime(monkeypatch):
    """Give each test an isolated managed runtime environment."""
    monkeypatch.setenv("QWENPAW_RUNTIME_ID", "runtime-a")
    monkeypatch.setenv("QWENPAW_RUNTIME_INTERNAL_TOKEN", "secret-a")
    monkeypatch.setenv("QWENPAW_RUNTIME_API_URL", _RUNTIME_URL)
    monkeypatch.setattr(
        "qwenpaw.cli.main.read_last_api",
        lambda: ("127.0.0.1", 9002),
    )
    monkeypatch.setattr(
        agent_management,
        "read_last_api",
        lambda: ("127.0.0.1", 9002),
    )


def _boundary_transport(boundary: TestClient) -> httpx.MockTransport:
    """Exercise the real app through TestClient's public HTTP interface."""

    def respond(request):
        response = boundary.request(
            request.method,
            str(request.url),
            headers=request.headers.multi_items(),
            content=request.read(),
        )
        return httpx.Response(
            response.status_code,
            headers=response.headers.multi_items(),
            content=response.content,
        )

    return httpx.MockTransport(respond)


@pytest.mark.parametrize("managed", [True, False])
def test_agents_list_passes_real_boundary(monkeypatch, managed):
    """Exercise Click, the HTTP client, and the real boundary middleware."""
    app = FastAPI()
    app.add_middleware(RuntimeBoundaryMiddleware)
    seen = []

    @app.get("/api/agents")
    async def agents(request: Request):
        seen.append(request.url.port)
        return {"agents": [{"id": f"runtime-{request.url.port}"}]}

    if not managed:
        monkeypatch.delenv("QWENPAW_RUNTIME_INTERNAL_TOKEN")
        monkeypatch.delenv("QWENPAW_RUNTIME_ID")
        monkeypatch.delenv("QWENPAW_RUNTIME_API_URL")
    with TestClient(app) as boundary:
        monkeypatch.setattr(
            httpx,
            "Client",
            partial(httpx.Client, transport=_boundary_transport(boundary)),
        )
        result = CliRunner().invoke(cli, ["agents", "list"])
    expected_port = 9001 if managed else 9002
    assert result.exit_code == 0, result.exception
    assert f"runtime-{expected_port}" in result.output
    assert seen == [expected_port]


@pytest.mark.parametrize(
    "factory",
    [cli_http.client, agent_management.create_agent_api_client],
)
@pytest.mark.parametrize(
    "target,expected",
    [
        (_RUNTIME_URL, "secret-a"),
        (f"{_RUNTIME_URL}/api/", "secret-a"),
        ("http://127.0.0.1:9002", None),
        ("http://localhost:9001", None),
        ("https://127.0.0.1:9001", None),
        ("http://example.com:9001", None),
        ("http://127.0.0.1.example.com:9001", None),
    ],
)
def test_token_is_scoped_to_runtime_origin(
    monkeypatch,
    factory,
    target,
    expected,
):
    seen = []

    def respond(request):
        seen.append(request.headers.get(_TOKEN_HEADER))
        return httpx.Response(200)

    monkeypatch.setattr(
        httpx,
        "Client",
        partial(httpx.Client, transport=httpx.MockTransport(respond)),
    )
    with factory(target) as client:
        client.get("/agents")
    assert seen == [expected]


@pytest.mark.parametrize(
    "factory",
    [cli_http.client, agent_management.create_agent_api_client],
)
def test_token_does_not_follow_redirects_or_absolute_urls(
    monkeypatch,
    factory,
):
    seen = []
    external = "http://127.0.0.1:9002/api/agents"

    def respond(request):
        seen.append(request.headers.get(_TOKEN_HEADER))
        if request.url.port == 9001:
            return httpx.Response(302, headers={"Location": external})
        return httpx.Response(200)

    monkeypatch.setattr(
        httpx,
        "Client",
        partial(httpx.Client, transport=httpx.MockTransport(respond)),
    )
    with factory(_RUNTIME_URL) as client:
        client.get("/agents", follow_redirects=True)
        client.get(external)
    assert seen == ["secret-a", None, None]


@pytest.mark.parametrize(
    "missing",
    [
        "QWENPAW_RUNTIME_ID",
        "QWENPAW_RUNTIME_API_URL",
        "QWENPAW_RUNTIME_INTERNAL_TOKEN",
    ],
)
def test_incomplete_runtime_metadata_keeps_app_behavior(monkeypatch, missing):
    monkeypatch.delenv(missing)
    assert agent_management.resolve_agent_api_base_url() == (
        "http://127.0.0.1:9002"
    )
    seen = []

    def respond(request):
        seen.append(request.headers.get(_TOKEN_HEADER))
        return httpx.Response(200)

    monkeypatch.setattr(
        httpx,
        "Client",
        partial(httpx.Client, transport=httpx.MockTransport(respond)),
    )
    with cli_http.client(_RUNTIME_URL) as client:
        client.get("/agents")
    assert seen == [None]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--port", "9002", "agents", "list"],
        ["agents", "list", "--base-url", "http://example.com"],
    ],
)
def test_explicit_cli_endpoint_never_receives_token(monkeypatch, arguments):
    seen = []

    def respond(request):
        seen.append(request.headers.get(_TOKEN_HEADER))
        return httpx.Response(200, json={"agents": []})

    monkeypatch.setattr(
        httpx,
        "Client",
        partial(httpx.Client, transport=httpx.MockTransport(respond)),
    )
    result = CliRunner().invoke(cli, arguments)
    assert result.exit_code == 0, result.exception
    assert seen == [None]


@pytest.mark.parametrize("target", [None, "http://127.0.0.1:9002"])
@pytest.mark.asyncio
async def test_async_agent_requests_scope_token(monkeypatch, target):
    seen = []

    def respond(request):
        seen.append(request.headers.get(_TOKEN_HEADER))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)),
    )
    await agent_management.collect_final_agent_chat_response_async(
        target,
        {},
        "agent-a",
        1,
    )
    await agent_management.stop_agent_chat_async(target, "session", "agent-a")
    await agent_management._call_fork_api(
        "agent-a",
        "session",
        base_url=target,
    )
    expected = "secret-a" if target is None else None
    assert seen == [expected] * 3


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com:9001",
        "http://localhost:9001",
        "https://127.0.0.1:9001",
        "http://user:password@127.0.0.1:9001",
        "http://127.0.0.1:bad",
        "http://127.0.0.1:9001/other",
        "http://127.0.0.1:9001/?q=x",
        "http://127.0.0.1:9001/#fragment",
    ],
)
def test_invalid_runtime_endpoint_does_not_override_app(monkeypatch, endpoint):
    monkeypatch.setenv("QWENPAW_RUNTIME_API_URL", endpoint)
    assert agent_management.resolve_agent_api_base_url() == (
        "http://127.0.0.1:9002"
    )
    seen = []

    def respond(request):
        seen.append(request.headers.get(_TOKEN_HEADER))
        return httpx.Response(200)

    monkeypatch.setattr(
        httpx,
        "Client",
        partial(httpx.Client, transport=httpx.MockTransport(respond)),
    )
    with cli_http.client(_RUNTIME_URL) as client:
        client.get("/agents")
    assert seen == [None]


def test_ipv6_runtime_endpoint(monkeypatch):
    endpoint = "http://[::1]:9001"
    monkeypatch.setenv("QWENPAW_RUNTIME_API_URL", endpoint)
    assert agent_management.resolve_agent_api_base_url() == endpoint
    seen = []

    def respond(request):
        seen.append(request.headers.get(_TOKEN_HEADER))
        return httpx.Response(200, json={"agents": []})

    monkeypatch.setattr(
        httpx,
        "Client",
        partial(httpx.Client, transport=httpx.MockTransport(respond)),
    )
    result = CliRunner().invoke(cli, ["agents", "list"])
    assert result.exit_code == 0, result.exception
    assert seen == ["secret-a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_external_client_cannot_send_token_through_proxy(
    monkeypatch,
    asynchronous,
):
    """Exercise actual proxy routing rather than a mock transport."""
    seen = []

    class Proxy(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers.get(_TOKEN_HEADER)))
            if self.path.startswith("http://external.example"):
                self.send_response(302)
                self.send_header("Location", f"{_RUNTIME_URL}/api/agents")
            else:
                self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    with HTTPServer(("127.0.0.1", 0), Proxy) as proxy:
        thread = Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        proxy_url = f"http://127.0.0.1:{proxy.server_port}"
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            monkeypatch.setenv(name, proxy_url)
        monkeypatch.setenv("NO_PROXY", "")
        try:
            if asynchronous:
                async with async_api_client("http://external.example") as api:
                    await api.get("/agents", follow_redirects=True)
                    await api.get(f"{_RUNTIME_URL}/api/agents")
            else:
                with cli_http.client("http://external.example") as api:
                    api.get("/agents", follow_redirects=True)
                    api.get(f"{_RUNTIME_URL}/api/agents")
        finally:
            proxy.shutdown()
            thread.join(timeout=5)
    assert len(seen) == 3
    assert seen[1][0] == f"{_RUNTIME_URL}/api/agents"
    assert all(token is None for _, token in seen)


@pytest.mark.parametrize("managed", [True, False])
def test_cli_api_operations_pass_boundary(
    monkeypatch,
    tmp_path,
    managed,
):
    """Cover missing API entry points without performing plugin installs."""
    app = FastAPI()
    app.add_middleware(RuntimeBoundaryMiddleware)
    seen = []

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "DELETE"])
    async def endpoint(request: Request, path: str):
        seen.append((request.method, path, request.url.port))
        return {"status": "ok", "name": "demo"}

    if not managed:
        for name in (
            "QWENPAW_RUNTIME_ID",
            "QWENPAW_RUNTIME_API_URL",
            "QWENPAW_RUNTIME_INTERNAL_TOKEN",
        ):
            monkeypatch.delenv(name)
    monkeypatch.setattr(
        plugin_commands.config_utils,
        "read_last_api",
        lambda: ("127.0.0.1", 9002),
    )
    archive = tmp_path / "plugin.zip"
    archive.write_bytes(b"fixture zip")
    port = 9001 if managed else 9002
    with TestClient(app) as boundary:
        monkeypatch.setattr(
            httpx,
            "Client",
            partial(httpx.Client, transport=_boundary_transport(boundary)),
        )
        ok, _ = doctor_cmd._check_api_health(f"http://127.0.0.1:{port}", 2)
        assert ok
        assert update_cmd._probe_service(f"http://127.0.0.1:{port}").is_running
        assert plugin_commands._api_install_plugin("fixture")
        assert plugin_commands._api_upload_plugin(archive)
        assert plugin_commands._api_uninstall_plugin("demo")
    assert seen == [
        ("GET", "healthz", port),
        ("GET", "version", port),
        ("POST", "plugins/install", port),
        ("POST", "plugins/upload", port),
        ("DELETE", "plugins/demo", port),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_stream", [False, True])
async def test_proactive_request_auth_stream_and_total_timeout(
    monkeypatch,
    caplog,
    slow_stream,
):
    seen = []
    closed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"da"
            if slow_stream:
                await asyncio.sleep(2)
            yield b'ta: {"done":true}\n\n'

        async def aclose(self):
            closed.append(True)

    def respond(request):
        seen.append(
            (
                request.url.port,
                request.headers.get(_TOKEN_HEADER),
                request.headers.get("X-Agent-Id"),
            ),
        )
        return httpx.Response(200, stream=Stream())

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        partial(httpx.AsyncClient, transport=httpx.MockTransport(respond)),
    )
    with caplog.at_level("INFO"):
        await send_proactive_message_via_http("agent-a", "message", 1)
    assert seen == [(9001, "secret-a", "agent-a")]
    assert closed == [True]
    expected = "Timeout (1s)" if slow_stream else "sent successfully via HTTP"
    assert expected in caplog.text
