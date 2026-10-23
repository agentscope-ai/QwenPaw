"""Official OneBot payload and complete retained model contracts."""
import importlib
import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


SOURCE = Path(__file__).resolve().parents[3] / "plugins/channel/onebot"
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
    "ws_host": "127.0.0.1",
    "ws_port": 6199,
    "access_token": "",
    "share_session_in_group": False,
    "media_dir": None,
    "media_base64": False,
    "media_base64_max_mb": 10,
    "media_download_max_mb": 50,
}


def test_onebot_installable_payload_uses_real_driver_and_unique_requirements(monkeypatch):
    required = (
        "plugin.json", "channel.json", "requirements.txt", "README.md",
        "qwenpaw_channel_onebot/__init__.py", "qwenpaw_channel_onebot/driver.py",
    )
    missing = [name for name in required if not (SOURCE / name).is_file()]
    assert not missing, f"Missing installable OneBot payload: {missing}"
    manifest = json.loads((SOURCE / "plugin.json").read_text("utf-8"))
    assert manifest["id"] == "onebot"
    assert manifest["type"] == "channel"
    assert manifest["entry"]["descriptor"] == "channel.json"
    assert not manifest.get("dependencies")
    requirements = [
        Requirement(line.strip())
        for line in (SOURCE / "requirements.txt").read_text("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    names = [canonicalize_name(item.name) for item in requirements]
    assert len(names) == len(set(names))
    assert "aiohttp" in names
    assert not {"aiohttp", "onebot", "platform", "asyncio", "json"} & {
        path.stem for path in SOURCE.iterdir() if path.is_dir() or path.suffix == ".py"
    }
    from qwenpaw.channel_protocol.shared_response_driver import SharedResponseDriver

    monkeypatch.syspath_prepend(str(SOURCE))
    module = importlib.import_module("qwenpaw_channel_onebot.driver")
    assert Path(module.__file__).resolve() == SOURCE / "qwenpaw_channel_onebot/driver.py"
    assert issubclass(module.OneBotDriver, SharedResponseDriver)


def test_onebot_descriptor_matches_shared_runner_and_complete_legacy_config():
    path = SOURCE / "channel.json"
    assert path.is_file(), "Missing installable OneBot channel descriptor"

    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.config.config import OneBotConfig

    descriptor = SharedChannelDescriptor.load(path)
    assert descriptor.schema_version == 2
    assert descriptor.channel_key == "onebot"
    assert descriptor.process_mode == "runner_process"
    assert descriptor.dependency_mode == "shared"
    assert descriptor.entrypoint.scope == "runner"
    assert descriptor.entrypoint.module == "qwenpaw_channel_onebot.driver"
    assert descriptor.entrypoint.qualname == "OneBotDriver"
    assert descriptor.requirements_file == "requirements.txt"
    assert "channel.generic.v1" in descriptor.capabilities

    properties = descriptor.config_schema["properties"]
    model_schema = OneBotConfig.model_json_schema()
    assert set(properties) == set(model_schema["properties"]) == set(CONFIG_DEFAULTS)
    assert set(descriptor.config_fields) == set(properties)
    assert len(descriptor.config_fields) == len(properties)
    for name, field in model_schema["properties"].items():
        for constraint, expected in field.items():
            assert properties[name][constraint] == expected, (name, constraint)
    assert descriptor.config_schema.get("required", []) == model_schema.get("required", [])
    assert OneBotConfig().model_dump(mode="json") == CONFIG_DEFAULTS
    assert {name: field["default"] for name, field in properties.items()} == CONFIG_DEFAULTS
