"""MQTT/Mattermost migration proof through official artifacts and real workers."""

import asyncio
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import sys

import psutil
import pytest

from extension_process_suite import runtime, eventually, identity
from extension_sample import ROOT
from g2_mqtt_broker import Broker

sys.path.insert(0, str(ROOT / "tests/integration"))
from mock_mattermost import BOT_USER_ID, BOT_USERNAME, MockMattermost


def official_source(directory, key, **_ignored):
    source = ROOT / "plugins/channel" / key
    assert (
        source.is_dir()
    ), f"Official {key} plugin artifact is missing: {source}"
    destination = Path(directory) / key
    shutil.copytree(
        source, destination, ignore=shutil.ignore_patterns("__pycache__")
    )
    return destination


class ImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(
            ("qwenpaw_channel_mqtt", "qwenpaw_channel_mattermost", "paho")
        ):
            raise AssertionError(
                "Platform implementation imported in host: " + fullname
            )


@pytest.fixture(autouse=True)
def forbid_host_sdk_import():
    guard = ImportGuard()
    sys.meta_path.insert(0, guard)
    yield
    sys.meta_path.remove(guard)


@pytest.fixture
def broker():
    value = Broker()
    yield value
    value.close()


@pytest.fixture
def mattermost():
    value = MockMattermost()
    value.start()
    yield value
    value.stop()


async def mqtt(runtime, broker, **settings):
    result = await runtime(
        "mqtt",
        source_factory=official_source,
        host="127.0.0.1",
        port=broker.port,
        transport=settings.pop("transport", "tcp"),
        subscribe_topic="in/+",
        publish_topic="out/{client_id}",
        **settings,
    )
    await eventually(lambda: bool(broker.subscriptions))
    return result


async def mm(runtime, server, **settings):
    result = await runtime(
        "mattermost",
        source_factory=official_source,
        url=server.url,
        bot_token="local-test-token",
        **settings,
    )
    await eventually(lambda: server.has_connection)
    return result


async def route(rt, target, meta=None):
    result = await rt.process.call(
        "channel.response.open",
        {
            **identity(rt),
            "to_handle": target,
            "meta": meta or {},
        },
    )
    return result["response_handle"]


async def finish(rt, handle):
    return await rt.process.call(
        "channel.response.finish",
        {
            **identity(rt),
            "response_handle": handle,
            "outcome": "completed",
        },
    )


async def prepare(rt, handle):
    return await rt.process.call(
        "channel.response.prepare",
        {
            **identity(rt),
            "response_handle": handle,
            "delivery_id": hashlib.sha256(
                (handle + ":prepare").encode()
            ).hexdigest(),
        },
    )


def request_text(request):
    return "\n".join(
        part.text
        for message in request.input
        for part in message.content
        if getattr(part, "type", None) == "text"
    )


def typing_rows(server):
    return [
        body
        for method, path, body in server.requests
        if method == "POST" and path.endswith("/typing")
    ]


@pytest.mark.parametrize(
    "key,qualname",
    [("mqtt", "MQTTDriver"), ("mattermost", "MattermostDriver")],
)
def test_official_artifact_is_passively_described_without_driver_import(
    tmp_path, key, qualname
):
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    source = official_source(tmp_path, key)
    manifest = PluginManifest.model_validate(
        json.loads((source / "plugin.json").read_text())
    )
    assert manifest.entry.descriptor == "channel.json"
    description = describe_channel(source, manifest)
    descriptor = description.descriptor
    assert descriptor.schema_version == 2
    assert descriptor.channel_key == key
    assert descriptor.entrypoint.module == "qwenpaw_channel_" + key + ".driver"
    assert descriptor.entrypoint.qualname == qualname
    assert "channel.generic.v1" in descriptor.capabilities
    assert "streaming" not in descriptor.capabilities
    assert "approval_card" not in descriptor.capabilities
    assert set(descriptor.config_fields) == set(
        descriptor.config_schema["properties"]
    )
    from qwenpaw.config.config import MQTTConfig, MattermostConfig

    model = MQTTConfig if key == "mqtt" else MattermostConfig
    properties = descriptor.config_schema["properties"]
    assert set(properties) == set(model.model_fields)
    for field, default in model().model_dump().items():
        assert properties[field].get("default") == default
    for name in (
        "README.md",
        "requirements.txt",
        f"qwenpaw_channel_{key}/driver.py",
    ):
        assert (source / name).is_file()
    assert not any(
        name.startswith("qwenpaw_channel_" + key) for name in sys.modules
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
async def test_disabled_loader_does_not_spawn_or_import_platform(
    tmp_path, monkeypatch, key
):
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.plugins.workspace_projector import WorkspaceProjector

    source = official_source(tmp_path / "incoming", key)
    manifest = PluginManifest.model_validate(
        json.loads((source / "plugin.json").read_text())
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir", lambda: tmp_path / "installed"
    )

    async def forbidden(*args, **kwargs):
        raise AssertionError(
            "Disabled discovery spawned worker or dependency installer"
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    try:
        loader = PluginLoader(
            [tmp_path / "installed"],
            channel_runtime=ChannelRuntimeSettings(
                python_executable=sys.executable,
                support_root=ROOT / "src",
                qwenpaw_version="2.2.2b4",
                selected_channels=None,
            ),
        )
        loader.registry.projector = WorkspaceProjector(
            live_workspaces=lambda: []
        )
        record = await loader.load_plugin(
            manifest, source, {"enabled": False}, activate=False
        )
        assert record.status != "failed" and not record.enabled
        assert not loader.registry.runtime_owners.leases(key)
        assert not any(
            name.startswith("qwenpaw_channel_" + key) for name in sys.modules
        )
    finally:
        PluginRegistry._instance = previous


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "topic,payload,sender,text",
    [
        (
            "in/device",
            '{"text":"Hello","redirect_client_id":"redirect"}',
            "redirect",
            "Hello",
        ),
        ("in/device", "plain input", "device", "plain input"),
        ("single", "fallback", "unknown-client", "fallback"),
    ],
)
async def test_mqtt_native_identity_and_reply_target_survive(
    runtime, broker, topic, payload, sender, text
):
    rt = await mqtt(runtime, broker)
    broker.emit(topic, payload)
    await eventually(
        lambda: len(rt.ws.requests) == 1 and len(broker.publishes) == 1
    )
    request = rt.ws.requests[0]
    assert request.session_id == "mqtt:" + sender and request.user_id == sender
    assert text in request_text(request)
    assert (
        request.channel == "mqtt"
        and request.channel_meta["client_id"] == sender
    )
    assert broker.publishes == [("out/" + sender, "host answer", 2)]
    pid = rt.process.health_snapshot()["pid"]
    assert pid != os.getpid() and psutil.pid_exists(pid)
    receipt = await rt.manager.stop_one("mqtt")
    assert receipt.stopped and not psutil.pid_exists(pid)


@pytest.mark.asyncio
async def test_mqtt_identical_text_and_reused_mid_are_distinct_events(
    runtime, broker
):
    rt = await mqtt(runtime, broker)
    broker.emit("in/device", "same", mid=17)
    await eventually(
        lambda: len(rt.ws.requests) == 1 and len(broker.publishes) == 1
    )
    broker.emit("in/device", "same", mid=17)
    await eventually(
        lambda: len(rt.ws.requests) == 2 and len(broker.publishes) == 2
    )
    assert [request.session_id for request in rt.ws.requests] == [
        "mqtt:device"
    ] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("qos", [0, 1, 2])
async def test_mqtt_publish_waits_for_real_protocol_confirmation(
    runtime, broker, qos
):
    rt = await mqtt(runtime, broker, qos=qos)
    await rt.channel.send_content_parts(
        "device", [{"type": "text", "text": "scheduled"}], {}
    )
    assert broker.publishes == [("out/device", "scheduled", qos)]


@pytest.mark.asyncio
async def test_mqtt_media_placeholder_behavior_is_preserved(runtime, broker):
    rt = await mqtt(runtime, broker)
    await rt.channel.send_content_parts(
        "device",
        [
            {"type": "image", "image_url": "https://fixture.invalid/image"},
            {"type": "video", "video_url": "https://fixture.invalid/video"},
            {"type": "file", "file_url": "https://fixture.invalid/file"},
            {"type": "audio", "data": "AA==", "format": "wav"},
        ],
        {},
    )
    assert [row[1] for row in broker.publishes] == [
        "[Image] https://fixture.invalid/image",
        "[Video] https://fixture.invalid/video",
        "[File] https://fixture.invalid/file",
        "[Audio]",
    ]


@pytest.mark.asyncio
async def test_mqtt_lost_publish_confirmation_is_unknown_and_never_replayed(
    runtime, broker
):
    rt = await mqtt(runtime, broker, qos=1)
    handle = await route(rt, "device")
    params = {
        **identity(rt),
        "delivery_id": "publish-without-receipt",
        "to_handle": handle,
        "operation": "message.create",
        "content_parts": [{"type": "text", "text": "one effect"}],
    }
    broker.confirm = False
    task = asyncio.create_task(rt.process.call("channel.send", params))
    try:
        await eventually(lambda: len(broker.publishes) == 1)
        broker.disconnect()
        result = await task
        assert result["state"] == "unknown"
        await eventually(
            lambda: broker.connections >= 2
            and rt.process.health_snapshot()["platform_state"] == "connected"
        )
        repeated = await rt.process.call("channel.send", params)
        assert repeated["state"] == "unknown"
        assert broker.publishes == [("out/device", "one effect", 1)]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_mqtt_stale_generation_cannot_send(runtime, broker):
    from qwenpaw.channel_protocol.errors import RpcError

    rt = await mqtt(runtime, broker)
    old_identity = identity(rt)
    handle = await route(rt, "device")
    with pytest.raises(RpcError):
        await rt.process.call(
            "channel.send",
            {
                **old_identity,
                "generation": old_identity["generation"] + 1,
                "delivery_id": "stale",
                "to_handle": handle,
                "operation": "message.create",
                "content_parts": [
                    {"type": "text", "text": "must not publish"}
                ],
            },
        )
    assert broker.publishes == []


@pytest.mark.asyncio
async def test_mqtt_two_workspaces_own_separate_workers_and_stop_independently(
    runtime, broker
):
    other = Broker()
    try:
        first = await mqtt(runtime, broker)
        second = await mqtt(
            runtime,
            other,
            existing_loader=first.loader,
            workspace_name="workspace-B",
        )
        pids = [rt.process.health_snapshot()["pid"] for rt in (first, second)]
        assert len(set(pids)) == 2
        assert (
            identity(first)["instance_id"] != identity(second)["instance_id"]
        )
        await first.channel.send_content_parts(
            "first", [{"type": "text", "text": "A"}], {}
        )
        await second.channel.send_content_parts(
            "second", [{"type": "text", "text": "B"}], {}
        )
        assert broker.publishes == [("out/first", "A", 2)]
        assert other.publishes == [("out/second", "B", 2)]
        assert (await first.manager.stop_one("mqtt")).stopped
        assert not psutil.pid_exists(pids[0]) and psutil.pid_exists(pids[1])
        await second.channel.send_content_parts(
            "second", [{"type": "text", "text": "still live"}], {}
        )
        assert other.publishes[-1] == ("out/second", "still live", 2)
    finally:
        other.close()


@pytest.mark.asyncio
async def test_mattermost_dm_roundtrip_and_stable_post_dedup(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost)
    for _ in range(2):
        mattermost.push_dm_post(
            text="Hello",
            channel_id="dm-one",
            user_id="human",
            post_id="native-one",
        )
        await eventually(lambda: len(mattermost.posts) == 1)
    mattermost.push_dm_post(
        text="fence", channel_id="dm-one", user_id="human", post_id="fence"
    )
    await eventually(lambda: len(mattermost.posts) == 2)
    assert len(rt.ws.requests) == 2
    assert (
        sum("Hello" in request_text(request) for request in rt.ws.requests)
        == 1
    )
    request = rt.ws.requests[0]
    assert (
        request.session_id == "mattermost_dm:dm-one"
        and request.user_id == "human"
    )
    assert (
        request.channel == "mattermost"
        and request.channel_meta["mm_channel_id"] == "dm-one"
    )
    assert "Hello" in request_text(request)
    assert mattermost.posts[0] == {
        "channel_id": "dm-one",
        "message": "host answer",
        "root_id": "",
    }


@pytest.mark.asyncio
async def test_mattermost_mentions_and_accepted_thread_follow_preserve_root(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost, thread_follow_without_mention=True)
    mattermost.push_channel_post(
        text="@" + BOT_USERNAME + " start",
        channel_id="group",
        user_id="human",
        post_id="root-one",
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    mattermost.push_channel_post(
        text="follow",
        channel_id="group",
        user_id="other",
        post_id="follow-one",
        root_id="root-one",
    )
    await eventually(lambda: len(mattermost.posts) == 2)
    assert [request.session_id for request in rt.ws.requests] == [
        "mattermost_thread:root-one"
    ] * 2
    assert [row["root_id"] for row in mattermost.posts] == ["root-one"] * 2
    assert [row["channel_id"] for row in mattermost.posts] == ["group"] * 2


@pytest.mark.asyncio
async def test_mattermost_own_and_unmentioned_messages_never_reach_host(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost)
    mattermost.push_dm_post(text="self", user_id=BOT_USER_ID)
    mattermost.push_channel_post(text="unmentioned", post_id="ignored")
    # A later accepted event is a deterministic processing fence.
    mattermost.push_dm_post(
        text="accepted", user_id="human", post_id="accepted"
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    assert len(rt.ws.requests) == 1 and "accepted" in request_text(
        rt.ws.requests[0]
    )


@pytest.mark.asyncio
async def test_mattermost_first_context_history_order_and_trigger_exclusion(
    runtime, mattermost
):
    mattermost.responses["/api/v4/posts/root-one/thread"] = (
        200,
        {
            "order": ["second", "first", "trigger"],
            "posts": {
                "second": {
                    "id": "second",
                    "user_id": "other",
                    "message": "SECOND",
                    "create_at": 2000,
                },
                "first": {
                    "id": "first",
                    "user_id": "human",
                    "message": "FIRST",
                    "create_at": 1000,
                },
                "trigger": {
                    "id": "trigger",
                    "user_id": "human",
                    "message": "@" + BOT_USERNAME + " TRIGGER",
                    "create_at": 3000,
                },
            },
        },
    )
    rt = await mm(runtime, mattermost)
    mattermost.push_channel_post(
        text="@" + BOT_USERNAME + " TRIGGER",
        channel_id="group",
        user_id="human",
        post_id="trigger",
        root_id="root-one",
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    text = request_text(rt.ws.requests[0])
    assert text.index("FIRST") < text.index("SECOND") < text.index("TRIGGER")
    assert text.count("TRIGGER") == 1


@pytest.mark.asyncio
async def test_mattermost_long_text_preserves_every_character_and_root(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost)
    text = "a" * 4000 + "b" * 4000 + "c" * 13
    await rt.channel.send_content_parts(
        "dm-one", [{"type": "text", "text": text}], {}
    )
    assert "".join(row["message"] for row in mattermost.posts) == text
    assert len(mattermost.posts) == 3
    assert all(
        len(row["message"]) <= 4000 and row["channel_id"] == "dm-one"
        for row in mattermost.posts
    )


@pytest.mark.asyncio
async def test_mattermost_stop_exits_worker_and_closes_websocket(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost)
    pid = rt.process.health_snapshot()["pid"]
    receipt = await rt.manager.stop_one("mattermost")
    assert receipt.stopped and not psutil.pid_exists(pid)
    await eventually(lambda: not mattermost.has_connection)


@pytest.mark.asyncio
async def test_mattermost_prepare_and_finish_track_concurrent_response_owners(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost, show_typing=True)
    first, second = await route(rt, "dm-one"), await route(rt, "dm-one")
    assert first != second
    for handle in (first, first, second):
        assert (await prepare(rt, handle))["state"] == "acknowledged"
    await eventually(lambda: bool(typing_rows(mattermost)))
    await finish(rt, first)
    before = len(typing_rows(mattermost))
    await eventually(lambda: len(typing_rows(mattermost)) > before)
    await finish(rt, second)
    after = len(typing_rows(mattermost))
    await asyncio.sleep(
        4.1
    )  # Original typing refresh cadence is four seconds.
    assert len(typing_rows(mattermost)) == after


@pytest.mark.asyncio
async def test_mattermost_host_acl_denial_does_not_prepare_typing(
    runtime, mattermost
):
    rt = await mm(
        runtime,
        mattermost,
        show_typing=True,
        access_control_dm=True,
        deny_message="Denied",
    )
    mattermost.push_dm_post(
        text="unapproved", user_id="unapproved", post_id="denied-post"
    )
    await eventually(lambda: len(mattermost.posts) == 1)
    assert rt.ws.requests == []
    assert typing_rows(mattermost) == []


@pytest.mark.asyncio
async def test_mattermost_definite_http_failure_cannot_claim_success(
    runtime, mattermost
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await mm(runtime, mattermost)
    mattermost.responses["/api/v4/posts"] = (
        400,
        {"message": "controlled rejection"},
    )
    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.send_content_parts(
            "dm-one", [{"type": "text", "text": "rejected"}], {}
        )
    assert (
        caught.value.state == "failed"
        and not caught.value.side_effect_possible
    )
    assert mattermost.posts == []


@pytest.mark.asyncio
async def test_mattermost_file_upload_preserves_display_name_and_uploaded_id(
    runtime, mattermost
):
    rt = await mm(runtime, mattermost)
    mattermost.responses["/api/v4/files"] = (
        201,
        {"file_infos": [{"id": "uploaded-one"}]},
    )
    await rt.channel.send_content_parts(
        "dm-one",
        [
            {
                "type": "file",
                "file_url": "data:application/pdf;base64,cGRmLWRhdGE=",
                "filename": "report.pdf",
            }
        ],
        {},
    )
    assert len(mattermost.file_uploads) == 1
    assert b'filename="report.pdf"' in mattermost.file_uploads[0]
    assert b"pdf-data" in mattermost.file_uploads[0]
    assert len(mattermost.posts) == 1
    assert mattermost.posts[0]["channel_id"] == "dm-one"
    assert mattermost.posts[0]["file_ids"] == ["uploaded-one"]


@pytest.mark.asyncio
async def test_shared_runtime_fixture_adds_workspace_without_reinstall(
    runtime,
):
    first = await runtime()
    second = await runtime(
        existing_loader=first.loader, workspace_name="fixture-B"
    )
    assert first.record is second.record
    first_pid, second_pid = [
        rt.process.health_snapshot()["pid"] for rt in (first, second)
    ]
    assert first_pid != second_pid
    assert (await first.manager.stop_one("sample_chat")).stopped
    assert not psutil.pid_exists(first_pid) and psutil.pid_exists(second_pid)
