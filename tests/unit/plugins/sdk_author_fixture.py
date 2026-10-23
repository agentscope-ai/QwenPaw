# -*- coding: utf-8 -*-
"""Portable author fixture: a minimal SDK package without host imports."""

import json


def make_plugin(tmp_path, source, capabilities):
    root = tmp_path / "extension-plugin"
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "extension-contract",
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.0", "capabilities": capabilities},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(source, encoding="utf-8")
    return root
