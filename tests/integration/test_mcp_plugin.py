# -*- coding: utf-8 -*-
"""MCP acceptance: usable tools and the host's management/authentication flow.

Run with pytest tests/integration/test_mcp_plugin.py. All peers and credentials
are local; plugin/SDK lifecycle contracts belong to tests/unit/plugins.
Keep MCP coverage in these two flows instead of adding per-fix test files.
"""

# pylint: disable=protected-access,redefined-outer-name
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from urllib.parse import urlencode

import httpx
import pytest

from qwenpaw.app.routers import mcp, mcp_oauth
from qwenpaw.app.driver_runtime_service import LazyDriverService
from qwenpaw.app.mcp.config_service import MCPConfigService
from qwenpaw.app.mcp.schemas import (
    MCPAccessPolicy,
    MCPClientCreateRequest,
    MCPClientUpdateRequest,
)
from qwenpaw.drivers.capabilities import DriverInvocation
from qwenpaw.drivers.storage import load_card
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.plugins import SDKError

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins/protocol/mcp"
PEER = ROOT / "tests/fixtures/mcp/plugin_peer.py"
pytestmark = [pytest.mark.integration, pytest.mark.p1]


@asynccontextmanager
async def local_peer(tmp_path, transport):
    """The host owns stdio; this fixture owns only the HTTP server process."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    endpoint = {"transport": transport}
    if transport == "stdio":
        endpoint.update(
            command=sys.executable,
            args=[str(PEER), "stdio", "0", "unused"],
        )
        yield endpoint
        return
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    endpoint["url"] = base + ("/sse" if transport == "sse" else "/mcp")
    evidence = tmp_path / "oauth.json"
    with (tmp_path / "peer.log").open("wb") as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-B",
            str(PEER),
            "sse" if transport == "sse" else "streamable-http",
            str(port),
            str(evidence),
            stdout=log,
            stderr=log,
        )
        try:
            async with httpx.AsyncClient() as client:
                async with asyncio.timeout(15):
                    while True:
                        assert process.returncode is None, "Local peer exited"
                        try:
                            await client.get(base + "/health", timeout=0.2)
                            break
                        except httpx.TransportError:
                            await asyncio.sleep(0.05)
            yield endpoint
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()


async def echo(host, key="echo", text="hello"):
    result = await host.call_driver(key, "echo", {"text": text})
    assert not result.is_error
    assert any(block.text == text for block in result.content)


async def assert_sessions_terminated(endpoint):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            endpoint["url"].removesuffix("/mcp") + "/sessions",
        )
    sessions = response.json()
    assert sessions, "The peer must have observed a successful handshake"
    assert all(row["terminated"] for row in sessions)
    assert all(
        row["delete"] == {"status": 200, "auth_matches": True}
        for row in sessions
    )


async def assert_endpoint_credentials_isolated(host, tmp_path, endpoint):
    """A failed replacement and its retry never share another target's key."""
    async with local_peer(
        tmp_path / "replacement",
        "streamable_http",
    ) as other:
        bases = [row["url"].removesuffix("/mcp") for row in (endpoint, other)]
        async with httpx.AsyncClient() as http:

            async def history(index):
                return (await http.get(bases[index] + "/requests")).json()

            before = len(await history(0))
            workspace = await host._workspace("isolation")
            runtime = LazyDriverService(workspace)
            workspace._service_manager.services["driver_manager"] = runtime
            await runtime.start()
            service = MCPConfigService(workspace)

            async def drain_reload():
                await asyncio.gather(
                    *tuple(service._driver_config._reload_tasks),
                )

            async def call():
                return await runtime.invoke_capability(
                    DriverInvocation(
                        "driver://mcp/isolated/tools/echo#invoke",
                        {"text": "safe"},
                    ),
                )

            try:
                await service.create_client(
                    "isolated",
                    MCPClientCreateRequest(
                        name="Isolated",
                        **endpoint,
                        headers={"Authorization": "Bearer target-A"},
                    ),
                )
                await drain_reload()
                await service.update_policy(
                    "isolated",
                    MCPAccessPolicy(default_effect="allow"),
                )
                assert (await call()).ok
                await http.post(
                    bases[1] + "/control",
                    json={"blocked": True, "deny": True},
                )
                await service.update_client(
                    "isolated",
                    MCPClientUpdateRequest(
                        url=other["url"],
                        headers={"Authorization": "Bearer target-B"},
                    ),
                )
                async with asyncio.timeout(10):
                    while not await history(1):
                        await asyncio.sleep(0.01)
                await call()  # A may be denied immediately after a binding change.
                assert set((await history(0))[before:]) == {"Bearer target-A"}
                await http.post(bases[1] + "/control", json={"blocked": False})
                await drain_reload()
                await call()
                assert set((await history(0))[before:]) == {"Bearer target-A"}
                await http.post(bases[1] + "/control", json={"deny": False})
                await service.update_client(
                    "isolated",
                    MCPClientUpdateRequest(name="Retried"),
                )
                await drain_reload()
                assert (await call()).ok
                assert set(await history(1)) == {"Bearer target-B"}
            finally:
                await http.post(
                    bases[1] + "/control",
                    json={"blocked": False, "deny": False},
                )
                await drain_reload()
                await runtime.shutdown_all()
            assert set((await history(0))[before:]) == {"Bearer target-A"}
            await assert_sessions_terminated(other)


@pytest.mark.parametrize("transport", ["stdio", "sse", "streamable_http"])
async def test_mcp_connect_discover_call_and_reconnect(tmp_path, transport):
    async with local_peer(tmp_path, transport) as endpoint:
        async with PluginTestHost(tmp_path / "host") as host:
            await host.load(PLUGIN)
            source = {
                "name": "echo",
                "protocol": "mcp",
                "endpoint": endpoint,
                "policy": {"default_effect": "allow"},
            }
            await host.open_driver(source)
            tools = await host.list_driver_capabilities("echo")
            assert {tool["name"] for tool in tools} == {"echo", "process_info"}
            assert any(
                tool["capability_id"] == "driver://mcp/echo/tools/echo#invoke"
                for tool in tools
            )
            for text in ("first", "second"):
                await echo(host, text=text)
            info = await host.call_driver("echo", "process_info", {})
            remote = info.structured_content or json.loads(
                info.content[0].text,
            )
            if transport == "stdio":
                os.kill(remote["pid"], 15)
                # Retry only this idempotent echo after the peer exits.
                async with asyncio.timeout(15):
                    while True:
                        try:
                            await echo(host, text="reconnected")
                            break
                        except SDKError:
                            await asyncio.sleep(0.1)
            else:
                await host.close_driver("echo")
                await host.open_driver(source)
                await echo(host, text="reconnected")
            await host.close_driver("echo")
            if transport == "streamable_http":
                await assert_sessions_terminated(endpoint)


# Keep the representative management/authentication journey in one scenario.
# pylint: disable-next=too-many-statements
async def test_qwenpaw_mcp_management_and_authentication(tmp_path):
    async with local_peer(tmp_path, "streamable_http") as endpoint:
        async with PluginTestHost(tmp_path / "host") as host:
            await host.install(PLUGIN)
            host._http_app.state.plugin_loader = host._loader
            host._http_app.include_router(mcp_oauth.router, prefix="/api")
            host._http_app.include_router(mcp.router, prefix="/api")

            async def api(method, path, status=200, **kwargs):
                result = await host.request(
                    method,
                    "/api/mcp" + path,
                    user_id="alice",
                    headers={"X-Agent-Id": "test"},
                    **kwargs,
                )
                assert result.status == status, result.text
                return result

            await api(
                "POST",
                "",
                201,
                json={
                    "client_key": "echo",
                    "client": {
                        "name": "Echo",
                        **endpoint,
                        "enabled": False,
                        "headers": {"Authorization": "Bearer original"},
                    },
                },
            )
            assert [row["key"] for row in (await api("GET", "")).json()] == [
                "echo",
            ]
            assert (await api("GET", "/echo")).json()["enabled"] is False
            await api("PUT", "/echo", json={"name": "Renamed"})
            assert (await api("GET", "/echo")).json()["name"] == "Renamed"
            workspace = host._workspaces["test"]
            path = workspace.workspace_dir / "drivers/mcp/echo.yaml"
            before = path.read_bytes()
            assert workspace.driver_manager is None
            base = endpoint["url"].removesuffix("/mcp")

            async def authorize(error=None):
                response = await api(
                    "POST",
                    "/oauth/start/echo",
                    json={
                        "url": endpoint["url"],
                        "client_id": "controlled-client",
                        "scope": "read",
                        "auth_endpoint": base + "/oauth/authorize",
                        "token_endpoint": base + "/oauth/token",
                    },
                )
                state = response.json()["session_id"]
                assert path.read_bytes() == before
                pending = await api(
                    "GET",
                    f"/oauth/status/echo?session_id={state}",
                )
                assert pending.json()["attempt_status"] == "pending"
                query = {"state": state, "code": "controlled-code"}
                if error:
                    query["error"] = error
                await api(
                    "GET",
                    "/oauth/callback?" + urlencode(query),
                    400 if error else 200,
                )
                status = await api(
                    "GET",
                    f"/oauth/status/echo?session_id={state}",
                )
                assert status.json()["attempt_status"] == (
                    "failed" if error else "succeeded"
                )

            await authorize("access_denied")
            assert path.read_bytes() == before
            await authorize()
            status = (await api("GET", "/oauth/status/echo")).json()
            assert status["authorized"] is True and status["scope"] == "read"
            assert json.loads((tmp_path / "oauth.json").read_text())["pkce"]
            assert workspace.driver_manager is None
            policy = {
                "default_effect": "allow",
                "client_overrides": [],
                "tool_defaults": [],
                "tool_overrides": [],
                "unmanaged_rules_count": 0,
            }
            assert (
                await api("PUT", "/policy/echo", json=policy)
            ).json() == policy
            await api("PUT", "/tools/echo", json={"tools": ["echo"]})
            saved = load_card(path)
            assert saved.config["tools"] == ["echo"]
            await host.open_driver(asdict(saved))
            assert (await api("PATCH", "/toggle/echo")).json()[
                "enabled"
            ] is True
            # Exercise the connection after the host's reload finishes.
            tasks = [
                task
                for task in asyncio.all_tasks()
                if task.get_name() == "driver-reload:echo"
            ]
            await asyncio.gather(*tasks)
            tools = (await api("GET", "/tools/echo")).json()
            assert any(tool["name"] == "echo" for tool in tools)
            await echo(host)
            await api("DELETE", "/oauth/echo")
            assert (await api("GET", "/oauth/status/echo")).json()[
                "authorized"
            ] is False
            await host.close_driver("echo")
            await assert_sessions_terminated(endpoint)
            await api("DELETE", "/echo")
            assert (await api("GET", "")).json() == []
            await assert_endpoint_credentials_isolated(
                host,
                tmp_path,
                endpoint,
            )
            await assert_sessions_terminated(endpoint)
