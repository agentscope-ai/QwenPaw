"""WeChat official source and passive resource contracts; no platform imports."""

import json
from pathlib import Path

from packaging.requirements import Requirement

from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
from qwenpaw.plugins.official_channel_catalog import (
    official_channel_for_plugin,
    official_channel_owners,
)

ROOT = Path(__file__).resolve().parents[3]


def test_wechat_descriptor_declares_the_accepted_executable_contract():
    source = ROOT / "plugins/channel/wechat"
    path = source / "channel.json"
    assert path.is_file(), "Missing official WeChat descriptor artifact"
    descriptor = SharedChannelDescriptor.load(path)
    assert descriptor.channel_key == "wechat"
    assert descriptor.schema_version == 2
    assert descriptor.process_mode == "runner_process"
    assert descriptor.dependency_mode == "shared"
    assert descriptor.entrypoint.scope == "runner"
    assert descriptor.entrypoint.module == "qwenpaw_channel_wechat.driver"
    assert descriptor.entrypoint.qualname == "WeChatDriver"
    assert {
        "channel.generic.v1",
        "channel.management.qrcode.v1",
        "channel.management.verify.v1",
        "channel.text_merge.v1",
    } <= set(descriptor.capabilities)


def test_wechat_official_resource_is_claimed_by_its_delivered_owner():
    assert official_channel_owners().get("wechat") == "wechat"
    record = official_channel_for_plugin("wechat")
    assert record is not None
    assert record["channel_key"] == "wechat"
    assert record["source_dir"] == "wechat"


def test_wechat_executable_source_and_dependency_manifest_are_complete():
    source = ROOT / "plugins/channel/wechat"
    required = (
        "plugin.json",
        "channel.json",
        "README.md",
        "requirements.txt",
        "qwenpaw_channel_wechat/__init__.py",
        "qwenpaw_channel_wechat/driver.py",
        "qwenpaw_channel_wechat/platform.py",
        "qwenpaw_channel_wechat/client.py",
        "qwenpaw_channel_wechat/utils.py",
    )
    assert all((source / name).is_file() for name in required), [
        name for name in required if not (source / name).is_file()
    ]
    manifest = json.loads((source / "plugin.json").read_text("utf-8"))
    assert manifest["id"] == "wechat"
    assert manifest["entry"]["descriptor"] == "channel.json"
    requirements = {
        Requirement(line.strip()).name.lower().replace("_", "-")
        for line in (source / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {"httpx", "pycryptodome"} <= requirements
