# -*- coding: utf-8 -*-
"""Historical CH-0-001 consistency plus current shared-runner boundaries."""

from __future__ import annotations

import asyncio
import importlib.abc
import json
import sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

EXPECTED_CHANNELS = {
    "imessage",
    "discord",
    "dingtalk",
    "feishu",
    "qq",
    "telegram",
    "mattermost",
    "mqtt",
    "console",
    "matrix",
    "slack",
    "voice",
    "sip",
    "wecom",
    "xiaoyi",
    "yuanbao",
    "wechat",
    "onebot",
}


def test_registry_and_media_tables_cover_exact_builtin_baseline() -> None:
    """Historical eighteen rows; current Console plus eighteen SDK-free plugins."""
    import qwenpaw

    assert Path(qwenpaw.__file__).resolve() == ROOT / "src/qwenpaw/__init__.py"
    from qwenpaw.plugins.official_channel_catalog import OFFICIAL_CHANNELS
    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor

    official = {row["channel_key"] for row in OFFICIAL_CHANNELS}
    assert len(OFFICIAL_CHANNELS) == len(official) == 18
    assert official == (EXPECTED_CHANNELS - {"console"}) | {"azure_bot"}
    modules = {
        json.loads(
            (
                ROOT / "plugins/channel" / row["source_dir"] / "channel.json"
            ).read_text(encoding="utf-8"),
        )["entrypoint"]["module"]
        for row in OFFICIAL_CHANNELS
    }

    class NoDriverImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if any(
                fullname == name or fullname.startswith(name + ".")
                for name in modules
            ):
                raise AssertionError(
                    "Host descriptor discovery imported " + fullname,
                )

    guard = NoDriverImports()
    sys.meta_path.insert(0, guard)
    try:
        for row in OFFICIAL_CHANNELS:
            descriptor = SharedChannelDescriptor.load(
                ROOT / "plugins/channel" / row["source_dir"] / "channel.json",
            )
            assert descriptor.channel_key == row["channel_key"]
            assert descriptor.schema_version == 2
            assert descriptor.process_mode == "runner_process"
            assert descriptor.dependency_mode == "shared"
    finally:
        sys.meta_path.remove(guard)


def test_dispatch_table_matches_current_queue_owners() -> None:
    """Keep historical dispatch rows; current admission stays in Core."""
    from qwenpaw.app.channels.unified_queue_manager import UnifiedQueueManager

    async def check_real_queue():
        entered, release = asyncio.Event(), asyncio.Event()

        async def consume(queue, *_args):
            entered.set()
            await release.wait()

        queues = UnifiedQueueManager(consume, queue_maxsize=1)
        try:
            result = await queues.admit("console", "session", 20, "first")
            await entered.wait()
            assert result.accepted
            full = await queues.admit(
                "console",
                "session",
                20,
                "second",
                timeout=0.03,
            )
            assert (full.accepted, full.reason_code) == (
                False,
                "QUEUE_CAPACITY_TIMEOUT",
            )
        finally:
            release.set()
            await queues.stop_all()

    asyncio.run(check_real_queue())


def test_acl_identity_is_produced_by_runner_and_consumed_by_core(
    tmp_path,
    monkeypatch,
) -> None:
    """The ACL identity contract is explicit in docs and source."""
    from qwenpaw.app.channels.console.channel import ConsoleChannel
    from qwenpaw.app.channels.access_control import AccessControlStore

    channel = ConsoleChannel(None, True, "", workspace_dir=tmp_path)
    store = AccessControlStore(tmp_path / "acl.json")
    store.add_to_whitelist("console", "real-user")
    channel.access_control_group = True
    monkeypatch.setattr(channel, "_get_acl_store", lambda: store)
    payload = {
        "sender_id": "shared-room",
        "acl_sender_id": "real-user",
        "meta": {"is_group": True, "user_name": "display"},
    }
    assert asyncio.run(channel._access_control_gate(payload)) is False
    payload["acl_sender_id"] = "unlisted-user"
    payload["sender_id"] = "real-user"
    assert asyncio.run(channel._access_control_gate(payload)) is True
    assert store.get_acl("console")["pending"][0]["user_id"] == "unlisted-user"


def test_media_path_rules_and_configuration_gaps_are_source_derived(
    tmp_path,
    monkeypatch,
) -> None:
    """Historical gaps are not requirements; host paths ignore worker cwd."""
    from qwenpaw.config.channel_config_compat import absolute_execution_paths

    host, child = tmp_path / "host", tmp_path / "child"
    host.mkdir()
    child.mkdir()
    monkeypatch.chdir(child)
    monkeypatch.setenv("HOME", str(host))
    monkeypatch.setenv("USERPROFILE", str(host))
    raw = {"media_dir": "link/../media", "db_path": "~/chat.db"}
    result = absolute_execution_paths(
        raw,
        path_fields=("media_dir", "db_path"),
        working_dir=host,
    )
    assert result == {
        "media_dir": str(host / "link/../media"),
        "db_path": str(host / "chat.db"),
    }
    assert raw == {"media_dir": "link/../media", "db_path": "~/chat.db"}
    assert absolute_execution_paths(
        {"media_dir": None},
        path_fields=("media_dir",),
        working_dir=host,
    ) == {"media_dir": None}


def test_interfaces_are_dto_only_and_compatibility_is_complete() -> None:
    """Runner signatures prohibit Core objects and list all combinations."""

    from qwenpaw.channel_protocol.models import InboundEvent
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    wire = {
        "event_id": "e",
        "event_kind": "message",
        "channel_key": "console",
        "instance_id": "instance",
        "generation": 1,
        "conversation": {"id": "group", "type": "group"},
        "sender_id": "actor",
        "acl_sender_id": "actor",
        "sender_name": "display",
        "content_parts": [{"type": "text", "text": "hello"}],
    }
    event = InboundEvent.from_mapping(wire)
    assert (
        json.loads(json.dumps(event.to_mapping()))["acl_sender_id"] == "actor"
    )
    for invalid in (
        {**wire, "agent": object()},
        {**wire, "acl_sender_id": ""},
        {**wire, "content_parts": [object()]},
    ):
        with pytest.raises(ProtocolValidationError):
            InboundEvent.from_mapping(invalid)
