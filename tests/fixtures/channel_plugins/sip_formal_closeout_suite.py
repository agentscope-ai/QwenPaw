"""Official SIP bundle through real Core/Agent; external SDKs controlled."""

import asyncio
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from real_host_runtime import bind_real_runtime

pytest_plugins = ["extension_process_suite"]
ROOT = Path(__file__).resolve().parents[3]


def formal_sip_source(directory, key, **_):
    from qwenpaw.plugins.official_channels import bundled_channel_source

    assert key == "sip"
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


def external_sdk_directory(tmp_path):
    """SDK module substitutes; installed distributions stay audited."""
    site, work = tmp_path / "sdk-boundary", tmp_path / "native-wire"
    site.mkdir()
    work.mkdir()
    for name in ("sip_vendor_boundary.py", "sip_formal_sdk_boundary.py"):
        (site / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    (site / "boundary-work.txt").write_text(str(work))
    modules = {
        "pyVoIP/__init__.py": "",
        "pyVoIP/VoIP.py": "pyVoIP.VoIP",
        "dashscope_realtime/__init__.py": "dashscope_realtime",
        "dashscope_realtime/asr.py": "dashscope_realtime.asr",
        "dashscope/__init__.py": "",
        "dashscope/audio/__init__.py": "",
        "dashscope/audio/tts_v2.py": "dashscope.audio.tts_v2",
        "livekit/__init__.py": "livekit",
        "livekit/api.py": "livekit.api",
        "livekit/rtc.py": "livekit.rtc",
    }
    for path, module in modules.items():
        target = site / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "from sip_formal_sdk_boundary import modules\n"
            f"globals().update(modules[{module!r}].__dict__)\n"
            if module
            else '"""Controlled external SDK package for isolated tests."""\n'
        )
    # Dependencies are already physically installed in this interpreter.
    # Reuse their real metadata: adding duplicate test dist-info is ambiguous.
    # Only the external SDK import surface is controlled on dependency_paths.
    return site, work


def ledger(work, pid, kind):
    path = work / "ledger.jsonl"
    return (
        [
            row
            for row in map(json.loads, path.read_text().splitlines())
            if row["pid"] == pid and row["kind"] == kind
        ]
        if path.exists()
        else []
    )


def emit(work, pid, **value):
    with (work / f"inbox-{pid}.jsonl").open("a") as stream:
        stream.write(json.dumps(value) + "\n")


@pytest.mark.asyncio
async def test_formal_dev_audio_agent_session_and_stop(
    runtime, tmp_path, monkeypatch
):
    import psutil

    class Guard(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith(
                (
                    "pyVoIP",
                    "dashscope_realtime",
                    "qwenpaw_channel_sip",
                    "dashscope.audio.tts_v2",
                )
            ):
                raise AssertionError("SIP implementation in host: " + fullname)

    guard = Guard()
    assert not any(
        n.startswith(("pyVoIP", "dashscope_realtime", "qwenpaw_channel_sip"))
        for n in sys.modules
    )
    sys.meta_path.insert(0, guard)
    dependencies, work = external_sdk_directory(tmp_path)
    try:
        rt = await runtime(
            "sip",
            source_factory=formal_sip_source,
            dependency_paths=(dependencies,),
            sip_mode="dev",
            sip_server="registrar.test",
            sip_port=25061,
            dashscope_api_key="formal-sip-key",
            welcome_greeting="",
        )
        host = await bind_real_runtime(
            rt, monkeypatch, reply="SIP formal answer"
        )
        await eventually(
            lambda: rt.process.health_snapshot().get("platform_state")
            == "connected"
        )
        pid = rt.process.health_snapshot()["pid"]
        assert pid != os.getpid() and psutil.pid_exists(pid)
        await eventually(lambda: ledger(work, pid, "loaded"))
        emit(
            work,
            pid,
            kind="incoming",
            call_id="formal-call",
            sender="sip:alice@example.test",
            audio_hex=(b"\x80" * 160).hex(),
        )
        await eventually(lambda: ledger(work, pid, "asr-audio"))
        assert ledger(work, pid, "asr")[0]["key"] == "formal-sip-key"
        assert [r["hex"] for r in ledger(work, pid, "asr-audio")] == [
            (b"\0" * 638).hex()
        ]
        emit(work, pid, kind="transcript", text="formal spoken question")
        await eventually(lambda: ledger(work, pid, "audio"))
        assert len(rt.ws.requests) == len(host.calls) == len(host.builds) == 1
        request = rt.ws.requests[0]
        assert request.channel == "sip"
        assert request.user_id == "sip:alice@example.test"
        assert request.session_id == "sip:formal-call"
        assert [p.text for m in request.input for p in m.content] == [
            "formal spoken question"
        ]
        assert host.builds[0]["agent"] == "QwenPawAgent"
        assert host.builds[0]["pid"] == os.getpid()
        assert [r["text"] for r in ledger(work, pid, "synthesis")] == [
            "SIP formal answer"
        ]
        assert [r["hex"] for r in ledger(work, pid, "audio")] == [
            (b"\x80" * 160).hex()
        ]
        await eventually(
            lambda: len(
                list((rt.ws.workspace_dir / "sessions").rglob("*.json"))
            )
            == 1
        )
        sessions = list((rt.ws.workspace_dir / "sessions").rglob("*.json"))
        assert len(sessions) == 1
        text = sessions[0].read_text()
        assert "formal spoken question" in text and "SIP formal answer" in text
        emit(work, pid, kind="inspect")
        await eventually(lambda: ledger(work, pid, "call-state"))
        assert ledger(work, pid, "call-state")[-1]["calls"] == [
            {"state": "answered", "hangups": 0}
        ]
        installed = {
            str(p.relative_to(rt.source)): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in rt.source.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
        print(
            "SIP_FORMAL "
            + json.dumps(
                {
                    "host_pid": os.getpid(),
                    "worker_pid": pid,
                    "agent": host.builds,
                    "installed_sha256": installed,
                    "session_sha256": hashlib.sha256(
                        sessions[0].read_bytes()
                    ).hexdigest(),
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
        await rt.manager.stop_all()
        await eventually(lambda: not psutil.pid_exists(pid))
        assert len(ledger(work, pid, "phone-stopped")) == 1
        assert rt.channel.channel_process.health_snapshot()["pid"] is None
    finally:
        (work / "stop-boundary").touch()
        sys.meta_path.remove(guard)
