# -*- coding: utf-8 -*-
"""
Install the executable sample artifact under any valid third-channel name.
"""

import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]


def sample_source(directory, key="sample_chat", *, capabilities=None):
    source = Path(directory) / key
    shutil.copytree(
        Path(__file__).with_name("sample_chat"),
        source,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    if key != "sample_chat":
        (source / "sample_chat").rename(source / key)
    for filename in ("plugin.json", "channel.json"):
        path = source / filename
        value = json.loads(path.read_text())
        if filename == "plugin.json":
            value["id"] = key
        else:
            value["channel_key"] = key
            value["entrypoint"]["module"] = key + ".driver"
            if capabilities is not None:
                value["capabilities"] = capabilities
        path.write_text(json.dumps(value))
    return source
