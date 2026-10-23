"""Private WeCom payload contracts, independent of catalog activation."""

import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


SOURCE = Path(__file__).resolve().parents[3] / "plugins/channel/wecom"
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
    "bot_id": "",
    "secret": "",
    "ws_url": "",
    "media_dir": None,
    "welcome_text": "",
    "share_session_in_group": True,
    "max_reconnect_attempts": -1,
    "streaming_enabled": False,
}


def test_wecom_installable_payload_and_native_requirements_are_complete():
    required = (
        "plugin.json",
        "channel.json",
        "requirements.txt",
        "README.md",
        "qwenpaw_channel_wecom/__init__.py",
        "qwenpaw_channel_wecom/driver.py",
    )
    missing = [name for name in required if not (SOURCE / name).is_file()]
    assert not missing, f"Missing installable WeCom payload: {missing}"
    manifest = json.loads((SOURCE / "plugin.json").read_text("utf-8"))
    assert manifest["id"] == "wecom"
    assert manifest["type"] == "channel"
    assert manifest["entry"]["descriptor"] == "channel.json"
    assert not manifest.get("dependencies")
    requirements = {
        canonicalize_name(requirement.name): requirement
        for line in (SOURCE / "requirements.txt").read_text("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        for requirement in [Requirement(line.strip())]
    }
    assert {"wecom-aibot-python-sdk", "pillow"} <= set(requirements)
    assert str(requirements["wecom-aibot-python-sdk"].specifier) == "==1.0.2"


def test_wecom_descriptor_matches_shared_runner_and_complete_config_model():
    path = SOURCE / "channel.json"
    assert path.is_file(), "Missing installable WeCom channel descriptor"

    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.config.config import WecomConfig

    descriptor = SharedChannelDescriptor.load(path)
    assert descriptor.schema_version == 2
    assert descriptor.channel_key == "wecom"
    assert descriptor.process_mode == "runner_process"
    assert descriptor.dependency_mode == "shared"
    assert descriptor.entrypoint.scope == "runner"
    assert descriptor.entrypoint.module == "qwenpaw_channel_wecom.driver"
    assert descriptor.entrypoint.qualname == "WeComDriver"
    assert descriptor.requirements_file == "requirements.txt"
    assert "channel.generic.v1" in descriptor.capabilities

    properties = descriptor.config_schema["properties"]
    model_properties = WecomConfig.model_json_schema()["properties"]
    assert set(properties) == set(model_properties) == set(CONFIG_DEFAULTS)
    assert set(descriptor.config_fields) == set(properties)
    assert len(descriptor.config_fields) == len(properties)
    for name, field in model_properties.items():
        for constraint, expected in field.items():
            assert properties[name][constraint] == expected, (name, constraint)
    assert WecomConfig().model_dump(mode="json") == CONFIG_DEFAULTS
    assert {
        name: field["default"] for name, field in properties.items()
    } == CONFIG_DEFAULTS
