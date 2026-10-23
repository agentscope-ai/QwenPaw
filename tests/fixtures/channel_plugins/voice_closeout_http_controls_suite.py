"""No broad success fallback for selected, closed or owned Voice ingress."""

import asyncio
from datetime import datetime, timezone
import json
import os
import sys
import time
from urllib.parse import urlsplit

import psutil
import pytest

from real_host_runtime import bind_real_runtime
from voice_closeout_support import (
    AUTH,
    PUBLIC,
    fault_runtime,
    official_voice_source,
    runtime,
    voice_external,
    voice_host,
    voice_host_guard,
)

__all__ = [
    "fault_runtime",
    "runtime",
    "voice_external",
    "voice_host",
    "voice_host_guard",
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,status",
    [
        ("?_qp_endpoint=", 400),
        ("?_qp_endpoint=one&_qp_endpoint=two", 400),
        ("?_qp_endpoint=unknown-owner", 503),
    ],
)
async def test_explicit_selector_never_uses_legacy_success_fallback(
    voice_host, query, status
):
    for path in ("/voice/incoming", "/voice/status-callback"):
        async with voice_host.client.post(
            voice_host.base + path + query
        ) as response:
            assert response.status == status
            assert "<Response" not in await response.text()


@pytest.mark.asyncio
async def test_closed_real_service_never_uses_legacy_success_fallback(
    voice_host,
):
    await voice_host.service.aclose()
    voice_host.app.state.plugin_registry = voice_host.service.registry
    for service in (voice_host.service, None):
        voice_host.app.state.channel_ingress = service
        for path in ("/voice/incoming", "/voice/status-callback"):
            async with voice_host.client.post(
                voice_host.base + path
            ) as response:
                assert response.status == 503
                assert "<Response" not in await response.text()


def process_observation(pid):
    process = psutil.Process(pid)
    result = {
        "pid": pid,
        "ppid": process.ppid(),
        "rss_bytes": process.memory_info().rss,
        "threads": process.num_threads(),
        "executable": process.exe(),
        "cmdline": process.cmdline(),
    }
    try:
        result["inet_sockets"] = len(process.net_connections(kind="inet"))
    except (psutil.AccessDenied, NotImplementedError) as exc:
        result["inet_sockets"] = None
        result["socket_observation_error"] = type(exc).__name__
    return result


@pytest.mark.asyncio
async def test_owned_signature_and_ingress_fence_fail_closed_with_resources(
    voice_host, voice_external, monkeypatch, tmp_path
):
    gateway, external = voice_host, voice_external
    started = time.monotonic()
    rt = await gateway.runtime(
        "voice",
        source_factory=official_voice_source,
        dependency_paths=(external.sdk,),
        python_executable=external.python,
        runtime_identity=external.identity,
        twilio_account_sid="AC-formal",
        twilio_auth_token=AUTH,
        phone_number_sid="PN-formal",
    )
    await bind_real_runtime(rt, monkeypatch)
    await rt.channel._wait_connected()
    owners = rt.loader.registry.runtime_owners
    leases = owners.leases("voice")
    assert leases
    worker_pid = rt.process.health_snapshot()["pid"]
    tunnels = [
        json.loads(line)
        for line in external.tunnel_log.read_text().splitlines()
    ]
    live_tunnels = [r["pid"] for r in tunnels if psutil.pid_exists(r["pid"])]
    assert len(live_tunnels) == 1
    assert len({os.getpid(), worker_pid, live_tunnels[0]}) == 3
    observation = {
        "scope": (
            "minimal FastAPI production Voice router/A3, real Loader/Manager/"
            "Runtime ready, no active call; "
            "external REST/model/cloudflared controlled"
        ),
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "ready_observed_seconds_since_runtime_start": time.monotonic()
        - started,
        "parent": process_observation(os.getpid()),
        "worker": process_observation(worker_pid),
        "tunnels": [process_observation(p) for p in live_tunnels],
        "parent_asyncio_tasks": len(asyncio.all_tasks()),
        "child_health": rt.process.health_snapshot(),
        "selected_python": str(external.python),
        "parent_python": sys.executable,
        "same_interpreter_claim": False,
        "fixture_scope_warning": (
            "Parent includes local ASGI/Twilio REST fixtures "
            "and actual Runtime; "
            "no baseline/reduction comparison, no full App/phone claim"
        ),
    }
    assert observation["worker"]["ppid"] == os.getpid()
    assert observation["tunnels"][0]["ppid"] == worker_pid
    assert observation["parent"]["rss_bytes"] > 0
    assert observation["worker"]["rss_bytes"] > 0
    destination = tmp_path / "voice-active-owner-resource-observation.json"
    destination.write_text(json.dumps(observation, indent=2) + "\n")
    headers = {
        "Host": urlsplit(PUBLIC).netloc,
        "X-Twilio-Signature": "invalid",
    }
    for path in ("/voice/incoming", "/voice/status-callback"):
        async with gateway.client.post(
            gateway.base + path, headers=headers
        ) as response:
            assert response.status == 403
            assert "<Response" not in await response.text()
    # A missing App service cannot hide the actual registry's active owner.
    gateway.app.state.plugin_registry = gateway.service.registry
    gateway.app.state.channel_ingress = None
    for path in ("/voice/incoming", "/voice/status-callback"):
        async with gateway.client.post(
            gateway.base + path, headers=headers
        ) as response:
            assert response.status == 503
            assert "<Response" not in await response.text()
    gateway.app.state.channel_ingress = gateway.service
    assert await rt.manager.quiesce()
    assert owners.leases("voice") == leases
    assert psutil.pid_exists(worker_pid)
    assert rt.channel.endpoint_service.resolve(forwarding=True) is None
    for path in ("/voice/incoming", "/voice/status-callback"):
        async with gateway.client.post(
            gateway.base + path, headers=headers
        ) as response:
            assert response.status == 503
            assert "<Response" not in await response.text()
    receipt = await rt.manager.stop_one("voice")
    assert receipt.stopped and receipt.exited and not receipt.forced
    assert not receipt.residual and not psutil.pid_exists(worker_pid)
    assert not owners.leases("voice")
    assert all(not psutil.pid_exists(p) for p in live_tunnels)
    observation["cleanup"] = {
        "worker_gone": not psutil.pid_exists(worker_pid),
        "tunnels_gone": all(not psutil.pid_exists(p) for p in live_tunnels),
        "voice_leases": len(owners.leases("voice")),
    }
    destination.write_text(json.dumps(observation, indent=2) + "\n")
