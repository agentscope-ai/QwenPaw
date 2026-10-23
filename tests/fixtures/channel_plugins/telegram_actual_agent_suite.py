"""Formal Telegram ZIP through actual Runtime/Agent and persisted session."""

import json
import os
import hashlib
import time

import psutil

import pytest

from telegram_business_suite import forbid_host_sdk
from telegram_support import (
    eventually,
    fault_runtime,
    push,
    rows,
    runtime,
    telegram_sdk,
    TOKEN,
)
from g2_lifecycle_suite import official_zip_source
from telegram_support import bind_telegram_runtime


@pytest.mark.asyncio
async def test_formal_zip_core_agent_model_pid_sdk_reply_and_public_session(
    runtime, telegram_sdk, monkeypatch, tmp_path
):
    from qwenpaw.runtime._state_utils import StateProxy

    parent = psutil.Process()
    baseline = {
        "rss_bytes": parent.memory_info().rss,
        "threads": parent.num_threads(),
        "worker_count": 0,
    }
    started = time.perf_counter()
    rt = await runtime(
        "telegram",
        source_factory=official_zip_source,
        bot_token=TOKEN,
        python_executable=telegram_sdk.python,
        runtime_identity=telegram_sdk.identity,
        dependency_paths=(telegram_sdk.site,),
    )
    host = await bind_telegram_runtime(rt, monkeypatch)
    push(telegram_sdk.work, text="native actual agent")
    try:
        await eventually(
            lambda: bool(host.calls)
            and bool(rows(telegram_sdk.work, "sendMessage"))
        )
    except TimeoutError:
        raise AssertionError(host.events)
    assert host.calls[0]["pid"] == os.getpid()
    assert host.builds == [
        {
            "pid": os.getpid(),
            "session_id": "telegram:12345",
            "agent": "QwenPawAgent",
        }
    ]
    post = rows(telegram_sdk.work, "sendMessage")[-1]
    assert post["arguments"]["chat_id"] == 12345
    assert post["arguments"]["text"] == "actual agent answer"
    assert post["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
    proxy = StateProxy()
    await host.session.load_session_state(
        session_id="telegram:12345",
        user_id="456",
        channel="telegram",
        agent=proxy,
    )
    state = json.dumps(proxy.data, ensure_ascii=False)
    assert "native actual agent" in state
    assert "actual agent answer" in state
    assert rt.source.is_relative_to(rt.loader.plugin_dirs[0])
    worker = psutil.Process(rt.process.health_snapshot()["pid"])
    artifact = next((tmp_path / "official-bundle").rglob("*telegram*.zip"))
    metrics = {
        "scope": (
            "Telegram formal ZIP/local model and native PTB HTTP service; "
            "cross-16 comparable release remains pending"
        ),
        "baseline_same_parent_before_install": baseline,
        "parent_pid": parent.pid,
        "parent_rss_bytes": parent.memory_info().rss,
        "parent_threads": parent.num_threads(),
        "workers": [
            {
                "pid": worker.pid,
                "rss_bytes": worker.memory_info().rss,
                "threads": worker.num_threads(),
            }
        ],
        "install_connect_actual_agent_ms": (time.perf_counter() - started)
        * 1000,
        "artifact_bytes": artifact.stat().st_size,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    metrics["parent_plus_workers_rss_bytes"] = metrics[
        "parent_rss_bytes"
    ] + sum(v["rss_bytes"] for v in metrics["workers"])
    assert (await rt.manager.stop_one("telegram")).stopped
    assert psutil.pid_exists(worker.pid) is False
    metrics["after_workspace_stopped"] = {
        "parent_rss_bytes": parent.memory_info().rss,
        "parent_threads": parent.num_threads(),
        "worker_count": 0,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command,needle",
    [
        ("/version", "Daemon version"),
        ("/daemon version", "Daemon version"),
        ("/status", "Daemon Status"),
        ("/approval", "审批"),
    ],
)
async def test_native_control_commands_reach_real_runtime_without_model(
    runtime, telegram_sdk, monkeypatch, command, needle
):
    rt = await runtime(
        "telegram",
        source_factory=official_zip_source,
        bot_token=TOKEN,
        python_executable=telegram_sdk.python,
        runtime_identity=telegram_sdk.identity,
        dependency_paths=(telegram_sdk.site,),
    )
    host = await bind_telegram_runtime(rt, monkeypatch)
    push(
        telegram_sdk.work,
        text=command,
        entities=[
            {
                "type": "bot_command",
                "offset": 0,
                "length": len(command.split()[0]),
            }
        ],
    )
    await eventually(lambda: bool(rows(telegram_sdk.work, "sendMessage")))
    assert (
        needle
        in rows(telegram_sdk.work, "sendMessage")[-1]["arguments"]["text"]
    )
    assert host.calls == []
    assert rt.ws.requests[0].input[0].content[0].text == command
    await eventually(lambda: rt.ws.requests[0]._channel_control_state is None)
