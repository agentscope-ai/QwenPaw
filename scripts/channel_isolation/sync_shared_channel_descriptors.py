#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate or check candidate static configuration schemas at build time."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> int:
    """Keep inherited configuration defaults in the static descriptors."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "src"))
    # This development-only command is the sole schema-generation importer.
    from qwenpaw.config.config import ChannelConfig
    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from qwenpaw.plugins.official_channel_catalog import OFFICIAL_CHANNELS

    stale = []
    for row in OFFICIAL_CHANNELS:
        key = row["channel_key"]
        plugin_root = root / "plugins/channel" / row["source_dir"]
        manifest = PluginManifest.from_dict(
            json.loads((plugin_root / "plugin.json").read_text()),
        )
        if manifest.id != row["plugin_id"]:
            raise ValueError("Official channel owner mismatch")
        if manifest.entry.descriptor != "channel.json":
            raise ValueError("Candidate must declare channel.json")
        path = plugin_root / "channel.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        field = ChannelConfig.model_fields.get(key)
        if field is not None:
            model = field.annotation
            schema = model.model_json_schema()
            for name, default in model().model_dump(mode="json").items():
                schema["properties"][name]["default"] = default
            raw["config_schema"] = schema
            raw["config_fields"] = list(schema["properties"])
        # Azure and third-party-style schema-only entries retain their own
        # schema. Entrypoints, capabilities and labels are never regenerated.
        descriptor = SharedChannelDescriptor.from_mapping(raw)
        content = (
            json.dumps(descriptor.to_mapping(), ensure_ascii=False, indent=2)
            + "\n"
        )
        if args.check:
            if (
                not path.exists()
                or path.read_text(encoding="utf-8") != content
            ):
                stale.append(str(path.relative_to(root)))
        else:
            path.write_text(content, encoding="utf-8")
        describe_channel(plugin_root, manifest)
    if stale:
        print("Stale shared descriptors: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
