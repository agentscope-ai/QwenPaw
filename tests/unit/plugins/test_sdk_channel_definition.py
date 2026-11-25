# -*- coding: utf-8 -*-
"""Descriptor and source inspection must never import the channel SDK."""

import json
from pathlib import Path

import pytest

from qwenpaw.plugins.channel_workers import ChannelDefinition
from qwenpaw.plugins.compliance import check_plugin


def package(path, *, version="1.2.0"):
    definition = ChannelDefinition(
        "example",
        {"en": "Example", "zh": "示例"},
        "example.driver:Driver",
        {"type": "object", "properties": {}},
        (),
        ("channel.generic.v1",),
    )
    (path / "plugin.json").write_text(
        json.dumps(
            {
                "id": "sdk-example",
                "version": "0.1",
                "type": "channel",
                "entry": {"descriptor": "channel.json"},
                "sdk": {"version": version, "capabilities": ["channels"]},
            },
        ),
    )
    (path / "channel.json").write_text(json.dumps(definition.to_dict()))
    (path / "requirements.txt").write_text("")
    (path / "example").mkdir()
    (path / "example/__init__.py").write_text("")
    (path / "example/driver.py").write_text(
        "raise RuntimeError('must not import')\nclass Driver:\n    pass\n",
    )
    return definition


@pytest.mark.parametrize(
    "fields",
    [("missing",), ("count",), ("token", "token")],
)
def test_authorization_declaration_requires_distinct_string_fields(fields):
    with pytest.raises(ValueError, match="Authorization fields"):
        ChannelDefinition(
            "example",
            {"en": "Example", "zh": "示例"},
            "driver:Driver",
            {
                "type": "object",
                "properties": {
                    "token": {"type": "string"},
                    "count": {"type": "integer"},
                },
            },
            ("token", "count"),
            ("channel.generic.v1",),
            authorization_fields=fields,
        )


def test_authorization_allowlist_does_not_grant_all_string_fields():
    from qwenpaw.channel_protocol.management import management_credential_keys

    definition = ChannelDefinition(
        "example",
        {"en": "Example", "zh": "示例"},
        "driver:Driver",
        {
            "type": "object",
            "properties": {
                "token": {"type": "string"},
                "endpoint": {"type": "string"},
            },
        },
        ("token", "endpoint"),
        ("channel.generic.v1",),
        authorization_fields=("token",),
    )
    assert management_credential_keys(
        "example",
        definition.config_schema,
    ) == frozenset(
        {"token"},
    )


def test_channel_definition_roundtrip_freezing_and_no_import(tmp_path):
    definition = package(tmp_path)
    assert ChannelDefinition.load(tmp_path / "channel.json") == definition
    data = definition.to_dict()
    data["label"]["en"] = "changed"
    assert definition.label["en"] == "Example"
    with pytest.raises(TypeError):
        definition.label["en"] = "changed"
    report = check_plugin(tmp_path)
    assert report.ok, report.findings
    assert report.runtime_checked is False


@pytest.mark.parametrize(
    "case",
    [
        "syntax",
        "missing",
        "wrong-class",
        "private-import",
        "requirement",
        "capability",
        "schema",
        "old-sdk",
        "symlink",
    ],
)
def test_static_channel_invalid_packages(tmp_path, case):
    package(tmp_path, version="1.0" if case == "old-sdk" else "1.2")
    source = tmp_path / "example/driver.py"
    if case == "missing":
        source.unlink()
    elif case == "syntax":
        source.write_text("class Driver(\n")
    elif case == "wrong-class":
        source.write_text("class Other: pass\n")
    elif case == "private-import":
        source.write_text(
            (
                "from qwenpaw.channel_protocol.shared_response_driver import "
                "SharedResponseDriver\n"
                "class Driver(SharedResponseDriver): pass\n"
            ),
        )
    elif case == "requirement":
        (tmp_path / "requirements.txt").write_text("-r outside.txt\n")
    elif case == "symlink":
        source.unlink()
        source.symlink_to(Path(__file__))
    elif case in {"capability", "schema"}:
        descriptor = tmp_path / "channel.json"
        data = json.loads(descriptor.read_text())
        if case == "capability":
            data["capabilities"] = ["channel.generic.v99"]
        else:
            data["config_schema"]["$ref"] = "https://invalid.example/schema"
        descriptor.write_text(json.dumps(data))
    report = check_plugin(tmp_path)
    assert not report.ok
    assert any(
        f.code
        in {
            "private-import",
            "sdk-version",
            "invalid-input",
            "external-source",
            "channel-entry",
            "syntax",
        }
        for f in report.findings
    )
