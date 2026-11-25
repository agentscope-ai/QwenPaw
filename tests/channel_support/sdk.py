# -*- coding: utf-8 -*-
"""Shared files and paths for real SDK channel tests; no host behavior mocks."""

import hashlib
import json


def make_channel(root, source, definition, *, capabilities, requirements=""):
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": definition.channel_key,
                "version": "0.1.0",
                "type": "channel",
                "entry": {"descriptor": "channel.json"},
                "sdk": {"version": "1.2.0", "capabilities": capabilities},
            },
        ),
    )
    (root / "channel.json").write_text(json.dumps(definition.to_dict()))
    (root / "driver.py").write_text(source)
    (root / "requirements.txt").write_text(requirements)
    return root


def workspace_store(root, plugin_id, workspace_id):
    return (
        root
        / "plugin-data"
        / plugin_id
        / "workspaces"
        / hashlib.sha256(workspace_id.encode()).hexdigest()
    )
