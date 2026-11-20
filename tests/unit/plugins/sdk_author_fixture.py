# -*- coding: utf-8 -*-
"""Portable author fixture: a minimal SDK package without host imports."""

import json


def make_plugin(
    tmp_path,
    source,
    capabilities,
    *,
    plugin_id="extension-contract",
    sdk_version="1.0",
):
    root = tmp_path / (
        "extension-plugin" if plugin_id == "extension-contract" else plugin_id
    )
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": sdk_version, "capabilities": capabilities},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(source, encoding="utf-8")
    return root
