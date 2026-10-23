"""Actual WeCom worker isolation and enabled candidate rollback."""

import json
import os
from pathlib import Path

import psutil
import pytest

from wecom_closeout_suite import (
    formal_wecom_source,
    trust_directory,
    eventually,
)
from wecom_native_support import WeComExternal, text_frame
from real_host_runtime import bind_real_runtime

pytest_plugins = ["extension_process_suite"]


def gateway(tmp_path, name):
    directory = tmp_path / name
    directory.mkdir()
    return WeComExternal(directory).start()


def question(server, mid, text):
    frame = text_frame(mid)
    frame["body"]["text"]["content"] = text
    server.push(frame)


def finals(server, mid):
    return [
        row
        for row in server.rows("aibot_respond_msg")
        if row["headers"]["req_id"] == "cb-" + mid
        and row["body"].get("stream", {}).get("finish") is True
    ]


def settings(server):
    return {
        "bot_id": "isolation-bot",
        "secret": "isolation-secret",
        "ws_url": server.url,
        "streaming_enabled": True,
    }


@pytest.mark.asyncio
async def test_formal_two_workspaces_keep_same_actor_and_event_isolated(
    runtime, tmp_path, monkeypatch
):
    from extension_process_suite import identity
    from qwenpaw.channel_protocol.errors import RpcError

    server_a, server_b = gateway(tmp_path, "gateway-a"), gateway(
        tmp_path, "gateway-b"
    )
    try:
        dependency = trust_directory(tmp_path, server_a)
        with (dependency / "certifi/cacert.pem").open("ab") as stream:
            stream.write(server_b.cert.read_bytes())
        first = await runtime(
            "wecom",
            source_factory=formal_wecom_source,
            dependency_paths=(dependency,),
            workspace_name="first",
            **settings(server_a),
        )
        host_a = await bind_real_runtime(
            first, monkeypatch, reply="workspace isolated answer"
        )
        second = await runtime(
            "wecom",
            existing_loader=first.loader,
            workspace_name="second",
            **settings(server_b),
        )
        old = identity(second)
        host_b = await bind_real_runtime(
            second, monkeypatch, reply="workspace isolated answer"
        )
        first.channel = await first.manager.get_channel("wecom")
        first.process = first.channel.channel_process
        await eventually(
            lambda: first.process.health_snapshot()["platform_state"]
            == second.process.health_snapshot()["platform_state"]
            == "connected"
        )
        pid_a = first.process.health_snapshot()["pid"]
        pid_b = second.process.health_snapshot()["pid"]
        assert len({pid_a, pid_b, os.getpid()}) == 3
        assert identity(second) != old
        with pytest.raises(RpcError):
            await second.process.call(
                "channel.response.open",
                {**old, "to_handle": "wecom:sender-A", "meta": {}},
            )
        assert server_a.rows("aibot_respond_msg") == []
        assert server_b.rows("aibot_respond_msg") == []
        question(server_a, "same-event", "first workspace question")
        question(server_b, "same-event", "second workspace question")
        await eventually(
            lambda: len(finals(server_a, "same-event"))
            == len(finals(server_b, "same-event"))
            == 1
        )
        assert len(first.ws.requests) == len(second.ws.requests) == 1
        assert (
            first.ws.requests[0].session_id
            == second.ws.requests[0].session_id
            == "wecom:sender-A"
        )
        assert host_a.builds and host_b.builds
        for rt, server, own, foreign in (
            (
                first,
                server_a,
                "first workspace question",
                "second workspace question",
            ),
            (
                second,
                server_b,
                "second workspace question",
                "first workspace question",
            ),
        ):
            assert rt.ws.requests[0].user_id == "sender-A"
            assert rt.ws.requests[0].input[0].content[0].text == own
            assert (
                finals(server, "same-event")[0]["body"]["stream"]["content"]
                == "workspace isolated answer"
            )
            sessions = list((rt.ws.workspace_dir / "sessions").rglob("*.json"))
            assert sessions and any(own in p.read_text() for p in sessions)
            assert all(foreign not in p.read_text() for p in sessions)
        first_effects = server_a.rows("aibot_respond_msg")
        await first.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid_a))
        await eventually(lambda: server_a.connection is None)
        assert psutil.pid_exists(pid_b)
        question(server_b, "survives", "second remains connected")
        await eventually(lambda: len(finals(server_b, "survives")) == 1)
        assert len(first.ws.requests) == 1 and len(second.ws.requests) == 2
        assert server_a.rows("aibot_respond_msg") == first_effects
        assert (
            finals(server_b, "survives")[0]["body"]["stream"]["content"]
            == "workspace isolated answer"
        )
        await second.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid_b))
        await eventually(lambda: server_b.connection is None)
    finally:
        server_a.stop()
        server_b.stop()


@pytest.mark.asyncio
async def test_enabled_candidate_failure_restores_code_session_and_delivery(
    runtime, tmp_path, monkeypatch
):
    server = gateway(tmp_path, "gateway")
    try:
        dependency = trust_directory(tmp_path, server)
        rt = await runtime(
            "wecom",
            source_factory=formal_wecom_source,
            dependency_paths=(dependency,),
            **settings(server),
        )
        host = await bind_real_runtime(
            rt, monkeypatch, reply="rollback retained answer"
        )
        await eventually(
            lambda: rt.process.health_snapshot()["platform_state"]
            == "connected"
        )
        question(server, "before-update", "persist before update")
        await eventually(lambda: len(finals(server, "before-update")) == 1)
        # The wire final precedes completion of the session metadata write.
        assert await rt.manager._drain_channel("wecom", timeout=5)
        sessions = {
            p: p.read_bytes()
            for p in (rt.ws.workspace_dir / "sessions").rglob("*.json")
        }
        assert sessions and all(
            b"persist before update" in v for v in sessions.values()
        )
        installed = rt.source / "qwenpaw_channel_wecom/driver.py"
        original = installed.read_bytes()
        candidate = formal_wecom_source(tmp_path / "update", "wecom")
        manifest_path = candidate / "plugin.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "2.0.0"
        manifest_path.write_text(json.dumps(manifest))
        with (candidate / "qwenpaw_channel_wecom/driver.py").open("a") as file:
            file.write(
                "\n_OriginalDriver = WeComDriver\n"
                "class WeComDriver(_OriginalDriver):\n"
                "    async def start(self, config):\n"
                '        if config.get("enabled"):\n'
                "            raise RuntimeError("
                '"CONTROLLED_CANDIDATE_FAILURE")\n'
                "        return await super().start(config)\n"
            )
        report = await rt.loader.lifecycle.reload(
            "wecom", new_source=candidate
        )
        assert not report.ok and report.errors
        assert installed.read_bytes() == original
        assert {p: p.read_bytes() for p in sessions} == sessions
        current = await rt.manager.get_channel("wecom")
        assert current is not None and current.enabled
        assert current._launch_spec.config["bot_id"] == "isolation-bot"
        assert current._launch_spec.config["secret"] == "isolation-secret"
        assert current._launch_spec.config["ws_url"] == server.url
        await eventually(
            lambda: current.channel_process.health_snapshot()["platform_state"]
            == "connected"
        )
        question(server, "after-update", "question after rollback")
        await eventually(lambda: len(finals(server, "after-update")) == 1)
        assert (
            finals(server, "after-update")[0]["body"]["stream"]["content"]
            == "rollback retained answer"
        )
        assert len(rt.ws.requests) == len(host.builds) == 2
        assert any(
            "persist before update" in p.read_text()
            and "question after rollback" in p.read_text()
            for p in sessions
        )
        pid = current.channel_process.health_snapshot()["pid"]
        await rt.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid))
        await eventually(lambda: server.connection is None)
    finally:
        server.stop()
