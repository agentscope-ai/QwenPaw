# -*- coding: utf-8 -*-
"""A minimal ACP agent used to exercise the TUI's AcpTransport in tests.

Run as ``python _fake_acp_agent.py`` (stdio). It speaks just enough ACP to:
* answer ``initialize`` / ``new_session``
* stream a thought, two text deltas and a completed tool call on ``prompt``
* request permission when the prompt text contains ``need-permission``
* honour ``cancel``

This lets the transport be tested end-to-end without the heavy QwenPaw
backend (agentscope, etc.).
"""

from __future__ import annotations

# Test double: it intentionally overrides ACP Agent methods with simplified
# signatures and ignores most params.
# pylint: disable=arguments-renamed,unused-argument

import asyncio

from acp import (
    Agent,
    InitializeResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PROTOCOL_VERSION,
    PromptResponse,
    run_agent,
    start_tool_call,
    text_block,
    tool_content,
    update_agent_message,
    update_agent_thought,
    update_tool_call,
    update_user_message,
)
from acp.schema import (
    AgentCapabilities,
    Implementation,
    ListSessionsResponse,
    PermissionOption,
    SessionInfo,
    ToolCallUpdate,
)

# A canned "past" session the resume tests can list and load.
_PAST_SESSION_ID = "old-session-1"
_PAST_SESSION_TITLE = "Earlier chat about Rust"
_PAST_HISTORY = [
    ("user", "How do I write a loop in Rust?"),
    ("agent", "Use a `for` loop over a range."),
    ("user", "Thanks!"),
]


class FakeAgent(Agent):
    def __init__(self) -> None:
        self._conn = None
        self._cancel: dict[str, asyncio.Event] = {}
        self._session_count = 0

    def on_connect(self, conn) -> None:  # noqa: ANN001
        self._conn = conn

    async def initialize(
        self,
        protocol_version,
        client_capabilities=None,
        client_info=None,
        **kw,
    ):  # noqa: ANN001
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(),
            agent_info=Implementation(name="fake-agent", version="0.0.1"),
        )

    async def new_session(
        self,
        cwd,
        additional_directories=None,
        mcp_servers=None,
        **kw,
    ):  # noqa: ANN001
        self._session_count += 1
        return NewSessionResponse(session_id=f"sess-{self._session_count}")

    async def cancel(self, session_id, **kw):  # noqa: ANN001
        ev = self._cancel.get(session_id)
        if ev:
            ev.set()

    async def list_sessions(
        self,
        cursor=None,
        cwd=None,
        additional_directories=None,
        **kw,
    ):  # noqa: ANN001
        return ListSessionsResponse(
            sessions=[
                SessionInfo(
                    session_id=_PAST_SESSION_ID,
                    cwd=cwd or "",
                    title=_PAST_SESSION_TITLE,
                    updated_at="2026-01-01T00:00:00+00:00",
                ),
            ],
        )

    async def load_session(
        self,
        cwd,
        session_id,
        additional_directories=None,
        mcp_servers=None,
        **kw,
    ):  # noqa: ANN001
        for role, text in _PAST_HISTORY:
            if role == "user":
                update = update_user_message(text_block(text))
            else:
                update = update_agent_message(text_block(text))
            await self._conn.session_update(
                session_id=session_id,
                update=update,
            )
        return LoadSessionResponse()

    async def prompt(
        self,
        prompt,
        session_id,
        message_id=None,
        **kw,
    ):  # noqa: ANN001
        text = ""
        for block in prompt:
            text += getattr(block, "text", "") or ""

        cancel = asyncio.Event()
        self._cancel[session_id] = cancel

        await self._conn.session_update(
            session_id=session_id,
            update=update_agent_thought(text_block("thinking...")),
        )
        await self._conn.session_update(
            session_id=session_id,
            update=update_agent_message(text_block("Hello ")),
        )
        await self._conn.session_update(
            session_id=session_id,
            update=update_agent_message(text_block("world")),
        )

        if "need-permission" in text:
            outcome = await self._conn.request_permission(
                options=[
                    PermissionOption(
                        option_id="allow",
                        name="Allow",
                        kind="allow_once",
                    ),
                    PermissionOption(
                        option_id="deny",
                        name="Deny",
                        kind="reject_once",
                    ),
                ],
                session_id=session_id,
                tool_call=ToolCallUpdate(
                    tool_call_id="t1",
                    title="dangerous_tool",
                    raw_input={"command": "rm -rf /tmp/nope"},
                ),
            )
            chosen = getattr(
                getattr(outcome, "outcome", None),
                "option_id",
                "cancelled",
            )
            await self._conn.session_update(
                session_id=session_id,
                update=update_agent_message(text_block(f" [perm:{chosen}]")),
            )

        # A tool call: start then complete.
        await self._conn.session_update(
            session_id=session_id,
            update=start_tool_call(
                "t2",
                "read_file",
                kind="read",
                status="in_progress",
            ),
        )
        await self._conn.session_update(
            session_id=session_id,
            update=update_tool_call(
                "t2",
                status="completed",
                content=[tool_content(text_block("file contents"))],
            ),
        )

        if "loop" in text:
            # Stay busy so the test can exercise cancel().
            try:
                await asyncio.wait_for(cancel.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                pass

        self._cancel.pop(session_id, None)
        return PromptResponse(stop_reason="end_turn")

    async def close_session(self, session_id, **kw):  # noqa: ANN001
        return None


if __name__ == "__main__":
    asyncio.run(run_agent(FakeAgent()))
