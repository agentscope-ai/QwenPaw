"""Independent Slack artifact and real worker contracts."""

import json
import sys
from pathlib import Path
import importlib.abc
import os

import pytest

from slack_support import (
    callback_done,
    eventually,
    fault_runtime,
    finish,
    identity,
    push,
    route,
    rows,
    runtime,
    send,
    set_mode,
    slack,
    slack_sdk,
)


class HostImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(
            ("slack_bolt", "slack_sdk", "qwenpaw_channel_slack")
        ):
            raise AssertionError(
                "Slack implementation imported in host: " + fullname
            )


@pytest.fixture(autouse=True)
def forbid_host_sdk():
    guard = HostImportGuard()
    sys.meta_path.insert(0, guard)
    yield
    sys.meta_path.remove(guard)


ROOT = Path(__file__).resolve().parents[3]


def test_slack_official_artifact_and_sdk_free_descriptor():
    """A missing/invalid plugin cannot replace the legacy channel owner."""
    source = ROOT / "plugins/channel/slack"
    for relative in (
        "plugin.json",
        "channel.json",
        "requirements.txt",
        "README.md",
        "qwenpaw_channel_slack/__init__.py",
        "qwenpaw_channel_slack/driver.py",
    ):
        assert (source / relative).is_file(), relative

    from qwenpaw.config.config import SlackConfig
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    manifest = PluginManifest.model_validate(
        json.loads((source / "plugin.json").read_text())
    )
    descriptor = describe_channel(source, manifest).descriptor
    assert manifest.id == "slack"
    assert manifest.entry.descriptor == "channel.json"
    assert descriptor.schema_version == 2
    assert descriptor.channel_key == "slack"
    assert descriptor.process_mode == "runner_process"
    assert descriptor.dependency_mode == "shared"
    assert descriptor.entrypoint.scope == "runner"
    assert descriptor.entrypoint.module == "qwenpaw_channel_slack.driver"
    assert descriptor.requirements_file == "requirements.txt"
    assert "channel.generic.v1" in descriptor.capabilities
    assert set(descriptor.config_fields) == set(SlackConfig.model_fields)
    assert set(descriptor.config_fields) == set(
        descriptor.config_schema["properties"]
    )
    for key, default in SlackConfig().model_dump().items():
        assert (
            descriptor.config_schema["properties"][key].get("default")
            == default
        )
    assert not any(
        name.startswith(("slack_bolt", "slack_sdk", "qwenpaw_channel_slack"))
        for name in sys.modules
    )


@pytest.mark.asyncio
async def test_real_socket_native_callback_host_dm_and_sdk_origin(
    runtime, slack_sdk
):
    rt = await slack(runtime, slack_sdk, proxy="http://proxy:8080")
    connect = rows(slack_sdk.work, "ws-connect")[0]
    assert connect["arguments"]["proxy"] == "http://proxy:8080"
    auth = rows(slack_sdk.work, "auth.test")[0]
    assert auth["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
    assert Path(auth["sdk_source"]).is_relative_to(slack_sdk.site)
    push(slack_sdk.work, text="Hello bot")
    await eventually(lambda: bool(rows(slack_sdk.work, "chat.postMessage")))
    assert len(rt.ws.requests) == 1
    request = rt.ws.requests[0]
    assert request.user_id == "U456"
    assert request.channel == "slack"
    assert request.session_id == "slack:dm:U456"
    assert len(request.input) == 1
    assert request.input[0].content[0].text == "Hello bot"
    assert request.channel_meta["slack_channel_id"] == "D123"
    assert request.channel_meta["slack_message_ts"] == "1000000000.000001"
    posted = rows(slack_sdk.work, "chat.postMessage")[-1]["arguments"]
    assert posted["channel"] == "D123"
    assert posted["text"] == "host answer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event,session",
    [
        ({"channel": "C123", "text": "<@U999> hello"}, "slack:ch:C123"),
        (
            {
                "channel": "C123",
                "thread_ts": "1234567890.123456",
                "text": "<@U999> hello",
            },
            "slack:thread:C123:1234567890.123456",
        ),
        (
            {"channel": "D123", "thread_ts": "123.456"},
            "slack:thread:D123:123.456",
        ),
    ],
)
async def test_original_channel_thread_and_dm_session_precedence(
    runtime, slack_sdk, event, session
):
    rt = await slack(runtime, slack_sdk)
    push(slack_sdk.work, **event)
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert rt.ws.requests[0].session_id == session
    assert rt.ws.requests[0].user_id == "U456"
    assert rt.ws.requests[0].channel == "slack"
    assert len(rt.ws.requests[0].input) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings,event",
    [
        ({"require_mention": True}, {"channel": "C123"}),
        (
            {"require_mention": False},
            {"channel": "C123", "thread_ts": "1234567890.123456"},
        ),
        ({"dm_disabled": True}, {}),
        (
            {"group_disabled": True},
            {"channel": "C123", "text": "<@U999> hello"},
        ),
        ({}, {"bot_id": "B999"}),
        ({}, {"subtype": "channel_join"}),
        ({}, {"subtype": "message_deleted"}),
        ({}, {"subtype": "custom_unsupported"}),
    ],
)
async def test_platform_gates_ack_without_host_execution(
    runtime, slack_sdk, settings, event
):
    rt = await slack(runtime, slack_sdk, **settings)
    push(slack_sdk.work, **event)
    await callback_done(slack_sdk)
    assert rt.ws.requests == []
    assert rows(slack_sdk.work, "chat.postMessage") == []


@pytest.mark.asyncio
async def test_message_app_mention_pair_and_stable_redelivery_execute_once(
    runtime, slack_sdk
):
    rt = await slack(runtime, slack_sdk, require_mention=True)
    push(slack_sdk.work, channel="C123", text="hello")
    await callback_done(slack_sdk)
    assert rt.ws.requests == []
    push(slack_sdk.work, callback="app_mention", channel="C123", text="hello")
    await eventually(lambda: len(rt.ws.requests) == 1)
    push(slack_sdk.work, callback="app_mention", channel="C123", text="hello")
    await callback_done(slack_sdk, 3)
    assert len(rt.ws.requests) == 1
    assert rt.ws.requests[0].input[0].content[0].text == "hello"


@pytest.mark.asyncio
async def test_no_proxy_aggregate_bypass_applies_to_native_rest_ws_and_http(
    runtime, slack_sdk, monkeypatch
):
    monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy:8080")
    monkeypatch.setenv("NO_PROXY", "files.slack.com")
    rt = await slack(runtime, slack_sdk)
    assert rows(slack_sdk.work, "ws-connect")[0]["arguments"]["proxy"] is None
    push(
        slack_sdk.work,
        callback="app_mention",
        channel="C123",
        thread_ts="1234567890.123456",
        files=[
            {
                "mimetype": "image/png",
                "name": "file.png",
                "url_private": "https://files.slack.com/file.png",
            }
        ],
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    for method in ("auth.test", "users.info", "conversations.replies"):
        assert all(
            row["proxy"] is None for row in rows(slack_sdk.work, method)
        )
    assert rows(slack_sdk.work, "http-get")[0]["proxy"] == ""
    await rt.channel.send_content_parts(
        "C123",
        [
            {
                "type": "file",
                "file_url": "data:application/pdf;base64,cGRmLWRhdGE=",
            }
        ],
    )
    assert rows(slack_sdk.work, "http-post")[-1]["proxy"] == ""


@pytest.mark.asyncio
async def test_host_proxy_environment_fallback_reaches_native_worker(
    runtime, slack_sdk, monkeypatch
):
    monkeypatch.setenv("HTTP_PROXY", "http://env-proxy:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://other-proxy:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)
    rt = await slack(runtime, slack_sdk)
    assert rt.ws.config.channels.slack.proxy is None
    assert (
        rows(slack_sdk.work, "auth.test")[0]["proxy"]
        == "http://env-proxy:8080"
    )
    assert (
        rows(slack_sdk.work, "ws-connect")[0]["arguments"]["proxy"]
        == "http://env-proxy:8080"
    )
    push(
        slack_sdk.work,
        files=[
            {
                "mimetype": "image/png",
                "name": "file.png",
                "url_private": "https://files.slack.com/file.png",
            }
        ],
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert (
        rows(slack_sdk.work, "users.info")[0]["proxy"]
        == "http://env-proxy:8080"
    )
    assert (
        rows(slack_sdk.work, "http-get")[0]["proxy"] == "http://env-proxy:8080"
    )
    await rt.channel.send_content_parts(
        "C123",
        [
            {
                "type": "file",
                "file_url": "data:application/pdf;base64,cGRmLWRhdGE=",
            }
        ],
    )
    assert (
        rows(slack_sdk.work, "http-post")[-1]["proxy"]
        == "http://env-proxy:8080"
    )


@pytest.mark.asyncio
async def test_worker_forwards_only_standard_proxy_environment(
    runtime, slack_sdk, monkeypatch
):
    values = {
        "HTTP_PROXY": "http://upper-http:8080",
        "HTTPS_PROXY": "http://upper-https:8080",
        "ALL_PROXY": "http://upper-all:8080",
        "NO_PROXY": "example.local",
        "http_proxy": "http://lower-http:8080",
        "https_proxy": "http://lower-https:8080",
        "all_proxy": "http://lower-all:8080",
        "no_proxy": "other.local",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(
        "QWENPAW_TEST_UNRELATED_SECRET", "synthetic-do-not-forward"
    )
    for key in ("PYTHONHOME", "PYTHONPATH", "Http_Proxy"):
        monkeypatch.setenv(key, "synthetic-do-not-forward")
    rt = await slack(runtime, slack_sdk)
    auth = rows(slack_sdk.work, "auth.test")[0]
    assert auth["proxy_environment"] == values
    assert auth["unrelated_secret_present"] is False
    assert auth["excluded_environment"] == {
        "PYTHONHOME": False,
        "PYTHONPATH": False,
        "Http_Proxy": False,
    }
    assert auth["proxy"] == "http://upper-http:8080"
    assert (
        rows(slack_sdk.work, "ws-connect")[0]["arguments"]["proxy"]
        == "http://upper-http:8080"
    )
    assert rt.ws.config.channels.slack.proxy is None
