# -*- coding: utf-8 -*-
"""SDK-only channel installation and real process lifecycle via public TestHost."""

import json

import pytest

from qwenpaw.plugins.dependency_maintenance import live_readers
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.plugins.compliance import check_plugin
from tests.channel_support.sdk import workspace_store


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
    dependencies = root / "channel-dependencies"
    async with PluginTestHost(
        root,
        process_channels=("example-sdk-mailbox",),
    ) as host:
        assert live_readers((dependencies,))
        installed = await host.install(source)
        assert installed.ok and installed.status == "active", installed
        await host.start_channel(
            "example-sdk-mailbox",
            workspace_id="template-workspace",
        )
        health = await host.health_channel(
            "example-sdk-mailbox",
            workspace_id="template-workspace",
        )
        assert health.status == "healthy", health
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
    assert not live_readers((dependencies,))
