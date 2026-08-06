# -*- coding: utf-8 -*-
"""Tests for ACP session-scoped MCP Driver registration."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from acp import text_block
from acp.schema import (
    EnvVariable,
    HttpHeader,
    HttpMcpServer,
    McpServerStdio,
    SseMcpServer,
)

from qwenpaw.agents.acp.server import QwenPawACPAgent
from qwenpaw.agents.acp.session_mcp import (
    acp_mcp_scope_id,
    build_acp_mcp_driver_cards,
)
from qwenpaw.drivers.constants import (
    DRIVER_SCOPE_CONTEXT_KEY,
    POLICY_EFFECT_ASK,
)


def _stdio_server(name: str = "tools") -> McpServerStdio:
    return McpServerStdio(
        name=name,
        command="python",
        args=["server.py"],
        env=[EnvVariable(name="TOKEN", value="secret")],
    )


def test_build_acp_mcp_driver_cards_normalizes_all_transports() -> None:
    cards = build_acp_mcp_driver_cards(
        "session-1",
        [
            _stdio_server(),
            SseMcpServer(
                type="sse",
                name="events",
                url="https://example.test/sse",
                headers=[HttpHeader(name="X-Test", value="sse")],
            ),
            HttpMcpServer(
                type="http",
                name="api",
                url="https://example.test/mcp",
                headers=[HttpHeader(name="Authorization", value="token")],
            ),
        ],
    )

    assert [card.endpoint["transport"] for card in cards] == [
        "stdio",
        "sse",
        "streamable_http",
    ]
    assert cards[0].endpoint["env"] == {"TOKEN": "secret"}
    assert cards[1].endpoint["headers"] == {"X-Test": "sse"}
    assert cards[2].endpoint["headers"] == {
        "Authorization": "token",
    }
    assert all(
        card.policy.default_effect == POLICY_EFFECT_ASK for card in cards
    )
    assert all(card.config["transient"] is True for card in cards)
    assert len({card.name for card in cards}) == len(cards)


def test_build_acp_mcp_driver_cards_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="Duplicate ACP MCP server name"):
        build_acp_mcp_driver_cards(
            "session-1",
            [_stdio_server(), _stdio_server()],
        )


def test_build_acp_mcp_driver_cards_rejects_duplicate_headers() -> None:
    server = HttpMcpServer(
        type="http",
        name="api",
        url="https://example.test/mcp",
        headers=[
            HttpHeader(name="Authorization", value="one"),
            HttpHeader(name="authorization", value="two"),
        ],
    )

    with pytest.raises(ValueError, match="Duplicate ACP MCP HTTP header"):
        build_acp_mcp_driver_cards("session-1", [server])


async def test_acp_advertises_supported_remote_mcp_transports() -> None:
    agent = QwenPawACPAgent(agent_id="default")

    response = await agent.initialize(protocol_version=1)

    capabilities = response.agent_capabilities.mcp_capabilities
    assert capabilities is not None
    assert capabilities.http is True
    assert capabilities.sse is True


class _FakeConn:
    async def session_update(
        self,
        session_id: str,
        update: Any,
    ) -> None:
        del session_id, update


class _FakeDriverManager:
    def __init__(self) -> None:
        self.replacements: list[tuple[str, list[Any]]] = []
        self.removals: list[str] = []
        self.fail_replacement = False

    async def replace_transient_drivers(
        self,
        scope_id: str,
        cards: list[Any],
    ) -> None:
        if self.fail_replacement:
            raise RuntimeError("registration failed")
        self.replacements.append((scope_id, cards))

    async def remove_transient_drivers(self, scope_id: str) -> None:
        self.removals.append(scope_id)


class _FakeWorkspace:
    def __init__(self) -> None:
        self.driver_manager = _FakeDriverManager()
        self.requests: list[Any] = []

    async def stream_query(
        self,
        request: Any,
    ) -> AsyncIterator[Any]:
        self.requests.append(request)
        for event in ():
            yield event


class _TestACPAgent(QwenPawACPAgent):
    def __init__(self, workspace: _FakeWorkspace) -> None:
        super().__init__(agent_id="default")
        self._fake_workspace = workspace

    async def _ensure_workspace(self) -> _FakeWorkspace:
        self._workspace = self._fake_workspace
        return self._fake_workspace


async def test_acp_session_mcp_lifecycle_and_request_scope(tmp_path) -> None:
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())

    response = await agent.new_session(
        cwd=str(tmp_path),
        mcp_servers=[_stdio_server()],
    )
    scope_id = acp_mcp_scope_id(response.session_id)

    assert workspace.driver_manager.replacements[0][0] == scope_id
    assert len(workspace.driver_manager.replacements[0][1]) == 1

    await agent.prompt(
        prompt=[text_block("hello")],
        session_id=response.session_id,
    )
    request_context = workspace.requests[0].request_context
    assert request_context[DRIVER_SCOPE_CONTEXT_KEY] == scope_id

    await agent.resume_session(
        cwd=str(tmp_path),
        session_id=response.session_id,
        mcp_servers=[],
    )
    assert workspace.driver_manager.replacements[-1] == (scope_id, [])

    await agent.close_session(session_id=response.session_id)
    assert workspace.driver_manager.removals[-1] == scope_id


async def test_acp_new_session_rolls_back_failed_mcp_registration(
    tmp_path: Path,
) -> None:
    workspace = _FakeWorkspace()
    workspace.driver_manager.fail_replacement = True
    agent = _TestACPAgent(workspace)

    with pytest.raises(RuntimeError, match="registration failed"):
        await agent.new_session(
            cwd=str(tmp_path),
            mcp_servers=[_stdio_server()],
        )

    assert not agent._sessions
    assert len(workspace.driver_manager.removals) == 1


async def test_acp_load_session_restores_metadata_on_mcp_failure(
    tmp_path: Path,
) -> None:
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    await agent.load_session(
        cwd=str(tmp_path),
        session_id="session-1",
        mcp_servers=[],
    )
    previous = dict(agent._sessions["session-1"])
    workspace.driver_manager.fail_replacement = True

    with pytest.raises(RuntimeError, match="registration failed"):
        await agent.load_session(
            cwd="/replacement",
            session_id="session-1",
            mcp_servers=[_stdio_server()],
        )

    assert agent._sessions["session-1"] == previous


async def test_acp_resume_session_removes_new_metadata_on_mcp_failure(
    tmp_path: Path,
) -> None:
    workspace = _FakeWorkspace()
    workspace.driver_manager.fail_replacement = True
    agent = _TestACPAgent(workspace)

    with pytest.raises(RuntimeError, match="registration failed"):
        await agent.resume_session(
            cwd=str(tmp_path),
            session_id="session-1",
            mcp_servers=[_stdio_server()],
        )

    assert not agent._sessions


async def test_acp_close_waits_for_prompt_before_removing_mcp(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()

    class _OrderedDriverManager(_FakeDriverManager):
        async def remove_transient_drivers(self, scope_id: str) -> None:
            assert stopped.is_set()
            await super().remove_transient_drivers(scope_id)

    class _BlockingWorkspace(_FakeWorkspace):
        def __init__(self) -> None:
            super().__init__()
            self.driver_manager = _OrderedDriverManager()

        async def stream_query(
            self,
            request: Any,
        ) -> AsyncIterator[Any]:
            del request
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()
            yield

    workspace = _BlockingWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())
    response = await agent.new_session(
        cwd=str(tmp_path),
        mcp_servers=[_stdio_server()],
    )
    prompt_task = asyncio.create_task(
        agent.prompt(
            prompt=[text_block("hello")],
            session_id=response.session_id,
        ),
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    await agent.close_session(session_id=response.session_id)
    prompt_response = await asyncio.wait_for(prompt_task, timeout=1)

    assert prompt_response.stop_reason == "cancelled"
    assert stopped.is_set()
