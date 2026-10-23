"""Remaining ingress oracles through the unmodified bundle and real Agent."""

import asyncio

import aiohttp
from aiohttp import web
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from onebot_formal_closeout_suite import (
    eventually,
    formal_onebot_source,
    incoming,
)
from real_host_runtime import bind_real_runtime

pytest_plugins = ["extension_process_suite"]


async def test_formal_mention_acl_get_notice_empty_and_string(
    runtime, monkeypatch
):
    from qwenpaw.app.routers import config as routes
    from qwenpaw.config.config import load_agent_config, save_agent_config

    hits = []

    async def forbidden_download(request):
        hits.append(request.path)
        return web.Response(body=b"not requested", content_type="image/png")

    external = web.Application()
    external.router.add_get("/image", forbidden_download)
    server = web.AppRunner(external)
    await server.setup()
    site = web.TCPSite(server, "127.0.0.1", 0)
    await site.start()
    media_port = site._server.sockets[0].getsockname()[1]
    try:
        rt = await runtime(
            "onebot",
            source_factory=formal_onebot_source,
            ws_host="127.0.0.1",
            ws_port=0,
            require_mention=True,
            access_control_dm=True,
            access_control_group=True,
        )
        host = await bind_real_runtime(
            rt, monkeypatch, reply="remaining reply"
        )
        assert rt.channel.access_control_dm is True
        assert rt.channel.access_control_enabled is True
        gate_rows = []
        from qwenpaw.app.channels.base import BaseChannel

        real_gate = BaseChannel._access_control_gate

        async def observe_real_gate(channel, payload):
            blocked = await real_gate(channel, payload)
            actor = (
                payload.get("acl_sender_id")
                if isinstance(payload, dict)
                else getattr(payload, "acl_sender_id", None)
            )
            if channel is rt.channel:
                gate_rows.append((actor, blocked))
            return blocked

        monkeypatch.setattr(
            BaseChannel, "_access_control_gate", observe_real_gate
        )
        store = rt.channel._get_acl_store()
        store.add_to_whitelist("onebot", "12345")
        assert store.is_whitelisted("onebot", "12345")
        assert not store.is_whitelisted("onebot", "67890")
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
            result = await client.get("/config/channels/onebot")
        assert result.status_code == 200
        assert result.json()["enabled"] is True
        assert result.json()["require_mention"] is True
        endpoint = rt.channel.endpoint_service.resolve().endpoint
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(
                f"http://127.0.0.1:{endpoint.port}/ws"
            ) as ws:
                await ws.send_json({"echo": "unknown", "retcode": 0})
                await ws.send_json(
                    {
                        "post_type": "meta_event",
                        "meta_event_type": "lifecycle",
                        "self_id": 99999,
                    }
                )
                await ws.send_json(
                    {
                        "post_type": "meta_event",
                        "meta_event_type": "heartbeat",
                        "self_id": 99999,
                    }
                )
                await ws.send_json(
                    {"post_type": "notice", "notice_type": "poke"}
                )
                empty = incoming(801, "")
                empty["message"] = []
                await ws.send_json(empty)
                unmentioned = incoming(802, "hello", group=67890)
                await ws.send_json(unmentioned)
                unmentioned["message_id"] = 803
                unmentioned["message"] = [
                    {
                        "type": "image",
                        "data": {
                            "url": f"http://127.0.0.1:{media_port}/image"
                        },
                    }
                ]
                await ws.send_json(unmentioned)
                await ws.send_json(incoming(804, "denied", user=67890))
                denial = await asyncio.wait_for(ws.receive_json(), 8)
                assert denial["action"] == "send_private_msg"
                assert denial["params"]["user_id"] == 67890
                assert denial["params"]["message"][0]["type"] == "text"
                assert denial["params"]["message"][0]["data"]["text"]
                await ws.send_json(
                    {"retcode": 0, "data": {}, "echo": denial["echo"]}
                )
                assert (
                    rt.ws.requests == []
                    and host.calls == []
                    and host.builds == []
                )
                assert [
                    (row["channel"], row["user_id"])
                    for row in store.get_all_pending()
                ] == [("onebot", "67890")]
                mentioned = incoming(805, "hello", group=67890)
                mentioned.pop("self_id")
                mentioned["message"].insert(
                    0, {"type": "at", "data": {"qq": "99999"}}
                )
                plain = incoming(806, "")
                plain["message"] = "plain text message"
                for event, action, key, target in (
                    (mentioned, "send_group_msg", "group_id", 67890),
                    (plain, "send_private_msg", "user_id", 12345),
                ):
                    await ws.send_json(event)
                    reply = await asyncio.wait_for(ws.receive_json(), 8)
                    assert reply["action"] == action
                    assert reply["params"] == {
                        key: target,
                        "message": [
                            {
                                "type": "text",
                                "data": {"text": "remaining reply"},
                            }
                        ],
                    }
                    await ws.send_json(
                        {"retcode": 0, "data": {}, "echo": reply["echo"]}
                    )
                    assert await rt.ws.task_tracker.wait_all_done(timeout=8)
                assert (
                    len(rt.ws.requests)
                    == len(host.calls)
                    == len(host.builds)
                    == 2
                )
                assert [r.session_id for r in rt.ws.requests] == [
                    "onebot:67890:12345",
                    "onebot:12345",
                ]
                # Host admission and consumption both enforce the real gate.
                assert gate_rows == [
                    ("67890", True),
                    ("12345", False),
                    ("12345", False),
                    ("12345", False),
                    ("12345", False),
                ]
                assert [
                    r.input[0].content[0].text for r in rt.ws.requests
                ] == ["hello", "plain text message"]
                assert rt.ws.requests[0].channel_meta["is_group"] is True
                assert rt.ws.requests[0].channel_meta["group_id"] == "67890"
                assert (
                    rt.ws.requests[1].channel_meta["message_type"] == "private"
                )
                assert rt.ws.requests[1].channel_meta["sender_id"] == "12345"
                assert all(
                    r.user_id == "12345" and r.channel == "onebot"
                    for r in rt.ws.requests
                )
                assert hits == []
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(ws.receive_json(), 0.05)
                sessions = list(
                    (rt.ws.workspace_dir / "sessions").rglob("*.json")
                )
                assert len(sessions) == 2
                assert all(
                    "remaining reply" in p.read_text() for p in sessions
                )
        await rt.manager.stop_all()
        await eventually(lambda: rt.channel.endpoint_service.resolve() is None)
    finally:
        await server.cleanup()
