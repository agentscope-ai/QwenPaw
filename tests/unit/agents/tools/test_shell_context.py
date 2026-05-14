# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for per-request shell subprocess context."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from qwenpaw.agents.tools.shell import _build_subprocess_env
from qwenpaw.agents.tools.shell_context import (
    get_shell_command_context_env,
    reset_shell_command_context,
    set_shell_command_context,
)


def test_shell_context_env_overrides_process_env(monkeypatch):
    """Per-request shell context should be exported to subprocess env."""
    monkeypatch.setenv("PATH", "base-path")
    monkeypatch.setenv("QWENPAW_USER_ID", "process-user")

    token = set_shell_command_context(
        {
            "user_id": "@alice:example.org",
            "session_id": "matrix:!room",
            "channel": "matrix",
            "room_id": "!room",
            "event_id": "$event",
        },
    )
    try:
        env = _build_subprocess_env()
    finally:
        reset_shell_command_context(token)

    assert env["QWENPAW_USER_ID"] == "@alice:example.org"
    assert env["QWENPAW_SESSION_ID"] == "matrix:!room"
    assert env["QWENPAW_CHANNEL"] == "matrix"
    assert env["QWENPAW_ROOM_ID"] == "!room"
    assert env["QWENPAW_EVENT_ID"] == "$event"
    assert env["PATH"].startswith(
        str(Path(sys.executable).parent) + os.pathsep,
    )


def test_shell_context_skips_empty_optional_values():
    """Optional room/event fields should be unset when unavailable."""
    token = set_shell_command_context(
        {
            "user_id": "console-user",
            "session_id": "console:console-user",
            "channel": "console",
            "room_id": "",
            "event_id": None,
        },
    )
    try:
        env = get_shell_command_context_env()
    finally:
        reset_shell_command_context(token)

    assert env == {
        "QWENPAW_USER_ID": "console-user",
        "QWENPAW_SESSION_ID": "console:console-user",
        "QWENPAW_CHANNEL": "console",
    }


async def test_shell_context_is_isolated_across_concurrent_tasks():
    """Concurrent requests must not see each other's attribution values."""

    async def collect(user_id: str) -> str:
        token = set_shell_command_context(
            {
                "user_id": user_id,
                "session_id": f"console:{user_id}",
                "channel": "console",
            },
        )
        try:
            await asyncio.sleep(0)
            return get_shell_command_context_env()["QWENPAW_USER_ID"]
        finally:
            reset_shell_command_context(token)

    assert await asyncio.gather(collect("user-a"), collect("user-b")) == [
        "user-a",
        "user-b",
    ]
    assert get_shell_command_context_env() == {}
