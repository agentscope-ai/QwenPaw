"""Private QQ payload contracts, independent of official catalog activation."""

import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


SOURCE = Path(__file__).resolve().parents[3] / "plugins/channel/qq"
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
    "client_secret": "",
    "markdown_enabled": True,
    "max_reconnect_attempts": 100,
    "ack_message": "",
}


def test_qq_installable_payload_and_native_requirements_are_complete():
    required = (
        "plugin.json",
        "channel.json",
        "requirements.txt",
        "README.md",
        "qwenpaw_channel_qq/__init__.py",
        "qwenpaw_channel_qq/driver.py",
    )
    missing = [name for name in required if not (SOURCE / name).is_file()]
    assert not missing, f"Missing installable QQ payload: {missing}"
    manifest = json.loads((SOURCE / "plugin.json").read_text("utf-8"))
    assert manifest["id"] == "qq"
    assert manifest["type"] == "channel"
    assert manifest["entry"]["descriptor"] == "channel.json"
    assert not manifest.get("dependencies")
    requirements = {
        canonicalize_name(Requirement(line.strip()).name)
        for line in (SOURCE / "requirements.txt").read_text("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {"websocket-client", "httpx", "cryptography"} <= requirements
    assert requirements.isdisjoint({"botpy", "qq-botpy"})


def test_qq_descriptor_matches_shared_runner_and_complete_config_model():
    path = SOURCE / "channel.json"
    assert path.is_file(), "Missing installable QQ channel descriptor"

    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.config.config import QQConfig

    descriptor = SharedChannelDescriptor.load(path)
    assert descriptor.schema_version == 2
    assert descriptor.channel_key == "qq"
    assert descriptor.process_mode == "runner_process"
    assert descriptor.dependency_mode == "shared"
    assert descriptor.entrypoint.scope == "runner"
    assert descriptor.entrypoint.module == "qwenpaw_channel_qq.driver"
    assert descriptor.entrypoint.qualname == "QQDriver"
    assert (SOURCE / "qwenpaw_channel_qq/driver.py").is_file()
    assert descriptor.requirements_file == "requirements.txt"
    assert "channel.generic.v1" in descriptor.capabilities

    properties = descriptor.config_schema["properties"]
    model_properties = QQConfig.model_json_schema()["properties"]
    assert set(properties) == set(model_properties) == set(CONFIG_DEFAULTS)
    assert set(descriptor.config_fields) == set(properties)
    assert len(descriptor.config_fields) == len(properties)
    for name, field in model_properties.items():
        for constraint, expected in field.items():
            assert properties[name][constraint] == expected, (name, constraint)
    assert QQConfig().model_dump(mode="json") == CONFIG_DEFAULTS
    assert {
        name: field["default"] for name, field in properties.items()
    } == CONFIG_DEFAULTS
