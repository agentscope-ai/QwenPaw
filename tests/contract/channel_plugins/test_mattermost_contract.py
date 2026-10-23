# -*- coding: utf-8 -*-
"""Preserve BaseChannel host contracts through the official static proxy."""

import json
from pathlib import Path
import sys

from qwenpaw.app.channels.renderer import ChannelDisplayConfig
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.channel_adapter import describe_channel
from tests.contract.channels import ChannelContractTest

ROOT = Path(__file__).resolve().parents[3]


async def unused_agent(_request):
    raise AssertionError("Static construction invoked the Agent")
    yield


class TestMattermostChannelContract(ChannelContractTest):
    def create_instance(self):
        source = ROOT / "plugins/channel/mattermost"
        manifest = PluginManifest.from_dict(
            json.loads((source / "plugin.json").read_text()),
        )
        description = describe_channel(source, manifest)
        channel = description.create_proxy(
            unused_agent,
            {
                "enabled": True,
                **{
                    "url": "https://mattermost.example.com",
                    "bot_token": "test_bot_token_12345",
                    "bot_prefix": "[Test]",
                },
            },
            python_executable=sys.executable,
            support_root=ROOT / "src",
            instance_id="contract-mattermost",
            generation=1,
            qwenpaw_version="2.2.2b4",
            display_config=ChannelDisplayConfig(
                show_tool_calls=False,
                show_tool_results=False,
            ),
        )
        assert channel.channel == "mattermost"
        assert channel.channel_process.health_snapshot()["pid"] is None
        assert "qwenpaw_channel_mattermost.driver" not in sys.modules
        return channel
