# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.sender import build_text_message


def test_build_text_message() -> None:
    payload = build_text_message("hello")

    assert payload["msgtype"] == "text"
    assert payload["text"]["content"] == "hello"


def test_build_text_message_with_mentions() -> None:
    payload = build_text_message("hello", mentioned_list=["alice"])

    assert payload["text"]["mentioned_list"] == ["alice"]
