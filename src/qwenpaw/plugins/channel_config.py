# -*- coding: utf-8 -*-
"""Static channel configuration: host controls plus plugin JSON Schema."""

from copy import deepcopy
from collections.abc import Mapping
from types import SimpleNamespace
import hashlib
import json
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ..config.config import BaseChannelConfig
from ..config.channel_normalizers import (
    field_normalizer,
    normalize_channel_fields,
)


def channel_config_dict(value):
    """Detach config data without importing Drivers."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, SimpleNamespace):
        value = vars(value)
    if isinstance(value, Mapping):
        return {key: channel_config_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [channel_config_dict(item) for item in value]
    return deepcopy(value)


def validate_channel_config_schema(schema: Mapping) -> dict:
    """Check static Schema and local references without config values."""
    normalized_schema = channel_config_dict(schema)

    def check_refs(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(value, str) or not value.startswith("#")
                ):
                    raise ValueError("Channel schema references must be local")
                check_refs(value)
        elif isinstance(node, list):
            for value in node:
                check_refs(value)

    check_refs(normalized_schema)
    try:
        Draft202012Validator.check_schema(normalized_schema)
    except SchemaError as exc:
        raise ValueError(f"Invalid channel schema: {exc.message}") from exc
    for field in normalized_schema.get("properties", {}).values():
        field_normalizer(field)
    authorization = normalized_schema.get("x-qwenpaw-authorization-fields")
    if "x-qwenpaw-authorization-fields" in normalized_schema:
        properties = normalized_schema.get("properties", {})
        if (
            not isinstance(authorization, list)
            or any(
                not isinstance(name, str)
                or not isinstance(properties.get(name), dict)
                or properties[name].get("type") != "string"
                for name in authorization
            )
            or len(set(authorization)) != len(authorization)
        ):
            raise ValueError(
                "Authorization fields must name distinct string configuration fields",
            )
    resources = normalized_schema.get("x-qwenpaw-exclusive-resources", [])
    properties = normalized_schema.get("properties", {})
    if not isinstance(resources, list):
        raise ValueError("Exclusive resources must be a list")
    namespaces = set()
    for resource in resources:
        if (
            not isinstance(resource, dict)
            or not {"namespace", "fields"}
            <= set(resource)
            <= {"namespace", "fields", "operations"}
            or not isinstance(resource["namespace"], str)
            or not re.fullmatch(
                r"[a-z][a-z0-9_.:-]{0,127}",
                resource["namespace"],
            )
            or resource["namespace"] in namespaces
            or not isinstance(resource["fields"], list)
            or not resource["fields"]
            or any(
                not isinstance(name, str)
                or not isinstance(properties.get(name), dict)
                or properties[name].get("type") not in ("string", "integer")
                for name in resource["fields"]
            )
            or len(set(resource["fields"])) != len(resource["fields"])
        ):
            raise ValueError("Invalid exclusive resource declaration")
        operations = resource.get("operations", ["run"])
        if (
            not isinstance(operations, list)
            or not operations
            or any(
                not isinstance(operation, str)
                or operation
                not in {
                    "run",
                    "qrcode.fetch",
                    "qrcode.poll",
                    "connection.verify",
                }
                for operation in operations
            )
            or len(set(operations)) != len(operations)
        ):
            raise ValueError("Invalid exclusive resource operations")
        namespaces.add(resource["namespace"])
    routes = normalized_schema.get("x-qwenpaw-ingress-routes", [])
    if not isinstance(routes, list) or len(routes) > 32:
        raise ValueError("Ingress routes must be a list of at most 32 routes")
    seen = set()
    for route in routes:
        if (
            not isinstance(route, dict)
            or set(route) != {"method", "path"}
            or not isinstance(route["method"], str)
            or route["method"]
            not in {
                "GET",
                "HEAD",
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
                "OPTIONS",
                "WEBSOCKET",
            }
            or not isinstance(route["path"], str)
            or not re.fullmatch(r"/[A-Za-z0-9/_.-]*", route["path"])
            or ".." in route["path"]
            or "//" in route["path"]
            or "." in route["path"].split("/")
            or (route["method"], route["path"]) in seen
        ):
            raise ValueError("Invalid channel ingress route")
        seen.add((route["method"], route["path"]))
    return normalized_schema


def channel_resource_claims(
    schema: Mapping,
    config: Mapping,
    operation: str = "run",
) -> tuple[tuple[str, str], ...]:
    """Derive opaque composite claims before construction; never log values."""
    claims = []
    for resource in schema.get("x-qwenpaw-exclusive-resources", ()):
        if operation not in resource.get("operations", ("run",)):
            continue
        values = [config.get(name) for name in resource["fields"]]
        if any(
            type(value) not in (str, int)
            or (isinstance(value, str) and not value.strip())
            for value in values
        ):
            raise ValueError("CHANNEL_RESOURCE_IDENTITY_MISSING")
        digest = hashlib.sha256(
            json.dumps(
                values,
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode(),
        ).hexdigest()
        claims.append(("channel.resource:" + resource["namespace"], digest))
    return tuple(claims)


def _fill_defaults(schema, values):
    """Apply explicit defaults, recursively, to an already detached value."""
    if not isinstance(schema, dict):
        return values
    if isinstance(values, dict):
        for key, field in schema.get("properties", {}).items():
            if not isinstance(field, dict):
                continue
            if key not in values and "default" in field:
                values[key] = deepcopy(field["default"])
            if key in values:
                _fill_defaults(field, values[key])
    elif isinstance(values, list) and isinstance(schema.get("items"), dict):
        for value in values:
            _fill_defaults(schema["items"], value)
    return values


def channel_config_defaults(schema: Mapping) -> dict:
    """Return independent public defaults and declared plugin defaults."""
    schema = validate_channel_config_schema(schema)
    return _fill_defaults(schema, BaseChannelConfig().model_dump(mode="json"))


def validate_channel_config(schema: Mapping, values: Mapping) -> dict:
    """Normalize public fields; validate plugin values without coercion."""
    schema = validate_channel_config_schema(schema)
    normalized_values = channel_config_dict(values)
    if not isinstance(normalized_values, dict):
        raise ValueError("Channel configuration must be an object")
    normalized_values = _fill_defaults(schema, normalized_values)
    public = BaseChannelConfig.model_validate(normalized_values).model_dump(
        mode="json",
    )
    normalized_values.update(public)
    # Even a closed plugin schema accepts host-owned common fields. The host
    # model above is authoritative when a plugin tries to relax their types.
    properties = schema.setdefault("properties", {})
    for key, field in BaseChannelConfig.model_json_schema()[
        "properties"
    ].items():
        properties.setdefault(key, field)
    errors = list(Draft202012Validator(schema).iter_errors(normalized_values))
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.absolute_path)) or "config"
        raise ValueError(f"{path}: {error.message}")
    return normalize_channel_fields(schema, normalized_values)
