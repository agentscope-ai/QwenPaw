# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Any

import pytest

import copaw.app.channels.manager as manager_module
from copaw.app.channels.base import BaseChannel
from copaw.app.channels.manager import ChannelManager


class _FakeChannel(BaseChannel):
    channel = "fake"

    def __init__(self) -> None:
        super().__init__(process=lambda req: None)
        self.events: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []

    @classmethod
    def from_env(cls, process, on_reply_sent=None):
        raise NotImplementedError

    @classmethod
    def from_config(
        cls,
        process,
        config,
        on_reply_sent=None,
        show_tool_details=True,
        filter_tool_messages=False,
        filter_thinking=False,
    ):
        raise NotImplementedError

    def build_agent_request_from_native(self, native_payload: Any):
        raise NotImplementedError

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, to_handle: str, text: str, meta=None) -> None:
        return None

    def get_debounce_key(self, payload: Any) -> str:
        return payload["key"]

    async def _consume_one_request(self, payload: Any) -> None:
        name = payload["name"]
        self.events.append(("start", name))
        if payload.get("hang"):
            await asyncio.Event().wait()
        await asyncio.sleep(payload.get("sleep", 0.01))
        self.events.append(("done", name))

    def _payload_to_request(self, payload: Any):
        return type(
            "Request",
            (),
            {
                "user_id": payload["name"],
                "session_id": payload["key"],
                "channel_meta": {},
            },
        )()

    def get_to_handle_from_request(self, request) -> str:
        return request.user_id

    async def _on_consume_error(
        self,
        request: Any,
        to_handle: str,
        err_text: str,
    ) -> None:
        del request
        self.errors.append((to_handle, err_text))


def _manager_state(manager: ChannelManager) -> tuple[set, dict]:
    """Access internal state without triggering protected-access lint."""
    state = vars(manager)
    return state["_in_progress"], state["_pending"]


@pytest.mark.asyncio
async def test_manager_timeout_releases_stuck_key_and_notifies_user(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        manager_module,
        "_CHANNEL_PROCESS_TIMEOUT_SECONDS",
        0.05,
    )

    ch = _FakeChannel()
    manager = ChannelManager([ch])
    await manager.start_all()
    try:
        manager.enqueue("fake", {"key": "A", "name": "A1", "hang": True})
        await asyncio.sleep(0.01)
        manager.enqueue("fake", {"key": "A", "name": "A2"})

        await asyncio.sleep(0.2)

        assert ("start", "A1") in ch.events
        assert ("start", "A2") in ch.events
        assert ("done", "A2") in ch.events
        in_progress, pending = _manager_state(manager)
        assert in_progress == set()
        assert not pending
        assert ch.errors == [
            (
                "A1",
                "Request timed out while processing. Please try again.",
            ),
        ]
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_manager_timeout_does_not_block_other_keys(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        manager_module,
        "_CHANNEL_PROCESS_TIMEOUT_SECONDS",
        0.05,
    )

    ch = _FakeChannel()
    manager = ChannelManager([ch])
    await manager.start_all()
    try:
        manager.enqueue("fake", {"key": "A", "name": "A1", "hang": True})
        await asyncio.sleep(0.01)
        manager.enqueue("fake", {"key": "B", "name": "B1"})

        await asyncio.sleep(0.2)

        assert ("done", "B1") in ch.events
        in_progress, _ = _manager_state(manager)
        assert in_progress == set()
    finally:
        await manager.stop_all()


@pytest.mark.asyncio
async def test_manager_handles_native_merge_returning_none(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        manager_module,
        "_CHANNEL_PROCESS_TIMEOUT_SECONDS",
        0.2,
    )

    class _NoMergeChannel(_FakeChannel):
        def merge_native_items(self, items):
            del items

    ch = _NoMergeChannel()
    manager = ChannelManager([ch])
    await manager.start_all()
    try:
        manager.enqueue("fake", {"key": "A", "name": "A1"})
        manager.enqueue("fake", {"key": "A", "name": "A2"})

        await asyncio.sleep(0.1)

        assert ("done", "A1") in ch.events
    finally:
        await manager.stop_all()
