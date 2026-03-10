# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.sender import build_markdown_message


def test_build_markdown_message() -> None:
    payload = build_markdown_message("**hello**")

    assert payload["msgtype"] == "markdown"
    assert payload["markdown"]["content"] == "**hello**"
