# -*- coding: utf-8 -*-

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.channel import WeComChannel


def test_resolve_single_session_id() -> None:
    channel = WeComChannel()

    session_id = channel.resolve_session_id(
        "alice",
        {"chat_type": "single"},
    )

    assert session_id == "wecom:user:alice"


def test_resolve_group_session_id() -> None:
    channel = WeComChannel()

    session_id = channel.resolve_session_id(
        "alice",
        {"chat_type": "group", "chat_id": "room1"},
    )

    assert session_id == "wecom:chat:room1"


def test_to_handle_from_target_prefers_session_id() -> None:
    channel = WeComChannel()

    to_handle = channel.to_handle_from_target(
        user_id="alice",
        session_id="wecom:chat:room1",
    )

    assert to_handle == "wecom:chat:room1"
