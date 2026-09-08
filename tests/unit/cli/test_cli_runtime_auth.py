# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression coverage for CLI access to managed runtime APIs."""

from functools import partial

import httpx
import pytest
from click.testing import CliRunner
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.agents.tools import agent_management
from qwenpaw.app.auth import RuntimeBoundaryMiddleware
from qwenpaw.cli import http as cli_http
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
        # Use the ASGI transport without replacing client request behavior.
        monkeypatch.setattr(
            httpx,
            "Client",
            partial(httpx.Client, transport=boundary._transport),
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
