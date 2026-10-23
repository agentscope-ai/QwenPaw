"""Official bundle through real Core/Agent/session and native Gateway/REST."""

import json
import os

import psutil
import pytest

from extension_process_suite import eventually
from real_host_runtime import bind_real_runtime
from qq_closeout_formal_support import (
    external,
    official_qq_zip,
    qq_host_import_guard,
    runtime,
)

__all__ = ["external", "qq_host_import_guard", "runtime"]


@pytest.mark.asyncio
async def test_official_qq_gateway_actual_agent_session_and_native_reply(
    runtime, external, monkeypatch
):
    from qwenpaw.runtime._state_utils import StateProxy

    rt = await runtime(
        "qq",
        source_factory=official_qq_zip,
        app_id="local-app",
        client_secret="local-secret",
        bot_prefix="[MustNotPrefix]",
        markdown_enabled=True,
    )
    host = await bind_real_runtime(rt, monkeypatch, reply="actual QQ answer")
    await rt.channel._wait_connected()
    await eventually(lambda: len(external.connections) == 2)
    assert rt.record.manifest.id == "qq"
    assert rt.channel._launch_spec.plugin_id == "qq"
    assert rt.channel._launch_spec.private_env == {
        "QQ_API_BASE": external.base,
        "QQ_TOKEN_URL": external.base + "/token",
    }
    pid = rt.process.health_snapshot()["pid"]
    assert pid is not None and pid != os.getpid()
    assert external.api_rows() == []
    external.push(
        {
            "op": 0,
            "s": 2,
            "t": "C2C_MESSAGE_CREATE",
            "d": {
                "id": "formal-qq-message",
                "content": " hello formal QQ ",
                "author": {"user_openid": "actor-A"},
                "thread_id": "untrusted-thread",
            },
        }
    )
    await eventually(
        lambda: len(external.rows("/v2/users/actor-A/messages")) == 1
    )
    await eventually(
        lambda: any(
            isinstance(e, dict)
            and e.get("object") == "response"
            and e.get("status") == "completed"
            for e in host.events
        )
    )
    assert len(host.calls) == len(host.builds) == 1
    assert host.calls[0]["pid"] == os.getpid()
    assert host.builds[0]["agent"] == "QwenPawAgent"
    assert host.builds[0]["session_id"] == "qq:c2c:actor-A"
    assert len(rt.ws.requests) == 1
    request = rt.ws.requests[0]
    assert request.channel == "qq" and request.user_id == "actor-A"
    assert request.session_id == "qq:c2c:actor-A"
    assert request.channel_meta["sender_id"] == "actor-A"
    assert request.channel_meta["message_id"] == "formal-qq-message"
    sent = external.rows("/v2/users/actor-A/messages")
    assert len(sent) == 1
    assert sent[0]["method"] == "POST"
    assert sent[0]["auth"] == "QQBot native-token"
    assert sent[0]["body"] == {
        "markdown": {"content": "actual QQ answer"},
        "msg_type": 2,
        "msg_seq": 1,
        "msg_id": "formal-qq-message",
    }
    assert "[MustNotPrefix]" not in sent[0]["raw"].decode()
    assert all(
        row["body"] == {"appId": "local-app", "clientSecret": "local-secret"}
        for row in external.rows("/token")
    )
    saved = StateProxy()
    await host.session.load_session_state(
        session_id="qq:c2c:actor-A",
        user_id="actor-A",
        channel="qq",
        agent=saved,
    )
    persisted = json.dumps(saved.data, ensure_ascii=False)
    assert "hello formal QQ" in persisted and "actual QQ answer" in persisted
    receipt = await rt.manager.stop_one("qq")
    assert receipt.stopped and receipt.exited and not receipt.forced
    assert receipt.residual == () and not psutil.pid_exists(pid)
    assert not rt.loader.registry.runtime_owners.leases(plugin_id="qq")
