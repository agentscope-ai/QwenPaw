"""Discord official ZIP through the real host Agent and session lifecycle."""

import json
import os

import pytest

from discord_suite import forbid_host_sdk
from discord_support import (
    discord_sdk,
    eventually,
    fault_runtime,
    push,
    rows,
    runtime,
)
from g2_lifecycle_suite import official_zip_source
from real_host_runtime import bind_real_runtime


@pytest.mark.asyncio
async def test_official_zip_actual_agent_model_runs_in_host_and_session_is_readable(
    runtime, discord_sdk, monkeypatch
):
    from qwenpaw.runtime._state_utils import StateProxy

    rt = await runtime(
        "discord",
        source_factory=official_zip_source,
        bot_token="local-A",
        python_executable=discord_sdk.python,
        runtime_identity=discord_sdk.identity,
        dependency_paths=(discord_sdk.site,),
    )
    host = await bind_real_runtime(rt, monkeypatch)
    push(discord_sdk.work, text="native actual agent")
    try:
        await eventually(
            lambda: bool(host.calls) and bool(rows(discord_sdk.work, "send"))
        )
    except TimeoutError:
        raise AssertionError(host.events)
    assert host.calls[0]["pid"] == os.getpid()
    assert host.builds == [
        {
            "pid": os.getpid(),
            "session_id": "discord:dm:42",
            "agent": "QwenPawAgent",
        }
    ]
    assert (
        rows(discord_sdk.work, "send")[-1]["content"] == "actual agent answer"
    )
    assert (
        rows(discord_sdk.work, "send")[-1]["pid"]
        == rt.process.health_snapshot()["pid"]
        != os.getpid()
    )
    proxy = StateProxy()
    await host.session.load_session_state(
        session_id="discord:dm:42",
        user_id="42",
        channel="discord",
        agent=proxy,
    )
    serialized = json.dumps(proxy.data, ensure_ascii=False)
    assert "native actual agent" in serialized
    assert "actual agent answer" in serialized
