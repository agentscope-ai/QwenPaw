"""Real private Driver/Platform; only HTTP and host RPC doubled."""

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from g2_shared_response_suite import finish, prepare
from onebot_native_suite import HostBoundary
from qwenpaw.channel_protocol.models import IdentityParams, SendParams
from qwenpaw.channel_protocol.shared_worker import DriverContext

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.asyncio


@pytest.fixture
def private(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "plugins/channel/wechat"))
    return SimpleNamespace(
        driver=importlib.import_module("qwenpaw_channel_wechat.driver"),
        platform=importlib.import_module("qwenpaw_channel_wechat.platform"),
        client=importlib.import_module("qwenpaw_channel_wechat.client"),
    )


def message(number, *, user="user123", text="Hello", group=""):
    return {
        "message_type": 1,
        "from_user_id": user,
        "to_user_id": "bot123",
        "context_token": "context-" + str(number),
        "msg_id": str(number),
        "group_id": group,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }


async def collecting_platform(private, tmp_path):
    events = []

    async def collect(value):
        events.append(value)
        await asyncio.sleep(0)

    async def state(_value):
        pass

    platform = private.platform.WeChatPlatform(
        {"bot_token_file": str(tmp_path / "token")}, collect, state
    )
    return platform, events


async def test_native_id_dedup_concurrent_accepts_ten_and_caps_two_thousand(
    private, tmp_path
):
    platform, events = await collecting_platform(private, tmp_path)
    await asyncio.gather(
        *[
            platform._message(message(i % 10, text="batch" + str(i % 10)))
            for i in range(500)
        ]
    )
    assert len(events) == 10
    assert 500 - len(events) == 490
    assert len({row["event_id"] for row in events}) == 10
    for number in range(2100):
        empty = message("empty-" + str(number))
        empty["item_list"] = []
        await platform._message(empty)
    assert len(platform._processed) <= 2000
    assert "context-0" not in platform._processed
    assert "context-empty-2099" in platform._processed
    assert len(events) == 10


async def test_text_dedup_is_sender_scoped_thirty_seconds_and_id_stays_fenced(
    private, tmp_path, monkeypatch
):
    platform, events = await collecting_platform(private, tmp_path)
    clock = [100.0]
    monkeypatch.setattr(
        private.platform, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    await platform._message(message(1))
    await platform._message(message(2))
    await platform._message(message(3, user="other"))
    assert [row["sender_id"] for row in events] == ["user123", "other"]
    clock[0] = 129.999
    await platform._message(message(4))
    assert len(events) == 2
    clock[0] = 130.0
    await platform._message(message(5))
    assert len(events) == 3
    await platform._message(message(1))
    assert len(events) == 3


@pytest_asyncio.fixture
async def native_driver(private, monkeypatch, tmp_path):
    requests, results, clients = [], [], []
    polling = asyncio.Event()
    real_client = httpx.AsyncClient

    async def transport(request):
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        requests.append((path, body))
        if path.endswith("/getupdates"):
            await polling.wait()
            return httpx.Response(200, json={"ret": 0, "msgs": []})
        if path.endswith("/getconfig"):
            return httpx.Response(200, json={"typing_ticket": "ticket-A"})
        if path.endswith("/sendtyping"):
            return httpx.Response(200, json={"ret": 0})
        assert path.endswith("/sendmessage"), path
        return httpx.Response(
            200, json=results.pop(0) if results else {"ret": 0}
        )

    def external_client(**kwargs):
        client = real_client(
            **kwargs, transport=httpx.MockTransport(transport), trust_env=False
        )
        clients.append(client)
        return client

    monkeypatch.setattr(private.client.httpx, "AsyncClient", external_client)
    driver, peer = private.driver.WeChatDriver(), HostBoundary()
    identity = IdentityParams("wechat", "wechat-private-closeout", 1)
    driver.bind(DriverContext(peer, identity))
    try:
        await driver.start(
            {
                "bot_token": "temporary-test-token",
                "base_url": "https://local-boundary.test",
                "bot_token_file": str(tmp_path / "token"),
                "workspace_dir": str(tmp_path),
            }
        )
        yield SimpleNamespace(
            driver=driver,
            peer=peer,
            identity=identity.to_mapping(),
            requests=requests,
            results=results,
        )
    finally:
        await driver.stop()
        assert driver._platform is None
        assert all(client.is_closed for client in clients)


async def test_real_driver_group_acl_session_and_reference_counted_typing(
    native_driver,
):
    from extension_process_suite import eventually

    rt = native_driver
    platform = rt.driver._platform
    first = message(1, text="Hello Group", group="group456")
    await platform._message(first)
    await platform._message(first)
    ignored = message(2)
    ignored["message_type"] = 2
    await platform._message(ignored)
    assert len(rt.peer.batches) == 1
    event = rt.peer.batches[0]["events"][0]
    assert event["sender_id"] == event["acl_sender_id"] == "user123"
    assert event["metadata"]["session_id"] == "wechat:group:group456"
    assert event["metadata"]["is_group"] is True
    assert event["metadata"]["wechat_group_id"] == "group456"
    assert event["conversation"] == {
        "id": "group456",
        "type": "group",
        "thread_id": None,
    }
    assert event["content_parts"] == [{"type": "text", "text": "Hello Group"}]
    handle = event["response_handle"]
    second = await rt.peer.methods["channel.response.open"](
        {**rt.identity, "to_handle": "wechat:user123", "meta": {}}, None
    )
    other = second["response_handle"]
    await prepare(rt.peer, rt.identity, other)
    await eventually(
        lambda: any(
            path.endswith("/sendtyping") and body["status"] == 1
            for path, body in rt.requests
        )
    )
    assert len(platform._typing_users) == 1
    assert platform._typing_users["user123"]["handles"] == {handle, other}
    await finish(rt.peer, rt.identity, handle)
    assert set(platform._typing) == {other}
    assert not any(
        path.endswith("/sendtyping") and body["status"] == 2
        for path, body in rt.requests
    )
    await finish(rt.peer, rt.identity, other)
    assert not platform._typing and not platform._typing_users
    assert sum(path.endswith("/getconfig") for path, _ in rt.requests) == 1
    stops = [
        body
        for path, body in rt.requests
        if path.endswith("/sendtyping") and body["status"] == 2
    ]
    assert len(stops) == 1
    assert stops[0]["ilink_user_id"] == "user123"


async def send(rt, handle, delivery_id, text):
    return await rt.peer.methods["channel.send"](
        SendParams.from_mapping(
            {
                **rt.identity,
                "delivery_id": delivery_id,
                "to_handle": handle,
                "operation": "message.create",
                "content_parts": [{"type": "text", "text": text}],
            }
        ),
        None,
    )


async def test_ret_minus_two_fences_later_sends_in_same_real_driver_response(
    native_driver,
):
    rt = native_driver
    opened = await rt.peer.methods["channel.response.open"](
        {
            **rt.identity,
            "to_handle": "wechat:user123",
            "meta": {"wechat_context_token": "ctx_token"},
        },
        None,
    )
    handle = opened["response_handle"]
    rt.results.append({"ret": -2})
    result = await send(rt, handle, "invalid-context-A", "first")
    assert result["state"] == "failed"
    assert result["reason_code"] == "CONTEXT_TOKEN_INVALID"
    assert result["retryable"] is False
    assert await send(rt, handle, "invalid-context-A", "first") == result
    later = await send(rt, handle, "invalid-context-B", "must not send")
    assert later["state"] == "failed"
    assert later["reason_code"] == "CONTEXT_TOKEN_INVALID"
    sent = [
        body for path, body in rt.requests if path.endswith("/sendmessage")
    ]
    assert len(sent) == 1
    assert sent[0]["msg"]["to_user_id"] == "user123"
    assert sent[0]["msg"]["context_token"] == "ctx_token"
    await finish(rt.peer, rt.identity, handle)


async def test_real_native_long_text_chunks_reconstruct_original_five_thousand(
    native_driver,
):
    rt = native_driver
    rt.driver._platform._contexts["user123"] = "ctx_token"
    opened = await rt.peer.methods["channel.response.open"](
        {**rt.identity, "to_handle": "wechat:user123", "meta": {}}, None
    )
    handle = opened["response_handle"]
    result = await send(rt, handle, "long-text", "A" * 5000)
    assert result["state"] == "acknowledged"
    sent = [
        body["msg"]
        for path, body in rt.requests
        if path.endswith("/sendmessage")
    ]
    assert len(sent) > 1
    assert (
        "".join(row["item_list"][0]["text_item"]["text"] for row in sent)
        == "A" * 5000
    )
    assert all(row["to_user_id"] == "user123" for row in sent)
    assert all(row["context_token"] == "ctx_token" for row in sent)
    assert len({row["client_id"] for row in sent}) == len(sent)
    await finish(rt.peer, rt.identity, handle)
