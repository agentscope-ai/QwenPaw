# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for BaseChannel external ACL checker integration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qwenpaw.app.channels.base import BaseChannel, _external_acl_checkers
from qwenpaw.app.channels.console.channel import ConsoleChannel


@pytest.fixture
def console_channel(tmp_path: Path) -> ConsoleChannel:
    """Return a ConsoleChannel with access control enabled.

    Uses a temporary workspace directory.
    """

    async def process(_request: Any):
        yield None

    channel = ConsoleChannel(
        process=process,
        enabled=True,
        bot_prefix="",
        workspace_dir=tmp_path,
    )
    channel.access_control_dm = True
    return channel


@pytest.fixture(autouse=True)
def _clear_external_checkers():
    """Ensure external checkers are cleaned up after each test."""
    yield
    _external_acl_checkers.clear()


@pytest.mark.asyncio
async def test_external_checker_allow(console_channel: ConsoleChannel) -> None:
    def checker(_channel: str, _sender: str, _meta: dict) -> str:
        return "allow"

    BaseChannel.register_external_acl_checker(checker)
    payload = {"sender_id": "alice@example.com", "meta": {}}
    blocked = await console_channel._access_control_gate(payload)
    assert blocked is False


@pytest.mark.asyncio
async def test_external_checker_deny(console_channel: ConsoleChannel) -> None:
    def checker(_channel: str, _sender: str, _meta: dict) -> str:
        return "deny"

    BaseChannel.register_external_acl_checker(checker)
    payload = {"sender_id": "bob@example.com", "meta": {}}
    blocked = await console_channel._access_control_gate(payload)
    assert blocked is True


@pytest.mark.asyncio
async def test_external_checker_fallthrough(
    console_channel: ConsoleChannel,
) -> None:
    def checker(_channel: str, _sender: str, _meta: dict) -> None:
        return None

    BaseChannel.register_external_acl_checker(checker)
    payload = {"sender_id": "unknown@example.com", "meta": {}}
    # No whitelist/blacklist entry, so user goes to pending and is blocked.
    blocked = await console_channel._access_control_gate(payload)
    assert blocked is True
    store = console_channel._get_acl_store()
    acl = store.get_acl("console")
    assert any(p["user_id"] == "unknown@example.com" for p in acl["pending"])


@pytest.mark.asyncio
async def test_external_checker_exception_is_ignored(
    console_channel: ConsoleChannel,
) -> None:
    def checker(_channel: str, _sender: str, _meta: dict) -> None:
        raise RuntimeError("boom")

    BaseChannel.register_external_acl_checker(checker)
    payload = {"sender_id": "crash@example.com", "meta": {}}
    # Should fall through to native ACL, landing in pending.
    blocked = await console_channel._access_control_gate(payload)
    assert blocked is True
