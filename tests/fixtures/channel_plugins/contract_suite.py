# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position,wrong-import-order
"""Shared BaseChannel contracts apply to official host proxies without SDKs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.contract.channels import ChannelContractTest  # noqa: E402
from c6_artifacts import proxy  # noqa: E402


class _OfficialPluginContract(ChannelContractTest):
    def create_instance(self):
        return proxy(self.source_dir, {"enabled": True})


class TestFeishuPluginContract(_OfficialPluginContract):
    source_dir = "feishu"

    def test_channel_type_is_feishu(self, instance):
        assert instance.channel == "feishu"

    def test_construction_does_not_start_worker(self, instance):
        assert instance.channel_process.health_snapshot()["pid"] is None


class TestDingTalkPluginContract(_OfficialPluginContract):
    source_dir = "dingtalk"

    def test_channel_type_is_dingtalk(self, instance):
        assert instance.channel == "dingtalk"

    def test_construction_does_not_start_worker(self, instance):
        assert instance.channel_process.health_snapshot()["pid"] is None


class TestTelegramPluginContract(_OfficialPluginContract):
    source_dir = "telegram"


class TestSlackPluginContract(_OfficialPluginContract):
    source_dir = "slack"


class TestDiscordPluginContract(_OfficialPluginContract):
    source_dir = "discord"


class TestMqttPluginContract(_OfficialPluginContract):
    source_dir = "mqtt"


class TestMattermostPluginContract(_OfficialPluginContract):
    source_dir = "mattermost"


class TestQQPluginContract(_OfficialPluginContract):
    source_dir = "qq"


class TestWecomPluginContract(_OfficialPluginContract):
    source_dir = "wecom"


class TestYuanbaoPluginContract(_OfficialPluginContract):
    source_dir = "yuanbao"


class TestXiaoyiPluginContract(_OfficialPluginContract):
    source_dir = "xiaoyi"


class TestWechatPluginContract(_OfficialPluginContract):
    source_dir = "wechat"


class TestMatrixPluginContract(_OfficialPluginContract):
    source_dir = "matrix"


class TestIMessagePluginContract(_OfficialPluginContract):
    source_dir = "imessage"


class TestOnebotPluginContract(_OfficialPluginContract):
    source_dir = "onebot"


class TestAzureBotPluginContract(_OfficialPluginContract):
    source_dir = "azure_bot"


class TestVoicePluginContract(_OfficialPluginContract):
    source_dir = "voice"


class TestSipPluginContract(_OfficialPluginContract):
    source_dir = "sip"
