# -*- coding: utf-8 -*-
"""Scope binding recovery over a controlled loopback HTTP fault server.

The server injects failures and does not run the PowerContext service.
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import unquote

import httpx
import pytest
from agentscope.message import Msg, TextBlock, ToolResultState

from plugins.memory.powercontext.backend import manager as manager_module
from plugins.memory.powercontext.backend.config import PowerContextMemoryConfig
from plugins.memory.powercontext.backend.manager import (
    PowerContextMemoryManager,
)
from qwenpaw.memory import MemoryBackendContext


class ScopeFaultHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def finish(self):
        try:
            super().finish()
        finally:
            self.server.state.connection_closed.set()

    def log_message(
        self,
        _format,
        *_args,
    ):
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):  # pylint: disable=invalid-name
        state = self.server.state
        if (
            self.path.startswith("/v1/scopes/")
            and "/artifacts/" not in self.path
        ):
            state.lookups.append(self.path)
            if state.hold_lookup.is_set():
                state.lookup_entered.set()
                state.release_lookup.wait(timeout=5)
            if not state.healthy.is_set():
                if state.failure == "disconnect":
                    self.close_connection = True
                    return
                if state.failure == "wrong-scope":
                    self.send_json(200, {"scope_id": "scp_unexpected"})
                    return
                self.send_json(
                    state.failure,
                    {
                        "error": {
                            "code": "scope_unavailable",
                            "message": "injected failure",
                        },
                    },
                )
                return
            requested = unquote(self.path.rsplit("/", 1)[-1])
            if state.default_creation and requested != state.scope_id:
                self.send_json(404, {"error": {"code": "scope_not_found"}})
            else:
                self.send_json(200, {"scope_id": state.scope_id})
            return
        state.operations.append(("GET", self.path, {}))
        self.send_json(200, {"items": [], "next_cursor": None})

    def do_POST(self):  # pylint: disable=invalid-name
        state = self.server.state
        payload = json.loads(
            self.rfile.read(int(self.headers["Content-Length"])),
        )
        if self.path == "/v1/scopes":
            state.creation_payloads.append(payload)
            state.scopes.setdefault(
                payload["idempotency_key"],
                state.scope_id,
            )
            if state.drop_created_response:
                state.drop_created_response = False
                self.close_connection = True
                return
            self.send_json(200, {"scope_id": state.scope_id})
            return
        state.operations.append(("POST", self.path, payload))
        if self.path == "/v1/context/prepare":
            content = "Scope recovery context."
            self.send_json(
                200,
                {
                    "schema": "powercontext.prepared-context.v1",
                    "status": "ready",
                    "content": content,
                    "content_bytes": len(content.encode("utf-8")),
                },
            )
        elif self.path == "/v1/memory/search":
            self.send_json(200, {"hits": []})
        else:
            self.send_json(200, {"saved": True})


@pytest.fixture(name="scope_server")
def fault_server(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setattr(
        manager_module,
        "_SCOPE_RETRY_INITIAL_DELAY",
        0.02,
        raising=False,
    )
    monkeypatch.setattr(
        manager_module,
        "_SCOPE_RETRY_MAX_DELAY",
        0.05,
        raising=False,
    )
    state = SimpleNamespace(
        healthy=threading.Event(),
        hold_lookup=threading.Event(),
        lookup_entered=threading.Event(),
        release_lookup=threading.Event(),
        connection_closed=threading.Event(),
        scope_id="scp_existing",
        failure=503,
        lookups=[],
        operations=[],
        default_creation=False,
        drop_created_response=True,
        creation_payloads=[],
        scopes={},
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), ScopeFaultHandler)
    server.state = state
    thread = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01),
        daemon=True,
    )
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        state.release_lookup.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def make_manager(tmp_path, server, *, default_scope=False, token=""):
    config = PowerContextMemoryConfig(
        base_url=server.url,
        scope_id="" if default_scope else server.scope_id,
        token=token,
        timeout=1,
    )
    return PowerContextMemoryManager(
        MemoryBackendContext(
            agent_id="scope-recovery-test",
            working_dir=tmp_path,
            host_working_dir=tmp_path,
            backend_config=config.model_dump(),
        ),
    )


def message():
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text="Verify Scope recovery.")],
    )


async def wait_until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("failure", [503, "disconnect"])
async def test_same_manager_recovers_without_restarting(
    tmp_path,
    scope_server,
    failure,
):
    scope_server.failure = failure
    manager = make_manager(tmp_path, scope_server)
    try:
        await manager.start()
        assert not manager.list_memory_tools()
        assert manager.get_auto_memory_interval() == 0
        assert await manager.get_auto_memory_search_options() is None
        assert (
            await manager.memory_search("check")
        ).state == ToolResultState.ERROR
        assert (
            await manager.memory_remember("fact", "check")
        ).state == ToolResultState.ERROR
        assert (
            await manager.prepare_context("check")
        ).state == ToolResultState.ERROR
        assert (
            await manager.artifact_list("profile")
        ).state == ToolResultState.ERROR
        assert await manager.auto_memory_search([message()]) is None
        assert await manager.auto_memory([message()]) == ""
        assert not scope_server.operations

        scope_server.healthy.set()
        await wait_until(manager.list_memory_tools)
        assert len(manager.list_memory_tools()) == 10
        assert manager.get_auto_memory_interval() == 1
        assert await manager.get_auto_memory_search_options() is not None
        assert (
            await manager.memory_search("check")
        ).state == ToolResultState.SUCCESS
        assert (
            await manager.memory_remember("fact", "check")
        ).state == ToolResultState.SUCCESS
        assert (
            await manager.artifact_list("profile")
        ).state == ToolResultState.SUCCESS
        recalled = await manager.auto_memory_search([message()])
        assert (
            recalled is not None
            and "Scope recovery context." in recalled["text"]
        )
        assert (
            await manager.auto_memory([message()])
            == "Saved auto-memory to PowerContext."
        )
        assert all(
            payload.get("scope_id", scope_server.scope_id)
            == scope_server.scope_id
            for _, _, payload in scope_server.operations
        )
    finally:
        assert await manager.close()


@pytest.mark.parametrize("failure", [401, 403, 404, 422, "wrong-scope"])
async def test_permanent_binding_error_is_reported_without_retry(
    tmp_path,
    scope_server,
    failure,
):
    scope_server.failure = failure
    manager = make_manager(tmp_path, scope_server)
    try:
        await manager.start()
        result = await manager.memory_search("check")
        assert result.state == ToolResultState.ERROR
        expected = (
            "invalid response"
            if failure == "wrong-scope"
            else f"HTTP {failure}"
        )
        assert expected in result.content[0].text
        lookups = len(scope_server.lookups)
        scope_server.healthy.set()
        await asyncio.sleep(0.15)
        assert len(scope_server.lookups) == lookups
        assert not manager.list_memory_tools()
        assert manager.get_auto_memory_interval() == 0
        assert not scope_server.operations
    finally:
        assert await manager.close()


async def test_close_cancels_retry_backoff(
    tmp_path,
    scope_server,
    monkeypatch,
):
    monkeypatch.setattr(
        manager_module,
        "_SCOPE_RETRY_INITIAL_DELAY",
        0.1,
        raising=False,
    )
    manager = make_manager(tmp_path, scope_server)
    await manager.start()
    assert not scope_server.connection_closed.is_set()
    assert await manager.close()
    await wait_until(scope_server.connection_closed.is_set)
    lookups = len(scope_server.lookups)
    scope_server.healthy.set()
    await asyncio.sleep(0.15)
    assert len(scope_server.lookups) == lookups
    assert not manager.list_memory_tools()
    assert manager.get_auto_memory_interval() == 0


async def test_close_retries_failed_unbound_connection_cleanup(
    tmp_path,
    scope_server,
    monkeypatch,
):
    close = manager_module.PowerContextMemoryClient.close
    attempted_clients = []

    async def fail_first_close(client):
        attempted_clients.append(client)
        if len(attempted_clients) == 1:
            raise RuntimeError("injected close failure")
        await close(client)

    monkeypatch.setattr(
        manager_module.PowerContextMemoryClient,
        "close",
        fail_first_close,
    )
    manager = make_manager(tmp_path, scope_server)
    try:
        await manager.start()
        assert not await manager.close()
        assert not scope_server.connection_closed.is_set()
        assert not manager.list_memory_tools()
        assert await manager.close()
        await wait_until(scope_server.connection_closed.is_set)
    finally:
        monkeypatch.setattr(
            manager_module.PowerContextMemoryClient,
            "close",
            close,
        )
        for client in attempted_clients:
            await close(client)
        assert await manager.close()


@pytest.mark.parametrize(
    ("failure", "error_type", "expected"),
    [
        ("url", httpx.UnsupportedProtocol, "unsupported protocol"),
        ("header", httpx.LocalProtocolError, "Illegal header value"),
    ],
)
async def test_invalid_transport_configuration_is_not_retried(
    tmp_path,
    scope_server,
    monkeypatch,
    failure,
    error_type,
    expected,
):
    transport_errors = []
    send = httpx.AsyncClient.send

    async def record_transport_failure(client, *args, **kwargs):
        try:
            return await send(client, *args, **kwargs)
        except httpx.TransportError as exc:
            transport_errors.append(type(exc))
            raise

    monkeypatch.setattr(httpx.AsyncClient, "send", record_transport_failure)
    if failure == "url":
        scope_server.url = scope_server.url.replace("http:", "ftp:", 1)
    manager = make_manager(
        tmp_path,
        scope_server,
        token="synthetic\ninvalid-header" if failure == "header" else "",
    )
    try:
        await manager.start()
        result = await manager.memory_search("check")
        assert result.state == ToolResultState.ERROR
        assert expected in result.content[0].text
        assert "retrying" not in result.content[0].text
        await asyncio.sleep(0.15)
        assert transport_errors == [error_type]
        assert not manager.list_memory_tools()
        assert not scope_server.lookups
        assert not scope_server.operations
    finally:
        assert await manager.close()


async def test_close_during_initial_lookup_prevents_activation(
    tmp_path,
    scope_server,
):
    scope_server.hold_lookup.set()
    scope_server.healthy.set()
    manager = make_manager(tmp_path, scope_server)
    startup = asyncio.create_task(manager.start())
    try:
        await wait_until(scope_server.lookup_entered.is_set)
        assert await asyncio.wait_for(manager.close(), timeout=1)
        scope_server.release_lookup.set()
        await asyncio.wait_for(startup, timeout=2)
        await wait_until(scope_server.connection_closed.is_set)
        assert not manager.list_memory_tools()
        assert manager.get_auto_memory_interval() == 0
        result = await manager.memory_search("closed")
        assert result.state == ToolResultState.ERROR
        assert len(scope_server.lookups) == 1
        assert not scope_server.operations
    finally:
        scope_server.release_lookup.set()
        await asyncio.gather(startup, return_exceptions=True)
        assert await manager.close()


async def test_retry_stops_when_binding_becomes_forbidden(
    tmp_path,
    scope_server,
):
    manager = make_manager(tmp_path, scope_server)
    try:
        await manager.start()
        scope_server.failure = 403
        await wait_until(lambda: len(scope_server.lookups) >= 2)
        async with asyncio.timeout(2):
            while True:
                result = await manager.memory_search("check")
                if "HTTP 403" in result.content[0].text:
                    break
                await asyncio.sleep(0.01)
        assert result.state == ToolResultState.ERROR
        lookups = len(scope_server.lookups)
        scope_server.healthy.set()
        await asyncio.sleep(0.15)
        assert len(scope_server.lookups) == lookups
        assert not manager.list_memory_tools()
        assert not scope_server.operations
    finally:
        assert await manager.close()


async def test_close_cancels_inflight_binding_without_reactivation(
    tmp_path,
    scope_server,
):
    manager = make_manager(tmp_path, scope_server)
    try:
        await manager.start()
        scope_server.hold_lookup.set()
        scope_server.healthy.set()
        await wait_until(scope_server.lookup_entered.is_set)
        assert await asyncio.wait_for(manager.close(), timeout=1)
        lookups = len(scope_server.lookups)
        scope_server.release_lookup.set()
        await asyncio.sleep(0.15)
        assert len(scope_server.lookups) == lookups
        assert not manager.list_memory_tools()
        assert manager.get_auto_memory_interval() == 0
    finally:
        scope_server.release_lookup.set()
        assert await manager.close()


async def test_default_scope_creation_response_loss_reuses_idempotency_key(
    tmp_path,
    scope_server,
):
    scope_server.default_creation = True
    scope_server.healthy.set()
    manager = make_manager(tmp_path, scope_server, default_scope=True)
    try:
        await manager.start()
        assert len(scope_server.scopes) == 1
        await wait_until(manager.list_memory_tools)
        assert len(scope_server.creation_payloads) >= 2
        assert all(
            payload == scope_server.creation_payloads[0]
            for payload in scope_server.creation_payloads
        )
        assert len(scope_server.scopes) == 1
        result = await manager.memory_remember("fact", "only one Scope")
        assert result.state == ToolResultState.SUCCESS
        assert (
            scope_server.operations[-1][2]["scope_id"] == scope_server.scope_id
        )
    finally:
        assert await manager.close()
