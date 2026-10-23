"""Preserve the original Azure register API's form without importing SDKs."""

import asyncio
import importlib.abc
import json
import sys

import official_g1_suite as core

registry = core.registry
saved_host = core.saved_host


def legacy_registration_fields():
    """Read the preserved original API literal, never the current descriptor."""
    source = (
        core.ROOT
        / "tests/fixtures/channel_plugins/legacy_azure_registration_fields.json"
    )
    return json.loads(source.read_text())


def test_form_preserves_actual_azure_registration_metadata(
    saved_host, registry, monkeypatch
):
    from qwenpaw.app.channels.catalog import get_configurable_channel_catalog
    from qwenpaw.plugins.official_channel_catalog import OFFICIAL_CHANNELS

    legacy = legacy_registration_fields()
    assert len(legacy) == 10
    descriptor = json.loads(
        (core.ROOT / "plugins/channel/azure_bot/channel.json").read_text()
    )
    assert descriptor["config_schema"]["x-ui"]["config_fields"] == legacy
    modules = tuple(
        json.loads(
            (
                core.ROOT
                / "plugins/channel"
                / row["source_dir"]
                / "channel.json"
            ).read_text()
        )["entrypoint"]["module"]
        for row in OFFICIAL_CHANNELS
    )
    attempts = []

    class NoDrivers(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if any(
                fullname == name or fullname.startswith(name + ".")
                for name in modules
            ):
                attempts.append(fullname)
                raise AssertionError("passive form imported " + fullname)

    async def no_spawn(*_args, **_kwargs):
        attempts.append("subprocess")
        raise AssertionError("passive form spawned a process")

    monkeypatch.setattr(sys, "meta_path", [NoDrivers(), *sys.meta_path])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_spawn)
    azure = get_configurable_channel_catalog()["azure_bot"]
    assert azure["owner"] == azure["plugin_id"] == "azure-bot"
    assert azure["availability"] == "missing_code"
    assert azure["config_schema"] == descriptor["config_schema"]
    assert attempts == []
    assert registry.get_registered_channels() == {}

    names = [field["name"] for field in legacy]
    actual = [
        field for field in azure["config_fields"] if field["name"] in names
    ]
    differences = []
    if [field["name"] for field in actual] != names:
        differences.append(
            {"order": [field["name"] for field in actual], "expected": names}
        )
    by_name = {field["name"]: field for field in actual}
    for original in legacy:
        projected = by_name.get(original["name"], {})
        for key, expected in original.items():
            if key not in projected or projected[key] != expected:
                differences.append(
                    {
                        "field": original["name"],
                        "key": key,
                        "expected": expected,
                        "actual": projected.get(key),
                        "present": key in projected,
                    }
                )
    assert differences == [], json.dumps(differences, ensure_ascii=False)
