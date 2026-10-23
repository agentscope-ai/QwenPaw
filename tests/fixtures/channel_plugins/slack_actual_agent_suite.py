"""Actual Slack ZIP through Runtime/Builder/Executor/QwenPawAgent/session."""

import hashlib
import json
import os
import time

import psutil
import pytest

from slack_suite import forbid_host_sdk
from slack_support import (
    eventually,
    fault_runtime,
    push,
    rows,
    runtime,
    slack_sdk,
)
from g2_lifecycle_suite import official_zip_source
from real_host_runtime import bind_real_runtime


@pytest.mark.asyncio
async def test_zip_real_agent_session_and_all_worker_metrics(
    runtime, slack_sdk, monkeypatch, tmp_path
):
    from qwenpaw.runtime._state_utils import StateProxy

    parent = psutil.Process()
    before = {
        "rss_bytes": parent.memory_info().rss,
        "threads": parent.num_threads(),
        "worker_count": 0,
    }
    started = time.perf_counter()
    rt = await runtime(
        "slack",
        source_factory=official_zip_source,
        bot_token="local-A",
        app_token="xapp-test-token",
        python_executable=slack_sdk.python,
        runtime_identity=slack_sdk.identity,
        dependency_paths=(slack_sdk.site,),
    )
    host = await bind_real_runtime(rt, monkeypatch)
    push(slack_sdk.work, text="native actual agent")
    try:
        await eventually(
            lambda: bool(host.calls)
            and bool(rows(slack_sdk.work, "chat.postMessage"))
        )
    except TimeoutError:
        raise AssertionError(host.events)
    assert host.calls[0]["pid"] == os.getpid()
    assert host.builds == [
        {
            "pid": os.getpid(),
            "session_id": "slack:dm:U456",
            "agent": "QwenPawAgent",
        }
    ]
    post = rows(slack_sdk.work, "chat.postMessage")[-1]
    assert post["arguments"]["text"] == "actual agent answer"
    assert post["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
    proxy = StateProxy()
    await host.session.load_session_state(
        session_id="slack:dm:U456",
        user_id="U456",
        channel="slack",
        agent=proxy,
    )
    serialized = json.dumps(proxy.data, ensure_ascii=False)
    assert "native actual agent" in serialized
    assert "actual agent answer" in serialized
    assert rt.source.is_relative_to(rt.loader.plugin_dirs[0])
    artifact = next((tmp_path / "official-bundle").rglob("*slack*.zip"))
    worker = psutil.Process(rt.process.health_snapshot()["pid"])
    metrics = {
        "scope": (
            "Slack ZIP real Agent/local model service and nativ"
            "e SDK transport simulation; all 16 final release t"
            "argets remain separate"
        ),
        "baseline_same_parent_before_install": before,
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
    ] + sum(row["rss_bytes"] for row in metrics["workers"])
    assert (
        metrics["parent_plus_workers_rss_bytes"] > metrics["parent_rss_bytes"]
    )
    assert (await rt.manager.stop_one("slack")).stopped
    metrics["after_workspace_disabled"] = {
        "parent_rss_bytes": parent.memory_info().rss,
        "parent_threads": parent.num_threads(),
        "worker_count": 0,
        "former_worker_alive": psutil.pid_exists(worker.pid),
    }
    assert metrics["after_workspace_disabled"]["former_worker_alive"] is False
