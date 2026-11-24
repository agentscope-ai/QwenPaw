# -*- coding: utf-8 -*-
"""Feishu native parsing, response cards and SDK lifecycle."""

import asyncio
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS
import httpx
import pytest
import pytest_asyncio
from qwenpaw.channel_protocol.models import SendParams
from tests.channel_support.driver import bind, module

pytestmark = pytest.mark.asyncio


def namespace(value):
    if isinstance(value, dict):
        return NS(**{k: namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [namespace(v) for v in value]
    return value


def ok(**values):
    return NS(success=lambda: True, data=NS(**values), code=0, msg="")


class WebSocket:
    def __init__(self, *args, **kwargs):
        self._conn = None

    async def _connect(self):
        self._conn = NS(close=self._disconnect)

    async def _ping_loop(self):
        await asyncio.Event().wait()

    async def _disconnect(self):
        self._conn = None


class Api:
    def __init__(self, kind, rows):
        self.kind, self.rows = kind, rows

    async def acreate(self, request):
        body = request.request_body
        row = {
            "kind": self.kind,
            "receive_id_type": getattr(request, "receive_id_type", None),
            "receive_id": getattr(body, "receive_id", None),
            "msg_type": getattr(body, "msg_type", None),
            "content": getattr(body, "content", None),
            "data": getattr(body, "data", None),
        }
        if self.kind == "image":
            row["bytes"] = body.image.read()
        elif self.kind == "file":
            row["file_name"] = body.file_name
            row["file_type"] = body.file_type
            row["bytes"] = body.file.read()
        self.rows.append(row)
        return ok(
            message_id="sent",
            image_key="img-uploaded",
            file_key="file-uploaded",
            card_id="card-A",
        )

    async def areply(self, request):
        self.rows.append(
            {
                "kind": "reply",
                "message_id": request.message_id,
                "msg_type": request.request_body.msg_type,
                "content": request.request_body.content,
            },
        )
        return ok(message_id="reply")

    async def aget(self, request):
        return NS(success=lambda: True, file=io.BytesIO(b"inbound-image"))

    async def acontent(self, request):
        self.rows.append(
            {
                "kind": "update",
                "card_id": request.card_id,
                "content": request.request_body.content,
            },
        )
        return ok()

    async def asettings(self, request):
        self.rows.append(
            {
                "kind": "settings",
                "card_id": request.card_id,
                "settings": request.request_body.settings,
            },
        )
        return ok()


@pytest_asyncio.fixture
async def native(tmp_path, monkeypatch):
    if not isinstance(
        getattr(sys.modules.get("lark_oapi"), "__file__", None),
        str,
    ):
        monkeypatch.delitem(sys.modules, "lark_oapi", raising=False)
    platform_module = module("feishu", "platform")
    rows = []
    client = NS(
        _config=NS(),
        im=NS(
            v1=NS(
                **{
                    name: Api(kind, rows)
                    for name, kind in [
                        ("message", "create"),
                        ("image", "image"),
                        ("file", "file"),
                        ("message_resource", "download"),
                        ("message_reaction", "reaction"),
                    ]
                },
            ),
        ),
        cardkit=NS(
            v1=NS(card=Api("card", rows), card_element=Api("update", rows)),
        ),
    )

    class Builder:
        def __getattr__(self, name):
            return lambda *args: self

        def build(self):
            return client

    monkeypatch.setattr(platform_module.lark.Client, "builder", Builder)
    monkeypatch.setattr(
        platform_module.TokenManager,
        "get_self_tenant_token",
        staticmethod(lambda _: "token"),
    )
    monkeypatch.setattr(platform_module.lark_ws, "Client", WebSocket)
    real_http = httpx.AsyncClient

    def http_client(**kwargs):
        return real_http(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"code": 0, "bot": {"open_id": "ou_bot"}},
                ),
            ),
        )

    monkeypatch.setattr(platform_module.httpx, "AsyncClient", http_client)
    driver = module("feishu").FeishuDriver()
    peer, identity = bind("feishu", driver, tmp_path)
    await driver.start(
        {
            "app_id": "app-test",
            "app_secret": "secret",
            "workspace_dir": str(tmp_path),
            "streaming_enabled": True,
            "require_mention": True,
        },
    )
    try:
        yield NS(
            driver=driver,
            peer=peer,
            identity=identity.to_mapping(),
            rows=rows,
        )
    finally:
        await driver.stop()


def message(
    mid,
    *,
    sender="ou_alice",
    group=False,
    mentioned=False,
    thread="",
    kind="text",
    content=None,
    **header,
):
    return {
        "header": {"event_id": mid, **header},
        "event": {
            "sender": {"sender_id": {"open_id": sender}, "name": "Alice"},
            "message": {
                "message_id": mid,
                "chat_id": "oc_room",
                "chat_type": "group" if group else "p2p",
                "thread_id": thread,
                "message_type": kind,
                "content": json.dumps(
                    content
                    or {"text": "@_user_1 hello" if mentioned else "hello"},
                ),
                "mentions": (
                    [{"id": {"open_id": "ou_bot"}, "key": "@_user_1"}]
                    if mentioned
                    else []
                ),
            },
        },
    }


async def ingress(rt, value):
    await rt.driver._platform._dispatch_native_message(
        namespace(value),
        rt.driver._message,
    )
    return rt.peer.batches[-1]["events"][0] if rt.peer.batches else None


async def send(rt, handle, parts=None, **fields):
    params = SendParams.from_mapping(
        {
            **rt.identity,
            "to_handle": handle,
            "delivery_id": "delivery",
            "operation": "message.create",
            **(
                {"content_parts": parts or []}
                if not fields.get("operation", "").startswith("stream.")
                else {}
            ),
            **fields,
        },
    )
    return await rt.peer.methods["channel.send"](params, None)


@pytest.mark.parametrize("group", [False, True])
async def test_dm_and_group_mention_keep_sender_and_reply_target(
    native,
    group,
):
    rt = native
    if group:
        await ingress(rt, message("ignored", group=True))
        assert not rt.peer.batches
    event = await ingress(
        rt,
        message("accepted", group=group, mentioned=group),
    )
    assert event["acl_sender_id"] == "ou_alice"
    assert event["conversation"]["type"] == ("group" if group else "dm")
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    assert (
        await send(
            rt,
            event["response_handle"],
            [{"type": "text", "text": "answer"}],
        )
    )["state"] == "acknowledged"
    row = next(r for r in rt.rows if r["kind"] == "create")
    assert row["receive_id"] == ("oc_room" if group else "ou_alice")
    assert "answer" in row["content"]


async def test_image_download_and_upload_preserve_bytes(native, tmp_path):
    rt = native
    event = await ingress(
        rt,
        message("image", kind="image", content={"image_key": "native-image"}),
    )
    part = next(p for p in event["content_parts"] if p["type"] == "image")
    assert (
        Path(part["image_url"].replace("file://", "")).read_bytes()
        == b"inbound-image"
    )
    path = tmp_path / "image.png"
    path.write_bytes(b"outbound-image")
    assert (
        await send(
            rt,
            event["response_handle"],
            [{"type": "image", "image_url": str(path)}],
        )
    )["state"] == "acknowledged"
    assert (
        next(r for r in rt.rows if r["kind"] == "image")["bytes"]
        == b"outbound-image"
    )
    assert any(
        r["msg_type"] == "image"
        and json.loads(r["content"])["image_key"] == "img-uploaded"
        for r in rt.rows
        if "msg_type" in r
    )


async def test_file_upload_decodes_percent_encoded_locator_name(
    native,
    tmp_path,
):
    rt = native
    event = await ingress(rt, message("file"))
    path = tmp_path / "附件-主要工作工时对标测算情况.docx"
    path.write_bytes(b"outbound-file")
    locator = path.as_uri()
    assert "%E9%99%84" in locator
    assert (
        await send(
            rt,
            event["response_handle"],
            [{"type": "file", "file_url": locator}],
        )
    )["state"] == "acknowledged"
    row = next(item for item in rt.rows if item["kind"] == "file")
    assert row["file_name"] == "附件-主要工作工时对标测算情况.docx"
    assert row["file_type"] == "doc"
    assert row["bytes"] == b"outbound-file"


async def test_file_upload_decodes_https_locator_name(native):
    rt = native
    event = await ingress(rt, message("https"))
    assert (
        await send(
            rt,
            event["response_handle"],
            [
                {
                    "type": "file",
                    "file_url": "https://example.com/a/%E9%99%84%E4%BB%B6"
                    ".docx?token=1",
                },
            ],
        )
    )["state"] == "acknowledged"
    row = next(item for item in rt.rows if item["kind"] == "file")
    assert row["file_name"] == "附件.docx"


async def test_upload_file_name_keeps_windows_basename(native):
    platform = module("feishu", "platform")
    name = platform.LarkOapiPlatform._upload_file_name(
        {"file_url": "D:\\dir\\附件.docx"},
        "D:\\dir\\附件.docx",
    )
    assert name == "附件.docx"


async def test_file_upload_prefers_explicit_filename(native, tmp_path):
    rt = native
    event = await ingress(rt, message("rename"))
    path = tmp_path / "原文.docx"
    path.write_bytes(b"outbound-file")
    assert (
        await send(
            rt,
            event["response_handle"],
            [
                {
                    "type": "file",
                    "file_url": path.as_uri(),
                    "filename": "改名后.docx",
                },
            ],
        )
    )["state"] == "acknowledged"
    row = next(item for item in rt.rows if item["kind"] == "file")
    assert row["file_name"] == "改名后.docx"


async def test_thread_reply_rejection_logs_only_diagnostic_fields(
    native,
    monkeypatch,
    caplog,
):
    event = await ingress(native, message(f"reply-source", thread=f"topic"))
    api = native.driver._platform._client.im.v1.message

    async def reject(_request):
        return NS(success=lambda: False, code=230001, msg=f"private-response")

    monkeypatch.setattr(api, f"areply", reject)
    result = await send(
        native,
        event[f"response_handle"],
        [{f"type": f"text", f"text": f"private-message"}],
    )
    assert result[f"reason_code"] == f"MESSAGE_REJECTED"
    assert f"send rejected: thread=True code=230001" in caplog.text
    assert f"private-response" not in caplog.text
    assert f"private-message" not in caplog.text


async def test_stream_finalizes_same_card(native):
    rt = native
    event = await ingress(rt, message("stream"))
    handle = event["response_handle"]
    assert (
        await send(
            rt,
            handle,
            operation="stream.start",
            stream_type="message",
            sequence=0,
            accumulated_text="first",
        )
    )["state"] == "acknowledged"
    params = SendParams.from_mapping(
        {
            **rt.identity,
            "to_handle": handle,
            "delivery_id": "end",
            "target_delivery_id": "delivery",
            "operation": "stream.end",
            "stream_type": "message",
            "sequence": 1,
            "accumulated_text": "final answer",
        },
    )
    assert (await rt.peer.methods["channel.send"](params, None))[
        "state"
    ] == "acknowledged"
    assert [r["card_id"] for r in rt.rows if r["kind"] == "update"] == [
        "card-A",
    ]
    assert [r["content"] for r in rt.rows if r["kind"] == "update"][
        -1
    ] == "final answer"
    assert "first" in next(r["data"] for r in rt.rows if r["kind"] == "card")
    settings = next(r["settings"] for r in rt.rows if r["kind"] == "settings")
    assert json.loads(settings)["config"]["streaming_mode"] is False
    assert len([r for r in rt.rows if r["kind"] == "create"]) == 1


async def test_legitimate_approval_action_maps_authenticated_actor(
    native,
    caplog,
):
    caplog.set_level(f"INFO", logger=f"qwenpaw_channel_feishu")
    rt = native
    event = await ingress(rt, message("approval", group=True, mentioned=True))
    assert (
        await send(
            rt,
            event["response_handle"],
            [{"type": "text", "text": "Allow?"}],
            approval={
                "request_id": "rid-A",
                "tool_name": "shell",
                "severity": "high",
            },
        )
    )["state"] == "acknowledged"
    card = json.loads(
        next(r for r in rt.rows if r["kind"] == "create")["content"],
    )
    action = card["elements"][-1]["actions"][0]["value"]
    payload = namespace(
        {
            "header": {"event_id": "click"},
            "event": {
                "operator": {"open_id": "ou_alice"},
                "action": {"value": {}},
            },
        },
    )
    payload.event.action.value = action
    rt.driver._platform._on_card_sync(payload, rt.driver._card)
    async with asyncio.timeout(2):
        while len(rt.peer.batches) < 2:
            await asyncio.sleep(0.005)
    click = rt.peer.batches[-1]["events"][0]
    assert click["acl_sender_id"] == "ou_alice"
    assert click["content_parts"] == [
        {"type": "text", "text": "/approval approve rid-A"},
    ]
    assert f"Feishu approval card accepted by platform" in caplog.text
    assert f"Feishu approval callback: accepted=True" in caplog.text
    assert f"rid-A" not in caplog.text


async def test_stop_joins_sdk_thread_and_closes_http(native):
    platform = native.driver._platform
    thread, client = platform._ws_thread, platform._http_client
    await native.driver.stop()
    assert not thread.is_alive() and client.is_closed
    assert native.driver._platform is None


@pytest_asyncio.fixture
async def reconnect(monkeypatch):
    """Drive real supervisor/connect code through explicitly gated attempts."""
    driver_module = module("feishu")
    driver = driver_module.FeishuDriver()
    states, calls = [], []
    attempts = asyncio.Queue()
    outcomes = {"disconnect": [], "connect": []}
    connected = asyncio.Event()
    disconnected = asyncio.Event()
    disconnected.set()

    async def state(value):
        states.append(value)
        if value == "connected":
            connected.set()

    async def wait_disconnected():
        await disconnected.wait()
        disconnected.clear()

    async def operation(name):
        calls.append(name)
        if outcomes[name]:
            error = outcomes[name].pop(0)
            if error is not None:
                raise error

    async def disconnect():
        await operation("disconnect")

    async def connect(*callbacks):
        await operation("connect")

    async def sleep(delay):
        gate = asyncio.Event()
        await attempts.put((delay, gate))
        await gate.wait()

    async def close():
        calls.append("close")

    # Replace only this module's asyncio reference; event-loop scheduling and
    # pytest's own asyncio remain real. No wall-clock backoff sleeps are used.
    driver._context = NS(set_platform_state=state)
    driver._platform = NS(
        wait_disconnected=wait_disconnected,
        disconnect=disconnect,
        connect=connect,
        close=close,
    )
    # _connect() and stop() need the real asyncio primitives.
    monkeypatch.setattr(
        driver_module,
        "asyncio",
        NS(sleep=sleep, Event=asyncio.Event, gather=asyncio.gather),
    )
    driver._stopping = False
    driver._connected = True
    driver._supervisor = asyncio.create_task(driver._supervise())

    async def next_attempt():
        return await asyncio.wait_for(attempts.get(), timeout=1)

    try:
        yield NS(
            driver=driver,
            states=states,
            calls=calls,
            outcomes=outcomes,
            next_attempt=next_attempt,
            connected=connected,
        )
    finally:
        await driver.stop()


async def test_supervisor_retries_initial_cleanup_failure(reconnect):
    rt = reconnect
    rt.outcomes["disconnect"] = [RuntimeError("cleanup timeout"), None]
    delay, gate = await rt.next_attempt()
    assert delay == 1.0
    gate.set()
    delay, gate = await rt.next_attempt()
    assert delay == 2.0
    assert rt.calls == ["disconnect"]
    assert not rt.driver._supervisor.done()
    gate.set()
    # A successful reconnect returns the supervisor to wait_disconnected().
    await asyncio.wait_for(rt.connected.wait(), timeout=1)
    assert rt.calls == ["disconnect", "disconnect", "connect"]
    assert rt.states[-1] == "connected"
    assert "failed" not in rt.states


async def test_supervisor_retries_connect_and_cleanup_failure(reconnect):
    rt = reconnect
    rt.outcomes["disconnect"] = [None, RuntimeError("cleanup timeout"), None]
    rt.outcomes["connect"] = [RuntimeError("connect failed"), None]
    _, gate = await rt.next_attempt()
    gate.set()
    delay, gate = await rt.next_attempt()
    assert delay == 2.0
    assert rt.calls == ["disconnect", "connect"]
    gate.set()
    delay, gate = await rt.next_attempt()
    assert delay == 4.0
    assert rt.calls == ["disconnect", "connect", "disconnect"]
    assert not rt.driver._supervisor.done()
    gate.set()
    await asyncio.wait_for(rt.connected.wait(), timeout=1)
    assert rt.calls == [
        "disconnect",
        "connect",
        "disconnect",
        "disconnect",
        "connect",
    ]
    assert rt.states[-1] == "connected"
    assert "failed" not in rt.states


async def test_supervisor_stop_cancels_persistent_cleanup_retry(reconnect):
    rt = reconnect
    rt.outcomes["disconnect"] = [RuntimeError("cleanup stuck")] * 8
    for expected_delay in (1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0):
        delay, gate = await rt.next_attempt()
        assert delay == expected_delay
        assert "connect" not in rt.calls
        gate.set()
    await rt.next_attempt()
    task = rt.driver._supervisor
    async with asyncio.timeout(1):
        await rt.driver.stop()
    assert task.cancelled()
    assert rt.driver._supervisor is None
    assert rt.calls == ["disconnect"] * 7 + ["close"]
    assert rt.states[-1] == "disconnected"
