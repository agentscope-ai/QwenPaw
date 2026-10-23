"""Generic form metadata boundaries, independent of channel identities."""

from copy import deepcopy

import pytest


def test_layout_only_reorders_requested_declared_fields_without_duplicates():
    from qwenpaw.app.channels.catalog import config_fields

    schema = {
        "type": "object",
        "properties": {
            "alpha": {"type": "string", "default": "a"},
            "beta": {"type": "integer", "default": 2},
            "private": {"type": "boolean", "default": False},
        },
        "x-ui": {
            "config_fields": [
                {"name": "beta", "label": "Second"},
                {"name": "beta", "label": "Duplicate"},
                {"name": "undeclared", "type": "text"},
                {"name": "private", "label": "Not requested"},
                {"name": "alpha", "label": "First"},
            ]
        },
    }
    before = deepcopy(schema)
    fields = config_fields(schema, ["alpha", "beta"])
    assert [field["name"] for field in fields] == ["beta", "alpha"]
    assert {field["name"] for field in fields} == {"alpha", "beta"}
    assert len(fields) == 2
    assert fields[0]["type"] == "number"
    assert fields[0]["default"] == 2
    assert fields[1]["default"] == "a"
    assert schema == before


@pytest.mark.parametrize("schema_required", [False, True])
def test_property_metadata_precedence_preserves_schema_constraints_and_input(
    schema_required,
):
    from qwenpaw.app.channels.catalog import config_fields

    local = {
        "label": {"en-US": "Local label", "zh-CN": "局部名称"},
        "help": {"en-US": "Local help", "zh-CN": "局部提示"},
        "placeholder": "Local placeholder",
        "required": False,
        "default": "must not override schema",
    }
    schema = {
        "type": "object",
        "properties": {
            "setting": {
                "type": ["string", "null"],
                "title": "Schema title",
                "default": "schema default",
                "x-ui": local,
            }
        },
        "required": ["setting"] if schema_required else [],
        "x-ui": {
            "config_fields": [
                {
                    "name": "setting",
                    "label": "Root label",
                    "help": "Root help",
                    "placeholder": "Root placeholder",
                    "required": False,
                    "default": "root default",
                }
            ]
        },
    }
    before = deepcopy(schema)
    (field,) = config_fields(schema)
    assert field["name"] == "setting"
    assert field["type"] == "text"
    for key in ("label", "help", "placeholder"):
        assert field[key] == local[key]
    assert field["required"] is schema_required
    assert field["default"] == "schema default"
    assert schema == before


def test_non_string_ui_type_does_not_crash_or_replace_schema_widget():
    from qwenpaw.app.channels.catalog import config_fields

    for ui_type in ({"widget": "password"}, ["password"]):
        schema = {
            "type": "object",
            "properties": {
                "setting": {"type": "string", "x-ui": {"type": ui_type}}
            },
        }
        before = deepcopy(schema)
        (field,) = config_fields(schema)
        assert field == {
            "name": "setting",
            "label": "setting",
            "type": "text",
        }
        assert schema == before
