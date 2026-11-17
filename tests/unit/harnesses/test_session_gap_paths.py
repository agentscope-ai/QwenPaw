# -*- coding: utf-8 -*-
"""Gap-path tests for HarnessSessionBridge lifecycle helpers.

Complements ``test_session.py`` by covering ``has_history``,
``hydrate`` (including the no-op when a transcript exists), ``clear``,
and the history-kind branches of ``_history_messages``.
"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.chats.session import DatabaseSession
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.plugins.harnesses import HarnessHistoryItem, HarnessHistoryKind
from qwenpaw.runtime.backends.session import HarnessSessionBridge
from qwenpaw.schemas import (
    AgentResponse,
    AgentRequest,
    Message,
    MessageType,
    Role,
    RunStatus,
    TextContent,
)


@pytest.fixture
def session(tmp_path: Path) -> DatabaseSession:
    return DatabaseSession(
        catalog=TranscriptCatalog(tmp_path),
        legacy_save_dir=str(tmp_path / "sessions"),
    )


@pytest.fixture
def bridge(session) -> HarnessSessionBridge:
    return HarnessSessionBridge(session)


# ---------------------------------------------------------------------------
# hydrate
# ---------------------------------------------------------------------------


class TestHydrate:
    def _history(self):
        return [
            HarnessHistoryItem(kind=HarnessHistoryKind.USER, text="hi"),
            HarnessHistoryItem(
                kind=HarnessHistoryKind.MESSAGE,
                text="hello",
                item_id="m1",
            ),
            HarnessHistoryItem(
                kind=HarnessHistoryKind.REASONING,
                text="thinking...",
            ),
            HarnessHistoryItem(
                kind=HarnessHistoryKind.TOOL_CALL,
                item_id="tc1",
                tool_name="shell",
                data={"arguments": {"cmd": "ls"}},
            ),
            HarnessHistoryItem(
                kind=HarnessHistoryKind.TOOL_OUTPUT,
                item_id="tc1",
                tool_name="shell",
                text="file.txt",
            ),
        ]

    async def test_hydrate_persists_all_kinds(self, bridge, session):
        await bridge.hydrate(
            session_id="s",
            user_id="u",
            channel="c",
            backend="codex",
            history=self._history(),
        )

        persisted = await session.get_session_state_dict("s", "u", "c")
        context = persisted["agent"]["state"]["context"]

        assert len(context) == 5
        roles = [m["role"] for m in context]
        assert roles == [
            "user",
            "assistant",
            "assistant",
            "assistant",
            "assistant",
        ]

        blocks = [m["content"][0] for m in context]
        assert blocks[0]["type"] == "text"
        assert blocks[1]["type"] == "text"
        assert blocks[2]["type"] == "thinking"
        assert blocks[2]["thinking"] == "thinking..."
        assert blocks[3]["type"] == "tool_call"
        assert blocks[3]["name"] == "shell"
        assert '"cmd"' in blocks[3]["input"]
        assert blocks[4]["type"] == "tool_result"
        assert blocks[4]["output"] == "file.txt"
        # Provider item ids carried as extra metadata.
        assert context[1]["metadata"]["provider_item_id"] == "m1"

    async def test_hydrate_skipped_when_history_exists(
        self,
        bridge,
        session,
    ):
        await bridge.hydrate(
            session_id="s",
            user_id="u",
            channel="c",
            backend="codex",
            history=self._history(),
        )
        # Second hydrate must not overwrite.
        await bridge.hydrate(
            session_id="s",
            user_id="u",
            channel="c",
            backend="other",
            history=[
                HarnessHistoryItem(kind=HarnessHistoryKind.USER, text="x"),
            ],
        )
        persisted = await session.get_session_state_dict("s", "u", "c")
        context = persisted["agent"]["state"]["context"]
        assert len(context) == 5


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    async def test_clear_resets_context(self, bridge, session):
        request = AgentRequest(
            session_id="s",
            user_id="u",
            channel="c",
            input=[
                Message(role=Role.USER, content=[TextContent(text="hi")]),
            ],
        )
        response = AgentResponse(
            id="r1",
            output=[
                Message(
                    type=MessageType.MESSAGE,
                    role=Role.ASSISTANT,
                    status=RunStatus.Completed,
                    content=[TextContent(text="yo")],
                ),
            ],
            status=RunStatus.Completed,
        )
        await bridge.append_turn(
            request=request,
            response=response,
            backend="codex",
        )
        assert (
            await bridge.has_history(
                session_id="s",
                user_id="u",
                channel="c",
            )
            is True
        )

        await bridge.clear(session_id="s", user_id="u", channel="c")

        assert (
            await bridge.has_history(
                session_id="s",
                user_id="u",
                channel="c",
            )
            is False
        )


# ---------------------------------------------------------------------------
# _response_messages error fallback
# ---------------------------------------------------------------------------


class TestResponseErrorFallback:
    async def test_error_without_output_recorded(self, bridge, session):
        request = AgentRequest(
            session_id="s",
            user_id="u",
            input=[
                Message(role=Role.USER, content=[TextContent(text="hi")]),
            ],
        )
        response = AgentResponse(
            id="r1",
            output=[],
            status=RunStatus.Failed,
            error={"message": "provider exploded"},
        )
        await bridge.append_turn(
            request=request,
            response=response,
            backend="codex",
        )

        persisted = await session.get_session_state_dict("s", "u")
        context = persisted["agent"]["state"]["context"]
        last = context[-1]
        assert last["content"][0]["text"] == "provider exploded"
        assert last["metadata"]["status"] == "failed"
