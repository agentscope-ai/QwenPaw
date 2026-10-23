"""G1 real formal resources and passive discovery, with no platform imports."""

import asyncio
from copy import deepcopy
import importlib.abc
import json
import sys

import official_g1_suite as core
import pytest

registry = core.registry
saved_host = core.saved_host


def test_actual_all18_passive_catalog_supports_azure_nullable_fields(
    saved_host,
    registry,
    monkeypatch,
):
    from qwenpaw.app.channels.catalog import get_configurable_channel_catalog
    from qwenpaw.plugins.official_channel_catalog import OFFICIAL_CHANNELS

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
                raise AssertionError(
                    "passive catalog imported driver: " + fullname
                )

    async def no_spawn(*_args, **_kwargs):
        attempts.append("subprocess")
        raise AssertionError("passive discovery spawned a process")

    monkeypatch.setattr(sys, "meta_path", [NoDrivers(), *sys.meta_path])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_spawn)
    catalog = get_configurable_channel_catalog()
    assert len(OFFICIAL_CHANNELS) == 18
    assert set(catalog) == {
        "console",
        *(row["channel_key"] for row in OFFICIAL_CHANNELS),
    }
    azure = catalog["azure_bot"]
    assert azure["owner"] == azure["plugin_id"] == "azure-bot"
    assert azure["availability"] == "missing_code"
    assert azure["config_schema"]["properties"]["app_id"]["type"] == [
        "string",
        "null",
    ]
    fields = {row["name"]: row for row in azure["config_fields"]}
    assert fields["app_id"]["type"] == "text"
    assert fields["app_password"]["type"] == "password"
    assert attempts == []
    assert registry.get_registered_channels() == {}


@pytest.mark.parametrize(
    "kind,widget",
    [
        ("boolean", "switch"),
        ("integer", "number"),
        ("number", "number"),
        ("string", "text"),
        ("object", "json"),
        ("array", "json"),
    ],
)
@pytest.mark.parametrize("null_first", [True, False])
def test_form_handles_one_nullable_type_without_mutating_schema(
    kind, widget, null_first
):
    from qwenpaw.app.channels.catalog import config_fields

    types = ["null", kind] if null_first else [kind, "null"]
    schema = {
        "type": "object",
        "properties": {
            "setting": {"type": types, "title": "Setting", "default": None},
        },
        "required": ["setting"],
    }
    before = deepcopy(schema)
    (field,) = config_fields(schema)
    assert field == {
        "name": "setting",
        "label": "Setting",
        "type": widget,
        "default": None,
        "required": True,
        **({"json_type": kind} if kind in {"object", "array"} else {}),
    }
    assert schema == before


@pytest.mark.parametrize(
    "types", [["null"], ["integer", "string"], ["null", "string", "integer"]]
)
def test_ambiguous_or_null_only_schema_is_not_misrepresented_as_one_widget(
    types,
):
    from qwenpaw.app.channels.catalog import config_fields

    schema = {"type": "object", "properties": {"setting": {"type": types}}}
    original = deepcopy(schema)
    assert config_fields(schema) == []
    assert schema == original


def test_form_preserves_scalar_anyof_enum_password_object_and_array():
    from qwenpaw.app.channels.catalog import config_fields

    schema = {
        "type": "object",
        "required": ["count"],
        "properties": {
            "count": {"type": "integer", "default": 3},
            "enabled": {"type": "boolean", "default": False},
            "ratio": {"type": "number", "default": 1.5},
            "label": {
                "type": "string",
                "title": "Display label",
                "default": "hi",
            },
            "api_token": {
                "anyOf": [{"type": "null"}, {"type": "string"}],
                "default": None,
            },
            "choice": {"type": ["string", "null"], "enum": ["one", None]},
            "legacy_choice": {
                "anyOf": [
                    {"type": "string", "enum": ["x", "y"]},
                    {"type": "null"},
                ]
            },
            "object": {"type": "object", "default": {"business": "value"}},
            "array": {"type": "array", "default": [1, 2]},
        },
    }
    before = deepcopy(schema)
    fields = {row["name"]: row for row in config_fields(schema)}
    assert set(fields) == set(schema["properties"])
    assert fields["count"] == {
        "name": "count",
        "label": "count",
        "type": "number",
        "default": 3,
        "required": True,
    }
    assert (
        fields["enabled"]["type"] == "switch"
        and fields["enabled"]["default"] is False
    )
    assert (
        fields["ratio"]["type"] == "number"
        and fields["ratio"]["default"] == 1.5
    )
    assert (
        fields["label"]["label"] == "Display label"
        and fields["label"]["default"] == "hi"
    )
    assert (
        fields["api_token"]["type"] == "password"
        and fields["api_token"]["default"] is None
    )
    assert fields["choice"]["type"] == "select" and fields["choice"][
        "options"
    ] == ["one", None]
    assert fields["legacy_choice"]["options"] == ["x", "y"]
    assert fields["object"]["json_type"] == "object" and fields["object"][
        "default"
    ] == {"business": "value"}
    assert fields["array"]["json_type"] == "array" and fields["array"][
        "default"
    ] == [1, 2]
    assert schema == before
