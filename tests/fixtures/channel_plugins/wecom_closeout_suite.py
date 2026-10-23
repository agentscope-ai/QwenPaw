"""Unchanged official ZIP to real Agent; only TLS trust and model are local."""

import asyncio
from dataclasses import asdict
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from wecom_native_support import WeComExternal, text_frame
from real_host_runtime import bind_real_runtime

pytest_plugins = ["extension_process_suite"]


def formal_wecom_source(directory, key, **_):
    from qwenpaw.plugins.official_channels import bundled_channel_source

    assert key == "wecom"
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


def trust_directory(tmp_path, server):
    # Actual certifi implementation; only external CA data changes. The SDK
    # passes certifi.where(), so SSL_CERT_FILE cannot supply test trust roots.
    source = Path(importlib.util.find_spec("certifi").origin).parent
    target = tmp_path / "tls-dependencies"
    shutil.copytree(
        source,
        target / "certifi",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (target / "certifi/cacert.pem").write_bytes(server.cert.read_bytes())
    assert {p.name: p.read_bytes() for p in source.glob("*.py")} == {
        p.name: p.read_bytes() for p in (target / "certifi").glob("*.py")
    }
    return target


@pytest.mark.asyncio
async def test_formal_zip_dm_group_acl_agent_and_session(
    runtime, tmp_path, monkeypatch
):
    import psutil

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "aibot" or fullname.startswith(
                ("aibot.", "qwenpaw_channel_wecom")
            ):
                raise AssertionError(
                    "WeCom implementation/SDK imported in host: " + fullname
                )

    guard = Guard()
    assert not any(
        n == "aibot" or n.startswith(("aibot.", "qwenpaw_channel_wecom"))
        for n in sys.modules
    )
    sys.meta_path.insert(0, guard)
    server_dir = tmp_path / "gateway"
    server_dir.mkdir()
    server = WeComExternal(server_dir).start()
    try:
        dependencies = trust_directory(tmp_path, server)
        rt = await runtime(
            "wecom",
            source_factory=formal_wecom_source,
            dependency_paths=(dependencies,),
            bot_id="formal-bot",
            secret="formal-secret",
            ws_url=server.url,
            streaming_enabled=True,
            access_control_dm=True,
            access_control_group=True,
        )
        host = await bind_real_runtime(
            rt, monkeypatch, reply="formal WeCom answer"
        )
        await eventually(
            lambda: rt.process.health_snapshot().get("platform_state")
            == "connected"
        )
        store = rt.channel._get_acl_store()
        store.add_to_whitelist("wecom", "sender-A")
        assert rt.channel.access_control_dm and rt.channel.access_control_group
        server.push(text_frame("denied", actor="denied-actor"))
        await eventually(
            lambda: any(
                r["user_id"] == "denied-actor" for r in store.get_all_pending()
            )
        )
        assert rt.ws.requests == [] and host.calls == []
        allowed_start = len(server.rows("aibot_respond_msg"))
        for mid, group, session, user in [
            ("direct", False, "wecom:sender-A", "sender-A"),
            ("group", True, "wecom:group:group-A", "group"),
        ]:
            before = len(rt.ws.requests)
            server.push(text_frame(mid, group=group))
            await eventually(lambda: len(rt.ws.requests) == before + 1)
            await eventually(
                lambda: any(
                    row["headers"]["req_id"] == "cb-" + mid
                    and row["body"].get("stream", {}).get("finish") is True
                    for row in server.rows("aibot_respond_msg")
                )
            )
            request = rt.ws.requests[-1]
            assert request.channel == "wecom" and request.user_id == user
            assert request.session_id == session
            assert [
                p.text for message in request.input for p in message.content
            ] == ["hello native"]
            assert request.channel_meta["wecom_sender_id"] == "sender-A"
            assert "frame" not in json.dumps(
                request.channel_meta, default=asdict
            )
            final = [
                r
                for r in server.rows("aibot_respond_msg")
                if r["headers"]["req_id"] == "cb-" + mid
                and r["body"].get("stream", {}).get("finish") is True
            ]
            assert (
                len(final) == 1
                and final[0]["body"]["stream"]["content"]
                == "formal WeCom answer"
            )
        assert len(rt.ws.requests) == len(host.calls) == len(host.builds) == 2
        assert all(r["agent"] == "QwenPawAgent" for r in host.builds)
        sessions = list((rt.ws.workspace_dir / "sessions").rglob("*.json"))
        assert len(sessions) == 2
        assert all(
            "hello native" in p.read_text()
            and "formal WeCom answer" in p.read_text()
            for p in sessions
        )
        assert len(server.rows("aibot_respond_msg")) > allowed_start
        assert not any(
            n == "aibot" or n.startswith(("aibot.", "qwenpaw_channel_wecom"))
            for n in sys.modules
        )
        pid = rt.process.health_snapshot()["pid"]
        assert pid != os.getpid() and psutil.pid_exists(pid)
        print(
            "WECOM_FORMAL "
            + json.dumps(
                {
                    "host_pid": os.getpid(),
                    "worker_pid": pid,
                    "requests": len(rt.ws.requests),
                    "agent_builds": host.builds,
                    "session_files": [str(p) for p in sessions],
                    "wire": server.rows(),
                }
            ),
            flush=True,
        )
        await rt.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid))
        await eventually(lambda: server.connection is None)
    finally:
        server.stop()
        sys.meta_path.remove(guard)
