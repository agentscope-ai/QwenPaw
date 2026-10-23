"""Real Host/worker sparse card projection and merged reply ownership."""

import os
import json

import pytest

from wecom_closeout_suite import (
    WeComExternal,
    eventually,
    formal_wecom_source,
    trust_directory,
)
from wecom_native_support import text_frame
from real_host_runtime import bind_real_runtime

pytest_plugins = ["extension_process_suite"]


@pytest.mark.asyncio
async def test_formal_sparse_card_defaults_and_merged_last_frame_all_handles(
    runtime, tmp_path, monkeypatch
):
    import psutil
    from qwenpaw.app.channels.unified_queue_manager import EnqueueResult
    from qwenpaw.schemas import Message, RunStatus

    gateway_dir = tmp_path / "gateway"
    gateway_dir.mkdir()
    server = WeComExternal(gateway_dir).start()
    try:
        dependencies = trust_directory(tmp_path, server)
        rt = await runtime(
            "wecom",
            source_factory=formal_wecom_source,
            dependency_paths=(dependencies,),
            bot_id="formal-bot",
            secret="formal-secret",
            ws_url=server.url,
        )
        host = await bind_real_runtime(rt, monkeypatch)
        await eventually(
            lambda: rt.process.health_snapshot().get("platform_state")
            == "connected"
        )
        received = []

        async def record_native(payload):
            received.append(payload)
            return EnqueueResult(True)

        # Real ingress validation and ACK; recording the admission boundary
        # lets this test isolate actual Host merge/projection, not Agent logic.
        rt.channel.set_enqueue_async(record_native)
        for number, text in enumerate(["Hello", "World", "!"], start=1):
            frame = text_frame("merge-" + str(number))
            frame["body"]["text"]["content"] = text
            server.push(frame)
            await eventually(lambda: len(received) == number)
        assert host.calls == host.builds == []
        assert rt.channel.merge_native_items([]) is None
        one = rt.channel.merge_native_items(received[:1])
        assert len(one["content_parts"]) == 1
        assert one["content_parts"][0].text == "Hello"
        merged = rt.channel.merge_native_items(received)
        assert len(merged["content_parts"]) == 3
        assert [part.text for part in merged["content_parts"]] == [
            "Hello",
            "World",
            "!",
        ]
        handles = [item["meta"]["response_handle"] for item in received]
        assert len(set(handles)) == 3
        assert merged["meta"]["response_handle"] == handles[-1]
        assert merged["meta"]["_merged_response_handles"] == handles
        request = rt.channel.build_agent_request_from_native(merged)
        handle = rt.channel.get_to_handle_from_request(request)
        meta = request.channel_meta
        await rt.channel.send_content_parts(
            handle, merged["content_parts"], meta
        )
        replies = server.rows("aibot_respond_msg")
        assert len(replies) == 1
        assert replies[0]["headers"]["req_id"] == "cb-merge-3"
        assert replies[0]["body"]["stream"]["content"] == "Hello\nWorld\n!"
        assert replies[0]["body"]["stream"]["finish"] is True

        # The legacy sparse metadata defaults are supplied by the real Host,
        # not invented in a private Driver test or intercepted send method.
        event = Message(
            object="message",
            status=RunStatus.Completed,
            role="assistant",
            content=[],
            metadata={
                "message_type": "tool_guard_approval",
                "approval_request_id": "rid-1",
            },
        )
        await rt.channel.on_event_message_completed(
            request, handle, event, meta
        )
        replies = server.rows("aibot_respond_msg")
        assert len(replies) == 3
        assert replies[1]["body"]["stream"]["content"] == ""
        assert replies[1]["body"]["stream"]["finish"] is True
        assert replies[2]["body"]["template_card"]["main_title"]["desc"] == (
            "tool | medium"
        )
        assert (
            replies[2]["body"]["template_card"]["task_id"]
            == "tg_approval_rid-1"
        )
        assert all(row["headers"]["req_id"] == "cb-merge-3" for row in replies)
        await rt.channel._finish_route(meta, "completed")
        rows = rt.channel._state["wecom.shared.responses"]["value"]
        receipts = {row["response_handle"]: row for row in rows}
        assert set(receipts) == set(handles)
        assert all(receipts[h]["kind"] == "terminal" for h in handles)
        assert all(receipts[h]["cleanup_state"] == "complete" for h in handles)
        assert all(receipts[h]["outcome"] == "completed" for h in handles)
        assert server.rows("aibot_respond_msg") == replies
        pid = rt.process.health_snapshot()["pid"]
        assert pid != os.getpid() and psutil.pid_exists(pid)
        print(
            "WECOM_MERGE_CARD "
            + json.dumps(
                {
                    "worker_pid": pid,
                    "host_pid": os.getpid(),
                    "response_handles": handles,
                    "wire": replies,
                    "receipts": receipts,
                }
            ),
            flush=True,
        )
        await rt.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid))
        await eventually(lambda: server.connection is None)
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_formal_enabled_configuration_get(
    runtime, tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from qwenpaw.app.routers import config as routes
    from qwenpaw.config.config import load_agent_config, save_agent_config

    gateway_dir = tmp_path / "config-gateway"
    gateway_dir.mkdir()
    server = WeComExternal(gateway_dir).start()
    try:
        rt = await runtime(
            "wecom",
            source_factory=formal_wecom_source,
            dependency_paths=(trust_directory(tmp_path, server),),
            bot_id="formal-bot",
            secret="formal-secret",
            ws_url=server.url,
        )
        host = await bind_real_runtime(rt, monkeypatch)
        await eventually(
            lambda: rt.process.health_snapshot().get("platform_state")
            == "connected"
        )
        profile = load_agent_config(rt.ws.agent_id)
        profile.channels = rt.ws._config.channels
        save_agent_config(rt.ws.agent_id, profile)

        async def selected_workspace(_):
            return rt.ws

        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_agent_for_request",
            selected_workspace,
        )
        app = FastAPI()
        app.state.plugin_loader = rt.loader
        app.include_router(routes.router)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/config/channels/wecom")
        assert response.status_code == 200
        assert response.json()["enabled"] is True
        assert response.json()["bot_id"] == "formal-bot"
        assert response.json()["ws_url"] == server.url
        assert len(server.rows("aibot_subscribe")) >= 1
        assert host.calls == host.builds == []
    finally:
        server.stop()
