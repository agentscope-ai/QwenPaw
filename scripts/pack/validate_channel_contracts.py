#!/usr/bin/env python3
"""Release preflight for retained host models and official static schemas.

Run before producing release artifacts. PEP517's isolated stdlib resource
builder remains usable without application dependencies; release entrypoints
install the small channel-contract-requirements.txt set and invoke this gate.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import runpy
import sys
import tempfile
import os


def _contract(value):
    """Drop presentation annotations, retaining every validation constraint."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {"title", "description", "examples", "$comment"}:
                continue
            if key in {
                "properties",
                "patternProperties",
                "$defs",
                "definitions",
                "dependentSchemas",
            }:
                result[key] = {
                    name: _contract(schema) for name, schema in item.items()
                }
            elif key in {
                "items",
                "additionalItems",
                "contains",
                "additionalProperties",
                "propertyNames",
                "unevaluatedItems",
                "unevaluatedProperties",
                "if",
                "then",
                "else",
                "not",
                "contentSchema",
                "allOf",
                "anyOf",
                "oneOf",
                "prefixItems",
            }:
                result[key] = _contract(item)
            else:
                # These are data, not schema nodes: dependentRequired field
                # names, $vocabulary keys, default/const/enum and extensions.
                result[key] = deepcopy(item)
        if result.get("type") == "object":
            # Omitted additionalProperties is true in JSON Schema.
            result.setdefault("additionalProperties", True)
        return result
    if isinstance(value, list):
        return [_contract(item) for item in value]
    return value


def validate_official_channel_contracts(project_root: Path) -> None:
    """Refuse schema/default/field drift without importing channel drivers."""
    from qwenpaw.config.config import ChannelConfig
    from qwenpaw.channel_protocol.shared import (
        SharedChannelDescriptor,
        validate_channel_contract,
    )
    from qwenpaw.plugins.channel_config import validate_channel_config_schema

    root = Path(project_root).resolve()
    inventory = runpy.run_path(
        str(root / "src/qwenpaw/plugins/official_channel_catalog.py"),
    )["OFFICIAL_CHANNELS"]
    for row in inventory:
        source = root / "plugins/channel" / row["source_dir"]
        manifest = json.loads((source / "plugin.json").read_text("utf-8"))
        if manifest.get("id") != row["plugin_id"]:
            raise ValueError(f"{row['channel_key']}: manifest owner mismatch")
        entry = manifest.get("entry", {}).get("descriptor", "")
        if (
            not isinstance(entry, str)
            or not entry
            or any(char in entry for char in "\\:")
            or any(part in {"", ".", ".."} for part in entry.split("/"))
        ):
            raise ValueError(f"{row['channel_key']}: descriptor path invalid")
        path = source / entry
        if not path.resolve().is_relative_to(source.resolve()):
            raise ValueError(
                f"{row['channel_key']}: descriptor escapes source"
            )
        key = row["channel_key"]
        try:
            descriptor = SharedChannelDescriptor.load(path)
        except ValueError as exc:
            raise ValueError(f"{key}: {exc}") from exc
        if descriptor.channel_key != key:
            raise ValueError(f"{key}: descriptor routing identity mismatch")
        validate_channel_contract(key, descriptor.capabilities)
        schema = validate_channel_config_schema(descriptor.config_schema)
        field = ChannelConfig.model_fields.get(key)
        if field is None:
            # Schema-only channels have no retained host model to compare.
            continue
        _validate_model_contract(field.annotation, key, schema)


def _validate_model_contract(model, key, schema):
    """Compare actual defaults and explicit declarative host constraints."""
    from jsonschema import Draft202012Validator
    from qwenpaw.config.channel_normalizers import field_normalizer

    expected = deepcopy(model.model_json_schema())
    defaults = model().model_dump(mode="json")
    for name, value in defaults.items():
        expected["properties"][name]["default"] = value
    decorators = model.__pydantic_decorators__
    if decorators.model_validators:
        raise ValueError(
            f"{key}: model validators need a declarative contract"
        )
    declared_normalizers = {
        name: normalizer
        for name, field in expected["properties"].items()
        if (normalizer := field_normalizer(field)) is not None
    }
    bound_normalizers = set()
    for validator in decorators.field_validators.values():
        for name in validator.info.fields:
            if name in declared_normalizers:
                if (
                    validator.info.mode != "after"
                    or validator.func is not declared_normalizers[name]
                ):
                    raise ValueError(
                        f"{key}.{name}: normalizer validator must bind the "
                        "registered function in after mode"
                    )
                bound_normalizers.add(name)
                continue
            extra = model.model_fields[name].json_schema_extra
            if not isinstance(extra, dict) or not set(extra).intersection(
                {
                    "pattern",
                    "enum",
                    "const",
                    "format",
                    "minimum",
                    "maximum",
                    "exclusiveMinimum",
                    "exclusiveMaximum",
                    "minLength",
                    "maxLength",
                    "minItems",
                    "maxItems",
                    "multipleOf",
                    "allOf",
                    "anyOf",
                    "oneOf",
                    "not",
                }
            ):
                raise ValueError(
                    f"{key}.{name}: custom validator needs explicit "
                    "JSON Schema constraints",
                )
    if declared_normalizers.keys() != bound_normalizers:
        raise ValueError(f"{key}: normalizer declaration lacks its validator")
    # JSON encoding distinguishes booleans from integer defaults, unlike
    # Python's ordinary mapping equality (False == 0).
    if json.dumps(_contract(expected), sort_keys=True) != json.dumps(
        _contract(schema),
        sort_keys=True,
    ):
        raise ValueError(f"{key}: descriptor differs from retained host model")
    if not Draft202012Validator(schema).is_valid(defaults):
        raise ValueError(f"{key}: host defaults violate descriptor schema")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args()
    # Import this release tree's lightweight models, without user bootstrap.
    sys.path.insert(0, str(args.project_root.resolve() / "src"))
    with tempfile.TemporaryDirectory(
        prefix="qwenpaw-channel-contract-"
    ) as config:
        os.environ["QWENPAW_WORKING_DIR"] = config
        os.environ["QWENPAW_SECRET_DIR"] = str(Path(config) / "secrets")
        os.environ["QWENPAW_RUNTIME_ID"] = "channel-contract-preflight"
        try:
            validate_official_channel_contracts(args.project_root)
        except (ValueError, OSError, KeyError) as exc:
            print(f"Channel contract preflight failed: {exc}", file=sys.stderr)
            return 1
    print("Official channel contracts validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
