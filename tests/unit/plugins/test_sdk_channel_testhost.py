# -*- coding: utf-8 -*-
"""SDK-only channel installation and real process lifecycle via public TestHost."""

import json

import pytest

from qwenpaw.plugins.channel_workers import ChannelDefinition
from qwenpaw.plugins.dependency_maintenance import live_readers
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.plugins.compliance import check_plugin
from tests.channel_support.sdk import make_channel, workspace_store
from tests.channel_support.process import alive

SOURCE = """
import os
from qwenpaw.plugins.channel_workers import ChannelDriver, ChannelSendResult


class Driver(ChannelDriver):
    async def start(self, ch):
        await ch.storage.awrite_json(
            "worker.json",
            {
                "pid": os.getpid(),
                "workspace": ch.workspace_id,
                "generation": ch.generation,
            },
        )
        await ch.report_status("connected")

    async def send(self, ch, response):
        await ch.storage.awrite_json(
            "sent.json",
            {
                "target": response.target.session_id,
                "text": response.content[0].text,
            },
        )
        return ChannelSendResult("stored")

"""


@pytest.mark.asyncio
async def test_public_testhost_runs_installed_process_channel_in_two_workspaces(
    tmp_path,
):
    source = tmp_path / "source"
    definition = ChannelDefinition(
        "sdk-worker",
        {"en": "SDK worker", "zh": "SDK 验证"},
        "driver:Driver",
        {"type": "object", "properties": {}},
        (),
        ("channel.generic.v1",),
    )
    make_channel(
        source,
        SOURCE,
        definition,
        capabilities=["channels", "resources", "storage"],
    )
    report = check_plugin(source)
    assert report.ok, report.findings
    root = tmp_path / "host"
    dependencies = root / "channel-dependencies"
    workspaces = ("one", "two")
    async with PluginTestHost(root, process_channels=("sdk-worker",)) as host:
        assert live_readers((dependencies,))
        installed = await host.install(source)
        assert installed.ok and installed.status == "active", installed
        for workspace in workspaces:
            await host.start_channel("sdk-worker", workspace_id=workspace)
            health = await host.health_channel(
                "sdk-worker",
                workspace_id=workspace,
            )
            assert health.status == "healthy", health

        async def deliver(text):
            pids = set()
            for workspace in workspaces:
                message = f"{text} {workspace}"
                await host.send_channel(
                    "sdk-worker",
                    message,
                    user_id="alice",
                    session_id="room",
                    workspace_id=workspace,
                )
                storage = workspace_store(root, "sdk-worker", workspace)
                worker = json.loads((storage / "worker.json").read_text())
                assert worker["workspace"] == workspace and alive(
                    worker["pid"],
                )
                assert json.loads((storage / "sent.json").read_text()) == {
                    "target": "room",
                    "text": message,
                }
                pids.add(worker["pid"])
            assert len(pids) == len(workspaces)
            return pids

        original = await deliver("before reload")
        reloaded = await host.reload("sdk-worker", new_source=source)
        assert reloaded.ok, reloaded
        assert all(not alive(pid) for pid in original)
        current = await deliver("after reload")
        assert original.isdisjoint(current)
        result = await host.uninstall("sdk-worker")
        assert result.clean and result.quiescent, result
        assert all(not alive(pid) for pid in current)
    assert not live_readers((dependencies,))


@pytest.mark.asyncio
async def test_generated_sdk_channel_template_and_runtime_probe(tmp_path):
    from qwenpaw.plugins.check import main, _runtime

    source = tmp_path / "generated"
    assert main(["--channel-template", str(source)]) == 0
    report = check_plugin(source)
    assert report.ok, report.findings
    runtime = await _runtime(source, report)
    assert runtime.ok, runtime.findings
    assert runtime.lifecycle_checks == (
        "install/probe:passed",
        "cleanup:passed",
    )
    assert any("platform connections" in note for note in runtime.uncovered)
    root = tmp_path / "host"
    async with PluginTestHost(
        root,
        process_channels=("example-sdk-mailbox",),
    ) as host:
        assert (await host.install(source)).ok
        await host.start_channel(
            "example-sdk-mailbox",
            workspace_id="template-workspace",
        )
        await host.send_channel(
            "example-sdk-mailbox",
            "template message",
            user_id="alice",
            session_id="room",
            workspace_id="template-workspace",
        )
        storage = workspace_store(
            root,
            "example-sdk-mailbox",
            "template-workspace",
        )
        (outbox,) = (storage / "outbox").glob("*.json")
        message = json.loads(outbox.read_text())
        assert message["workspace"] == "template-workspace"
        assert message["user"] == "alice" and message["session"] == "room"
        assert message["content"][0]["text"] == "template message"
        await host.stop_channel(
            "example-sdk-mailbox",
            workspace_id="template-workspace",
        )
        assert json.loads((storage / "status.json").read_text()) == {
            "connected": False,
        }
