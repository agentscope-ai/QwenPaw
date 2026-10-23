"""Unmodified official OneBot worker through real Core/Agent and reverse WS."""

import asyncio
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import sys

import aiohttp
import psutil
import pytest

from real_host_runtime import bind_real_runtime

pytest_plugins = ["extension_process_suite"]


def formal_onebot_source(directory, key, **_):
    from qwenpaw.plugins.official_channels import bundled_channel_source

    assert key == "onebot"
    with bundled_channel_source(key) as source:
        target = directory / key
        shutil.copytree(source, target)
        assert {
            str(p.relative_to(source)): p.read_bytes()
            for p in source.rglob("*")
            if p.is_file()
        } == {
            str(p.relative_to(target)): p.read_bytes()
            for p in target.rglob("*")
            if p.is_file()
        }
    return target


async def eventually(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(0.01)


def incoming(number, text, *, group=None, user=12345):
    value = {
        "post_type": "message",
        "message_type": "group" if group else "private",
        "message_id": number,
        "user_id": user,
        "self_id": 99999,
        "message": [{"type": "text", "data": {"text": text}}],
        "sender": {"nickname": "Formal User", "card": ""},
    }
    if group:
        value["group_id"] = group
    return value


async def test_formal_reverse_ws_auth_dm_group_agent_session_and_stop(
    runtime, monkeypatch
):
    class NoPrivateParent(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith("qwenpaw_channel_onebot"):
                raise AssertionError("private OneBot imported in parent")

    guard = NoPrivateParent()
    monkeypatch.setattr(sys, "meta_path", [guard, *sys.meta_path])
    rt = await runtime(
        "onebot",
        source_factory=formal_onebot_source,
        ws_host="127.0.0.1",
        ws_port=0,
        access_token="formal-secret",
        share_session_in_group=True,
    )
    host = await bind_real_runtime(
        rt, monkeypatch, reply="OneBot actual answer"
    )
    health = rt.process.health_snapshot()
    assert health["state"] == "ready"
    assert health["platform_state"] == "connected"
    pid = health["pid"]
    assert pid != os.getpid() and psutil.pid_exists(pid)
    current = rt.channel.endpoint_service.resolve()
    assert current is not None
    endpoint = current.endpoint
    assert endpoint.generation == health["generation"]
    assert endpoint.readiness == "ready" and endpoint.auth_required
    assert endpoint.host == "127.0.0.1" and endpoint.port > 0
    assert endpoint.path == "/ws" and not endpoint.bound_externally
    url = f"http://127.0.0.1:{endpoint.port}/ws"
    effects = []
    async with aiohttp.ClientSession() as client:
        for headers in ({}, {"Authorization": "Bearer incorrect"}):
            with pytest.raises(aiohttp.WSServerHandshakeError) as exc:
                await client.ws_connect(url, headers=headers)
            assert exc.value.status == 401
        assert rt.ws.requests == [] and host.calls == []
        async with client.ws_connect(
            url, headers={"Authorization": "Bearer formal-secret"}
        ) as ws:
            for number, group, prompt in (
                (501, None, "formal private question"),
                (502, 777, "formal group question"),
            ):
                await ws.send_json(incoming(number, prompt, group=group))
                frame = await asyncio.wait_for(ws.receive_json(), 8)
                effects.append(frame)
                assert frame["action"] == (
                    "send_group_msg" if group else "send_private_msg"
                )
                assert frame["params"] == {
                    "group_id" if group else "user_id": group or 12345,
                    "message": [
                        {
                            "type": "text",
                            "data": {"text": "OneBot actual answer"},
                        }
                    ],
                }
                assert isinstance(frame["echo"], str) and frame["echo"]
                await ws.send_json(
                    {
                        "retcode": 0,
                        "data": {"message_id": 9000 + number},
                        "echo": frame["echo"],
                    }
                )
                assert await rt.ws.task_tracker.wait_all_done(timeout=8)
            assert (
                len(rt.ws.requests) == len(host.calls) == len(host.builds) == 2
            )
            assert [r.user_id for r in rt.ws.requests] == ["12345", "12345"]
            assert [r.session_id for r in rt.ws.requests] == [
                "onebot:12345",
                "onebot:g:777",
            ]
            assert [r.input[0].content[0].text for r in rt.ws.requests] == [
                "formal private question",
                "formal group question",
            ]
            assert all(r.channel == "onebot" for r in rt.ws.requests)
            sessions = list((rt.ws.workspace_dir / "sessions").rglob("*.json"))
            assert len(sessions) == 2
            contents = [p.read_text() for p in sessions]
            for prompt in ("formal private question", "formal group question"):
                matching = [value for value in contents if prompt in value]
                assert (
                    len(matching) == 1
                    and "OneBot actual answer" in matching[0]
                )
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ws.receive_json(), 0.05)
        await rt.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid))
        assert rt.channel.endpoint_service.resolve() is None
        assert not rt.channel.endpoint_service.is_current(current)
    print(
        "ONEBOT_FORMAL "
        + json.dumps(
            {
                "pid": pid,
                "endpoint": endpoint.to_mapping(),
                "effects": effects,
                "agent_builds": host.builds,
                "sessions": [str(p) for p in sessions],
            }
        ),
        flush=True,
    )
