# -*- coding: utf-8 -*-

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.sender import parse_send_target


def test_parse_user_target() -> None:
    target = parse_send_target("wecom:user:alice")

    assert target.target_type == "user"
    assert target.target_id == "alice"


def test_parse_chat_target() -> None:
    target = parse_send_target("wecom:chat:room1")

    assert target.target_type == "chat"
    assert target.target_id == "room1"


def test_parse_invalid_target_raises() -> None:
    with pytest.raises(ValueError):
        parse_send_target("wecom:unknown:room1")
