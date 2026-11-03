# -*- coding: utf-8 -*-
"""Mattermost native posts, socket authentication and REST sends."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from tests.channel_support.driver import bind, module
from tests.channel_support.protocol import eventually, send


class Socket:
    def __init__(self):
        self.inbox, self.sent, self.closed = asyncio.Queue(), [], False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.inbox.get()

    async def send(self, raw):
        frame = json.loads(raw)
        self.sent.append(frame)
        if frame.get("action") == "authentication_challenge":
            await self.inbox.put(json.dumps({"seq_reply": 1, "status": "OK"}))


@pytest.fixture
async def mattermost(tmp_path, monkeypatch):
    native = module("mattermost", "platform")
    socket, requests = Socket(), []

    def respond(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer local-token"
        path = request.url.path
        if path.endswith("/users/me"):
            return httpx.Response(
                200,
                json={"id": "bot-id", "username": "paw"},
            )
        if path == "/api/v4/posts" and request.method == "POST":
            return httpx.Response(201, json={"id": "sent-post"})
        if path == "/api/v4/files":
            return httpx.Response(
                201,
                json={"file_infos": [{"id": "uploaded-file"}]},
            )
        if path.endswith("/files/file-A"):
            return httpx.Response(
                200,
                content=b"inbound attachment",
                headers={
                    "Content-Disposition": 'attachment; filename="note.txt"',
                },
            )
        if path.endswith("/info"):
            return httpx.Response(200, json={"name": "note.txt"})
        return httpx.Response(200, json={"order": [], "posts": {}})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        native.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(
            transport=httpx.MockTransport(respond),
            **kwargs,
        ),
    )
    monkeypatch.setattr(
        native.websockets,
        "connect",
        lambda *args, **kwargs: socket,
    )
    driver = module("mattermost").MattermostDriver()
    peer, identity = bind("mattermost", driver, tmp_path)
    await driver.start(
        dict(
            url="https://mm.invalid",
            bot_token="local-token",
            workspace_dir=str(tmp_path),
            media_dir=str(tmp_path / "media"),
        ),
    )
    await eventually(lambda: driver._connected)
    yield driver, peer, identity, socket, requests, tmp_path
    await driver.stop()


async def receive(
    value,
    channel_type="D",
    root="",
    text="hello",
    ident="post-A",
    files=(),
):
    driver, peer, _, socket, _, _ = value
    await socket.inbox.put(
        json.dumps(
            {
                "event": "posted",
                "data": {
                    "channel_type": channel_type,
                    "post": json.dumps(
                        {
                            "id": ident,
                            "channel_id": "channel-A",
                            "user_id": "human-id",
                            "message": text,
                            "root_id": root,
                            "file_ids": list(files),
                        },
                    ),
                },
            },
        ),
    )
    await eventually(lambda: bool(peer.batches))
    return peer.batches[-1]["events"][0]


async def test_start_authenticates_rest_identity_and_websocket(mattermost):
    driver, _, _, socket, requests, _ = mattermost
    assert requests[0].url.path == "/api/v4/users/me"
    assert socket.sent == [
        {
            "seq": 1,
            "action": "authentication_challenge",
            "data": {"token": "local-token"},
        },
    ]
    assert driver._connected


@pytest.mark.parametrize(
    "kind,root,text,expected_root",
    [
        ("D", "", "hello", ""),
        ("O", "", "@paw hello", "post-A"),
        ("O", "root-A", "@paw hello", "root-A"),
    ],
)
async def test_dm_group_mention_and_thread_preserve_reply_root(
    mattermost,
    kind,
    root,
    text,
    expected_root,
):
    driver, peer, identity, _, requests, _ = mattermost
    event = await receive(mattermost, kind, root, text)
    assert event["acl_sender_id"] == "human-id"
    expected_parts = [{"type": "text", "text": "hello"}]
    if not root:
        count = 20 if kind == "D" else 10
        expected_parts.insert(
            0,
            {
                "type": "text",
                "text": (
                    f"[Recent {count} DM context messages]\n"
                    "[History ended, please answer the following questions "
                    "based on the above context]"
                ),
            },
        )
    assert event["content_parts"] == expected_parts
    assert event["conversation"]["type"] == ("dm" if kind == "D" else "group")
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    posted = [
        json.loads(req.content) for req in requests if req.method == "POST"
    ]
    assert posted == [
        {
            "channel_id": "channel-A",
            "message": "native answer",
            "root_id": expected_root,
        },
    ]


async def test_attachment_download_and_upload_preserve_bytes(
    mattermost,
):
    _, peer, identity, _, requests, root = mattermost
    event = await receive(mattermost, files=["file-A"])
    part = event["content_parts"][-1]
    assert (
        part["type"] == "file"
        and Path(part["file_url"]).read_bytes() == b"inbound attachment"
    )
    assert Path(part["file_url"]).is_relative_to(root)
    result = await send(peer, identity, event["response_handle"], parts=[part])
    assert result["state"] == "acknowledged"
    upload = next(req for req in requests if req.url.path == "/api/v4/files")
    assert upload.url.params["channel_id"] == "channel-A"
    assert b"inbound attachment" in upload.content
    post = next(
        req for req in reversed(requests) if req.url.path == "/api/v4/posts"
    )
    assert json.loads(post.content) == {
        "channel_id": "channel-A",
        "message": "",
        "root_id": "",
        "file_ids": ["uploaded-file"],
    }


async def test_unmentioned_group_is_filtered_and_stop_closes_socket_http(
    mattermost,
):
    driver, peer, _, socket, _, _ = mattermost
    await socket.inbox.put(
        json.dumps(
            {
                "event": "posted",
                "data": {
                    "channel_type": "O",
                    "post": json.dumps(
                        {
                            "id": "ignored",
                            "channel_id": "channel-A",
                            "user_id": "human",
                            "message": "no mention",
                        },
                    ),
                },
            },
        ),
    )
    await receive(mattermost, ident="barrier")
    assert len(peer.batches) == 1
    platform = driver._platform
    task, http = platform._task, platform._http
    await driver.stop()
    assert socket.closed and task.done() and http.is_closed
    assert driver._platform is None and not platform._event_tasks
