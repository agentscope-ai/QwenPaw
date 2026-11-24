# -*- coding: utf-8 -*-
"""Target policy selection, durable ownership and host prefix formatting."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
from qwenpaw.app.channels.process_supervisor import LaunchSpec
from qwenpaw.__version__ import __version__
from qwenpaw.channel_protocol.response_policy import SendFormatPolicy
from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
from qwenpaw.plugins._channel_worker import prepare_driver
from qwenpaw.plugins.channel_workers import ChannelDefinition, ResponsePolicy
from qwenpaw.plugins.channels import ChannelMessage
from qwenpaw.plugins.messages import ContentBlock
from tests.channel_support.process import digest

from .test_sdk_channel_worker import Driver, send_params, setup

PROCESS_DRIVER = """
from qwenpaw.plugins.channel_workers import (
    ChannelDriver, ChannelSendResult, ResponsePolicy,
)

class Driver(ChannelDriver):
    async def start(self, ch):
        self.restarted = ch.generation > 1
        await ch.report_status("connected")

    def response_policy_for(self, target):
        if self.restarted:
            raise AssertionError("Do not recompute a persisted policy")
        return ResponsePolicy(
            streaming=not bool(target.metadata.get("thread_id")),
            configured_prefix=False,
        )

    async def send(self, ch, response):
        await ch.storage.awrite_json(
            "sent.json", [part.text for part in response.content],
        )
        return ChannelSendResult(response.delivery_id)
"""


async def test_real_worker_restores_target_policy_and_sends_without_prefix(
    tmp_path,
):
    code = tmp_path / "code"
    code.mkdir()
    (code / "driver.py").write_text(PROCESS_DRIVER)
    definition = ChannelDefinition(
        "sdk-target-policy",
        {"en": "Policy", "zh": "目标策略"},
        "driver:Driver",
        {"type": "object", "properties": {}},
        (),
        ("channel.generic.v1", "streaming"),
    )
    descriptor_path = code / "channel.json"
    descriptor_path.write_text(json.dumps(definition.to_dict()))
    (code / "requirements.txt").write_text("")
    descriptor = SharedChannelDescriptor.load(descriptor_path)
    spec = LaunchSpec(
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        code_root=code,
        descriptor_path=descriptor_path,
        source_revision=digest(code),
        descriptor=descriptor,
        requirements=(),
        channel_key="sdk-target-policy",
        instance_id="policy-instance",
        generation=1,
        qwenpaw_version=__version__,
        config={"bot_prefix": "configured:"},
        plugin_id="sdk-target-policy",
        workspace_id=str(tmp_path / "workspace"),
        sdk_workspace_id="one",
        sdk_storage_root=tmp_path / "storage",
        sdk_media_root=tmp_path / "media",
        startup_timeout=10,
        shutdown_timeout=5,
    )

    async def unused_model(*args, **kwargs):
        raise AssertionError("Only outbound transport is used")
        yield

    handles = []
    for generation in (1, 2):
        proxy = IsolatedChannelProxy(
            unused_model,
            launch_spec=replace(spec, generation=generation),
            descriptor=descriptor,
            workspace_dir=tmp_path / "workspace",
        )
        try:
            await proxy.start()

            async def rpc(method, values):
                return await proxy.channel_process.call(
                    method,
                    {**proxy._identity().to_mapping(), **values},
                )

            if generation == 1:
                assert proxy.bot_prefix == "configured:"
                await proxy.send("room", "mqtt payload")
                assert json.loads(
                    (tmp_path / "storage/sent.json").read_text(),
                ) == ["mqtt payload"]
                await proxy.send_content_parts(
                    "room",
                    [{"type": "text", "text": "mqtt parts"}],
                )
                assert json.loads(
                    (tmp_path / "storage/sent.json").read_text(),
                ) == ["mqtt parts"]
                for thread in ("", "thread-7"):
                    opened = await rpc(
                        "channel.response.open",
                        {"to_handle": "room", "meta": {"thread_id": thread}},
                    )
                    handles.append(opened["response_handle"])
            policies = await asyncio.gather(
                *(
                    rpc("channel.response.describe", {"response_handle": h})
                    for h in handles
                ),
            )
            assert policies == [
                {
                    "streaming": streaming,
                    "prepare": False,
                    "completion_reaction": False,
                    "send_format": {
                        "direct_prefix": True,
                        "parts_configured_prefix": True,
                        "configured_prefix": False,
                    },
                }
                for streaming in (True, False)
            ]
        finally:
            await proxy.stop()


class TargetDriver(Driver):
    def __init__(self):
        super().__init__()
        self.selected = []

    async def resolve_target(self, ch, target):
        return replace(target, key="platform:" + target.key)

    def response_policy_for(self, target):
        self.selected.append(target.key)
        return ResponsePolicy(
            streaming=not bool(target.metadata.get("thread_id")),
            configured_prefix=False,
        )


async def test_target_policies_are_resolved_once_and_survive_restart(tmp_path):
    adapter, peer, _ = await setup(
        tmp_path,
        TargetDriver,
        capabilities=("channel.generic.v1", "streaming"),
    )
    plain = ChannelMessage(
        "alice",
        (ContentBlock(text="hello"),),
        session_id="room",
        message_id="plain",
    )
    threaded = replace(plain, message_id="threaded", thread_id="thread-7")
    try:
        results = await asyncio.gather(
            adapter.ch.receive(plain),
            adapter.ch.receive(threaded),
            adapter.ch.receive(plain),
        )
        handles = [result.response_handle for result in results]
        assert handles[0] == handles[2] != handles[1]
        assert adapter.driver.selected == ["platform:room", "platform:room"]
        saved = [adapter.response_policy(handle) for handle in handles[:2]]
        assert [policy.streaming for policy in saved] == [True, False]
        assert [policy.send_format.configured_prefix for policy in saved] == [
            False,
            False,
        ]
        await adapter.stop()

        class RestartedDriver(TargetDriver):
            def response_policy_for(self, target):
                raise AssertionError("Existing routes must not be reselected")

        adapter, _, _ = await setup(
            tmp_path,
            RestartedDriver,
            peer=peer,
            generation=2,
            capabilities=("channel.generic.v1", "streaming"),
        )
        for message, handle, policy in zip(
            (plain, threaded),
            handles,
            saved,
        ):
            assert adapter.response_policy(handle) == policy
            result = await adapter.ch.receive(message)
            assert result.response_handle == handle
            assert adapter.response_policy(handle) == policy
    finally:
        await adapter.stop()


async def test_legacy_route_keeps_static_policy_without_new_callback(tmp_path):
    adapter, peer, _ = await setup(tmp_path)
    try:
        await adapter._persist_route(
            "old-route",
            {
                "target": json.dumps(
                    {
                        "key": "room",
                        "user_id": "alice",
                        "session_id": "room",
                        "metadata": {},
                    },
                ),
                "owner": json.dumps(
                    {"user_id": "alice", "session_id": "room"},
                ),
            },
        )
        await adapter.stop()

        class NewDriver(Driver):
            def response_policy_for(self, target):
                raise AssertionError("No new policy for legacy routes")

        adapter, _, _ = await setup(
            tmp_path,
            NewDriver,
            peer=peer,
            generation=2,
        )
        assert adapter.response_policy("old-route").to_mapping() == {
            "streaming": False,
            "prepare": False,
            "completion_reaction": False,
        }
    finally:
        await adapter.stop()


async def test_receiving_duplicate_during_send_does_not_reenter_route_lock(
    tmp_path,
):
    message = ChannelMessage(
        "alice",
        (),
        session_id="room",
        message_id="one",
    )

    class ReentrantDriver(Driver):
        async def send(self, ch, response):
            await ch.receive(message)
            return await super().send(ch, response)

    adapter, _, identity = await setup(tmp_path, ReentrantDriver)
    try:
        incoming = await adapter.ch.receive(message)
        async with asyncio.timeout(2):
            await adapter._send(
                send_params(identity, incoming.response_handle),
                None,
            )
        assert len(adapter.driver.sent) == 1
    finally:
        await adapter.stop()


@pytest.mark.parametrize(
    "policy",
    [
        ResponsePolicy(streaming=True),
        ResponsePolicy(prepare=True),
        ResponsePolicy(completion_reaction=True),
        ResponsePolicy(text_merge_delay_ms=0),
        ResponsePolicy(content_source="semantic"),
        {"streaming": False},
    ],
)
async def test_target_cannot_enable_undeclared_or_invalid_policy(
    tmp_path,
    policy,
):
    class InvalidDriver(Driver):
        def response_policy_for(self, target):
            return policy

    adapter, peer, _ = await setup(tmp_path, InvalidDriver)
    try:
        with pytest.raises(ValueError):
            await adapter.ch.receive(
                ChannelMessage(
                    "alice",
                    (),
                    session_id="room",
                    message_id="one",
                ),
            )
        assert peer.batches == []
        assert adapter._routes.snapshots() == ()
    finally:
        await adapter.stop()


def test_async_target_policy_is_rejected_before_driver_construction():
    class InvalidDriver(Driver):
        def __init__(self):
            raise AssertionError("Probe must not construct the driver")

        async def response_policy_for(self, target):
            return ResponsePolicy()

    with pytest.raises(ValueError, match="response_policy_for signature"):
        prepare_driver(InvalidDriver, {"mode": "probe"})


@pytest.mark.parametrize("value", [None, 0, "false"])
def test_configured_prefix_requires_boolean(value):
    with pytest.raises(ValueError, match="booleans"):
        ResponsePolicy(configured_prefix=value)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("override", ["", "explicit:"])
def test_prefix_control_preserves_explicit_metadata(enabled, override):
    proxy = object.__new__(IsolatedChannelProxy)
    proxy.bot_prefix = "configured:"
    policy = SendFormatPolicy(configured_prefix=enabled)
    meta = proxy._with_bot_prefix({"bot_prefix": override} if override else {})
    expected = override or ("configured:" if enabled else "")
    for entry, separator in (("direct", ""), ("parts", "  ")):
        fields = {"content_parts": [{"type": "text", "text": "answer"}]}
        result = proxy._format_send_fields(fields, meta, policy, entry)
        assert result == {
            "content_parts": [
                {
                    "type": "text",
                    "text": (
                        expected + separator + "answer"
                        if expected
                        else "answer"
                    ),
                },
            ],
        }
    assert proxy._stream_text("message", "answer", meta, policy) == (
        expected + "  answer" if expected else "answer"
    )
    assert SendFormatPolicy.from_mapping(policy.to_mapping()) == policy
