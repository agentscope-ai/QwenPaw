"""Azure Bot shared artifact; no invented Core AzureBotConfig model."""
import importlib
import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


SOURCE = Path(__file__).resolve().parents[3] / "plugins/channel/azure_bot"
# Frozen by AST literal_eval from legacy plugin.py register_channel, 1.0.1.
# http_port's integer type is also explicit in the old constructor annotation.
# The remaining 3 registered switches overlap BaseChannelConfig, not new fields.
PLATFORM_PROPERTIES = {
    "app_id": {"type": "string"},
    "app_password": {"type": "string"},
    "tenant_id": {"type": "string"},
    "http_host": {"type": "string", "default": "0.0.0.0"},
    "http_port": {"type": "integer", "default": 3978},
    "media_dir": {"type": "string"},
    "share_session_in_group": {"type": "boolean", "default": False},
}


def test_azure_bot_upgrade_payload_retains_identity_and_real_shared_driver(monkeypatch):
    required = (
        "plugin.json", "channel.json", "requirements.txt", "README.md",
        "qwenpaw_channel_azure_bot/__init__.py",
        "qwenpaw_channel_azure_bot/driver.py",
    )
    missing = [name for name in required if not (SOURCE / name).is_file()]
    assert not missing, f"Missing shared Azure Bot payload: {missing}"
    raw = json.loads((SOURCE / "plugin.json").read_text("utf-8"))
    assert raw["id"] == "azure-bot"
    assert SOURCE.name == "azure_bot"
    assert raw["type"] == "channel"
    assert Version(raw["version"]) > Version("1.0.1")
    assert raw["entry"] == {"descriptor": "channel.json"}
    assert not raw.get("dependencies")
    assert raw.get("publish", True) is True
    requirements = [
        Requirement(line.strip())
        for line in (SOURCE / "requirements.txt").read_text("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    names = [canonicalize_name(item.name) for item in requirements]
    assert len(names) == len(set(names))
    assert {"aiohttp", "pyjwt", "msal"} == set(names)
    assert not {"aiohttp", "jwt", "msal", "platform", "asyncio", "json"} & {
        path.stem for path in SOURCE.iterdir() if path.is_dir() or path.suffix == ".py"
    }

    from qwenpaw.__version__ import __version__
    from qwenpaw._version_compat import check_plugin_version_compat
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.channel_protocol.shared_response_driver import SharedResponseDriver

    manifest = PluginManifest.from_dict(raw)
    assert check_plugin_version_compat(manifest)[0]
    current = Version(Version(__version__).base_version)
    declared = raw["qwenpaw_version"]
    minimum = Version(declared["min"])
    maximum = Version(declared["max"]) if declared.get("max") else Version(f"{minimum.major}.{minimum.minor + 1}.0")
    # The loader currently suspends upper-bound enforcement. Do not let that
    # make the old, already-expired declared max look like a migration fix.
    assert minimum <= current < maximum
    monkeypatch.syspath_prepend(str(SOURCE))
    module = importlib.import_module("qwenpaw_channel_azure_bot.driver")
    assert Path(module.__file__).resolve() == SOURCE / "qwenpaw_channel_azure_bot/driver.py"
    assert issubclass(module.AzureBotDriver, SharedResponseDriver)


def test_azure_bot_descriptor_preserves_registered_and_public_config_contract():
    path = SOURCE / "channel.json"
    assert path.is_file(), "Missing shared Azure Bot channel descriptor"

    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.config.config import BaseChannelConfig
    from qwenpaw.plugins.channel_config import (
        channel_config_defaults, validate_channel_config,
        validate_channel_config_schema,
    )

    descriptor = SharedChannelDescriptor.load(path)
    assert descriptor.schema_version == 2
    assert descriptor.channel_key == "azure_bot"
    assert descriptor.process_mode == "runner_process"
    assert descriptor.dependency_mode == "shared"
    assert descriptor.entrypoint.scope == "runner"
    assert descriptor.entrypoint.module == "qwenpaw_channel_azure_bot.driver"
    assert descriptor.entrypoint.qualname == "AzureBotDriver"
    assert descriptor.requirements_file == "requirements.txt"
    assert "channel.generic.v1" in descriptor.capabilities
    public = BaseChannelConfig.model_json_schema()
    actual = validate_channel_config_schema(descriptor.config_schema)
    assert set(actual["properties"]) == set(public["properties"]) | set(PLATFORM_PROPERTIES)
    assert len(actual["properties"]) == 24
    assert set(descriptor.config_fields) == set(actual["properties"])
    assert len(descriptor.config_fields) == len(actual["properties"])
    for name, constraints in public["properties"].items():
        for constraint, value in constraints.items():
            if constraint not in {"title", "description"}:
                assert actual["properties"][name][constraint] == value, (name, constraint)
    for name, constraints in PLATFORM_PROPERTIES.items():
        prop = actual["properties"][name]
        variants = prop.get("anyOf", [prop])
        types = set()
        for variant in variants:
            declared_type = variant.get("type")
            types.update(declared_type if isinstance(declared_type, list) else [declared_type])
        assert types in ({constraints["type"]}, {constraints["type"], "null"}), name
        if "default" in constraints:
            assert prop["default"] == constraints["default"], name
    defaults = channel_config_defaults(actual)
    for name, value in BaseChannelConfig().model_dump(mode="json").items():
        assert defaults[name] == value, name
    # Legacy UI required=True is presentation metadata, not a server schema.
    # No Azure model exists; old config saving accepts missing credentials and
    # from_config normalizes them. Keep disabled empty configuration saveable.
    assert validate_channel_config(actual, {"enabled": False})["enabled"] is False
