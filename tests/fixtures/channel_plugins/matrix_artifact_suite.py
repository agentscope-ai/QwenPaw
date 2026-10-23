"""Private Matrix installable payload and complete retained config contracts."""

import importlib
import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


SOURCE = Path(__file__).resolve().parents[3] / "plugins/channel/matrix"
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
    "homeserver": "",
    "user_id": "",
    "access_token": "",
    "group_allow_from": [],
    "groups": {},
    "encryption": False,
    "vision_enabled": True,
    "history_limit": 50,
    "password": "",
    "device_name": "qwenpaw-worker",
    "sync_timeout_ms": 30000,
    "mention_pill_in_body": False,
    "outbound_structured_mentions": True,
    "streaming_enabled": False,
    "share_session_in_group": True,
}


def test_matrix_installable_payload_uses_real_driver_and_unique_requirements(monkeypatch):
    required = (
        "plugin.json",
        "channel.json",
        "requirements.txt",
        "README.md",
        "qwenpaw_channel_matrix/__init__.py",
        "qwenpaw_channel_matrix/driver.py",
    )
    missing = [name for name in required if not (SOURCE / name).is_file()]
    assert not missing, f"Missing installable Matrix payload: {missing}"
    manifest = json.loads((SOURCE / "plugin.json").read_text("utf-8"))
    assert manifest["id"] == "matrix"
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
    # These are real direct imports. E2EE is an optional SDK extra; no
    # native backend or guessed SDK version is required by this contract.
    assert {"matrix-nio", "httpx"} <= set(names)
    assert not {"nio", "matrix", "platform", "httpx"} & {
        path.stem for path in SOURCE.iterdir() if path.is_dir() or path.suffix == ".py"
    }

    from qwenpaw.channel_protocol.shared_response_driver import SharedResponseDriver

    monkeypatch.syspath_prepend(str(SOURCE))
    module = importlib.import_module("qwenpaw_channel_matrix.driver")
    assert Path(module.__file__).resolve() == SOURCE / "qwenpaw_channel_matrix/driver.py"
    assert issubclass(module.MatrixDriver, SharedResponseDriver)


def test_matrix_descriptor_matches_shared_runner_and_complete_legacy_config():
    path = SOURCE / "channel.json"
    assert path.is_file(), "Missing installable Matrix channel descriptor"

    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.config.config import MatrixConfig

    descriptor = SharedChannelDescriptor.load(path)
    assert descriptor.schema_version == 2
    assert descriptor.channel_key == "matrix"
    assert descriptor.process_mode == "runner_process"
    assert descriptor.dependency_mode == "shared"
    assert descriptor.entrypoint.scope == "runner"
    assert descriptor.entrypoint.module == "qwenpaw_channel_matrix.driver"
    assert descriptor.entrypoint.qualname == "MatrixDriver"
    assert descriptor.requirements_file == "requirements.txt"
    assert "channel.generic.v1" in descriptor.capabilities

    properties = descriptor.config_schema["properties"]
    model_schema = MatrixConfig.model_json_schema()
    assert set(properties) == set(model_schema["properties"]) == set(CONFIG_DEFAULTS)
    assert set(descriptor.config_fields) == set(properties)
    assert len(descriptor.config_fields) == len(properties)
    for name, field in model_schema["properties"].items():
        for constraint, expected in field.items():
            assert properties[name][constraint] == expected, (name, constraint)
    assert descriptor.config_schema.get("required", []) == model_schema.get("required", [])
    assert MatrixConfig().model_dump(mode="json") == CONFIG_DEFAULTS
    assert {name: field["default"] for name, field in properties.items()} == CONFIG_DEFAULTS
    assert MatrixConfig(homeserver="https://matrix.example///").homeserver == "https://matrix.example"
