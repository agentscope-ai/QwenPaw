"""A Manager-owned QR login must leave the real Console Agent available."""

import asyncio
import json
import os
import time

import psutil
import pytest

from extension_process_suite import eventually
from real_host_runtime import bind_real_runtime
from wechat_w4_formal_support import (
    official_wechat_zip,
    runtime,
    wechat_host_import_guard,
)
from wechat_w4_waiting_support import native_ilink, qr_ilink

__all__ = ["runtime", "native_ilink", "qr_ilink", "wechat_host_import_guard"]


@pytest.mark.asyncio
async def test_manager_waiting_qr_keeps_console_agent_then_connects_and_stops(
    runtime,
    qr_ilink,
    monkeypatch,
    tmp_path,
    capfd,
):
    from qwenpaw.runtime._state_utils import StateProxy
    from qwenpaw.schemas import TextContent

    external = qr_ilink
    rt = await runtime(
        "wechat",
        source_factory=official_wechat_zip,
        bot_token="temporary-file-token",
        bot_token_file=str(tmp_path / "warm-auth/token"),
        media_dir=str(tmp_path / "media"),
        base_url=external.mock.base_url,
    )
    warm_pid = rt.process.health_snapshot()["pid"]
    fresh_auth = tmp_path / "waiting-auth/token"
    values = rt.ws._config.model_dump(mode="json")
    values["channels"]["wechat"].update(
        {
            "bot_token": "",
            "bot_token_file": str(fresh_auth),
        }
    )
    rt.ws._config = type(rt.ws._config).model_validate(values)
    rt.ws.config = rt.ws._config
    reply = "Console Agent available during QR wait"
    binding = asyncio.create_task(
        bind_real_runtime(rt, monkeypatch, reply=reply)
    )
    try:
        await eventually(lambda: external.qr_polls or binding.done())
        if binding.done():
            await binding
            pytest.fail("WeChat connected before an actual QR poll")
        assert not psutil.pid_exists(warm_pid)
        pending = await rt.manager.get_channel("wechat")
        assert pending is not None
        process = pending.channel_process
        waiting_health = process.health_snapshot()
        pid = waiting_health["pid"]
        assert pid != os.getpid() and psutil.pid_exists(pid)
        assert waiting_health["state"] == "ready"
        assert waiting_health["platform_state"] == "connecting"
        assert pending._launch_spec.startup_timeout == 5
        assert not fresh_auth.exists()
        # The link must cross worker IPC before the same pending QR is scanned.
        terminal = capfd.readouterr()
        assert external.mock.base_url + "/scan" in terminal.err
        assert "temporary-file-token" not in terminal.out + terminal.err
        assert external.mock.base_url + "/scan" not in json.dumps(
            rt.ws._config.model_dump(mode="json")
        )
        assert external.qr_fetches == 1
        console = await rt.manager.get_channel("console")
        assert console is not None
        frames = [
            frame
            async for frame in console.stream_one(
                {
                    "channel_id": "console",
                    "sender_id": "console-user",
                    "content_parts": [
                        TextContent(text="chat during WeChat QR wait")
                    ],
                    "meta": {"session_id": "console-during-wechat-qr"},
                }
            )
        ]
        events = [
            json.loads(line[6:])
            for frame in frames
            for line in frame.splitlines()
            if line.startswith("data: ") and line[6:] != "[DONE]"
        ]
        assert any(
            event.get("object") == "response"
            and event.get("status") == "completed"
            for event in events
        )
        assert reply in json.dumps(events)
        assert rt.ws.requests[-1].channel == "console"
        assert rt.ws.requests[-1].session_id == "console-during-wechat-qr"
        elapsed = time.monotonic() - external.qr_polls[0]["time"]
        await asyncio.sleep(max(0, 5.2 - elapsed))
        elapsed = time.monotonic() - external.qr_polls[0]["time"]
        assert elapsed > pending._launch_spec.startup_timeout
        assert not binding.done()
        assert process.health_snapshot()["pid"] == pid
        assert process.health_snapshot()["platform_state"] == "connecting"
        assert len(external.qr_polls) >= 2
        assert {row["status"] for row in external.qr_polls} == {"waiting"}
        external.qr_confirmed = True
        async with asyncio.timeout(8):
            host = await binding
        assert rt.process is process
        assert process.health_snapshot()["platform_state"] == "connected"
        assert fresh_auth.read_text() == "temporary-file-token"
        assert external.qr_fetches == 1
        assert external.qr_polls[-1]["status"] == "confirmed"
        assert all(
            row["qrcode"] == ["controlled-runtime-code"]
            for row in external.qr_polls
        )
        target = "after-qr@im.wechat"
        external.mock.push_text_message(
            text="native chat after QR confirmation",
            from_user_id=target,
            context_token="after-qr-context",
        )
        await eventually(lambda: len(external.mock.sent_messages) == 1)
        sent = external.mock.sent_messages[0]
        assert sent["to_user_id"] == target
        assert sent["context_token"] == "after-qr-context"
        assert sent["item_list"] == [{"type": 1, "text_item": {"text": reply}}]
        assert len(host.calls) == 2 and len(host.builds) == 2
        assert all(row["pid"] == os.getpid() for row in host.calls)
        snapshot = StateProxy()
        await host.session.load_session_state(
            session_id="console-during-wechat-qr",
            user_id="console-user",
            channel="console",
            agent=snapshot,
        )
        assert reply in json.dumps(snapshot.data)
        owners = rt.loader.registry.runtime_owners
        leases = owners.leases("wechat")
        assert sum(lease.key.kind == "channel" for lease in leases) == 1
        assert sum(lease.key.kind == "wechat_auth" for lease in leases) == 2
        receipt = await rt.manager.stop_one("wechat")
        assert receipt.stopped and receipt.exited and not receipt.forced
        assert receipt.residual == () and not psutil.pid_exists(pid)
        assert owners.leases("wechat") == ()
        (tmp_path / "waiting-runtime-observation.json").write_text(
            json.dumps(
                {
                    "qr_wait_seconds": elapsed,
                    "startup_budget": 5,
                    "warm_worker_exited": not psutil.pid_exists(warm_pid),
                    "waiting_worker_pid": pid,
                    "qr_poll_count": len(external.qr_polls),
                    "console_completed_during_wait": True,
                    "actual_agent_builds": host.builds,
                    "native_send_count": len(external.mock.sent_messages),
                    "stop_receipt": {
                        "stopped": receipt.stopped,
                        "exited": receipt.exited,
                        "forced": receipt.forced,
                        "residual": list(receipt.residual),
                    },
                    "remaining_wechat_leases": len(owners.leases("wechat")),
                },
                indent=2,
            )
        )
    finally:
        if not binding.done():
            binding.cancel()
        await asyncio.gather(binding, return_exceptions=True)
