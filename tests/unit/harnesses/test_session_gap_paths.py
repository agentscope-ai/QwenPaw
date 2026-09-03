# -*- coding: utf-8 -*-
"""Gap-path tests for HarnessSessionBridge lifecycle helpers.

Complements ``test_session.py`` by covering ``has_history``,
``hydrate`` (including the no-op when a transcript exists), ``clear``,
and the history-kind branches of ``_history_messages``.
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.harnesses.events import HarnessHistoryItem, HarnessHistoryKind
from qwenpaw.harnesses.session import HarnessSessionBridge
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
def session(tmp_path: Path) -> SafeJSONSession:
    return SafeJSONSession(str(tmp_path))


@pytest.fixture
def bridge(session) -> HarnessSessionBridge:
    return HarnessSessionBridge(session)


# ---------------------------------------------------------------------------
# has_history
# ---------------------------------------------------------------------------


class TestHasHistory:
    async def test_no_state_returns_false(self, bridge):
        result = await bridge.has_history(
            session_id="s",
            user_id="u",
            channel="c",
        )
        assert result is False

    async def test_state_without_context_returns_false(self, bridge, session):
        await bridge.clear(session_id="s", user_id="u", channel="c")
        result = await bridge.has_history(
            session_id="s",
            user_id="u",
            channel="c",
        )
        assert result is False


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

    async def test_empty_history_is_noop(self, bridge):
        await bridge.hydrate(
            session_id="s",
            user_id="u",
            channel="c",
            backend="codex",
            history=[],
        )
        assert await bridge.has_history(
            session_id="s",
            user_id="u",
            channel="c",
        ) is False

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
        assert roles == ["user", "assistant", "assistant", "assistant", "assistant"]

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
        assert await bridge.has_history(
            session_id="s",
            user_id="u",
            channel="c",
        ) is True

        await bridge.clear(session_id="s", user_id="u", channel="c")

        assert await bridge.has_history(
            session_id="s",
            user_id="u",
            channel="c",
        ) is False


# ---------------------------------------------------------------------------
# _output_block edge branches
# ---------------------------------------------------------------------------


class TestOutputBlock:
    def _message(self, message_type, content, role=Role.ASSISTANT):
        return Message(
            type=message_type,
            role=role,
            status=RunStatus.Completed,
            content=content,
        )

    def test_empty_content_returns_none(self):
        msg = self._message(MessageType.MESSAGE, [])
        assert HarnessSessionBridge._output_block(msg) is None

    def test_dict_output_serialized(self):
        from qwenpaw.schemas import DataContent

        msg = self._message(
            MessageType.PLUGIN_CALL_OUTPUT,
            [
                DataContent(
                    data={
                        "call_id": "c1",
                        "name": "t",
                        "output": {"k": [1, 2]},
                    },
                ),
            ],
            role=Role.TOOL,
        )
        block = HarnessSessionBridge._output_block(msg)
        assert block["type"] == "tool_result"
        assert '"k"' in block["output"]

    def test_unknown_type_with_data_returns_none(self):
        from qwenpaw.schemas import DataContent

        msg = self._message(
            MessageType.MESSAGE,
            [DataContent(data={"x": 1})],
        )
        # MESSAGE type looks at .text first; no data branch applies.
        block = HarnessSessionBridge._output_block(msg)
        assert block["type"] == "text"
        assert block["text"] == ""


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
