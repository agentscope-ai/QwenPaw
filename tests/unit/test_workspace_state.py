# -*- coding: utf-8 -*-
from qwenpaw.workspace_state import is_qwenpaw_state_path


def test_qwenpaw_state_paths_are_root_scoped_and_cross_platform() -> None:
    assert is_qwenpaw_state_path("chats.json") is True
    assert is_qwenpaw_state_path("sessions/chat.json") is True
    assert is_qwenpaw_state_path(r"sessions\chat.json") is True
    assert is_qwenpaw_state_path("exports/chats.json") is False
    assert is_qwenpaw_state_path("events.jsonl") is False
