# -*- coding: utf-8 -*-
"""SDK-only channel installation and real process lifecycle via public TestHost."""

import json

import pytest

from qwenpaw.plugins.channel_workers import ChannelDefinition
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

    async def stop(self, ch):
        await ch.storage.awrite_json("stopped.json", True)
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
    pids = []
    async with PluginTestHost(root, process_channels=("sdk-worker",)) as host:
        installed = await host.install(source)
        assert installed.ok and installed.status == "active", installed
        for workspace in ("one", "two"):
            await host.start_channel("sdk-worker", workspace_id=workspace)
            health = await host.health_channel(
                "sdk-worker",
                workspace_id=workspace,
            )
            assert health.status == "healthy", health
            await host.send_channel(
                "sdk-worker",
                "hello " + workspace,
                user_id="alice",
                session_id="room",
                workspace_id=workspace,
            )
            storage = workspace_store(root, "sdk-worker", workspace)
            worker = json.loads((storage / "worker.json").read_text())
            assert worker["workspace"] == workspace
            assert (
                json.loads((storage / "sent.json").read_text())["text"]
                == "hello " + workspace
            )
            assert alive(worker["pid"])
            pids.append(worker["pid"])
        assert pids[0] != pids[1]
        manifest = json.loads((source / "plugin.json").read_text())
        manifest["version"] = "0.1.1"
        (source / "plugin.json").write_text(json.dumps(manifest))
        reloaded = await host.reload("sdk-worker", new_source=source)
        assert reloaded.ok, reloaded
        assert all(not alive(pid) for pid in pids)
        current = []
        for workspace in ("one", "two"):
            storage = workspace_store(root, "sdk-worker", workspace)
            worker = json.loads((storage / "worker.json").read_text())
            assert worker["pid"] not in pids and alive(worker["pid"])
            current.append(worker["pid"])
        updated = await host.update_config("sdk-worker", {"validation": True})
        assert updated.ok, updated
        assert all(not alive(pid) for pid in current)
        disabled = await host.set_enabled("sdk-worker", False)
        assert disabled.ok and disabled.quiescent, disabled
        enabled = await host.set_enabled("sdk-worker", True)
        assert enabled.ok, enabled
        current = []
        for workspace in ("one", "two"):
            await host.send_channel(
                "sdk-worker",
                "after-enable",
                user_id="alice",
                session_id="room",
                workspace_id=workspace,
            )
            storage = workspace_store(root, "sdk-worker", workspace)
            current.append(
                json.loads((storage / "worker.json").read_text())["pid"],
            )
        result = await host.uninstall("sdk-worker")
        assert result.clean and result.quiescent, result
        assert all(not alive(pid) for pid in (*pids, *current))


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
        files = list(
            (root / "plugin-data/example-sdk-mailbox/workspaces").glob(
                "*/outbox/*.json",
            ),
        )
        assert len(files) == 1
        message = json.loads(files[0].read_text())
        assert message["workspace"] == "template-workspace"
        assert message["user"] == "alice" and message["session"] == "room"
        assert message["content"][0]["text"] == "template message"
        await host.stop_channel(
            "example-sdk-mailbox",
            workspace_id="template-workspace",
        )
        assert json.loads(
            (files[0].parent.parent / "status.json").read_text(),
        ) == {
            "connected": False,
        }
        removed = await host.uninstall("example-sdk-mailbox")
        assert removed.clean and removed.quiescent
