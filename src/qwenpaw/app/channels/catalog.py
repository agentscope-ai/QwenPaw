# -*- coding: utf-8 -*-
"""Editable channel metadata, independent of executable registrations."""

from __future__ import annotations

from copy import deepcopy

from ...plugins.official_channel_catalog import official_channel_owners

OFFICIAL_CHANNEL_OWNERS = official_channel_owners()
RESPONSE_FIELDS = frozenset(
    {
        "isBuiltin",
        "owner",
        "form_kind",
        "process_mode",
        "availability",
        "qrcode_available",
        "global_enabled",
        "runtime_state",
        "repair",
        "diagnostic",
        "config_schema",
        "config_fields",
        "defaults",
        "label",
        "description",
        "plugin_id",
        "icon",
        "doc_url",
    },
)


def config_fields(schema, names=None):
    """Adapt scalar schema fields to the Console's existing widgets."""
    properties = schema.get("properties", {})
    requested = [
        name
        for name in (names if names is not None else properties)
        if isinstance(name, str) and name in properties
    ]
    presentation = schema.get("x-ui", {})
    layout = (
        presentation.get("config_fields", [])
        if isinstance(presentation, dict)
        else []
    )
    declared = {}
    for item in layout if isinstance(layout, list) else ():
        if isinstance(item, dict) and item.get("name") in requested:
            declared.setdefault(item["name"], item)
    ordered = [
        *declared,
        *(name for name in requested if name not in declared),
    ]
    result = []
    for name in ordered:
        field = dict(properties[name])
        alternatives = field.get("anyOf", [])
        value = next(
            (item for item in alternatives if item.get("type") != "null"),
            field,
        )
        kind = value.get("type")
        if isinstance(kind, list):
            choices = [item for item in kind if item != "null"]
            kind = choices[0] if len(choices) == 1 else None
        if not isinstance(kind, str) or kind not in {
            "boolean",
            "integer",
            "number",
            "string",
            "object",
            "array",
        }:
            continue
        widget = {
            "boolean": "switch",
            "integer": "number",
            "number": "number",
            "object": "json",
            "array": "json",
        }.get(kind, "text")
        row = {"name": name, "label": field.get("title", name), "type": widget}
        if kind in {"object", "array"}:
            row["type"] = "json"
            row["json_type"] = kind
        if kind not in {"object", "array"} and "enum" in value:
            row.update(type="select", options=value["enum"])
        elif kind == "string" and any(
            part in name for part in ("secret", "token", "password")
        ):
            row["type"] = "password"
        local = field.get("x-ui", {})
        ui = {
            **declared.get(name, {}),
            **(local if isinstance(local, dict) else {}),
        }
        for key in ("label", "help", "placeholder"):
            if key in ui:
                row[key] = deepcopy(ui[key])
        if (
            kind == "string"
            and "enum" not in value
            and isinstance(ui.get("type"), str)
            and ui.get("type") in {"text", "password"}
        ):
            row["type"] = ui["type"]
        if type(ui.get("required")) is bool:
            row["required"] = ui["required"]
        if name in schema.get("required", ()):
            row["required"] = True
        if "default" in field:
            row["default"] = field["default"]
        result.append(row)
    return result


def clean_channel_config(value, schema=None):
    """Drop catalogue metadata unless the plugin declares it as a setting."""
    declared = schema.get("properties", {}) if schema is not None else {}
    return {
        key: item
        for key, item in value.items()
        if key not in RESPONSE_FIELDS or key in declared
    }


def _catalog_files():
    """Read filesystem inputs without touching live plugin registrations."""
    from ...config.utils import get_plugins_dir, load_config
    from ...plugins.official_channel_catalog import OFFICIAL_CHANNELS
    from ...plugins.official_channels import bundled_channel_description

    descriptions = {}
    installed = {}
    plugins_dir = get_plugins_dir()
    for official in OFFICIAL_CHANNELS:
        plugin_id = official["plugin_id"]
        try:
            descriptions[plugin_id] = bundled_channel_description(plugin_id)
        except (OSError, ValueError, KeyError) as exc:
            descriptions[plugin_id] = str(exc)
        installed[plugin_id] = (
            plugins_dir / plugin_id / "plugin.json"
        ).is_file()
    return descriptions, installed, load_config().plugins


def get_configurable_channel_catalog(saved_keys=()):
    """Keep the synchronous CLI catalog available."""
    return _assemble_channel_catalog(saved_keys, *_catalog_files())


async def get_configurable_channel_catalog_async(saved_keys=()):
    """Read passive files off-loop, then merge current runtime registrations."""
    from ...utils.io_utils import run_sync_io

    saved_keys = tuple(saved_keys)
    files = await run_sync_io(_catalog_files)
    return _assemble_channel_catalog(saved_keys, *files)


def _assemble_channel_catalog(saved_keys, descriptions, installed, settings):
    """Assemble one catalog from filesystem and live registry snapshots."""
    from ...config.config import ChannelConfig
    from ...plugins.registry import PluginRegistry
    from ...plugins.settings import is_plugin_enabled
    from ...plugins.channel_config import channel_config_defaults
    from ...plugins.official_channel_catalog import OFFICIAL_CHANNELS

    registry = PluginRegistry()
    owners = official_channel_owners()
    result = {}
    for key, field in ChannelConfig.model_fields.items():
        model = field.annotation
        official = key in owners
        result[key] = {
            "label": key,
            "description": "",
            "plugin_id": owners.get(key, ""),
            "owner": owners.get(key, "builtin"),
            "form_kind": key,
            "process_mode": "runner_process" if official else "in_process",
            "config_fields": config_fields(model.model_json_schema()),
            "defaults": model().model_dump(mode="json"),
        }
    for official in OFFICIAL_CHANNELS:
        key, plugin_id = official["channel_key"], official["plugin_id"]
        base = result.setdefault(
            key,
            {"label": key, "description": "", "form_kind": "schema"},
        )
        enabled = is_plugin_enabled(settings.get(plugin_id))
        state = (
            "missing_code"
            if not installed[plugin_id]
            else ("disabled" if not enabled else "validation_pending")
        )
        if (
            installed[plugin_id]
            and enabled
            and registry.channel_runtime is None
        ):
            state = "missing_runtime"
        base.update(
            owner=plugin_id,
            plugin_id=plugin_id,
            process_mode="runner_process",
            availability=state,
            global_enabled=enabled,
            icon=official["icon"],
            doc_url=official["doc_url"],
        )
        description = descriptions[plugin_id]
        if isinstance(description, str):
            # Keep builtin lightweight settings editable if release resources
            # are damaged; never trust or execute unauthenticated metadata.
            base["diagnostic"] = description
            base.setdefault("config_fields", [])
        else:
            descriptor = description.descriptor
            base.update(
                label=descriptor.label["en"],
                description=description.description,
                config_schema=descriptor.config_schema,
                config_fields=config_fields(
                    descriptor.config_schema,
                    descriptor.config_fields,
                ),
                defaults=channel_config_defaults(descriptor.config_schema),
            )
    for key, row in registry.get_channel_catalog().items():
        base = result.setdefault(
            key,
            {"owner": row.plugin_id, "form_kind": "schema"},
        )
        base.update(
            label=row.label,
            description=row.description,
            plugin_id=row.plugin_id,
            config_fields=row.config_fields,
            icon=row.icon or base.get("icon", ""),
            doc_url=row.doc_url or base.get("doc_url", ""),
        )
        if row.description_record is not None:
            descriptor = row.description_record.descriptor
            base.update(
                owner=row.plugin_id,
                process_mode=descriptor.process_mode,
                config_schema=descriptor.config_schema,
                defaults=channel_config_defaults(descriptor.config_schema),
                global_enabled=row.global_enabled,
                availability=(
                    "disabled"
                    if not row.global_enabled
                    else (
                        "missing_runtime"
                        if row.runtime_settings is None
                        else "validation_pending"
                    )
                ),
            )
    for key in saved_keys:
        result.setdefault(
            key,
            {
                "label": key,
                "description": "",
                "plugin_id": key,
                "owner": key,
                "form_kind": "key_value",
                "process_mode": "runner_process",
                "availability": "missing_code",
                "global_enabled": is_plugin_enabled(settings.get(key)),
                "config_fields": [],
            },
        )
    for key, plugin_id in owners.items():
        row = result[key]
        action = (
            "install"
            if row["availability"] == "missing_code"
            else ("enable" if row["availability"] == "disabled" else "repair")
        )
        row["repair"] = {
            "action": action,
            "plugin_id": plugin_id,
            "source": "bundled:" + plugin_id,
        }
    return result
