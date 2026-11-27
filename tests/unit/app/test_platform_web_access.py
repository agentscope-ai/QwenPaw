# -*- coding: utf-8 -*-
"""Integration boundaries for account enrollment and streamed operations."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI

from qwenpaw.app import auth
from qwenpaw.app.routers.console_frontend import (
    create_console_frontend_router,
)
from qwenpaw.hub.models import RuntimeState
from qwenpaw.hub.platform_access import HubPlatformConnections
from qwenpaw.remote_access.enrollment import RelayEnrollmentService
from qwenpaw.remote_access.operation_dispatcher import RelayLocalApi
from qwenpaw.remote_access.platform_client import (
    PlatformRelayClient,
    PlatformSession,
    RegisteredNode,
    RelayPlatformError,
)
from qwenpaw.remote_access.node_transport import RelayNodeTransport
from qwenpaw.remote_access.protocol import (
    RelayFrame,
    RelayFrameType,
    RelayOperation,
    decode_frame,
)
from qwenpaw.remote_access.store import RelayNodeStore
from qwenpaw.security import secret_store


@pytest.fixture(autouse=True)
def isolated_key(monkeypatch):
    monkeypatch.setattr(secret_store, "_cached_master_key", b"k" * 32)
    monkeypatch.setattr(secret_store, "_cached_fernet", None)


@pytest.mark.asyncio
async def test_oauth_binding_retry_refresh_and_local_logout(tmp_path):
    class Platform:
        base_url = "https://platform.test"
        fail = True

        def __init__(self, _url):
            pass

        async def exchange_oauth_code(self, **_kwargs):
            return PlatformSession(
                "cloud-user",
                "Cloud",
                "access",
                "refresh",
                time.time() - 1,
            )

        async def create_oauth_enrollment(self, **_kwargs):
            if self.fail:
                raise RelayPlatformError("quota", "Quota", status_code=409)
            return object()

        async def register_node(self, **_kwargs):
            return RegisteredNode("node", "node-secret", "nonce", 1)

        async def refresh_session(self, session):
            def refresh_response(request):
                assert request.url.path == "/api/cli/v1/oauth/refresh"
                assert json.loads(request.content) == {
                    "refresh_token": "refresh",
                }
                return httpx.Response(
                    200,
                    json={
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 3600,
                        "token_type": "Bearer",
                    },
                )

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(refresh_response),
            ) as client:
                return await PlatformRelayClient(
                    self.base_url,
                    client=client,
                ).refresh_session(session)

        async def revoke_oauth_refresh_token(self, _refresh):
            raise RelayPlatformError("offline", "Offline", status_code=503)

    store = RelayNodeStore(tmp_path / "platform.json")
    service = RelayEnrollmentService(store, client_factory=Platform)
    login = await service.start(
        platform_url=Platform.base_url,
        name="Office",
        callback_origin="http://127.0.0.1:19088",
    )
    query = parse_qs(urlsplit(login.authorization_url).query)
    nonce = urlsplit(query["redirect_uri"][0]).path.split("/")[-1]
    with pytest.raises(ValueError):
        await service.complete_oauth(
            nonce=nonce,
            state_value="wrong",
            code="code",
        )
    with pytest.raises(RelayPlatformError):
        await service.complete_oauth(
            nonce=nonce,
            state_value=query["state"][0],
            code="code",
        )
    assert (await service.status()).logged_in
    assert (await service.status()).node_id is None
    Platform.fail = False
    assert (await service.bind()).node_id == "node"
    assert store.load().session.access_token == "new-access"
    raw = store.path.read_text()
    assert "new-access" not in raw and "new-refresh" not in raw
    with pytest.raises(RelayPlatformError):
        await service.logout()
    assert not (await service.status()).logged_in
    assert (await service.status()).node_id == "node"


@pytest.mark.asyncio
async def test_sse_is_delivered_before_completion_and_cancel_closes_upstream():
    first = asyncio.Event()
    complete = asyncio.Event()
    closed = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"text":"first"}\n\n'
            first.set()
            await complete.wait()
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            closed.set()

    async def respond(request):
        assert request.url.path == "/api/console/chat"
        assert request.headers["x-agent-id"] == "personal"
        assert request.headers["x-qwenpaw-runtime-token"] == "boundary"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=Stream(),
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
    ) as client:
        dispatcher = RelayLocalApi(
            "http://127.0.0.1:19088",
            client=client,
            headers=lambda: {"X-QwenPaw-Runtime-Token": "boundary"},
        ).dispatcher()
        response = await dispatcher.dispatch(
            RelayOperation.CONSOLE_REQUEST,
            json.dumps(
                {
                    "method": "POST",
                    "path": "/console/chat",
                    "agent_id": "personal",
                    "body": base64.b64encode(b'{"input": []}').decode("ascii"),
                },
            ).encode(),
        )
        async with response as result:
            chunk = await anext(result.body)
            assert b"first" in chunk and not complete.is_set()
        assert closed.is_set()
        closed.clear()
        frames = []
        delivered = asyncio.Event()
        transport = RelayNodeTransport(dispatcher)

        class Socket:
            async def send(self, wire):
                frame = decode_frame(wire)
                frames.append(frame)
                if frame.frame_type == RelayFrameType.DATA:
                    delivered.set()

        socket = Socket()
        await transport._receive(
            socket,
            RelayFrame(
                RelayFrameType.OPEN,
                stream_id="chat",
                request_id="chat",
                metadata={"operation_id": "console.request"},
            ),
        )
        await transport._receive(
            socket,
            RelayFrame(
                RelayFrameType.DATA,
                stream_id="chat",
                payload=json.dumps(
                    {
                        "method": "POST",
                        "path": "/console/chat",
                        "agent_id": "personal",
                        "body": "",
                    },
                ).encode(),
            ),
        )
        await transport._receive(
            socket,
            RelayFrame(RelayFrameType.END, stream_id="chat"),
        )
        task = transport._tasks["chat"]
        await asyncio.wait_for(delivered.wait(), timeout=1)
        assert b"first" in frames[-1].payload and not complete.is_set()
        await transport._receive(
            socket,
            RelayFrame(RelayFrameType.CANCEL, stream_id="chat"),
        )
        await asyncio.gather(task, return_exceptions=True)
        assert closed.is_set()
        for path in (
            "/hub/users",
            "/auth/login",
            "/remote-access/platform",
            "/models/../envs",
            "https://other.test/models",
        ):
            with pytest.raises(ValueError):
                await dispatcher.dispatch(
                    RelayOperation.CONSOLE_REQUEST,
                    json.dumps({"method": "GET", "path": path}).encode(),
                )
        with pytest.raises(ValueError):
            await dispatcher.dispatch(
                RelayOperation.CONSOLE_REQUEST,
                json.dumps(
                    {"method": "GET", "path": "/models", "agent_id": ".."},
                ).encode(),
            )


def test_hub_bindings_are_scoped_to_local_user_and_runtime_owner(
    tmp_path,
    monkeypatch,
):
    users = {
        name: SimpleNamespace(user_id=name, disabled=False)
        for name in ("alice", "bob")
    }
    runtimes = {
        name: SimpleNamespace(
            runtime_id=name,
            owner_user_id=name,
            tenant_id=name,
            state=RuntimeState.RUNNING,
            host="127.0.0.1",
            port=19088,
        )
        for name in users
    }
    hub = HubPlatformConnections(
        tmp_path,
        SimpleNamespace(get_user=users.get),
        SimpleNamespace(get=runtimes.__getitem__),
        SimpleNamespace(
            get_runtime_secret=lambda **kw: kw["runtime_id"],
            get_or_create_system_secret=lambda _name: (
                "stable-hub-vault-secret"
            ),
        ),
    )
    for name, user in users.items():
        connection = hub.get(user)
        state = connection.store.create(
            platform_url="https://platform.test",
            qwenpaw_id=name,
            name=name,
        )
        connection.store.save(
            replace(
                state,
                account_id="same-cloud-account",
                runtime_id=name,
                session=PlatformSession(
                    "same-cloud-account",
                    "Cloud",
                    f"{name}-access",
                    f"{name}-refresh",
                    time.time() + 3600,
                ),
            ),
        )
    assert (
        hub.get(users["alice"]).store.path != hub.get(users["bob"]).store.path
    )
    key = hub.get(users["alice"]).store.load().key_pair.thumbprint()
    monkeypatch.setattr(secret_store, "_cached_master_key", b"x" * 32)
    monkeypatch.setattr(secret_store, "_cached_fernet", None)
    restored = HubPlatformConnections(
        tmp_path,
        hub.auth,
        hub.runtimes,
        hub.credentials,
    )
    loaded = restored.get(users["alice"]).store.load()
    assert loaded.key_pair.thumbprint() == key
    assert loaded.session.access_token == "alice-access"
    assert (
        "alice-access"
        not in restored.get(users["alice"]).store.path.read_text()
    )
    assert hub._headers("alice")["X-QwenPaw-Runtime-Token"] == "alice"
    assert hub._headers("bob")["X-QwenPaw-Runtime-Token"] == "bob"
    runtimes["alice"].owner_user_id = "bob"
    with pytest.raises(ValueError, match="ownership"):
        hub._headers("alice")
    users["bob"].disabled = True
    with pytest.raises(ValueError, match="disabled"):
        hub._headers("bob")


@pytest.mark.asyncio
async def test_versioned_console_assets_stream_with_bounded_backpressure(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "console"
    root.mkdir()
    index = root / "index.html"
    index.write_text(
        '<meta name="qwenpaw-console-protocol" content="1">release one',
    )
    content = b"console chunk;" * 200_000
    (root / "bundle.js").write_bytes(content)
    private = tmp_path / "private.txt"
    private.write_text("private")
    app = FastAPI()
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        auth,
        "_load_auth_data",
        lambda: {"user": {"username": "owner"}, "jwt_secret": "s" * 64},
    )
    monkeypatch.setattr(
        auth,
        "_get_config_cached",
        lambda: (
            SimpleNamespace(
                security=SimpleNamespace(
                    allow_no_auth_hosts=[],
                ),
            ),
            0,
        ),
    )
    app.add_middleware(auth.AuthMiddleware)
    app.include_router(create_console_frontend_router(str(root)))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
    ) as client:
        assert (await client.get("/api/console/frontend")).status_code == 401
        client.headers.update(auth.platform_runtime_headers())
        manifest = (await client.get("/api/console/frontend")).json()
        assert manifest["protocol"] == 1
        prefix = f"/console/frontend/assets/{manifest['build']}"
        escape = await client.get(f"/api{prefix}/%2e%2e%2fprivate.txt")
        assert escape.status_code == 404
        transport = RelayNodeTransport(
            RelayLocalApi("http://127.0.0.1", client=client).dispatcher(),
        )
        frames = []

        class Socket:
            async def send(self, wire):
                frames.append(decode_frame(wire))

        socket = Socket()
        await transport._receive(
            socket,
            RelayFrame(
                RelayFrameType.OPEN,
                stream_id="asset",
                request_id="asset",
                metadata={
                    "operation_id": "console.request",
                    "schema_version": 1,
                },
            ),
        )
        await transport._receive(
            socket,
            RelayFrame(
                RelayFrameType.DATA,
                stream_id="asset",
                payload=json.dumps(
                    {"method": "GET", "path": f"{prefix}/bundle.js"},
                ).encode(),
            ),
        )
        await transport._receive(
            socket,
            RelayFrame(RelayFrameType.END, stream_id="asset"),
        )
        task = transport._tasks["asset"]
        for _ in range(100):
            if len(frames) >= 9:
                break
            await asyncio.sleep(0.01)
        assert len(frames) == 9
        assert not task.done()
        while not task.done():
            await transport._receive(
                socket,
                RelayFrame(RelayFrameType.WINDOW_UPDATE, stream_id="asset"),
            )
            await asyncio.sleep(0)
        await task
        chunks = [f.payload for f in frames if f.frame_type == "data"]
        assert b"".join(chunks) == content
        assert max(map(len, chunks)) <= 64 * 1024
        index.write_text("<html>release two</html>")
        assert (await client.get(f"/api{prefix}/bundle.js")).status_code == 409
