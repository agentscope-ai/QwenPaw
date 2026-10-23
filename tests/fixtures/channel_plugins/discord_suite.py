"""Independent Discord migration contracts at public and SDK boundaries."""

import asyncio
from dataclasses import replace
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import sys

import psutil
import pytest

from discord_support import (
    callback_done,
    discord,
    discord_sdk,
    finish,
    push,
    route,
    rows,
    send,
    set_mode,
    runtime,
    eventually,
    identity,
    fault_runtime,
)
from extension_sample import ROOT


class HostImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "discord" or fullname.startswith(
            ("discord.", "qwenpaw_channel_discord")
        ):
            raise AssertionError(
                "Discord SDK/implementation imported in host: " + fullname
            )


@pytest.fixture(autouse=True)
def forbid_host_sdk():
    guard = HostImportGuard()
    sys.meta_path.insert(0, guard)
    yield
    sys.meta_path.remove(guard)


def test_discord_official_manifest_and_driver_are_present():
    source = ROOT / "plugins/channel/discord"
    assert (source / "plugin.json").is_file()
    assert (source / "channel.json").is_file()
    assert (source / "requirements.txt").is_file()
    assert (source / "qwenpaw_channel_discord/driver.py").is_file()


def test_descriptor_is_complete_sdk_free_and_matches_config():
    from qwenpaw.config.config import DiscordConfig
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel

    source = ROOT / "plugins/channel/discord"
    manifest = PluginManifest.model_validate(
        json.loads((source / "plugin.json").read_text())
    )
    description = describe_channel(source, manifest)
    descriptor = description.descriptor
    assert manifest.entry.descriptor == "channel.json"
    assert descriptor.schema_version == 2
    assert descriptor.channel_key == "discord"
    assert descriptor.entrypoint.module == "qwenpaw_channel_discord.driver"
    assert descriptor.entrypoint.qualname == "DiscordDriver"
    assert "channel.generic.v1" in descriptor.capabilities
    assert "approval_card" not in descriptor.capabilities
    assert set(descriptor.config_fields) == set(
        descriptor.config_schema["properties"]
    )
    assert set(descriptor.config_fields) == set(DiscordConfig.model_fields)
    for key, default in DiscordConfig().model_dump().items():
        assert (
            descriptor.config_schema["properties"][key].get("default")
            == default
        )
    assert (source / "README.md").is_file()
    assert "discord" not in sys.modules


@pytest.mark.asyncio
async def test_gateway_proxy_auth_intents_and_real_host_dm(
    runtime, discord_sdk
):
    rt = await discord(
        runtime,
        discord_sdk,
        http_proxy="http://proxy.example:8080",
        http_proxy_auth="user:pass:tail",
    )
    gateway = rows(discord_sdk.work, "gateway")[0]
    assert gateway["token"] == "local-A" and gateway["reconnect"] is True
    assert gateway["proxy"] == "http://proxy.example:8080"
    assert gateway["auth"] == ["user", "pass:tail"]
    assert all(gateway["intents"].values())
    assert gateway["pid"] == rt.process.health_snapshot()["pid"] != os.getpid()
    assert Path(gateway["sdk_source"]).is_relative_to(discord_sdk.site)
    push(discord_sdk.work, text=" hello ", author_id=42, author_name="Human")
    await eventually(
        lambda: len(rt.ws.requests) == 1
        and bool(rows(discord_sdk.work, "send"))
    )
    request = rt.ws.requests[0]
    assert request.channel == "discord"
    assert request.user_id == "42"
    assert request.session_id == "discord:dm:42"
    assert request.channel_meta["channel_id"] == "123"
    assert request.channel_meta["message_id"] == "1"
    assert len(request.input) == 1
    assert request.input[0].content[0].text == "hello"
    assert rows(discord_sdk.work, "send")[0]["channel_id"] == 900042
    assert rows(discord_sdk.work, "send")[0]["content"] == "host answer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event,want",
    [
        ({"group": True}, "discord:ch:123"),
        (
            {
                "group": True,
                "is_thread": True,
                "channel_id": 789,
                "parent_id": 123,
            },
            "discord:ch:789",
        ),
        ({"group": True, "thread_id": 789}, "discord:ch:789"),
    ],
)
async def test_channel_thread_and_starter_sessions(
    runtime, discord_sdk, event, want
):
    rt = await discord(runtime, discord_sdk)
    push(discord_sdk.work, **event)
    await eventually(
        lambda: len(rt.ws.requests) == 1
        and bool(rows(discord_sdk.work, "send"))
    )
    request = rt.ws.requests[0]
    assert request.session_id == want
    assert request.user_id == "42"
    if want.endswith("789"):
        assert request.channel_meta["thread_id"] == "789"
        assert request.channel_meta["parent_channel_id"] == "123"
    assert rows(discord_sdk.work, "send")[0]["channel_id"] == int(
        want.rsplit(":", 1)[1]
    )


@pytest.mark.asyncio
async def test_thread_create_before_starter_keeps_race_target_and_stops_task(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk)
    push(discord_sdk.work, kind="thread", thread_id=789, starter_id=5)
    await eventually(lambda: len(rows(discord_sdk.work, "callback")) == 2)
    push(discord_sdk.work, ident=5, group=True, has_thread=True)
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert rt.ws.requests[0].session_id == "discord:ch:789"
    pid = rt.process.health_snapshot()["pid"]
    assert (await rt.manager.stop_one("discord")).stopped
    assert not psutil.pid_exists(pid)
    assert rows(discord_sdk.work, "gateway-close")
    assert rows(discord_sdk.work, "callback-end")[-1]["callback"] in {
        "on_thread_create",
        "on_message",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mention,event,text",
    [
        ("user", {"mention": True, "text": "<@777> hello"}, "hello"),
        ("nick", {"mention": True, "text": "<@!777> hello"}, "hello"),
        ("role", {"roles": [88], "text": "<@&88> hello"}, "hello"),
        (
            "everyone",
            {"everyone": True, "text": "@everyone hello"},
            "@everyone hello",
        ),
    ],
)
async def test_user_role_and_everyone_mentions_reach_host(
    runtime, discord_sdk, mention, event, text
):
    rt = await discord(runtime, discord_sdk, require_mention=True)
    push(discord_sdk.work, group=True, **event)
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert rt.ws.requests[0].input[0].content[0].text == text
    assert rt.ws.requests[0].channel_meta["bot_mentioned"] is True
    assert rt.ws.requests[0].user_id == "42"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings,event",
    [
        ({}, {"author_id": 777}),
        ({}, {"bot": True}),
        ({"require_mention": True}, {"group": True}),
        ({"require_mention": True}, {"group": True, "roles": [99]}),
    ],
)
async def test_self_bot_and_unmentioned_groups_do_not_execute(
    runtime, discord_sdk, settings, event
):
    rt = await discord(runtime, discord_sdk, **settings)
    push(discord_sdk.work, **event)
    await callback_done(discord_sdk)
    assert rt.ws.requests == []
    assert rows(discord_sdk.work, "send") == []
    assert rows(discord_sdk.work, "typing-enter") == []


@pytest.mark.asyncio
async def test_accept_bot_messages_and_real_author_acl(runtime, discord_sdk):
    rt = await discord(
        runtime,
        discord_sdk,
        accept_bot_messages=True,
        dm_policy="allowlist",
        allow_from=["42"],
        deny_message="Denied",
        access_control_dm=True,
    )
    from qwenpaw.app.channels.access_control import get_access_control_store

    get_access_control_store(rt.ws.workspace_dir).add_to_whitelist(
        "discord", "42"
    )
    push(discord_sdk.work, bot=True, author_id=99, author_name="42")
    await callback_done(discord_sdk)
    assert rt.ws.requests == []
    assert rows(discord_sdk.work, "typing-enter") == []
    push(
        discord_sdk.work,
        ident=2,
        bot=True,
        author_id=42,
        author_name="same name",
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert rt.ws.requests[0].user_id == "42"


@pytest.mark.asyncio
async def test_native_id_dedup_keeps_distinct_identical_text(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk)
    push(discord_sdk.work, ident=1)
    await eventually(lambda: len(rt.ws.requests) == 1)
    push(discord_sdk.work, ident=1)
    push(discord_sdk.work, ident=2)
    await callback_done(discord_sdk, 3)
    await eventually(lambda: len(rt.ws.requests) == 2)
    assert [
        request.input[0].content[0].text for request in rt.ws.requests
    ] == ["hello", "hello"]


@pytest.mark.asyncio
async def test_proactive_targets_cache_fetch_and_create_dm(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk, bot_prefix="[BOT] ")
    await rt.channel.send("discord:ch:123", "direct")
    await rt.channel.send("discord:ch:123", "cached")
    await rt.channel.send("discord:dm:42", "dm")
    await rt.channel.send("discord:dm:42", "existing")
    sent = rows(discord_sdk.work, "send")
    assert [(row["channel_id"], row["content"]) for row in sent] == [
        (123, "direct"),
        (123, "cached"),
        (900042, "dm"),
        (900042, "existing"),
    ]
    assert len(rows(discord_sdk.work, "fetch-channel")) == 1
    assert len(rows(discord_sdk.work, "fetch-user")) == 1
    assert len(rows(discord_sdk.work, "create-dm")) == 1
    target = rt.channel.to_handle_from_target(
        user_id="99", session_id="discord:ch:123"
    )
    await rt.channel.send(target, "opaque target")
    assert rows(discord_sdk.work, "send")[-1]["channel_id"] == 123


@pytest.mark.asyncio
async def test_parts_prefix_and_long_text_keep_all_characters(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk, bot_prefix="[BOT] ")
    text = "A" * 5000
    await rt.channel.send_content_parts(
        "discord:ch:123", [{"type": "text", "text": text}], {}
    )
    sent = rows(discord_sdk.work, "send")
    assert len(sent) >= 3
    assert all(len(row["content"]) <= 2000 for row in sent)
    assert "".join(row["content"] for row in sent) == text
    await rt.channel.send_content_parts(
        "discord:ch:123",
        [{"type": "text", "text": "explicit"}],
        {"bot_prefix": "[META] "},
    )
    assert rows(discord_sdk.work, "send")[-1]["content"] == "[META]   explicit"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,want",
    [
        ("send-reject", "failed"),
        ("send-rate", "failed"),
        ("send-server", "unknown"),
        ("send-unknown", "unknown"),
        ("send-second-reject", "unknown"),
    ],
)
async def test_definite_unknown_and_partial_chunk_failures(
    runtime, discord_sdk, mode, want
):
    rt = await discord(runtime, discord_sdk)
    handle = await route(rt)
    set_mode(discord_sdk.work, mode)
    result = await send(
        rt,
        handle,
        parts=[
            {
                "type": "text",
                "text": "x" * (3000 if mode == "send-second-reject" else 1),
            }
        ],
    )
    assert result["state"] == want
    assert len(rows(discord_sdk.work, "send")) == (
        2 if mode == "send-second-reject" else 1
    )
    if mode == "send-rate":
        assert result["retryable"] is True
    if want == "unknown":
        assert result.get("retryable", False) is False


@pytest.mark.asyncio
async def test_two_workspaces_have_independent_native_ids_targets_and_stop(
    runtime, discord_sdk
):
    first = await discord(runtime, discord_sdk)
    second = await discord(
        runtime,
        discord_sdk,
        token="local-B",
        existing_loader=first.loader,
        workspace_name="workspace-B",
    )

    first_pid, second_pid = (
        rt.process.health_snapshot()["pid"] for rt in (first, second)
    )
    assert first_pid != second_pid
    assert identity(first)["instance_id"] != identity(second)["instance_id"]
    push(discord_sdk.work, author_id=42)
    push(discord_sdk.work, token="local-B", author_id=43)
    await eventually(
        lambda: len(first.ws.requests) == len(second.ws.requests) == 1
    )
    assert first.ws.requests[0].user_id == "42"
    assert second.ws.requests[0].user_id == "43"
    await eventually(
        lambda: bool(rows(discord_sdk.work, "send", token="local-B"))
    )
    assert (
        rows(discord_sdk.work, "send", token="local-B")[0]["channel_id"]
        == 900043
    )
    assert (await first.manager.stop_one("discord")).stopped
    assert not psutil.pid_exists(first_pid) and psutil.pid_exists(second_pid)
    await second.channel.send("discord:ch:123", "still live")
    assert (
        rows(discord_sdk.work, "send", token="local-B")[-1]["content"]
        == "still live"
    )


@pytest.mark.asyncio
async def test_empty_native_content_still_builds_one_host_input(
    runtime, discord_sdk
):
    rt = await discord(runtime, discord_sdk)
    push(discord_sdk.work, text="")
    await eventually(lambda: len(rt.ws.requests) == 1)
    request = rt.ws.requests[0]
    assert request is not None and request.channel == "discord"
    assert len(request.input) == 1


@pytest.mark.asyncio
async def test_unset_proxy_is_actual_sdk_none(runtime, discord_sdk):
    await discord(runtime, discord_sdk)
    assert rows(discord_sdk.work, "gateway")[0]["proxy"] is None
