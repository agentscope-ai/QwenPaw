# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""B4 real host/child contracts; only the external SDK/network is
controlled.
"""

import asyncio
from dataclasses import replace
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace as NS

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN = (
    "dingtalk_stream",
    "qwenpaw.app.channels.dingtalk",
    "plugin_dingtalk",
    "dingtalk.platform",
    "dingtalk.channel",
    "dingtalk.driver",
    "_qwenpaw_shared_driver.platform",
    "alibabacloud_dingtalk",
    "dingtalk.sdk",
    "dingtalk.handler",
    "dingtalk.transport",
)


class ParentPlatformGuard(importlib.abc.MetaPathFinder):
    """A caught ImportError cannot hide an attempted host SDK import."""

    def find_spec(self, fullname, _path=None, _target=None):
        if any(
            fullname == name or fullname.startswith(name + ".")
            for name in FORBIDDEN
        ):
            raise AssertionError(f"Platform imported in host: {fullname}")


sys.meta_path.insert(0, ParentPlatformGuard())


def digest(root):
    result = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name, data = (
                path.relative_to(root).as_posix().encode(),
                path.read_bytes(),
            )
            result.update(len(name).to_bytes(8, "big"))
            result.update(name)
            result.update(len(data).to_bytes(8, "big"))
            result.update(data)
    return result.hexdigest()


async def eventually(predicate, timeout=6):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def restart(rt):
    generation = rt.process.health_snapshot()["generation"]
    await rt.process.stop()
    rt.spec = replace(rt.spec, generation=generation + 1)
    await rt.process.start(rt.spec)
    async with asyncio.timeout(6):
        while (await rt.channel.health_check()).get(
            "platform_state",
        ) != "connected":
            await asyncio.sleep(0.01)


WEBHOOK = "https://oapi.dingtalk.com/robot/sendBySession?session=old-session"
META = {
    "conversation_id": "cid-conversation",
    "conversation_type": "group",
    "is_group": True,
    "sender_staff_id": "staff-one",
    "sender_dingtalk_id": "ding1234",
    "_api_send": True,
}


def message(mid, *, group=False, mentioned=True, content=None, **fields):
    body = {
        "msgId": mid,
        "msgtype": "text",
        "text": {"content": "hello"},
        "senderId": "ding1234",
        "senderNick": "Alice",
        "senderStaffId": "staff-one",
        "conversationId": "cid-original",
        "conversationType": "2" if group else "1",
        "sessionWebhook": WEBHOOK,
        "sessionWebhookExpiredTime": 9999999999999,
        "isInAtList": mentioned,
        "robotCode": "client-one",
        "chatbotUserId": "robot-user",
        **fields,
    }
    if content is not None:
        body.update(content)
    return {
        "specVersion": "1.0",
        "type": "CALLBACK",
        "headers": {
            "appId": "client-one",
            "messageId": mid,
            "time": "1700000000000",
            "topic": "/v1.0/im/bot/messages/get",
            "contentType": "application/json",
        },
        "data": json.dumps(body),
    }


def set_admission(channel, callback):
    """Adapt the direct-proxy fixture to acknowledged local admission."""
    from qwenpaw.app.channels.unified_queue_manager import EnqueueResult

    async def admit(payload):
        callback(payload)
        return EnqueueResult(True)

    channel.set_enqueue_async(admit)


@pytest.fixture
def proxy_api():
    name = "qwenpaw.app.channels.isolated_proxy"
    assert importlib.util.find_spec(name), "B4 IsolatedChannelProxy is missing"
    api = importlib.import_module(name)
    assert hasattr(
        api,
        "IsolatedChannelProxy",
    ), "B4 host proxy class is missing"
    return api.IsolatedChannelProxy


@pytest_asyncio.fixture
async def runtime(proxy_api, tmp_path):
    from qwenpaw.app.channels.process_supervisor import (
        ChannelProcess,
        LaunchSpec,
    )
    from qwenpaw.schemas import Message, RunStatus, TextContent

    owned = []

    async def make(agent=None, initial_files=None, **settings):
        index = len(owned)
        work = tmp_path / f"work-{index}"
        work.mkdir()
        for name, value in (initial_files or {}).items():
            (work / name).write_text(value)
        code = tmp_path / f"code-{index}"
        plugin = code / "dingtalk"
        shutil.copytree(
            ROOT / "plugins/channel/dingtalk",
            code,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        fixture = Path(__file__).with_name("dingtalk_process_boundary.py")
        (plugin / "boundary.py").write_text(
            f"WORK = {str(work)!r}\n" + fixture.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        descriptor = json.loads((code / "channel.json").read_text())
        descriptor["entrypoint"]["module"] = "dingtalk.boundary"
        (code / "channel.json").write_text(json.dumps(descriptor))
        config = {
            "enabled": True,
            "client_id": "client-one",
            "client_secret": "test-only",
            "no_text_debounce": False,
            "media_dir": str(work / "media"),
            "workspace_dir": str(work),
            **settings,
        }
        spec = LaunchSpec(
            python_executable=sys.executable,
            support_root=ROOT / "src",
            code_root=code,
            descriptor_path=code / "channel.json",
            source_revision=digest(code),
            channel_key="dingtalk",
            instance_id=f"workspace-{index}",
            generation=1,
            qwenpaw_version="2.2.2b4",
            config=config,
            startup_timeout=4,
            shutdown_timeout=2.0,
        )
        requests, queued, pids = [], [], []

        async def default_agent(request):
            requests.append(request)
            pids.append(os.getpid())
            yield Message(
                object="message",
                status=RunStatus.Completed,
                role="assistant",
                content=[TextContent(text="host answer")],
            )

        process = ChannelProcess()
        channel = proxy_api(
            agent or default_agent,
            launch_spec=spec,
            channel_process=process,
            workspace_dir=work,
        )
        owned.append(channel)
        set_admission(channel, queued.append)
        rt = NS(
            channel=channel,
            process=process,
            spec=spec,
            work=work,
            requests=requests,
            queued=queued,
            pids=pids,
        )

        def rows(kind=None):
            path = work / "ledger.jsonl"
            records = (
                [json.loads(line) for line in path.read_text().splitlines()]
                if path.exists()
                else []
            )
            return [r for r in records if kind is None or r["kind"] == kind]

        def emit(event):
            with (work / "inbox.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event) + "\n")

        rt.rows, rt.emit = rows, emit
        await channel.start()
        await eventually(lambda: rows("connected"))
        async with asyncio.timeout(6):
            while (await channel.health_check()).get(
                "platform_state",
            ) != "connected":
                await asyncio.sleep(0.01)
        return rt

    yield make
    for channel in reversed(owned):
        await asyncio.wait_for(channel.stop(), 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_native_message_runs_host_agent_and_sends_from_real_child(
    runtime,
    group,
):
    from qwenpaw.app.channels.base import BaseChannel
    from qwenpaw.plugins.execution.process import PluginProcess

    rt = await runtime()
    rt.emit(message("first", group=group))
    await eventually(lambda: len(rt.queued) == 1)
    native = rt.queued[0]
    assert native["acl_sender_id"] == "ding1234"
    assert native["sender_id"] == "Alice#1234"
    assert native["meta"]["sender_staff_id"] == "staff-one"
    assert native["meta"]["response_handle"]
    await rt.channel.consume_one(native)
    sent = [r for r in rt.rows("http") if r["payload"]]
    assert len(sent) == 1
    assert sent[0]["url"] == WEBHOOK
    assert sent[0]["payload"]["markdown"]["text"].strip() == "host answer"
    assert isinstance(rt.channel, BaseChannel)
    assert isinstance(rt.process, PluginProcess)
    assert rt.requests[0].user_id == "Alice#1234"
    assert rt.requests[0].channel == "dingtalk"
    assert rt.pids == [os.getpid()]
    assert sent[0]["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
    assert not any(name.startswith(FORBIDDEN) for name in sys.modules)
    await rt.channel.stop()
    assert rt.process.health_snapshot()["pid"] is None
    assert rt.rows("http-close")[-1]["closed"]


async def inbound(rt, event):
    count = len(rt.queued)
    rt.emit(event)
    await eventually(lambda: len(rt.queued) > count)
    return rt.queued[-1]


def deliveries(rt):
    return [row for row in rt.rows("http") if row["payload"]]


def persisted_routes(rt):
    found = {}

    def walk(value):
        if isinstance(value, dict):
            if {
                "response_handle",
                "route_refs",
                "resource_refs",
            } <= value.keys():
                found[value["response_handle"]] = value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for path in (rt.work / "channel_state").glob("*.json"):
        walk(json.loads(path.read_text()))
    return found


def identity(rt):
    return {
        "channel_key": "dingtalk",
        "instance_id": rt.spec.instance_id,
        "generation": rt.process.health_snapshot()["generation"],
    }


def finish_params(rt, handle):
    return {**identity(rt), "response_handle": handle, "outcome": "cancelled"}


async def stream_request(rt, mid):
    native = await inbound(rt, message(mid, group=True))
    request = rt.channel.build_agent_request_from_native(native)
    return (
        request,
        rt.channel.get_to_handle_from_request(request),
        dict(request.channel_meta),
    )


async def public_stream(rt, handle, *, sequence=7):
    start = {
        **identity(rt),
        "delivery_id": "stream-resource",
        "to_handle": handle,
        "operation": "stream.start",
        "stream_type": "message",
        "sequence": 0,
        "accumulated_text": "started",
    }
    assert (await rt.process.call("channel.send", start))[
        "state"
    ] == "acknowledged"
    return await rt.process.call(
        "channel.send",
        {
            **start,
            "delivery_id": "delta-attempt",
            "operation": "stream.delta",
            "target_delivery_id": "stream-resource",
            "sequence": sequence,
            "accumulated_text": "partial",
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
async def test_original_identity_short_hash_group_hash_and_proactive_handle(
    runtime,
    shared,
):
    rt = await runtime(share_session_in_group=shared)
    first = await inbound(
        rt,
        message("session-a", group=True, conversationId="prefixA_same_suffix"),
    )
    other = await inbound(
        rt,
        message("session-b", group=True, conversationId="prefixB_same_suffix"),
    )
    request = rt.channel.build_agent_request_from_native(first)
    request2 = rt.channel.build_agent_request_from_native(other)
    assert request.user_id == ("group" if shared else "Alice#1234")
    assert request.channel_meta["sender_dingtalk_id"] == "ding1234"
    assert request.channel_meta["sender_staff_id"] == "staff-one"
    assert request.channel_meta["session_webhook"] == WEBHOOK
    expected = (
        hashlib.sha256(b"prefixA_same_suffix").hexdigest()[:16]
        if shared
        else "prefixA_same_suffix"[-8:]
    )
    # Match the baseline algorithm exactly through its published golden hash.
    if shared:
        assert request.session_id != request2.session_id
        assert "_" not in request.session_id
    else:
        assert request.session_id == request2.session_id
    assert request.session_id == expected
    from qwenpaw.channel_protocol.targets import decode_reply_target

    target = rt.channel.to_handle_from_target(
        user_id=request.user_id,
        session_id=request.session_id,
    )
    assert decode_reply_target(target) == {
        "user_id": "group" if shared else "Alice#1234",
        "session_id": expected,
    }
    dm = await inbound(rt, message("dm-identity", group=False))
    assert (
        rt.channel.build_agent_request_from_native(dm).user_id == "Alice#1234"
    )
    assert rt.channel.resolve_session_id("one", {}) == "dingtalk:one"
    other_member = await inbound(
        rt,
        message(
            "session-other-member",
            group=True,
            conversationId="prefixA_same_suffix",
            senderId="ding5678",
            senderNick="Bob",
            senderStaffId="staff-two",
        ),
    )
    assert other_member["acl_sender_id"] == "ding5678"
    assert (
        rt.channel.get_debounce_key(first)
        == rt.channel.get_debounce_key(other_member)
    ) is shared


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["meta", "url", "old-store", "new-store"])
async def test_direct_and_legacy_webhook_routes_bypass_openapi(
    runtime,
    source,
):
    handle, meta = "dingtalk:sw:legacy", {"_api_send": True}
    files = {}
    if source.endswith("store"):
        value = (
            WEBHOOK
            if source == "old-store"
            else {
                "webhook": WEBHOOK,
                "conversation_id": "cid-conversation",
                "conversation_type": "group",
            }
        )
        files["dingtalk_session_webhooks.json"] = json.dumps({handle: value})
    elif source == "meta":
        meta["sessionWebhook"] = WEBHOOK
    else:
        handle = WEBHOOK
    rt = await runtime(initial_files=files)
    await rt.channel.send(handle, "hello", meta)
    assert len(deliveries(rt)) == 1
    assert deliveries(rt)[0]["url"] == WEBHOOK
    assert deliveries(rt)[0]["payload"]["markdown"]["text"].strip() == "hello"
    assert rt.rows("group") == rt.rows("dm") == []
    assert all(r["kind"] == "terminal" for r in persisted_routes(rt).values())


@pytest.mark.asyncio
@pytest.mark.parametrize("group,method", [(True, "group"), (False, "dm")])
async def test_proactive_openapi_preserves_group_and_staff_identity(
    runtime,
    group,
    method,
):
    rt = await runtime()
    await rt.channel.send(
        "dingtalk:sw:missing",
        "hello",
        {
            **META,
            "is_group": group,
            "conversation_type": "group" if group else "dm",
        },
    )
    sent = rt.rows(method)
    assert len(sent) == 1
    request = sent[0]["request"]
    assert request["robotCode"] == "client-one"
    assert request["msgKey"] == "sampleMarkdown"
    assert json.loads(request["msgParam"])["text"].strip() == "hello"
    assert sent[0]["headers"]["x-acs-dingtalk-access-token"] == "api-token"
    assert (
        request["openConversationId"] == "cid-conversation"
        if group
        else request["userIds"] == ["staff-one"]
    )


@pytest.mark.asyncio
async def test_known_expired_webhook_falls_back_once_and_persists_invalidation(
    runtime,
):
    rt = await runtime()
    native = await inbound(rt, message("expired", group=True))
    await rt.channel.consume_one(native)
    (rt.work / "send-mode").write_text("webhook-rejected")
    await rt.channel.send(
        rt.channel.to_handle_from_target(
            user_id="Alice#1234",
            session_id=rt.requests[0].session_id,
        ),
        "again",
        dict(META),
    )
    assert len(deliveries(rt)) == 2
    assert len(rt.rows("group")) == 1
    assert (
        json.loads(rt.rows("group")[0]["request"]["msgParam"])["text"].strip()
        == "again"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("parts", [False, True])
@pytest.mark.parametrize("failure", ["unknown", "payload", "json", "empty"])
async def test_unknown_webhook_never_falls_back_or_exposes_secrets(
    runtime,
    parts,
    failure,
):
    from qwenpaw.schemas import TextContent

    rt = await runtime()
    (rt.work / "send-mode").write_text("webhook-" + failure)
    with pytest.raises(Exception) as caught:
        if parts:
            await rt.channel.send_content_parts(
                WEBHOOK,
                [TextContent(text="once")],
                dict(META),
            )
        else:
            await rt.channel.send(WEBHOOK, "once", dict(META))
    assert getattr(caught.value, "side_effect_possible", None) is True
    assert "test-only-secret" not in str(caught.value)
    assert len(deliveries(rt)) == 1
    assert rt.rows("group") == rt.rows("dm") == []
    from qwenpaw.channel_protocol.response_receipts import ResponseReceiptStore

    archived = [
        row
        for path in (rt.work / "channel_state").glob("*.receipts.sqlite3")
        for row in ResponseReceiptStore(path).list(limit=100)
    ]
    assert any(
        ref["attributes"].get("state") == "unknown"
        for row in archived
        for ref in row["value"]["resource_refs"]
    )


@pytest.mark.asyncio
async def test_strict_missing_target_is_determinate_and_releases_route(
    runtime,
):
    rt = await runtime()
    with pytest.raises(Exception) as caught:
        await rt.channel.send(
            "dingtalk:sw:unknown",
            "hello",
            {"_api_send": True},
        )
    assert getattr(caught.value, "side_effect_possible", None) is False
    assert deliveries(rt) == rt.rows("group") == rt.rows("dm") == []
    assert all(r["kind"] == "terminal" for r in persisted_routes(rt).values())


@pytest.mark.asyncio
async def test_prefix_refusal_and_blank_parts_preserve_content(runtime):
    from qwenpaw.schemas import TextContent, RefusalContent

    rt = await runtime(bot_prefix="[config]")
    await rt.channel.send_content_parts(
        WEBHOOK,
        [TextContent(text="   ")],
        dict(META),
    )
    assert deliveries(rt) == []
    await rt.channel.send_content_parts(
        WEBHOOK,
        [TextContent(text="hello"), RefusalContent(refusal="cannot comply")],
        {**META, "bot_prefix": "[caller]"},
    )
    assert (
        deliveries(rt)[0]["payload"]["markdown"]["text"].strip()
        == "[caller]  hello\ncannot comply"
    )


@pytest.mark.asyncio
async def test_file_upload_multipart_returns_media_id_and_keeps_source(
    runtime,
    tmp_path,
):
    from qwenpaw.schemas import FileContent

    rt = await runtime(endpoint="https://media-gateway.test")
    source = tmp_path / "report.txt"
    source.write_text("original bytes")
    await rt.channel.send_content_parts(
        WEBHOOK,
        [FileContent(file_url=source.as_uri(), filename="report.txt")],
        dict(META),
    )
    upload = rt.rows("http")[0]
    assert (
        upload["url"] == "https://media-gateway.test/media/upload"
        "?access_token=api-token&type=file"
    )
    assert upload["fields"][0]["filename"] == "report.txt"
    assert bytes(upload["fields"][0]["bytes"]) == b"original bytes"
    assert deliveries(rt)[0]["payload"] == {
        "msgtype": "file",
        "file": {
            "mediaId": "@media-one",
            "fileType": "txt",
            "fileName": "report.txt",
        },
    }
    assert source.read_text() == "original bytes"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown", "payload", "json", "empty"])
async def test_inline_image_unknown_never_sends_file_fallback(
    runtime,
    failure,
):
    from qwenpaw.schemas import ImageContent

    rt = await runtime()
    (rt.work / "send-mode").write_text("webhook-" + failure)
    with pytest.raises(Exception) as caught:
        await rt.channel.send_content_parts(
            WEBHOOK,
            [ImageContent(image_url="data:image/png;base64,aGVsbG8=")],
            {**META, "session_webhook": WEBHOOK},
        )
    assert getattr(caught.value, "side_effect_possible", None) is True
    assert len(rt.rows("http")) == 2
    assert len(deliveries(rt)) == 1
    assert deliveries(rt)[0]["payload"]["msgtype"] == "markdown"
    assert rt.rows("group") == []


@pytest.mark.asyncio
async def test_partial_multipart_unknown_does_not_repeat_prior_text(
    runtime,
    tmp_path,
):
    rt = await runtime()
    source = tmp_path / "report.txt"
    source.write_text("bytes")
    native = await inbound(rt, message("partial-media", group=True))
    params = {
        **identity(rt),
        "delivery_id": "partial-media-delivery",
        "to_handle": native["meta"]["response_handle"],
        "operation": "message.create",
        "content_parts": [
            {"type": "text", "text": "once"},
            {
                "type": "file",
                "file_url": source.as_uri(),
                "filename": "report.txt",
            },
        ],
    }
    (rt.work / "send-mode").write_text("file-unknown")
    assert (await rt.process.call("channel.send", params))[
        "state"
    ] == "unknown"
    assert [row["payload"]["msgtype"] for row in deliveries(rt)] == [
        "markdown",
        "file",
    ]
    assert deliveries(rt)[0]["payload"]["markdown"]["text"].strip() == "once"
    attempts = len(rt.rows("http"))
    (rt.work / "send-mode").unlink()
    await restart(rt)
    params.update(identity(rt))
    assert (await rt.process.call("channel.send", params))[
        "state"
    ] == "unknown"
    assert len(rt.rows("http")) == attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["picture", "richText", "voice"])
async def test_inbound_media_voice_and_rich_text_use_child_resources(
    runtime,
    kind,
):
    rt = await runtime()
    body = {"msgtype": kind}
    if kind == "richText":
        body["content"] = {
            "richText": [
                {"text": "hello"},
                {"type": "picture", "pictureDownloadCode": "download-one"},
            ],
        }
    elif kind == "picture":
        body["content"] = {"downloadCode": "download-one"}
    else:
        body["content"] = {
            "recognition": "spoken hello",
            "downloadCode": "voice-one",
        }
    payload = await inbound(rt, message("media-" + kind, content=body))
    parts = payload["content_parts"]
    if kind == "voice":
        assert any(
            p.type == "text" and "spoken hello" in p.text for p in parts
        )
    else:
        images = [p for p in parts if p.type == "image"]
        assert len(images) == 1
        path = Path(images[0].image_url.removeprefix("file://"))
        assert path.parent == rt.work / "media"
        assert path.read_bytes() == b"\x89PNG\r\n\x1a\noriginal image"
        assert (
            rt.rows("download")[0]["request"]["downloadCode"] == "download-one"
        )
        if kind == "richText":
            assert parts[0].text == "hello"
        await rt.channel.stop()
        assert path.exists()


@pytest.mark.asyncio
async def test_stream_card_delta_finalize_pending_store_and_mention(runtime):
    rt = await runtime(
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
        at_sender_on_reply=True,
    )
    request, target, meta = await stream_request(rt, "stream")
    await rt.channel.on_streaming_start(
        request,
        target,
        None,
        meta,
        "reasoning",
    )
    assert len(rt.rows("create")) == len(rt.rows("deliver")) == 1
    create, delivery = (
        rt.rows("create")[0]["request"],
        rt.rows("deliver")[0]["request"],
    )
    assert create["cardTemplateId"] == "template"
    assert create["cardAtUserIds"] == ["staff-one"]
    assert delivery["openSpaceId"] == "dtv1.card//IM_GROUP.cid-original"
    assert delivery["outTrackId"] == create["outTrackId"]
    pending = json.loads((rt.work / "dingtalk-active-cards.json").read_text())[
        "pending_cards"
    ]
    assert pending[0]["card_instance_id"] == create["outTrackId"]
    await rt.channel.on_streaming_delta(
        request,
        target,
        None,
        meta,
        "reasoning",
        "answer",
    )
    updates = len(rt.rows("update"))
    await rt.channel.on_streaming_delta(
        request,
        target,
        None,
        meta,
        "reasoning",
        "answer",
    )
    assert len(rt.rows("update")) == updates
    await rt.channel.on_streaming_end(
        request,
        target,
        None,
        meta,
        "reasoning",
        "answer",
    )
    update = rt.rows("update")[-1]["request"]
    assert update["isFinalize"] and update["isFull"]
    assert update["outTrackId"] == create["outTrackId"]
    assert "answer" in update["content"] and "💭" in update["content"]
    assert (
        json.loads((rt.work / "dingtalk-active-cards.json").read_text())[
            "pending_cards"
        ]
        == []
    )
    assert deliveries(rt) == []


@pytest.mark.asyncio
async def test_old_pending_card_recovers_same_original_id_once(runtime):
    old = {
        "version": 1,
        "pending_cards": [
            {
                "account_id": "default",
                "card_instance_id": "legacy-card",
                "conversation_id": "cid-legacy",
                "created_at": 1,
                "last_updated": 1,
                "state": "2",
            },
        ],
    }
    rt = await runtime(
        initial_files={"dingtalk-active-cards.json": json.dumps(old)},
        message_type="card",
        card_template_id="template",
    )
    assert rt.rows("create") == rt.rows("deliver") == []
    assert len(rt.rows("update")) == 1
    assert rt.rows("update")[0]["request"]["outTrackId"] == "legacy-card"
    assert rt.rows("update")[0]["request"]["isFinalize"]
    assert (
        json.loads((rt.work / "dingtalk-active-cards.json").read_text())[
            "pending_cards"
        ]
        == []
    )
    await restart(rt)
    assert len(rt.rows("update")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["create", "deliver", "update"])
@pytest.mark.parametrize("failure", ["unknown", "exit"])
async def test_unknown_card_effect_never_replayed_by_hooks_stop_or_recovery(
    runtime,
    kind,
    failure,
):
    from qwenpaw.app.channels.process_supervisor import ChannelCallUnknown

    rt = await runtime(
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    _request, _target, meta = await stream_request(rt, "unknown-card")
    if kind == "update":
        assert (await public_stream(rt, meta["response_handle"]))[
            "state"
        ] == "acknowledged"
    handle = meta["response_handle"]
    params = {
        **identity(rt),
        "delivery_id": "card-unknown",
        "to_handle": handle,
        "operation": "stream.delta" if kind == "update" else "stream.start",
        "stream_type": "message",
        "sequence": 9 if kind == "update" else 0,
        "accumulated_text": "possibly sent",
    }
    if kind == "update":
        # Existing stream resource is obtained through the proxy hooks.
        params["target_delivery_id"] = "stream-resource"
    (rt.work / "send-mode").write_text(kind + "-" + failure)
    if failure == "exit":
        with pytest.raises(ChannelCallUnknown):
            await rt.process.call("channel.send", params)
    else:
        assert (await rt.process.call("channel.send", params))[
            "state"
        ] == "unknown"
    counts = {
        name: len(rt.rows(name)) for name in ["create", "deliver", "update"]
    }
    (rt.work / "send-mode").unlink()
    await restart(rt)
    params.update(identity(rt))
    assert (await rt.process.call("channel.send", params))[
        "state"
    ] == "unknown"
    assert {name: len(rt.rows(name)) for name in counts} == counts
    assert deliveries(rt) == []
    if kind in {"create", "deliver"}:
        await rt.channel.stop()
        assert {name: len(rt.rows(name)) for name in counts} == counts


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown", "tea", "dara"])
async def test_card_creation_uncertainty_is_not_retried_by_later_hooks(
    runtime,
    failure,
):
    rt = await runtime(
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    request, target, meta = await stream_request(rt, "create-envelope")
    (rt.work / "send-mode").write_text("create-" + failure)
    for stream_type in ["reasoning", "message"]:
        with pytest.raises(Exception) as caught:
            await rt.channel.on_streaming_start(
                request,
                target,
                None,
                meta,
                stream_type,
            )
        assert getattr(caught.value, "side_effect_possible", None) is True
    assert len(rt.rows("create")) == 1
    assert rt.rows("deliver") == deliveries(rt) == []
    (rt.work / "send-mode").unlink()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unknown", "exit"])
async def test_unknown_finalization_is_journaled_and_never_replayed(
    runtime,
    failure,
):
    from qwenpaw.app.channels.process_supervisor import ChannelCallUnknown
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await runtime(
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    _request, _target, meta = await stream_request(rt, "final-unknown")
    handle = meta["response_handle"]
    assert (await public_stream(rt, handle))["state"] == "acknowledged"
    (rt.work / "send-mode").write_text("update-" + failure)
    with pytest.raises(ChannelCallUnknown if failure == "exit" else RpcError):
        await rt.process.call(
            "channel.response.finish",
            finish_params(rt, handle),
        )
    count = len(rt.rows("update"))
    (rt.work / "send-mode").unlink()
    await restart(rt)
    with pytest.raises(RpcError):
        await rt.process.call(
            "channel.response.finish",
            finish_params(rt, handle),
        )
    assert len(rt.rows("update")) == count
    receipt = persisted_routes(rt)[handle]
    assert receipt["kind"] == "terminal"
    assert receipt["cleanup_state"] == "pending"
    assert any(
        r["attributes"].get("cleanup") == "unknown"
        for r in receipt["resource_refs"]
    )
    assert not any(
        r["attributes"].get("cleanup") == "complete"
        for r in receipt["resource_refs"]
    )
    await rt.channel.stop()
    await rt.channel.start()
    assert len(rt.rows("update")) == count


@pytest.mark.asyncio
async def test_unknown_delta_allows_new_finalization_without_replaying_delta(
    runtime,
):
    rt = await runtime(
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    _request, _target, meta = await stream_request(rt, "delta-unknown")
    handle = meta["response_handle"]
    await public_stream(rt, handle)
    params = {
        **identity(rt),
        "delivery_id": "lost-delta",
        "to_handle": handle,
        "operation": "stream.delta",
        "stream_type": "message",
        "target_delivery_id": "stream-resource",
        "sequence": 19,
        "accumulated_text": "may have arrived",
    }
    (rt.work / "send-mode").write_text("update-unknown")
    assert (await rt.process.call("channel.send", params))[
        "state"
    ] == "unknown"
    (rt.work / "send-mode").unlink()
    await rt.process.call("channel.response.finish", finish_params(rt, handle))
    updates = [r["request"] for r in rt.rows("update")]
    assert len(updates) == 4
    assert updates[-1]["isFinalize"]
    assert updates[-1]["outTrackId"] == updates[-2]["outTrackId"]
    assert not updates[-2]["isFinalize"]
    assert (await rt.process.call("channel.send", params))[
        "state"
    ] == "unknown"
    assert len(rt.rows("update")) == 4


@pytest.mark.asyncio
async def test_restart_mid_stream_restores_same_card_and_original_webhook(
    runtime,
):
    rt = await runtime(
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    request, target, meta = await stream_request(rt, "restart-stream")
    await rt.channel.on_streaming_start(request, target, None, meta, "message")
    await rt.channel.on_streaming_delta(
        request,
        target,
        None,
        meta,
        "message",
        "before",
    )
    card_id = rt.rows("create")[0]["request"]["outTrackId"]
    old_pid = rt.process.health_snapshot()["pid"]
    await restart(rt)
    assert len(rt.rows("update")) == 2
    await rt.channel.on_streaming_end(
        request,
        target,
        None,
        meta,
        "message",
        "after restart",
    )
    assert len(rt.rows("create")) == len(rt.rows("deliver")) == 1
    assert rt.rows("update")[-1]["request"]["outTrackId"] == card_id
    assert rt.rows("update")[-1]["request"]["content"] == "after restart"
    assert rt.rows("update")[-1]["pid"] != old_pid
    assert deliveries(rt) == []


@pytest.mark.asyncio
async def test_concurrent_same_conversation_cards_have_separate_ownership(
    runtime,
):
    rt = await runtime(
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    items = [
        await stream_request(rt, mid) for mid in ["same-room-a", "same-room-b"]
    ]
    await asyncio.gather(
        *(
            rt.channel.on_streaming_start(r, t, None, m, "message")
            for r, t, m in items
        ),
    )
    ids = [row["request"]["outTrackId"] for row in rt.rows("create")]
    assert len(ids) == len(set(ids)) == 2
    assert len(rt.rows("deliver")) == 2
    for index, (request, target, meta) in enumerate(items):
        await rt.channel.on_streaming_end(
            request,
            target,
            None,
            meta,
            "message",
            f"answer-{index}",
        )
    updates = [
        row["request"]
        for row in rt.rows("update")
        if row["request"]["isFinalize"]
    ]
    assert len(updates) == 2
    assert {r["outTrackId"] for r in updates} == set(ids)
    assert {r["content"] for r in updates} == {"answer-0", "answer-1"}
    assert deliveries(rt) == []


@pytest.mark.asyncio
async def test_two_workspace_endpoints_and_stop_are_independent(runtime):
    first = await runtime(endpoint="https://one.test")
    second = await runtime(endpoint="https://two.test")
    assert (
        first.process.health_snapshot()["pid"]
        != second.process.health_snapshot()["pid"]
    )
    for rt, endpoint in [(first, "one.test"), (second, "two.test")]:
        assert (
            rt.rows("sync-http")[0]["url"]
            == f"https://{endpoint}/v1.0/gateway/connections/open"
        )
        assert rt.rows("sync-http")[0]["timeout"] == [10, 30]
        await rt.channel.send("dingtalk:sw:missing", "hello", dict(META))
        assert rt.rows("group")[0]["endpoint"] == endpoint
        assert rt.rows("token")[0]["endpoint"] == endpoint
    data = first.work / "keep.json"
    data.write_text('{"setting":true}')
    await first.channel.stop()
    assert first.process.health_snapshot()["pid"] is None
    assert data.read_text() == '{"setting":true}'
    assert (await second.channel.health_check())["status"] == "healthy"
    await second.channel.send(WEBHOOK, "still alive", dict(META))
    assert (
        deliveries(second)[0]["payload"]["markdown"]["text"].strip()
        == "still alive"
    )
    assert (
        deliveries(second)[0]["pid"] == second.process.health_snapshot()["pid"]
    )


@pytest.mark.asyncio
async def test_idempotent_start_and_public_restart_keep_accepted_dedup(
    runtime,
):
    rt = await runtime()
    old_pid = rt.process.health_snapshot()["pid"]
    native = await inbound(rt, message("restart-once"))
    await rt.channel.start()
    assert rt.process.health_snapshot()["pid"] == old_pid
    assert len(rt.rows("connected")) == 1
    await rt.channel.stop()
    await rt.channel.stop()
    await rt.channel.start()
    rt.spec = rt.channel._launch_spec
    assert rt.process.health_snapshot()["pid"] != old_pid
    assert rt.spec.generation == 2
    rt.emit(message("restart-once"))
    await eventually(lambda: len(rt.rows("ack")) == 2)
    assert len(rt.queued) == 1
    await rt.channel.consume_one(native)
    assert len(deliveries(rt)) == 1


@pytest.mark.asyncio
async def test_reconnect_remains_same_child_and_stop_quiesces_network(runtime):
    rt = await runtime()
    pid = rt.process.health_snapshot()["pid"]
    rt.emit({"disconnect": True})
    await eventually(lambda: len(rt.rows("connected")) >= 2)
    payload = await inbound(rt, message("after-reconnect"))
    await rt.channel.consume_one(payload)
    assert len(deliveries(rt)) == 1
    assert rt.process.health_snapshot()["pid"] == pid
    await rt.channel.stop()
    count = len(rt.rows("sync-http"))
    await asyncio.sleep(0.1)
    assert rt.process.health_snapshot()["pid"] is None
    assert len(rt.rows("sync-http")) == count


@pytest.mark.asyncio
async def test_generation_rejects_old_request_before_platform_effect(runtime):
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await runtime()
    payload = await inbound(rt, message("old-generation"))
    params = {
        **identity(rt),
        "delivery_id": "stale",
        "to_handle": payload["meta"]["response_handle"],
        "operation": "message.create",
        "content_parts": [{"type": "text", "text": "forbidden"}],
    }
    await restart(rt)
    with pytest.raises(RpcError) as caught:
        await rt.process.call("channel.send", params)
    assert caught.value.data["reason_code"] == "STALE_GENERATION"
    assert deliveries(rt) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize(
    "command",
    [
        "/approval approve pending",
        " /APPROVE pending ",
        "/deny pending",
        "/authorize-dingtalk-test approve pending",
    ],
)
async def test_typed_approval_uses_authenticated_actor_and_preserves_meta(
    runtime,
    monkeypatch,
    shared,
    command,
):
    from qwenpaw.runtime.commands import control
    from qwenpaw.runtime.commands.control.approval_handler import (
        ApprovalCommandHandler,
    )
    from qwenpaw.runtime.commands.control.base import ControlContext
    from qwenpaw.app.approvals.service import (
        ApprovalIdentityPolicy,
        ApprovalService,
        PendingApproval,
    )

    monkeypatch.setattr(
        control,
        "_COMMAND_REGISTRY",
        dict(control._COMMAND_REGISTRY),
    )
    alias = ApprovalCommandHandler()
    alias.command_name = "/authorize-dingtalk-test"
    control.register_command(alias)
    rt = await runtime(share_session_in_group=shared)
    payload = await inbound(
        rt,
        message("approval", group=True, text={"content": command}),
    )
    before = dict(payload["meta"])
    request = rt.channel.build_agent_request_from_native(payload)
    actor = ApprovalCommandHandler._actor(
        ControlContext(
            workspace=None,
            payload=request,
            channel=rt.channel,
            session_id=request.session_id,
            user_id=request.user_id,
            agent_id="default",
            args={},
        ),
    )
    pending = PendingApproval(
        request_id="pending",
        session_id=request.session_id,
        root_session_id=request.session_id,
        owner_agent_id="default",
        user_id="group" if shared else "Alice#1234",
        channel="dingtalk",
        agent_id="default",
        tool_name="reme:save",
        created_at=0,
        future=asyncio.get_running_loop().create_future(),
        identity_policy=ApprovalIdentityPolicy.EXACT_REQUESTER,
    )
    assert not ApprovalService.actor_can_resolve(pending, actor)
    pending.identity_policy = ApprovalIdentityPolicy.AGENT
    assert ApprovalService.actor_can_resolve(pending, actor)
    assert request.user_id == "ding1234"
    assert payload["meta"] == before
    assert request.channel_meta == before


@pytest.mark.asyncio
@pytest.mark.parametrize("operator", [None, "", "   "])
async def test_typed_approval_missing_actor_fails_closed(runtime, operator):
    from qwenpaw.schemas import TextContent

    rt = await runtime(share_session_in_group=True)
    payload = {
        "sender_id": "Alice#1234",
        "content_parts": [TextContent(text="/approve pending")],
        "meta": dict(META),
    }
    if operator is not None:
        payload["acl_sender_id"] = operator
    with pytest.raises(ValueError):
        rt.channel.build_agent_request_from_native(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize(
    "text",
    ["hello", "please /approve pending", "/approval-help", "/stop"],
)
async def test_nonapproval_text_keeps_display_or_shared_group_identity(
    runtime,
    shared,
    text,
):
    rt = await runtime(share_session_in_group=shared)
    payload = await inbound(
        rt,
        message("ordinary", group=True, text={"content": text}),
    )
    assert rt.channel.build_agent_request_from_native(payload).user_id == (
        "group" if shared else "Alice#1234"
    )


@pytest.mark.asyncio
async def test_host_acl_checks_actor_for_shared_group_and_blocks_agent(
    runtime,
    monkeypatch,
):
    rt = await runtime(access_control_group=True, share_session_in_group=True)
    from qwenpaw.app.channels.access_control import AccessControlStore

    checks = []
    store = AccessControlStore(rt.work / "acl.json")
    original_whitelist = store.is_whitelisted

    def checked_whitelist(channel, sender):
        checks.append((channel, sender))
        return original_whitelist(channel, sender)

    monkeypatch.setattr(store, "is_whitelisted", checked_whitelist)
    monkeypatch.setattr(
        "qwenpaw.app.channels.base.get_access_control_store",
        lambda *_a, **_k: store,
    )
    rt.emit(message("acl", group=True))
    await eventually(
        lambda: len(deliveries(rt)) == 1 and len(rt.rows("ack")) == 1
    )
    assert checks == [("dingtalk", "ding1234")]
    assert rt.requests == rt.queued == []
    assert [
        (row["channel"], row["user_id"]) for row in store.get_all_pending()
    ] == [("dingtalk", "ding1234")]
    assert len(deliveries(rt)) == 1
    store.add_to_whitelist("dingtalk", "ding1234")
    payload = await inbound(rt, message("authorized-shared", group=True))
    assert (
        rt.channel.build_agent_request_from_native(payload).user_id == "group"
    )
    assert rt.requests == []


@pytest.mark.asyncio
async def test_mention_policy_acks_rejection_then_accepts_dm(runtime):
    rt = await runtime(require_mention=True)
    rt.emit(message("not-mentioned", group=True, mentioned=False))
    await eventually(lambda: len(rt.rows("ack")) == 1)
    assert rt.queued == []
    payload = await inbound(rt, message("dm-unmentioned", mentioned=False))
    assert payload["meta"]["message_id"] == "dm-unmentioned"
    assert all(r["frame"]["code"] == 200 for r in rt.rows("ack"))


@pytest.mark.asyncio
async def test_host_admission_ack_waits_for_acceptance_and_transient_retry(
    runtime,
):
    rt = await runtime()
    attempts = []

    def accept(payload):
        attempts.append(payload)
        if len(attempts) == 1:
            assert rt.rows("ack") == []
            raise RuntimeError("queue temporarily unavailable")
        rt.queued.append(payload)

    set_admission(rt.channel, accept)
    payload = await inbound(rt, message("single-transient"))
    await eventually(lambda: len(rt.rows("ack")) == 1)
    assert len(attempts) == 2
    assert len({p["meta"]["response_handle"] for p in attempts}) == 1
    assert len(rt.rows("callback")) == 1
    await rt.channel.consume_one(payload)
    assert len(rt.requests) == len(deliveries(rt)) == 1


@pytest.mark.asyncio
async def test_exhausted_admission_is_bounded_and_allows_redelivery(
    runtime,
):
    rt = await runtime()
    attempts = []

    def reject(payload):
        attempts.append(payload)
        raise RuntimeError("queue unavailable")

    set_admission(rt.channel, reject)
    rt.emit(message("rejected"))
    await eventually(lambda: len(attempts) >= 2)
    await eventually(
        lambda: not any(
            r["kind"] == "active" for r in persisted_routes(rt).values()
        ),
    )
    count = len(attempts)
    assert 2 <= count <= 10
    await eventually(lambda: rt.rows("ack"))
    assert rt.rows("ack")[0]["frame"]["code"] != 200
    assert (await rt.channel.health_check())[
        "last_diagnostic"
    ] == "HOST_ADMISSION_EXHAUSTED"
    await asyncio.sleep(0.2)
    assert len(attempts) == count
    set_admission(rt.channel, rt.queued.append)
    payload = await inbound(rt, message("rejected"))
    await rt.channel.consume_one(payload)
    assert len(deliveries(rt)) == 1


@pytest.mark.asyncio
async def test_stop_cancels_pending_admission_and_real_child_exits(runtime):
    rt = await runtime()
    attempts = []

    def reject(payload):
        attempts.append(payload)
        raise RuntimeError("queue unavailable")

    set_admission(rt.channel, reject)
    rt.emit(message("stop-retrying"))
    await eventually(lambda: len(attempts) >= 2)
    await asyncio.wait_for(rt.channel.stop(), 3)
    count = len(attempts)
    await asyncio.sleep(0.2)
    assert len(attempts) == count
    assert rt.process.health_snapshot()["pid"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("tracker", [False, True])
async def test_cancellation_finalizes_only_owned_card_and_propagates(
    runtime,
    tracker,
):
    from qwenpaw.schemas import Message, RunStatus

    rt = None

    async def agent(_request):
        if not tracker:
            await rt.channel.on_streaming_start(
                _request,
                rt.channel.get_to_handle_from_request(_request),
                None,
                _request.channel_meta,
                "message",
            )
        yield Message(
            object="message",
            id="answer",
            type="message",
            role="assistant",
            status=RunStatus.InProgress,
        )
        await asyncio.Event().wait()

    rt = await runtime(
        agent=agent,
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    payload = await inbound(rt, message("cancelled", group=True))

    async def consume():
        if tracker:
            async for _event in rt.channel._stream_with_tracker(payload):
                pass
        else:
            await rt.channel.consume_one(payload)

    task = asyncio.create_task(consume())
    try:
        await eventually(
            lambda: any(
                row["attributes"].get("state") == "acknowledged"
                and row["attributes"].get("operation") == "stream.start"
                and row["resource_id"]
                != hashlib.sha256(
                    (payload["meta"]["response_handle"] + ":prepare").encode(),
                ).hexdigest()
                for row in persisted_routes(rt)[
                    payload["meta"]["response_handle"]
                ]["resource_refs"]
            ),
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(rt.rows("create")) == len(rt.rows("deliver")) == 1
        assert len(rt.rows("update")) == 2
        assert rt.rows("update")[-1]["request"]["isFinalize"]
        assert (
            rt.rows("update")[-1]["request"]["outTrackId"]
            == rt.rows("create")[0]["request"]["outTrackId"]
        )
        assert (
            persisted_routes(rt)[payload["meta"]["response_handle"]][
                "cleanup_state"
            ]
            == "complete"
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("tracker", [False, True])
async def test_agent_unknown_send_emits_one_response_no_second_error(
    runtime,
    tracker,
):
    rt = await runtime()
    payload = await inbound(rt, message("agent-unknown"))
    (rt.work / "send-mode").write_text("webhook-unknown")
    try:
        if tracker:
            async for _event in rt.channel._stream_with_tracker(payload):
                pass
        else:
            await rt.channel.consume_one(payload)
    except Exception as error:
        assert (
            getattr(error, "side_effect_possible", False)
            or "UNKNOWN" in str(error).upper()
        )
    assert len(rt.requests) == 1
    assert len(deliveries(rt)) == 1
    assert (
        deliveries(rt)[0]["payload"]["markdown"]["text"].strip()
        == "host answer"
    )
    assert rt.rows("group") == rt.rows("dm") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["normal", "unknown", "cancelled"])
async def test_bound_workspace_dispatch_uses_real_task_tracker_and_cleanup(
    runtime,
    outcome,
    monkeypatch,
):
    from unittest.mock import AsyncMock
    from qwenpaw.app.task_tracker import TaskTracker
    from qwenpaw.channel_protocol.models import SendParams
    from qwenpaw.channel_protocol.response_receipts import (
        ResponseReceiptStore,
        receipt_key,
    )
    from qwenpaw.schemas import Message, RunStatus

    async def blocked_agent(_request):
        yield Message(
            object="message",
            id="answer",
            type="message",
            role="assistant",
            status=RunStatus.InProgress,
        )
        await asyncio.Event().wait()

    rt = await runtime(
        agent=blocked_agent if outcome == "cancelled" else None,
        message_type="card" if outcome == "cancelled" else "markdown",
        card_template_id="template",
        streaming_enabled=outcome == "cancelled",
    )
    sends = []
    call = rt.process.call

    async def capture_send(method, params=None, **kwargs):
        result = await call(method, params, **kwargs)
        if method == "channel.send":
            sends.append(
                (SendParams.from_mapping(params).to_mapping(), result)
            )
        return result

    monkeypatch.setattr(rt.process, "call", capture_send)
    tracker = TaskTracker()
    chats = NS(
        get_or_create_chat=AsyncMock(return_value=NS(id="real-chat")),
        touch_chat=AsyncMock(),
        mark_chat_finished=AsyncMock(),
    )
    rt.channel.set_workspace(
        NS(task_tracker=tracker, chat_manager=chats),
        NS(is_control_command=lambda _: False),
    )
    payload = await inbound(rt, message("workspace-" + outcome, group=True))
    if outcome == "unknown":
        (rt.work / "send-mode").write_text("webhook-unknown")
    task = asyncio.create_task(rt.channel.consume_one(payload))
    try:
        if outcome == "cancelled":
            await eventually(lambda: len(rt.rows("update")) == 1)
            assert await tracker.request_stop("real-chat")
        await asyncio.wait_for(task, 6)
        handle = payload["meta"]["response_handle"]
        if outcome == "unknown":
            assert len(sends) == 1
            params, result = sends[0]
            assert params["to_handle"] == handle
            assert result["state"] == "unknown"
            assert result["reason_code"] == "PLATFORM_RESULT_UNKNOWN"
            store = ResponseReceiptStore(
                rt.channel._state_path().with_suffix(".receipts.sqlite3"),
            )
            key = receipt_key("dingtalk.shared.responses", handle)
            receipt = store.get(key)
            assert receipt["cleanup_state"] == "complete"
            assert receipt["route_refs"] == []
            assert handle not in persisted_routes(rt)
            attempts = [
                ref
                for ref in receipt["resource_refs"]
                if ref["kind"] == "dingtalk.attempt"
                and ref["resource_id"] == params["delivery_id"]
            ]
            assert len(attempts) == 1
            attrs = attempts[0]["attributes"]
            assert attrs["state"] == result["state"]
            assert attrs["reason_code"] == result["reason_code"]
            intent = {k: v for k, v in params.items() if k != "generation"}
            fingerprint = hashlib.sha256(
                json.dumps(intent, sort_keys=True).encode(),
            ).hexdigest()
            assert attrs["fingerprint"] == fingerprint
            old_pid = rt.process.health_snapshot()["pid"]
            await restart(rt)
            assert rt.process.health_snapshot()["pid"] != old_pid
            replay = {**params, "generation": rt.spec.generation}
            assert await rt.process.call("channel.send", replay) == result
            assert store.get(key) == receipt
            assert handle not in persisted_routes(rt)
        else:
            receipt = persisted_routes(rt)[handle]
        assert receipt["kind"] == "terminal"
        if outcome == "cancelled":
            assert receipt["outcome"] == "cancelled"
            assert len(rt.rows("update")) == 2
            assert rt.rows("update")[-1]["request"]["isFinalize"]
        else:
            assert len(deliveries(rt)) == 1
            if outcome == "normal":
                assert receipt["cleanup_state"] == "complete"
    finally:
        await tracker.request_stop("real-chat")
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancellation_during_normal_cleanup_keeps_owner_and_propagates(
    runtime,
):
    from qwenpaw.schemas import Message, RunStatus

    async def agent(_request):
        yield Message(
            object="message",
            id="answer",
            type="message",
            role="assistant",
            status=RunStatus.InProgress,
        )

    rt = await runtime(
        agent=agent,
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    payload = await inbound(rt, message("cancel-cleanup", group=True))
    (rt.work / "send-mode").write_text("finalize-block")

    async def consume():
        async for _event in rt.channel._stream_with_tracker(payload):
            pass

    task = asyncio.create_task(consume())
    try:
        await eventually(
            lambda: any(r["request"]["isFinalize"] for r in rt.rows("update")),
        )
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        handle = payload["meta"]["response_handle"]
        assert persisted_routes(rt)[handle]["cleanup_state"] != "complete"
        (rt.work / "update-release").touch()
        await eventually(
            lambda: persisted_routes(rt)[handle]["cleanup_state"]
            == "complete",
        )
        assert len(rt.rows("update")) == 2
        assert rt.rows("update")[-1]["request"]["isFinalize"]
    finally:
        (rt.work / "update-release").touch()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_sdk_send_retains_unknown_and_host_scheduling(runtime):
    rt = await runtime()
    (rt.work / "send-mode").write_text("webhook-block")
    task = asyncio.create_task(rt.channel.send(WEBHOOK, "once", dict(META)))
    try:
        await eventually(lambda: len(deliveries(rt)) == 1)
        ticks = 0
        until = asyncio.get_running_loop().time() + 0.15
        while asyncio.get_running_loop().time() < until:
            ticks += 1
            await asyncio.sleep(0.01)
        assert ticks >= 8
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert any(
            r["method"] == "channel.send"
            for r in rt.process.health_snapshot()["unknown_outcomes"]
        )
        assert len(deliveries(rt)) == 1
        (rt.work / "webhook-release").touch()
    finally:
        (rt.work / "webhook-release").touch()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("buffered", [False, True])
async def test_merge_and_media_buffer_release_all_original_routes(
    runtime,
    buffered,
):
    rt = await runtime(no_text_debounce=buffered)
    body = (
        {"msgtype": "picture", "content": {"downloadCode": "image-one"}}
        if buffered
        else None
    )
    items = [
        await inbound(rt, message(mid, content=body))
        for mid in ["merge-a", "merge-b"]
    ]
    merged = rt.channel.merge_native_items(items)
    await rt.channel.consume_one(merged)
    if buffered:
        assert rt.requests == []
        current = await inbound(rt, message("text-after-media"))
        items.append(current)
        await rt.channel.consume_one(current)
    assert len(rt.requests) == 1
    assert len(deliveries(rt)) == 1
    routes = persisted_routes(rt)
    assert [
        (
            routes[p["meta"]["response_handle"]]["kind"],
            routes[p["meta"]["response_handle"]]["cleanup_state"],
        )
        for p in items
    ] == [("terminal", "complete")] * len(items)


@pytest.mark.asyncio
async def test_standalone_approval_and_cron_card_modes_release_routes(runtime):
    rt = await runtime(
        message_type="markdown",
        cron_message_type="card",
        card_template_id="template",
    )
    await rt.channel.send_approval_notification(
        session_id="approval-session",
        user_id="Alice#1234",
        request_id="approval-standalone",
        tool_name="shell",
        severity="high",
        result_summary="Allow?",
        channel_meta={**META, "session_webhook": WEBHOOK},
    )
    assert len(rt.rows("create")) == len(rt.rows("deliver")) == 1
    assert rt.rows("update")[-1]["request"]["isFinalize"]
    assert all(
        r["kind"] == "terminal" and r["cleanup_state"] == "complete"
        for r in persisted_routes(rt).values()
    )


@pytest.mark.asyncio
async def test_lost_host_admission_ack_dedups_and_preserves_accepted_route(
    runtime,
    monkeypatch,
):
    rt = await runtime()
    writer = rt.process._peer._transport._writer
    write = writer.write
    dropped, recovered = asyncio.Event(), asyncio.Event()

    def lose_first_ack(data):
        frame = json.loads(bytes(data).split(b"\r\n\r\n", 1)[1])
        receipt = frame.get("result", {})
        if isinstance(receipt, dict):
            if receipt.get("accepted_event_ids") and not dropped.is_set():
                dropped.set()
                return
            if receipt.get("duplicate_event_ids"):
                recovered.set()
        write(data)

    monkeypatch.setattr(writer, "write", lose_first_ack)
    payload = await inbound(rt, message("accepted-ack-lost"))
    await asyncio.wait_for(dropped.wait(), 2)
    assert rt.rows("ack") == []
    await asyncio.wait_for(recovered.wait(), 38)
    await eventually(lambda: len(rt.rows("ack")) == 1)
    await inbound(rt, message("after-ack-recovery"))
    assert [p["meta"]["message_id"] for p in rt.queued].count(
        "accepted-ack-lost",
    ) == 1
    assert (
        persisted_routes(rt)[payload["meta"]["response_handle"]]["kind"]
        == "active"
    )
    await rt.channel.consume_one(payload)
    assert len(deliveries(rt)) == 1


@pytest.mark.asyncio
async def test_large_stream_checkpoint_bounds_keep_live_unknown_evidence(
    runtime,
):
    rt = await runtime(
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    active = await inbound(rt, message("keep-active"))
    unknown = await inbound(rt, message("keep-unknown"))
    params = {
        **identity(rt),
        "delivery_id": "keep-delivery",
        "to_handle": unknown["meta"]["response_handle"],
        "operation": "message.create",
        "content_parts": [{"type": "text", "text": "once"}],
    }
    (rt.work / "send-mode").write_text("create-unknown")
    assert (await rt.process.call("channel.send", params))[
        "state"
    ] == "unknown"
    (rt.work / "send-mode").unlink()
    text = "x" * 50_000
    for index in range(21):
        request, target, meta = await stream_request(rt, f"large-{index}")
        await rt.channel.on_streaming_start(
            request,
            target,
            None,
            meta,
            "message",
        )
        await rt.channel.on_streaming_end(
            request,
            target,
            None,
            meta,
            "message",
            text,
        )
        assert (
            await rt.process.call(
                "channel.response.finish",
                {
                    **finish_params(rt, meta["response_handle"]),
                    "outcome": "completed",
                },
            )
        )["state"] == "closed"
    assert len(rt.rows("create")) == 22
    assert len(rt.rows("deliver")) == 21
    assert all(
        path.stat().st_size <= 1024 * 1024
        for path in (rt.work / "channel_state").glob("*.json")
    )
    routes = persisted_routes(rt)
    assert routes[active["meta"]["response_handle"]]["kind"] == "active"
    assert routes[unknown["meta"]["response_handle"]]["kind"] == "active"
    count = len(deliveries(rt))
    assert (await rt.process.call("channel.send", params))[
        "state"
    ] == "unknown"
    assert len(deliveries(rt)) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["deliver", "update"])
async def test_card_partial_known_failure_preserves_side_effect_evidence(
    runtime,
    stage,
):
    """A known later refusal cannot make prior card creation safe to repeat."""
    rt = await runtime(
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    _request, _target, meta = await stream_request(rt, "partial-card")
    handle = meta["response_handle"]
    params = {
        **identity(rt),
        "delivery_id": "partial-card-start",
        "to_handle": handle,
        "operation": "stream.start",
        "stream_type": "message",
        "sequence": 0,
        "accumulated_text": "visible once",
    }
    (rt.work / "send-mode").write_text(stage + "-reject")
    assert (await rt.process.call("channel.send", params))[
        "state"
    ] == "unknown"
    assert len(rt.rows("create")) == len(rt.rows("deliver")) == 1
    card_id = rt.rows("create")[0]["request"]["outTrackId"]
    receipt = persisted_routes(rt)[handle]
    assert card_id in json.dumps(receipt["resource_refs"])
    assert deliveries(rt) == rt.rows("group") == rt.rows("dm") == []
    counts = len(rt.rows("create")), len(rt.rows("deliver"))
    (rt.work / "send-mode").unlink()
    await restart(rt)
    params.update(identity(rt))
    assert (await rt.process.call("channel.send", params))[
        "state"
    ] == "unknown"
    assert (len(rt.rows("create")), len(rt.rows("deliver"))) == counts
    assert card_id in json.dumps(persisted_routes(rt)[handle]["resource_refs"])
    assert deliveries(rt) == []

    # The host path has its own metadata and must suppress automatic fallback.
    from qwenpaw.schemas import Message, RunStatus, TextContent

    host = None
    agent_entries = []

    async def agent(_request):
        agent_entries.append(_request)
        await host.channel.on_streaming_start(
            _request,
            host.channel.get_to_handle_from_request(_request),
            None,
            _request.channel_meta,
            "message",
        )
        yield Message(
            object="message",
            id="answer",
            type="message",
            role="assistant",
            status=RunStatus.InProgress,
        )
        yield Message(
            object="message",
            id="answer",
            type="message",
            role="assistant",
            status=RunStatus.Completed,
            content=[TextContent(text="host answer")],
        )

    host = await runtime(
        agent=agent,
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
    )
    payload = await inbound(host, message("host-partial-card", group=True))
    (host.work / "send-mode").write_text(stage + "-reject")
    if stage == "deliver":
        from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

        with pytest.raises(ChannelDeliveryError) as caught:
            await host.channel.consume_one(payload)
        assert caught.value.side_effect_possible
        assert not agent_entries
    else:
        await host.channel.consume_one(payload)
        assert len(agent_entries) == 1
    assert len(host.rows("create")) == len(host.rows("deliver")) == 1
    host_card = host.rows("create")[0]["request"]["outTrackId"]
    assert host_card in json.dumps(
        persisted_routes(host)[payload["meta"]["response_handle"]][
            "resource_refs"
        ],
    )
    assert deliveries(host) == host.rows("group") == host.rows("dm") == []
    (host.work / "send-mode").unlink()


@pytest.mark.asyncio
async def test_local_checkpoint_capacity_rejection_leaves_no_unknown_attempts(
    runtime,
):
    """Local byte-budget refusal must not invent remote uncertainty."""
    rt = await runtime()
    opened = await rt.process.call(
        "channel.response.open",
        {
            **identity(rt),
            "to_handle": WEBHOOK,
            "meta": {"padding": "x" * (768 * 1024 - 4096)},
        },
    )
    handle = opened["response_handle"]
    params = {
        **identity(rt),
        "to_handle": handle,
        "operation": "message.create",
        "content_parts": [{"type": "text", "text": "acknowledged"}],
    }
    rejected = []
    for index in range(30):
        delivery_id = "capacity-" + str(index)
        effects_before = len(deliveries(rt))
        result = await rt.process.call(
            "channel.send",
            {**params, "delivery_id": delivery_id},
        )
        if result["state"] == "failed":
            assert result["reason_code"] == "RESPONSE_STATE_CAPACITY"
            assert result["retryable"] is False
            assert len(deliveries(rt)) == effects_before
            rejected.append(delivery_id)
            break
        assert result["state"] == "acknowledged"
    assert rejected, "Fixture must reach the real 768KiB local byte budget"
    effects = len(deliveries(rt))
    for index in range(5):
        delivery_id = "rejected-" + str(index)
        result = await rt.process.call(
            "channel.send",
            {**params, "delivery_id": delivery_id},
        )
        assert result["state"] == "failed"
        assert result["reason_code"] == "RESPONSE_STATE_CAPACITY"
        assert result["retryable"] is False
        rejected.append(delivery_id)
    assert len(deliveries(rt)) == effects
    assert rt.rows("group") == rt.rows("dm") == []
    assert not any(
        row["resource_id"] in rejected
        or row["attributes"].get("state") == "unknown"
        for row in persisted_routes(rt)[handle]["resource_refs"]
    )
    result = await rt.process.call(
        "channel.response.finish",
        {**finish_params(rt, handle), "outcome": "completed"},
    )
    assert result["state"] == "closed"
    receipt = persisted_routes(rt)[handle]
    assert receipt["cleanup_state"] == "complete"
    assert not any(
        row["resource_id"] in rejected
        or row["attributes"].get("state") == "unknown"
        for row in receipt["resource_refs"]
    )


@pytest.mark.asyncio
async def test_consume_prepares_card_and_thinking_before_empty_agent(runtime):
    entered, release = asyncio.Event(), asyncio.Event()
    before_agent = []
    rt = None

    async def agent(_request):
        before_agent.extend(rt.rows())
        entered.set()
        await release.wait()
        for event in ():
            yield event

    rt = await runtime(
        agent=agent,
        message_type="card",
        card_template_id="template",
        streaming_enabled=False,
    )
    payload = await inbound(rt, message("empty-agent", group=True))
    task = asyncio.create_task(rt.channel.consume_one(payload))
    try:
        await asyncio.wait_for(entered.wait(), 4)
        assert [
            r["request"]["emotionName"]
            for r in before_agent
            if r["kind"] == "emotion"
        ] == ["🤔Thinking"]
        assert sum(r["kind"] == "create" for r in before_agent) == 1
        assert sum(r["kind"] == "deliver" for r in before_agent) == 1
        assert not rt.rows("update")
    finally:
        release.set()
        await asyncio.wait_for(task, 5)
    card_id = rt.rows("create")[0]["request"]["outTrackId"]
    assert len(rt.rows("create")) == len(rt.rows("deliver")) == 1
    final = rt.rows("update")
    assert len(final) == 1
    assert final[0]["request"]["outTrackId"] == card_id
    assert final[0]["request"]["isFinalize"]
    assert [r["request"]["emotionName"] for r in rt.rows("emotion")] == [
        "🤔Thinking",
        "🥳Done",
    ]
    assert [r["request"]["emotionName"] for r in rt.rows("recall")] == [
        "🤔Thinking",
    ]
    assert deliveries(rt) == []


@pytest.mark.asyncio
async def test_consume_nonstream_segments_share_precreated_card(runtime):
    from qwenpaw.schemas import Message, RunStatus, TextContent

    async def agent(_request):
        for text in ("first answer", "second answer"):
            yield Message(
                object="message",
                id=text,
                type="message",
                role="assistant",
                status=RunStatus.Completed,
                content=[TextContent(text=text)],
            )

    rt = await runtime(
        agent=agent,
        message_type="card",
        card_template_id="template",
        streaming_enabled=False,
    )
    payload = await inbound(rt, message("nonstream-segments", group=True))
    await rt.channel.consume_one(payload)
    assert len(rt.rows("create")) == len(rt.rows("deliver")) == 1
    card_id = rt.rows("create")[0]["request"]["outTrackId"]
    updates = [r["request"] for r in rt.rows("update")]
    assert len(updates) == 3
    assert {r["outTrackId"] for r in updates} == {card_id}
    assert [r["isFinalize"] for r in updates] == [False, False, True]
    assert updates[0]["content"] == "first answer"
    assert (
        updates[1]["content"]
        == updates[2]["content"]
        == ("first answer\nsecond answer")
    )
    assert deliveries(rt) == []


@pytest.mark.asyncio
async def test_consume_first_stream_card_has_textual_sender_mention(runtime):
    rt = None

    async def agent(request):
        target = rt.channel.get_to_handle_from_request(request)
        for kind, text in (("reasoning", "thinking"), ("message", "answer")):
            await rt.channel.on_streaming_start(
                request,
                target,
                None,
                request.channel_meta,
                kind,
            )
            await rt.channel.on_streaming_end(
                request,
                target,
                None,
                request.channel_meta,
                kind,
                text,
            )
        for event in ():
            yield event

    rt = await runtime(
        agent=agent,
        message_type="card",
        card_template_id="template",
        streaming_enabled=True,
        at_sender_on_reply=True,
    )
    payload = await inbound(rt, message("mention-segments", group=True))
    await rt.channel.consume_one(payload)
    creates = rt.rows("create")
    assert len(creates) == len(rt.rows("deliver")) == 2
    first, second = [r["request"]["outTrackId"] for r in creates]
    first_updates = [
        r["request"]
        for r in rt.rows("update")
        if r["request"]["outTrackId"] == first
    ]
    second_updates = [
        r["request"]
        for r in rt.rows("update")
        if r["request"]["outTrackId"] == second
    ]
    assert len(first_updates) == len(second_updates) == 2
    anchor = "<a atId=staff-one>Alice</a>\n"
    assert all(r["content"].startswith(anchor) for r in first_updates)
    assert all("<a atId=" not in r["content"] for r in second_updates)
    assert first_updates[-1]["isFinalize"]
    assert second_updates[-1]["isFinalize"]
    assert deliveries(rt) == []


@pytest.mark.asyncio
async def test_consume_markdown_mentions_dingtalk_id_when_staff_missing(
    runtime,
):
    from qwenpaw.schemas import Message, RunStatus, TextContent

    async def agent(_request):
        for text in ("first answer", "second answer"):
            yield Message(
                object="message",
                id=text,
                type="message",
                role="assistant",
                status=RunStatus.Completed,
                content=[TextContent(text=text)],
            )

    rt = await runtime(agent=agent, at_sender_on_reply=True)
    payload = await inbound(
        rt,
        message("mention-fallback", group=True, senderStaffId=""),
    )
    await rt.channel.consume_one(payload)
    sent = deliveries(rt)
    assert len(sent) == 2
    assert sent[0]["payload"]["at"]["atDingtalkIds"] == ["ding1234"]
    assert not sent[0]["payload"]["at"].get("atUserIds")
    assert not sent[1]["payload"].get("at")
    assert not rt.rows("create")


@pytest.mark.asyncio
async def test_consume_known_precreation_refusal_still_runs_agent(runtime):
    from qwenpaw.schemas import Message, RunStatus, TextContent

    entries = []
    rt = None

    async def agent(request):
        entries.append(request)
        (rt.work / "send-mode").unlink()
        yield Message(
            object="message",
            id="answer",
            type="message",
            role="assistant",
            status=RunStatus.Completed,
            content=[TextContent(text="answer after ordinary refusal")],
        )

    rt = await runtime(
        agent=agent,
        message_type="card",
        card_template_id="template",
        streaming_enabled=False,
    )
    payload = await inbound(rt, message("known-prepare-refusal", group=True))
    (rt.work / "send-mode").write_text("create-reject")
    await rt.channel.consume_one(payload)
    assert len(entries) == 1
    assert len(rt.rows("create")) == 2
    assert len(rt.rows("deliver")) == 1
    card_id = rt.rows("deliver")[0]["request"]["outTrackId"]
    updates = [r["request"] for r in rt.rows("update")]
    assert updates[-1]["outTrackId"] == card_id
    assert updates[-1]["isFinalize"]
    assert updates[-1]["content"] == "answer after ordinary refusal"
    assert deliveries(rt) == []
