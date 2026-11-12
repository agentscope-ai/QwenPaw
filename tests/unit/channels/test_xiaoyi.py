# -*- coding: utf-8 -*-
"""XiaoYi socket authentication and routed A2A replies."""

import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from aiohttp import web, WSMsgType
from markdown_it import MarkdownIt
import pytest
from qwenpaw.__version__ import __version__
from qwenpaw.channel_protocol.models import ResponseFinishParams
from qwenpaw.config.config import ChannelConfig
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.channel_adapter import describe_channel
from qwenpaw.schemas import DataContent, Message, MessageType, TextContent
from tests.channel_support.driver import ROOT, bind, module
from tests.channel_support.protocol import eventually, finish, send


STREAMING = {f"config": {f"streaming_enabled": True}}


def inbound(message="message-A", session="session-A"):
    return {
        "agentId": "local-agent",
        "method": "message/stream",
        "id": "request-A",
        "params": {
            "sessionId": session,
            "id": "task-A",
            "message": {
                "messageId": message,
                "parts": [{"kind": "text", "text": "hello"}],
            },
        },
    }


@pytest.fixture
async def xiaoyi(tmp_path, monkeypatch, request):
    connections, headers, frames = {}, {}, []
    options = getattr(request, f"param", {})
    native = module(f"xiaoyi", f"platform")
    if f"queue_size" in options:
        monkeypatch.setattr(
            native,
            f"MAX_PENDING_MESSAGES",
            options[f"queue_size"],
        )
    if options.get(f"heartbeat"):
        connection = module(f"xiaoyi", f"connection")
        monkeypatch.setattr(connection, f"HEARTBEAT_INTERVAL", 0.08)
        monkeypatch.setattr(connection, f"PONG_TIMEOUT", 0.03)

    async def gateway(request):
        name = request.match_info["name"]
        headers[name] = dict(request.headers)
        ws = web.WebSocketResponse(autoping=False)
        await ws.prepare(request)
        connections[name] = ws
        async for frame in ws:
            if frame.type == WSMsgType.TEXT:
                frames.append((name, json.loads(frame.data)))
            elif frame.type == WSMsgType.PING and name not in options.get(
                f"ignore_pings",
                (),
            ):
                await ws.pong(frame.data)
            elif frame.type == WSMsgType.PONG:
                frames.append((name, {f"pong": bytes(frame.data)}))
        return ws

    async def media(request):
        name = request.match_info[f"name"]
        if name == f"missing":
            return web.Response(status=404)
        return web.Response(text=name)

    app = web.Application()
    app.router.add_get("/ws/{name}", gateway)
    app.router.add_get(f"/media/{{name}}", media)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    monkeypatch.setattr(
        native,
        "DEFAULT_WS_URL",
        f"ws://127.0.0.1:{port}/ws/primary",
    )
    monkeypatch.setattr(
        native,
        "DEFAULT_WS_URL_BACKUP",
        f"ws://127.0.0.1:{port}/ws/backup",
    )
    driver = module("xiaoyi").XiaoYiDriver()
    peer, identity = bind("xiaoyi", driver, tmp_path)
    try:
        config = {
            f"enabled": True,
            f"ak": f"local-ak",
            f"sk": f"local-sk",
            f"agent_id": f"local-agent",
            f"workspace_dir": str(tmp_path),
            **options.get(f"config", {}),
        }
        if options.get(f"single"):
            config[f"ws_url"] = native.DEFAULT_WS_URL
        await driver.start(config)
        count = 1 if options.get(f"single") else 2
        await eventually(lambda: len(connections) == count)
        yield driver, peer, identity, connections, headers, frames
    finally:
        await driver.stop()
        for ws in connections.values():
            await ws.close()
        await runner.cleanup()


def results(value):
    return [
        (server, json.loads(frame["msgDetail"])["result"])
        for server, frame in value[5]
        if frame.get("msgType") == "agent_response"
    ]


async def receive(value, server="primary", **kwargs):
    _, peer, _, connections, _, _ = value
    await connections[server].send_json(inbound(**kwargs))
    await eventually(lambda: bool(peer.batches))
    return peer.batches[-1]["events"][0]


async def prepare(peer, identity, handle):
    return await peer.methods[f"channel.response.prepare"](
        {
            **identity.to_mapping(),
            f"response_handle": handle,
            f"delivery_id": hashlib.sha256(
                f"{handle}:prepare".encode(),
            ).hexdigest(),
        },
        None,
    )


async def finish_with_outcome(peer, identity, handle, outcome):
    params = ResponseFinishParams.from_mapping(
        {
            **identity.to_mapping(),
            f"response_handle": handle,
            f"outcome": outcome,
        },
    )
    return await peer.methods[f"channel.response.finish"](params, None)


def with_files(message, *uris, session=f"session-A", name=f"test.txt"):
    value = inbound(message=message, session=session)
    value[f"params"][f"message"][f"parts"].extend(
        {f"kind": f"file", f"file": {f"name": name, f"uri": uri}}
        for uri in uris
    )
    return value


async def test_prepare_sends_working_before_any_reply(xiaoyi, monkeypatch):
    driver, peer, identity, _, _, _ = xiaoyi
    native = module(f"xiaoyi")
    monkeypatch.setattr(native, f"WORKING_INTERVAL", 0.02)
    event = await receive(xiaoyi)
    handle = event[f"response_handle"]
    assert driver.response_policy(handle).prepare
    assert not driver.response_policy(handle).streaming
    assert (await prepare(peer, identity, handle))[f"state"] == f"acknowledged"
    task = driver._working[handle]
    await prepare(peer, identity, handle)
    assert driver._working[handle] is task
    await eventually(lambda: len(results(xiaoyi)) >= 2)
    _, status = results(xiaoyi)[0]
    assert status[f"kind"] == f"status-update"
    assert status[f"final"] is False
    await finish(peer, identity, handle)
    await eventually(lambda: results(xiaoyi)[-1][1][f"final"])
    assert task.done() and handle not in driver._working
    statuses = [result[f"status"] for _, result in results(xiaoyi)[:-1]]
    assert statuses[-1][f"state"] == f"completed"
    for update in statuses[:-1]:
        assert update[f"state"] == f"working"
        assert update[f"message"][f"parts"] == [
            {f"kind": f"text", f"text": f"Working..."},
        ]


@pytest.mark.parametrize(
    (f"outcome", f"state"),
    [(f"cancelled", f"canceled"), (f"failed", f"failed")],
)
async def test_status_write_failure_is_best_effort(
    xiaoyi,
    monkeypatch,
    outcome,
    state,
):
    driver, peer, identity, _, _, _ = xiaoyi
    handle = (await receive(xiaoyi))[f"response_handle"]
    original = driver._platform.send_status

    async def send_status(route, status, text=f""):
        if status == f"working":
            raise driver.delivery_error(
                f"PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            )
        await original(route, status, text)

    monkeypatch.setattr(driver._platform, f"send_status", send_status)
    assert (await prepare(peer, identity, handle))[f"state"] == f"acknowledged"
    assert (await send(peer, identity, handle))[f"state"] == f"acknowledged"
    await finish_with_outcome(peer, identity, handle, outcome)
    await eventually(lambda: len(results(xiaoyi)) == 3)
    assert results(xiaoyi)[1][1][f"status"][f"state"] == state
    assert not driver._working


async def test_slow_attachment_preserves_order_without_blocking_other_input(
    xiaoyi,
    monkeypatch,
):
    driver, peer, _, connections, _, frames = xiaoyi
    started, release = asyncio.Event(), asyncio.Event()
    downloads = []

    async def download(url, *_args, **_kwargs):
        downloads.append(url)
        started.set()
        await release.wait()
        return f"attachment.txt"

    monkeypatch.setattr(
        module(f"xiaoyi", f"platform"),
        f"download_file",
        download,
    )
    first = with_files(f"message-A", f"https://example.test/file")
    await connections[f"primary"].send_json(first)
    await asyncio.wait_for(started.wait(), 3)
    try:
        await connections[f"primary"].send_json(inbound(message=f"second"))
        await connections[f"backup"].send_json(first)
        await connections[f"backup"].send_json(inbound(session=f"other"))
        await connections[f"primary"].ping(b"probe")
        await eventually(lambda: (f"primary", {f"pong": b"probe"}) in frames)
        await eventually(lambda: len(peer.batches) == 1)
        assert (
            peer.batches[0][f"events"][0][f"conversation"][f"id"] == f"other"
        )
    finally:
        release.set()
    await eventually(lambda: len(peer.batches) == 3)
    assert downloads == [f"https://example.test/file"]
    events = [batch[f"events"][0] for batch in peer.batches]
    assert [event[f"metadata"][f"native_message_id"] for event in events] == [
        f"message-A",
        f"message-A",
        f"second",
    ]
    assert events[1][f"content_parts"][1][f"file_url"] == f"attachment.txt"
    route = driver._route_attrs(events[1][f"response_handle"])
    assert route[f"server_name"] == f"primary"


@pytest.mark.parametrize(f"server", [f"primary", f"backup"])
async def test_reconnect_repairs_only_the_disconnected_socket(
    xiaoyi,
    monkeypatch,
    caplog,
    server,
):
    _, _, _, connections, _, _ = xiaoyi
    native = module(f"xiaoyi", f"platform")
    monkeypatch.setattr(native, f"RECONNECT_DELAYS", [0.01])
    healthy = f"backup" if server == f"primary" else f"primary"
    previous, survivor = connections[server], connections[healthy]
    await previous.close(code=1008, message=b"gateway probe")
    await eventually(lambda: connections[server] is not previous)
    assert connections[healthy] is survivor and not survivor.closed
    assert f"code=1008" in caplog.text and f"gateway probe" in caplog.text


@pytest.mark.parametrize(
    f"xiaoyi",
    [{f"heartbeat": True, f"ignore_pings": {f"primary"}}],
    indirect=True,
)
async def test_pong_timeout_reconnects_primary_only(
    xiaoyi,
    monkeypatch,
    caplog,
):
    _, _, _, connections, _, _ = xiaoyi
    native = module(f"xiaoyi", f"platform")
    monkeypatch.setattr(native, f"RECONNECT_DELAYS", [0.01])
    primary, backup = connections[f"primary"], connections[f"backup"]
    await eventually(lambda: connections[f"primary"] is not primary)
    assert f"Pong timeout" in caplog.text
    assert connections[f"backup"] is backup and not backup.closed


@pytest.mark.parametrize(
    f"xiaoyi",
    [{f"heartbeat": True, f"queue_size": 1}],
    indirect=True,
)
async def test_queue_backpressure_does_not_signal_a_pong_timeout(
    xiaoyi,
    monkeypatch,
    caplog,
):
    driver, peer, _, connections, _, frames = xiaoyi
    primary = connections[f"primary"]
    started, release = asyncio.Event(), asyncio.Event()

    async def download(*_args, **_kwargs):
        started.set()
        await release.wait()
        return f"attachment.txt"

    monkeypatch.setattr(
        module(f"xiaoyi", f"platform"),
        f"download_file",
        download,
    )
    await primary.send_json(with_files(f"first", f"https://example.test/file"))
    await asyncio.wait_for(started.wait(), 3)
    try:
        await primary.send_json(inbound(message=f"second"))
        connection = driver._platform._connections[f"primary"]
        await eventually(lambda: connection._dispatching_text)

        def heartbeat_count():
            return sum(
                name == f"primary" and frame.get(f"msgType") == f"heartbeat"
                for name, frame in frames
            )

        initial_heartbeats = heartbeat_count()
        await eventually(lambda: heartbeat_count() >= initial_heartbeats + 2)
        assert connections[f"primary"] is primary and not primary.closed
        assert f"Pong timeout" not in caplog.text
    finally:
        release.set()
    await eventually(lambda: len(peer.batches) == 2)


@pytest.mark.parametrize(
    f"xiaoyi",
    [{f"heartbeat": True, f"queue_size": 1}],
    indirect=True,
)
async def test_duplicate_waits_for_queue_if_first_socket_drops(
    xiaoyi,
    monkeypatch,
):
    driver, peer, _, connections, _, _ = xiaoyi
    platform = driver._platform
    primary, backup = connections[f"primary"], connections[f"backup"]
    started, release = asyncio.Event(), asyncio.Event()

    async def download(*_args, **_kwargs):
        started.set()
        await release.wait()
        return f"attachment.txt"

    native = module(f"xiaoyi", f"platform")
    monkeypatch.setattr(native, f"download_file", download)
    monkeypatch.setattr(native, f"RECONNECT_DELAYS", [0.01])
    await primary.send_json(with_files(f"first", f"https://example.test/file"))
    await asyncio.wait_for(started.wait(), 3)
    try:
        duplicate = inbound(message=f"duplicate")
        await primary.send_json(duplicate)
        first_connection = platform._connections[f"primary"]
        await eventually(lambda: first_connection._dispatching_text)
        await backup.send_json(duplicate)
        second_connection = platform._connections[f"backup"]
        await eventually(lambda: second_connection._dispatching_text)
        primary._req.transport.abort()
        await eventually(lambda: connections[f"primary"] is not primary)
    finally:
        release.set()
    await eventually(lambda: len(peer.batches) == 2)
    event = peer.batches[-1][f"events"][0]
    assert event[f"metadata"][f"native_message_id"] == f"duplicate"
    assert event[f"metadata"][f"server_name"] == f"backup"
    assert connections[f"backup"] is backup and not backup.closed


@pytest.mark.parametrize(f"xiaoyi", [{f"single": True}], indirect=True)
async def test_short_connections_exhaust_retries_on_custom_gateway(
    xiaoyi,
    monkeypatch,
):
    driver, _, _, connections, _, _ = xiaoyi
    native = module(f"xiaoyi", f"platform")
    monkeypatch.setattr(native, f"RECONNECT_DELAYS", [0.01])
    monkeypatch.setattr(native, f"MAX_RECONNECT_ATTEMPTS", 2)
    platform = driver._platform
    connection = platform._connections[f"primary"]
    for _ in range(2):
        previous = connection._ws
        await connections[f"primary"].close()
        await eventually(
            lambda: connection._ws is not previous and connection.connected,
        )
    await connections[f"primary"].close()
    await eventually(lambda: platform._last_state == f"failed")
    assert list(connections) == [f"primary"]


async def test_same_name_attachments_keep_independent_files(xiaoyi):
    _, peer, _, connections, _, _ = xiaoyi
    ws_url = module(f"xiaoyi", f"platform").DEFAULT_WS_URL
    media = ws_url.replace(f"ws://", f"http://").replace(
        f"/ws/primary",
        f"/media",
    )
    await connections[f"primary"].send_json(
        with_files(
            f"first",
            f"{media}/first",
            f"{media}/missing",
            name=f"CON.txt",
        ),
    )
    await connections[f"backup"].send_json(
        with_files(
            f"second",
            f"{media}/second",
            session=f"other",
            name=f"CON.txt",
        ),
    )
    await eventually(lambda: len(peer.batches) == 2)
    events = {
        event[f"metadata"][f"native_message_id"]: event[f"content_parts"]
        for batch in peer.batches
        for event in batch[f"events"]
    }
    first, second = events[f"first"], events[f"second"]
    assert first[0][f"text"] == f"hello [CON.txt: download failed]"
    files = [first[1], second[1]]
    assert [file[f"filename"] for file in files] == [f"CON.txt", f"CON.txt"]
    paths = [Path(file[f"file_url"]) for file in files]
    assert paths[0] != paths[1]
    assert all(path.name == f"_CON.txt" for path in paths)
    assert [path.read_bytes() for path in paths] == [b"first", b"second"]


async def test_stop_joins_pending_attachment_work(xiaoyi, monkeypatch):
    driver, peer, _, connections, _, _ = xiaoyi
    platform = driver._platform
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def download(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    monkeypatch.setattr(
        module(f"xiaoyi", f"platform"),
        f"download_file",
        download,
    )
    await connections[f"primary"].send_json(
        with_files(f"first", f"https://example.test/file"),
    )
    await asyncio.wait_for(started.wait(), 3)
    await connections[f"primary"].send_json(inbound(message=f"queued"))
    await eventually(lambda: len(platform._pending_events) == 2)
    http = platform._media_session
    await driver.stop()
    assert cancelled.is_set() and http.closed
    assert not platform._inbound and not platform._pending_events
    assert not peer.batches


async def test_repeated_push_reuses_attachment_after_admission_failure(
    xiaoyi,
    monkeypatch,
):
    driver, peer, _, connections, _, _ = xiaoyi
    platform = driver._platform
    admit = platform.on_event
    seen, downloads = [], []

    async def download(*_args, **_kwargs):
        downloads.append(f"file")
        return f"attachment.txt"

    async def fail_first(value):
        seen.append(value)
        return await admit(value) if len(seen) > 1 else False

    monkeypatch.setattr(
        module(f"xiaoyi", f"platform"),
        f"download_file",
        download,
    )
    monkeypatch.setattr(platform, f"on_event", fail_first)
    value = with_files(f"message-A", f"https://example.test/file")
    await connections[f"primary"].send_json(value)
    await eventually(lambda: bool(seen) and not platform._pending_events)
    await connections[f"backup"].send_json(value)
    await eventually(lambda: len(peer.batches) == 1)
    assert len(seen) == 2 and seen[0] == seen[1]
    assert seen[1][f"route"][f"server_name"] == f"primary"
    assert downloads == [f"file"]


def proxy_from_saved_config(tmp_path, input_config, process=None):
    source = ROOT / f"plugins" / f"channel" / f"xiaoyi"
    manifest = PluginManifest.from_dict(
        json.loads((source / f"plugin.json").read_text(encoding=f"utf-8")),
    )
    description = describe_channel(source, manifest)
    config = ChannelConfig.model_validate({f"xiaoyi": input_config})
    restored = ChannelConfig.model_validate_json(config.model_dump_json())
    prepared = description.prepare_proxy_config(
        restored.xiaoyi,
        working_dir=tmp_path,
        environment={},
    )
    return description.create_proxy(
        process,
        prepared.config,
        python_executable=sys.executable,
        support_root=ROOT / f"src",
        instance_id=f"xiaoyi-config-test",
        generation=1,
        qwenpaw_version=__version__,
        workspace_dir=tmp_path,
        prepared_config=prepared,
    )


@pytest.mark.parametrize(f"streaming_enabled", [True, False])
async def test_worker_uses_configured_reply_mode(
    xiaoyi,
    tmp_path,
    streaming_enabled,
):
    driver, _, _, connections, _, _ = xiaoyi
    await driver.stop()
    model_started, start_answer, finish_answer = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    queued = asyncio.Queue()
    tool_steps = (
        (f"write_file", f'{{"content": ""}}', f"Wrote 0 bytes."),
        (f"read_file", f'{{"file_path": "6.txt"}}', f"Empty file."),
    )
    thoughts = (f"First thought", f"Second thought", f"Last thought")

    async def enqueue(payload):
        queued.put_nowait(payload)
        return SimpleNamespace(accepted=True)

    async def process(_request):
        model_started.set()
        await start_answer.wait()
        for index, thought in enumerate(thoughts):
            message = Message(
                object=f"message",
                type=MessageType.REASONING,
                role=f"assistant",
            )
            yield message
            message.content = [TextContent(text=thought)]
            yield message.completed()
            if index == len(tool_steps):
                break
            name, arguments, output = tool_steps[index]
            for kind, key, value in (
                (MessageType.FUNCTION_CALL, f"arguments", arguments),
                (MessageType.FUNCTION_CALL_OUTPUT, f"output", output),
            ):
                tool_event = Message(
                    object=f"message",
                    type=kind,
                    role=f"assistant",
                    content=[DataContent(data={f"name": name, key: value})],
                )
                yield tool_event.completed()
        answer = Message(object=f"message", role=f"assistant")
        yield answer
        yield TextContent(text=f"first", delta=True, msg_id=answer.id)
        await finish_answer.wait()
        answer.content = [TextContent(text=f"first and final")]
        yield answer.completed()

    config = {
        f"enabled": True,
        f"ak": f"local-ak",
        f"sk": f"local-sk",
        f"agent_id": f"local-agent",
        f"ws_url": module(f"xiaoyi", f"platform").DEFAULT_WS_URL,
    }
    if streaming_enabled:
        config[f"streaming_enabled"] = True
    proxy = proxy_from_saved_config(tmp_path, config, process)
    proxy.set_enqueue_async(enqueue)
    running = None
    try:
        await proxy.start()
        await connections[f"primary"].send_json(inbound())
        payload = await asyncio.wait_for(queued.get(), 3)

        async def consume():
            async for _ in proxy._stream_with_tracker(payload):
                pass

        running = asyncio.create_task(consume())
        await asyncio.wait_for(model_started.wait(), 3)
        await eventually(lambda: len(results(xiaoyi)) == 1)
        assert results(xiaoyi)[0][1][f"status"][f"state"] == f"working"
        start_answer.set()
        before_final = 1 + len(thoughts) + len(tool_steps) * 2
        before_final += int(streaming_enabled)
        await eventually(lambda: len(results(xiaoyi)) == before_final)
        if streaming_enabled:
            preview = results(xiaoyi)[-1][1]
            assert preview[f"artifact"][f"parts"][0] == {
                f"kind": f"text",
                f"text": f"first",
            }
            assert preview[f"append"] is False and preview[f"lastChunk"]
        finish_answer.set()
        await asyncio.wait_for(running, 3)
        await eventually(lambda: len(results(xiaoyi)) == before_final + 3)
        rows = [row for _, row in results(xiaoyi)]
        assert rows[-1][f"final"] and rows[-1][f"append"]
        artifacts = [row for row in rows[:-1] if f"artifact" in row]
        append = not streaming_enabled
        assert all(
            row[f"append"] is append and row[f"lastChunk"] for row in artifacts
        )
        parts = [row[f"artifact"][f"parts"][0] for row in artifacts]
        shown_thoughts = [
            part[f"reasoningText"].strip().removeprefix(f"💭 ")
            for part in parts
            if f"reasoningText" in part
        ]
        assert shown_thoughts == list(thoughts)
        body = [part[f"text"] for part in parts if f"text" in part]
        assert body[-1].strip() == f"first and final"
        messages = [f"".join(body)] if append else body
        markdown = MarkdownIt()
        fences = [
            token.content
            for text in messages
            for token in markdown.parse(text)
            if token.type == f"fence"
        ]
        assert fences == [
            f"{value}\n"
            for _, arguments, output in tool_steps
            for value in (arguments, output)
        ]
    finally:
        if running is not None and not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        await proxy.stop()


@pytest.mark.parametrize(f"xiaoyi", [{}, STREAMING], indirect=True)
async def test_long_tool_text_preserves_code_fences_across_frames(xiaoyi):
    driver, peer, identity, _, _, _ = xiaoyi
    handle = (await receive(xiaoyi))[f"response_handle"]
    delivery = f"tool-result"
    output = f"x" * 4001
    text = f"**write_file**:\n```\n{output}\n```"
    reply = await send(
        peer,
        identity,
        handle,
        delivery=delivery,
        parts=[{f"type": f"text", f"role": f"rendered", f"text": text}],
        content_source=f"event",
    )
    assert reply[f"state"] == f"acknowledged"
    resource = driver._delivery_resource(handle, delivery)
    count = int(dict(resource.attributes)[f"frame_count"])
    await eventually(lambda: len(results(xiaoyi)) == count)
    rows = [row for _, row in results(xiaoyi)]
    chunks = [row[f"artifact"][f"parts"][0][f"text"] for row in rows]
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 4000 for chunk in chunks)
    assert f"".join(chunks) == f"\n\n{text}\n\n"
    assert len({row[f"artifact"][f"artifactId"] for row in rows}) == 1
    assert rows[0][f"append"] is (not driver.response_policy(handle).streaming)
    assert all(row[f"append"] is True for row in rows[1:])
    assert not any(row[f"lastChunk"] for row in rows[:-1])
    assert rows[-1][f"lastChunk"] is True


async def stream(
    peer,
    identity,
    handle,
    sequence,
    text,
    *,
    end=False,
    stream_type=f"message",
):
    target = f"{stream_type}-stream"
    operation = f"stream.end" if end else f"stream.delta"
    if sequence == 0:
        return await send(
            peer,
            identity,
            handle,
            delivery=target,
            operation=f"stream.start",
            stream_type=stream_type,
            accumulated_text=text,
        )
    return await send(
        peer,
        identity,
        handle,
        delivery=f"{target}-{sequence}",
        operation=operation,
        stream_type=stream_type,
        target_delivery_id=target,
        sequence=sequence,
        accumulated_text=text,
    )


@pytest.mark.parametrize(f"xiaoyi", [STREAMING], indirect=True)
async def test_body_stream_replaces_previews_and_publishes_final_text(xiaoyi):
    driver, peer, identity, _, _, _ = xiaoyi
    handle = (await receive(xiaoyi))[f"response_handle"]
    assert driver.response_policy(handle).streaming
    updates = (f"...", f"hello", f"hello world", f"hello world")
    for sequence, text in enumerate(updates):
        reply = await stream(peer, identity, handle, sequence, text)
        assert reply[f"state"] == f"acknowledged"
    await eventually(lambda: len(results(xiaoyi)) == 2)
    final_text = f"corrected\n" + f" a " * 1400
    reply = await stream(peer, identity, handle, 4, final_text, end=True)
    assert reply[f"state"] == f"acknowledged"
    await finish(peer, identity, handle)
    await eventually(lambda: len(results(xiaoyi)) == 6)
    previews = [row for _, row in results(xiaoyi)[:2]]
    final_parts = [row for _, row in results(xiaoyi)[2:4]]
    for preview, expected in zip(previews, updates[1:3]):
        assert preview[f"append"] is False and preview[f"lastChunk"]
        assert preview[f"artifact"][f"parts"][0] == {
            f"kind": f"text",
            f"text": expected,
        }
    ids = [row[f"artifact"][f"artifactId"] for row in previews + final_parts]
    assert ids[2] == ids[3] and len(set(ids)) == 3
    texts = [row[f"artifact"][f"parts"][0][f"text"] for row in final_parts]
    assert f"".join(texts) == final_text
    assert all(len(text) <= 4000 for text in texts)
    assert [row[f"append"] for row in final_parts] == [False, True]
    assert [row[f"lastChunk"] for row in final_parts] == [False, True]
    assert not any(row[f"final"] for row in previews + final_parts)
    assert results(xiaoyi)[-1][1][f"final"]


@pytest.mark.parametrize(f"xiaoyi", [STREAMING], indirect=True)
async def test_streaming_keeps_media_and_reasoning_separate(xiaoyi):
    _, peer, identity, _, _, _ = xiaoyi
    handle = (await receive(xiaoyi))[f"response_handle"]
    for seq, text in enumerate((f"...", f"partial thought", f"thought")):
        reply = await stream(
            peer,
            identity,
            handle,
            seq,
            text,
            end=seq == 2,
            stream_type=f"reasoning",
        )
        assert reply[f"state"] == f"acknowledged"
    media = [{f"type": f"image", f"image_url": f"https://example.test/photo"}]
    reply = await send(
        peer,
        identity,
        handle,
        parts=media,
        content_source=f"content_parts",
    )
    assert reply[f"state"] == f"acknowledged"
    await stream(peer, identity, handle, 0, f"...")
    await stream(peer, identity, handle, 1, f"short reply", end=True)
    await finish(peer, identity, handle)
    await eventually(lambda: len(results(xiaoyi)) == 6)
    rows = [row for _, row in results(xiaoyi)]
    assert rows[0][f"append"] is False
    parts = [
        part
        for row in rows[:-1]
        for part in row.get(f"artifact", {}).get(f"parts", [])
    ]
    assert [part[f"kind"] for part in parts] == [
        f"reasoningText",
        f"text",
        f"file",
        f"text",
    ]
    assert parts[0][f"reasoningText"] == f"thought\n\n"
    assert parts[-1][f"text"] == f"short reply"
    assert not any(row[f"final"] for row in rows[:-1])


@pytest.mark.parametrize(f"xiaoyi", [STREAMING], indirect=True)
async def test_cancel_ends_task_after_the_closed_preview(xiaoyi):
    _, peer, identity, _, _, _ = xiaoyi
    handle = (await receive(xiaoyi))[f"response_handle"]
    await stream(peer, identity, handle, 0, f"...")
    await stream(peer, identity, handle, 1, f"partial")
    await finish_with_outcome(peer, identity, handle, f"cancelled")
    await eventually(lambda: len(results(xiaoyi)) == 3)
    preview, status, final = [row for _, row in results(xiaoyi)]
    assert preview[f"lastChunk"] and not preview[f"final"]
    assert preview[f"artifact"][f"parts"][0][f"text"] == f"partial"
    assert status[f"status"][f"state"] == f"canceled" and final[f"final"]


@pytest.mark.parametrize(f"xiaoyi", [STREAMING], indirect=True)
async def test_partial_stream_write_keeps_unknown_receipt(xiaoyi, monkeypatch):
    driver, peer, identity, _, _, _ = xiaoyi
    handle = (await receive(xiaoyi))[f"response_handle"]
    await prepare(peer, identity, handle)
    await stream(peer, identity, handle, 0, f"...")
    original = driver._platform.send_stream_part
    chunks = []

    async def fail_second(*args, **kwargs):
        if chunks:
            raise driver.delivery_error(f"NOT_CONNECTED", retryable=True)
        await original(*args, **kwargs)
        chunks.append(args[3])

    monkeypatch.setattr(driver._platform, f"send_stream_part", fail_second)
    reply = await stream(peer, identity, handle, 1, f"x" * 4001)
    assert reply[f"state"] == f"unknown"
    assert reply[f"reason_code"] == f"PARTIAL_DELIVERY"
    resource = driver._delivery_resource(handle, f"message-stream")
    assert dict(resource.attributes)[f"unsettled"] == f"true"
    reply = await stream(peer, identity, handle, 2, f"final", end=True)
    assert reply[f"state"] == f"unknown"
    assert reply[f"reason_code"] == f"PLATFORM_RESULT_UNKNOWN"
    await finish_with_outcome(peer, identity, handle, f"failed")
    assert handle not in driver._working
    await eventually(lambda: len(results(xiaoyi)) == 2)
    assert chunks == [f"x" * 4000]
    assert all(not row[f"final"] for _, row in results(xiaoyi))


async def test_both_connections_authenticate_with_hmac_and_native_init(xiaoyi):
    _, _, _, _, headers, frames = xiaoyi
    for name in ("primary", "backup"):
        fields = {key.lower(): val for key, val in headers[name].items()}
        expected = base64.b64encode(
            hmac.new(
                b"local-sk",
                fields["x-ts"].encode(),
                hashlib.sha256,
            ).digest(),
        ).decode()
        assert (
            fields["x-access-key"] == "local-ak"
            and fields["x-agent-id"] == "local-agent"
        )
        assert fields["x-sign"] == expected and fields["x-ts"].isdigit()
    await eventually(
        lambda: len(
            [f for _, f in frames if f.get("msgType") == "clawd_bot_init"],
        )
        == 2,
    )
    assert all(
        json.loads(f["msgDetail"])["agentId"] == "local-agent"
        for _, f in frames
        if f.get("msgType") == "clawd_bot_init"
    )


@pytest.mark.parametrize("server", ["primary", "backup"])
async def test_native_text_keeps_session_task_and_same_server_reply(
    xiaoyi,
    server,
):
    driver, peer, identity, _, _, _ = xiaoyi
    event = await receive(xiaoyi, server)
    assert event["content_parts"] == [{"type": "text", "text": "hello"}]
    assert event["metadata"]["session_id"] == "xiaoyi:session-A"
    assert event["metadata"]["task_id"] == "task-A"
    assert (
        driver._route_attrs(event["response_handle"])["server_name"] == server
    )
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    await eventually(lambda: len(results(xiaoyi)) == 1)
    actual_server, result = results(xiaoyi)[0]
    assert actual_server == server and result["taskId"] == "task-A"
    assert result["artifact"]["parts"] == [
        {"kind": "text", "text": "native answer"},
    ]


async def test_completed_response_sends_status_then_final_empty_artifact_once(
    xiaoyi,
):
    _, peer, identity, _, _, _ = xiaoyi
    event = await receive(xiaoyi)
    await send(peer, identity, event["response_handle"])
    await finish(peer, identity, event["response_handle"])
    await eventually(lambda: len(results(xiaoyi)) == 3)
    rows = [result for _, result in results(xiaoyi)]
    assert [result["kind"] for result in rows] == [
        "artifact-update",
        "status-update",
        "artifact-update",
    ]
    assert (
        rows[1]["status"]["state"] == "completed" and rows[1]["final"] is False
    )
    assert rows[1][f"status"][f"message"][f"parts"] == [
        {f"kind": f"text", f"text": f"Done"},
    ]
    assert rows[2]["final"] is True and rows[2]["artifact"]["parts"] == [
        {"kind": "text", "text": ""},
    ]
    await finish(peer, identity, event["response_handle"])
    assert len(results(xiaoyi)) == 3


async def test_one_primary_disconnect_falls_back_to_backup_for_reply(xiaoyi):
    driver, peer, identity, connections, _, _ = xiaoyi
    event = await receive(xiaoyi)
    await connections["primary"].close()
    connections_by_name = driver._platform._connections
    await eventually(lambda: not connections_by_name[f"primary"].connected)
    assert connections_by_name[f"backup"].connected
    assert (await send(peer, identity, event["response_handle"]))[
        "state"
    ] == "acknowledged"
    await eventually(lambda: len(results(xiaoyi)) == 1)
    assert results(xiaoyi)[0][0] == "backup"


async def test_stop_releases_both_socket_readers_and_sessions(xiaoyi):
    driver, _, _, _, _, _ = xiaoyi
    platform = driver._platform
    connections = list(platform._connections.values())
    tasks = [
        task
        for conn in connections
        for task in (conn._receive_task, conn._heartbeat_task)
    ]
    sessions = [conn._session for conn in connections]
    await driver.stop()
    assert all(task.done() for task in tasks)
    assert all(session.closed for session in sessions)
    assert all(
        conn._ws is None and conn._session is None for conn in connections
    )
    assert driver._platform is None


def test_local_media_authorizes_workspace_and_rejects_outside(tmp_path):
    native = module("xiaoyi", "platform")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    media = workspace / "media"
    media.mkdir()
    allowed = workspace / "附件 with space.txt"
    allowed.write_text("local attachment")
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    platform = SimpleNamespace(_media_dir=media, _workspace_dir=workspace)
    for uri in (str(allowed), allowed.as_uri()):
        part = {"type": "file", "file_url": uri, "filename": allowed.name}
        assert native.XiaoYiPlatform._media_part(platform, part)["file"] == {
            "name": allowed.name,
            "mimeType": "application/octet-stream",
            "uri": uri,
        }
    for uri in (str(outside), outside.as_uri()):
        with pytest.raises(
            native.XiaoYiDeliveryError,
            match="MEDIA_PATH_UNAUTHORIZED",
        ):
            native.XiaoYiPlatform._media_part(
                platform,
                {"type": "file", "file_url": uri},
            )
    for part in (
        {"type": "image", "image_url": "https://example.test/image.png"},
        {"type": "audio", "data": "YWJjZA=="},
        {"type": "audio", "data": "data:audio/mpeg;base64,YWJjZA=="},
    ):
        assert native.XiaoYiPlatform._media_part(platform, part)["file"][
            "uri"
        ] == next(value for key, value in part.items() if key != "type")
