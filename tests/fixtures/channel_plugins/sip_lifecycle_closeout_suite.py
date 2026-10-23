"""Formal SIP backend/workspace ownership and enabled-update rollback."""

import json
import os
import subprocess
import sys

import psutil
import pytest

from real_host_runtime import bind_real_runtime
from sip_formal_closeout_suite import (
    formal_sip_source,
    external_sdk_directory,
    emit,
    ledger,
    eventually,
)

pytest_plugins = ["extension_process_suite"]


def settings(mode, suffix):
    return {
        "sip_mode": mode,
        "sip_server": "registrar.test",
        "sip_port": 25061 + suffix,
        "dashscope_api_key": "formal-sip-key",
        "welcome_greeting": "",
        "livekit_url": "wss://livekit.test",
        "livekit_api_key": "controlled-key",
        "livekit_api_secret": "controlled-secret",
        "livekit_room_name": f"workspace-room-{suffix}",
    }


def probe_claim(rt, mode, suffix, expected):
    # Separate interpreter exercises the installed resource claim against a
    # real owned worker; no SDK/IPC/Loader replacement or private test RPC.
    url = (
        f"sip://localhost:{25061 + suffix}"
        if mode == "dev"
        else "https://LIVEKIT.test:443/"
    )
    room = "dev-listener" if mode == "dev" else f"workspace-room-{suffix}"
    reason = (
        "SIP_PORT_ALREADY_IN_USE"
        if mode == "dev"
        else "SIP_LIVEKIT_ROOM_ALREADY_OWNED"
    )
    script = (
        "import importlib.util,json,sys\n"
        "spec=importlib.util.spec_from_file_location('claim',sys.argv[1])\n"
        "module=importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(module)\n"
        "claim=module.ResourceClaim(sys.argv[2],sys.argv[3],"
        "reason_code=sys.argv[4])\n"
        "try:\n claim.acquire()\n"
        "except RuntimeError as exc:\n print(str(exc))\n"
        "else:\n claim.close();print('acquired')\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(rt.source / "qwenpaw_channel_sip/runtime.py"),
            url,
            room,
            reason,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=8,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        reason if expected == "blocked" else "acquired"
    )


async def ready(rt):
    rt.channel = await rt.manager.get_channel("sip")
    rt.process = rt.channel.channel_process
    await eventually(
        lambda: rt.process.health_snapshot()["platform_state"] == "connected"
    )
    return rt.process.health_snapshot()["pid"]


async def incoming(work, pid, mode):
    emit(
        work,
        pid,
        kind="incoming" if mode == "dev" else "livekit-incoming",
        call_id="same-call",
        sender="sip:same-actor@example.test",
        audio_hex=((b"\x80" * 160) if mode == "dev" else b"\0" * 960).hex(),
    )
    await eventually(lambda: ledger(work, pid, "asr-audio"))


async def question(work, pid, text, count):
    emit(work, pid, kind="transcript", text=text)
    await eventually(lambda: len(ledger(work, pid, "audio")) == count)


@pytest.mark.parametrize("mode", ["dev", "livekit"])
async def test_two_formal_workspaces_backend_isolation_and_retired_epoch(
    runtime, tmp_path, monkeypatch, mode
):
    from extension_process_suite import identity
    from qwenpaw.channel_protocol.errors import RpcError

    dependencies, work = external_sdk_directory(tmp_path)
    try:
        first = await runtime(
            "sip",
            source_factory=formal_sip_source,
            dependency_paths=(dependencies,),
            workspace_name="first",
            **settings(mode, 1),
        )
        host_a = await bind_real_runtime(
            first, monkeypatch, reply="owned answer"
        )
        second = await runtime(
            "sip",
            existing_loader=first.loader,
            workspace_name="second",
            **settings(mode, 2),
        )
        old = identity(second)
        host_b = await bind_real_runtime(
            second, monkeypatch, reply="owned answer"
        )
        pid_a, pid_b = await ready(first), await ready(second)
        assert len({pid_a, pid_b, os.getpid()}) == 3
        assert identity(second) != old
        probe_claim(first, mode, 1, "blocked")
        probe_claim(second, mode, 2, "blocked")
        with pytest.raises(RpcError):
            await second.process.call(
                "channel.response.open",
                {**old, "to_handle": "sip:same-call", "meta": {}},
            )
        for pid in (pid_a, pid_b):
            await incoming(work, pid, mode)
        await question(work, pid_a, "only first workspace", 1)
        await question(work, pid_b, "only second workspace", 1)
        for rt, host, pid, suffix, own, foreign in (
            (
                first,
                host_a,
                pid_a,
                1,
                "only first workspace",
                "only second workspace",
            ),
            (
                second,
                host_b,
                pid_b,
                2,
                "only second workspace",
                "only first workspace",
            ),
        ):
            assert len(rt.ws.requests) == len(host.builds) == 1
            request = rt.ws.requests[0]
            assert request.channel == "sip"
            assert request.user_id == "sip:same-actor@example.test"
            assert request.session_id == (
                "sip:same-call"
                if mode == "dev"
                else f"sip:workspace-room-{suffix}"
            )
            assert request.input[0].content[0].text == own
            sessions = list((rt.ws.workspace_dir / "sessions").rglob("*.json"))
            assert len(sessions) == 1
            assert own in sessions[0].read_text()
            assert foreign not in sessions[0].read_text()
            assert [r["text"] for r in ledger(work, pid, "synthesis")] == [
                "owned answer"
            ]
            assert [r["hex"] for r in ledger(work, pid, "audio")] == [
                ((b"\x80" * 160) if mode == "dev" else b"\0" * 960).hex()
            ]
        # bind_real_runtime installs one process-global external model factory;
        # its second model records both real workspaces' independent builds.
        assert host_a.calls == [] and len(host_b.calls) == 2
        await first.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid_a))
        assert psutil.pid_exists(pid_b)
        probe_claim(first, mode, 1, "acquired")
        probe_claim(second, mode, 2, "blocked")
        if mode == "livekit":
            emit(work, pid_b, kind="disconnect-room")
            await eventually(lambda: len(ledger(work, pid_b, "room")) == 2)
            emit(work, pid_b, kind="late-old-room")
            await incoming(work, pid_b, mode)
            await eventually(lambda: len(ledger(work, pid_b, "asr")) == 2)
        await question(work, pid_b, "second workspace survives", 2)
        assert len(first.ws.requests) == 1 and len(second.ws.requests) == 2
        assert len(host_a.builds) == 1 and len(host_b.builds) == 2
        assert len(host_b.calls) == 3
        assert len(ledger(work, pid_a, "audio")) == 1
        assert len(ledger(work, pid_b, "synthesis")) == 2
        await second.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid_b))
        probe_claim(second, mode, 2, "acquired")
        for pid in (pid_a, pid_b):
            if mode == "dev":
                assert len(ledger(work, pid, "phone-stopped")) == 1
            else:
                assert len(ledger(work, pid, "api-closed")) == 1
                count = 1 if pid == pid_a else 2
                assert len(ledger(work, pid, "room-disconnected")) == count
                assert len(ledger(work, pid, "source-closed")) == count
                assert len(ledger(work, pid, "reader-open")) == count
                assert len(ledger(work, pid, "reader-closed")) == count
        print(
            "SIP_WORKSPACES "
            + json.dumps(
                {
                    "mode": mode,
                    "worker_pids": [pid_a, pid_b],
                    "agent_builds": [host_a.builds, host_b.builds],
                    "native": [
                        json.loads(r)
                        for r in (work / "ledger.jsonl")
                        .read_text()
                        .splitlines()
                    ],
                }
            ),
            flush=True,
        )
    finally:
        (work / "stop-boundary").touch()


async def test_enabled_failure_rollback_keeps_sip_session_config_and_new_call(
    runtime, tmp_path, monkeypatch
):
    dependencies, work = external_sdk_directory(tmp_path)
    try:
        rt = await runtime(
            "sip",
            source_factory=formal_sip_source,
            dependency_paths=(dependencies,),
            **settings("dev", 3),
        )
        host = await bind_real_runtime(
            rt, monkeypatch, reply="rollback answer"
        )
        old_pid = await ready(rt)
        await incoming(work, old_pid, "dev")
        await question(work, old_pid, "before update", 1)
        # Native audio precedes the real consumer's final usage/session save.
        # Snapshot only after that actual task completes, without changing
        # the byte-equality oracle or cancelling the consumer.
        assert await rt.ws.task_tracker.wait_all_done(timeout=8)
        sessions = {
            p: p.read_bytes()
            for p in (rt.ws.workspace_dir / "sessions").rglob("*.json")
        }
        assert sessions and all(
            b"before update" in b for b in sessions.values()
        )
        installed = rt.source / "qwenpaw_channel_sip/driver.py"
        original = installed.read_bytes()
        candidate = formal_sip_source(tmp_path / "update", "sip")
        manifest = json.loads((candidate / "plugin.json").read_text())
        manifest["version"] = "2.0.0"
        (candidate / "plugin.json").write_text(json.dumps(manifest))
        with (candidate / "qwenpaw_channel_sip/driver.py").open("a") as stream:
            stream.write(
                "\n_OriginalDriver = SIPDriver\n"
                "class SIPDriver(_OriginalDriver):\n"
                "    async def start(self, config):\n"
                '        if config.get("enabled"):\n'
                "            raise RuntimeError("
                '"CONTROLLED_CANDIDATE_FAILURE")\n'
                "        return await super().start(config)\n"
            )
        report = await rt.loader.lifecycle.reload("sip", new_source=candidate)
        assert not report.ok and report.errors
        assert installed.read_bytes() == original
        assert {p: p.read_bytes() for p in sessions} == sessions
        pid = await ready(rt)
        assert pid != old_pid and not psutil.pid_exists(old_pid)
        assert rt.channel.enabled
        for key, value in settings("dev", 3).items():
            assert rt.channel._launch_spec.config[key] == value
        await incoming(work, pid, "dev")
        await question(work, pid, "after rollback", 1)
        assert len(rt.ws.requests) == len(host.builds) == 2
        assert all(
            "before update" in p.read_text()
            and "after rollback" in p.read_text()
            for p in sessions
        )
        assert ledger(work, pid, "synthesis")[0]["text"] == "rollback answer"
        await rt.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid))
        assert len(ledger(work, pid, "phone-stopped")) == 1
    finally:
        (work / "stop-boundary").touch()
