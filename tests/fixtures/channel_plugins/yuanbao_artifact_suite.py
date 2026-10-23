"""Installable Yuanbao payload contracts, independent of catalog activation."""

import hashlib
import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


SOURCE = Path(__file__).resolve().parents[3] / "plugins/channel/yuanbao"
CONFIG_DEFAULTS = {
    "enabled": False,
    "bot_prefix": "",
    "show_tool_calls": True,
    "show_tool_results": True,
    "tool_call_max_length": 200,
    "tool_result_max_length": 500,
    "show_thinking": True,
    "dm_policy": "open",
    "group_policy": "open",
    "allow_from": [],
    "deny_message": "",
    "require_mention": False,
    "no_text_debounce": True,
    "access_control_dm": False,
    "access_control_group": False,
    "dm_disabled": False,
    "group_disabled": False,
    "app_id": "",
    "app_secret": "",
    "api_domain": "bot.yuanbao.tencent.com",
    "ws_url": "",
    "media_dir": None,
    "accept_bot_messages": False,
}
PROTO_DIGESTS = {
    "conn.json": "978b1110f19990c84125fd2f15d329287c13f2bf779d09ebe2b37086be7b7dd9",
    "biz.json": "0a17426c06bc20bcb50b9db78a9e503c3a7ef4c30325452a4ebe6289267c3ddd",
}


def test_yuanbao_installable_payload_keeps_real_protocol_resources_and_dependencies():
    required = (
        "plugin.json",
        "channel.json",
        "requirements.txt",
        "README.md",
        "qwenpaw_channel_yuanbao/__init__.py",
        "qwenpaw_channel_yuanbao/driver.py",
        "qwenpaw_channel_yuanbao/proto/conn.json",
        "qwenpaw_channel_yuanbao/proto/biz.json",
    )
    missing = [name for name in required if not (SOURCE / name).is_file()]
    assert not missing, f"Missing installable Yuanbao payload: {missing}"
    manifest = json.loads((SOURCE / "plugin.json").read_text("utf-8"))
    assert manifest["id"] == "yuanbao"
    assert manifest["type"] == "channel"
    assert manifest["entry"]["descriptor"] == "channel.json"
    assert not manifest.get("dependencies")
    requirements = {
        canonicalize_name(requirement.name): requirement
        for line in (SOURCE / "requirements.txt").read_text("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        for requirement in [Requirement(line.strip())]
    }
    # aiohttp and google.protobuf are direct imports in the frozen implementation.
    assert {"aiohttp", "protobuf"} <= set(requirements)
    assert "3.9.0" in requirements["aiohttp"].specifier
    for name, expected_digest in PROTO_DIGESTS.items():
        raw = (SOURCE / "qwenpaw_channel_yuanbao/proto" / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected_digest, name
        assert json.loads(raw)["nested"], name


def test_yuanbao_descriptor_matches_shared_runner_and_complete_legacy_config():
    path = SOURCE / "channel.json"
    assert path.is_file(), "Missing installable Yuanbao channel descriptor"

    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.config.config import YuanbaoConfig

    descriptor = SharedChannelDescriptor.load(path)
    assert descriptor.schema_version == 2
    assert descriptor.channel_key == "yuanbao"
    assert descriptor.process_mode == "runner_process"
    assert descriptor.dependency_mode == "shared"
    assert descriptor.entrypoint.scope == "runner"
    assert descriptor.entrypoint.module == "qwenpaw_channel_yuanbao.driver"
    assert descriptor.entrypoint.qualname == "YuanbaoDriver"
    assert descriptor.requirements_file == "requirements.txt"
    assert "channel.generic.v1" in descriptor.capabilities

    properties = descriptor.config_schema["properties"]
    model_properties = YuanbaoConfig.model_json_schema()["properties"]
    assert set(properties) == set(model_properties) == set(CONFIG_DEFAULTS)
    assert set(descriptor.config_fields) == set(properties)
    assert len(descriptor.config_fields) == len(properties)
    for name, field in model_properties.items():
        for constraint, expected in field.items():
            assert properties[name][constraint] == expected, (name, constraint)
    assert YuanbaoConfig().model_dump(mode="json") == CONFIG_DEFAULTS
    assert {
        name: field["default"] for name, field in properties.items()
    } == CONFIG_DEFAULTS
