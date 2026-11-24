# -*- coding: utf-8 -*-
"""Tests for ACP session-scoped MCP Driver registration."""

# pylint: disable=protected-access

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from acp import text_block
from acp.schema import (
    EnvVariable,
    HttpHeader,
    HttpMcpServer,
    McpServerStdio,
    SseMcpServer,
)

from qwenpaw.agents.acp.meta import ACP_CONFIG_META_KEY
from qwenpaw.agents.acp.server import QwenPawACPAgent
from qwenpaw.agents.acp.session_mcp import (
    acp_mcp_scope_id,
    build_acp_mcp_driver_cards,
)
from qwenpaw.config.context import current_runtime_parameters
from qwenpaw.drivers.constants import (
    DRIVER_SCOPE_CONTEXT_KEY,
    POLICY_EFFECT_ASK,
)
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.manager import DriverManager


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
        session_cwd="/workspace",
    )

    assert [card.endpoint["transport"] for card in cards] == [
        "stdio",
        "sse",
        "streamable_http",
    ]
    assert cards[0].endpoint["env"] == {"TOKEN": "secret"}
    assert cards[0].endpoint["cwd"] == "/workspace"
    assert cards[1].endpoint["headers"] == {"X-Test": "sse"}
    assert cards[2].endpoint["headers"] == {
        "Authorization": "token",
    }
    assert all(
        card.policy.default_effect == POLICY_EFFECT_ASK for card in cards
    )
    assert all(card.config["transient"] is True for card in cards)
    assert len({card.name for card in cards}) == len(cards)


def test_build_acp_mcp_driver_cards_preserves_session_cwd() -> None:
    cards = build_acp_mcp_driver_cards(
        "session-1",
        [_stdio_server()],
        session_cwd="/workspace ",
    )

    assert cards[0].endpoint["cwd"] == "/workspace "


def test_build_acp_mcp_driver_cards_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="Duplicate ACP MCP server name"):
        build_acp_mcp_driver_cards(
            "session-1",
            [_stdio_server(), _stdio_server()],
            session_cwd="/workspace",
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
        build_acp_mcp_driver_cards(
            "session-1",
            [server],
            session_cwd="/workspace",
        )


def test_build_acp_mcp_driver_cards_rejects_duplicate_environment() -> None:
    server = McpServerStdio(
        name="tools",
        command="python",
        args=["server.py"],
        env=[
            EnvVariable(name="PATH", value="one"),
            EnvVariable(name="Path", value="two"),
        ],
    )

    with pytest.raises(ValueError, match="Duplicate ACP MCP environment"):
        build_acp_mcp_driver_cards(
            "session-1",
            [server],
            session_cwd="/workspace",
        )


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

    async def release_session(self, session_id: str) -> None:
        self.released_session = session_id

    async def stream_query(
        self,
        request: Any,
    ) -> AsyncIterator[Any]:
        self.requests.append(request)
        for event in ():
            yield event

    async def for_session(self, session_id, parameters):
        return self

    @asynccontextmanager
    async def configure_session(self, session_id, parameters):
        yield self

    def session_workspace(self, session_id):
        return self


class _TestACPAgent(QwenPawACPAgent):
    def __init__(self, workspace: _FakeWorkspace) -> None:
        super().__init__(agent_id="default")
        self._fake_workspace = workspace

    async def _require_mcp(self) -> None:
        """These domain tests assume admission, without initializing plugins."""

    async def _ensure_workspace(self) -> _FakeWorkspace:
        self._workspace = self._fake_workspace
        self._workspace_ready = True
        return self._fake_workspace


async def test_acp_session_mcp_lifecycle_and_request_scope(tmp_path) -> None:
    workspace = _FakeWorkspace()
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())
    load_cwd = tmp_path / "loaded"
    resume_cwd = tmp_path / "resumed"
    load_cwd.mkdir()
    resume_cwd.mkdir()

    response = await agent.new_session(
        cwd=str(tmp_path),
        mcp_servers=[_stdio_server()],
    )
    assert agent._mcp_loader is None
    scope_id = acp_mcp_scope_id(response.session_id)

    assert workspace.driver_manager.replacements[0][0] == scope_id
    assert len(workspace.driver_manager.replacements[0][1]) == 1
    assert workspace.driver_manager.replacements[0][1][0].endpoint[
        "cwd"
    ] == str(tmp_path)

    await agent.load_session(
        cwd=str(load_cwd),
        session_id=response.session_id,
        mcp_servers=[_stdio_server()],
    )
    assert workspace.driver_manager.replacements[-1][1][0].endpoint[
        "cwd"
    ] == str(load_cwd)

    await agent.resume_session(
        cwd=str(resume_cwd),
        session_id=response.session_id,
        mcp_servers=[_stdio_server()],
    )
    assert workspace.driver_manager.replacements[-1][1][0].endpoint[
        "cwd"
    ] == str(resume_cwd)

    await agent.prompt(
        prompt=[text_block("hello")],
        session_id=response.session_id,
    )
    request_context = workspace.requests[0].request_context
    assert request_context[DRIVER_SCOPE_CONTEXT_KEY] == scope_id

    await agent.resume_session(
        cwd=str(resume_cwd),
        session_id=response.session_id,
        mcp_servers=[],
    )
    assert workspace.driver_manager.replacements[-1] == (scope_id, [])

    await agent.close_session(session_id=response.session_id)
    assert workspace.driver_manager.removals[-1] == scope_id


# pylint: disable-next=too-many-statements
async def test_acp_session_cleanup_cancellation_preserves_committed_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    old_cwd = tmp_path / "old"
    new_cwd = tmp_path / "new"
    old_cwd.mkdir()
    new_cwd.mkdir()
    teardown_started = asyncio.Event()
    allow_teardown = asyncio.Event()
    close_started = asyncio.Event()
    allow_close = asyncio.Event()
    close_finished = asyncio.Event()
    manager = DriverManager(
        tmp_path / "drivers",
        AsyncCredentialStore(tmp_path / "credentials.yaml"),
    )

    class _BlockingHandler:
        def __init__(self, card) -> None:
            self.card = card
            self.name = card.name

        async def init(self) -> None:
            pass

        async def shutdown(self) -> None:
            if self.card.endpoint["cwd"] == str(old_cwd):
                teardown_started.set()
                await allow_teardown.wait()
            else:
                close_started.set()
                await allow_close.wait()
                close_finished.set()

    monkeypatch.setattr(manager, "_build_handler", _BlockingHandler)
    workspace = _FakeWorkspace()
    workspace.driver_manager = manager
    agent = _TestACPAgent(workspace)
    response = await agent.new_session(
        cwd=str(old_cwd),
        mcp_servers=[_stdio_server()],
    )
    scope_id = acp_mcp_scope_id(response.session_id)
    load_task = asyncio.create_task(
        agent.load_session(
            cwd=str(new_cwd),
            session_id=response.session_id,
            mcp_servers=[_stdio_server()],
        ),
    )
    try:
        await asyncio.wait_for(teardown_started.wait(), timeout=1)

        assert load_task.done()
        load_task.cancel()
        await load_task
        assert agent._sessions[response.session_id].cwd == str(new_cwd)
        handler_name = next(iter(manager._scope_handlers[scope_id]))
        assert manager._handlers[handler_name].card.endpoint["cwd"] == str(
            new_cwd,
        )

        allow_teardown.set()
        await manager._wait_for_handler_cleanups()
        close_task = asyncio.create_task(
            agent.close_session(session_id=response.session_id),
        )
        await asyncio.wait_for(close_started.wait(), timeout=1)

        assert scope_id not in manager._scope_handlers
        assert handler_name not in manager._handlers
        assert not close_task.done()
        close_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await close_task
        assert response.session_id in agent._sessions

        allow_close.set()
        await manager._wait_for_handler_cleanups()
        assert close_finished.is_set()
        await agent.close_session(session_id=response.session_id)
        assert response.session_id not in agent._sessions
    finally:
        allow_teardown.set()
        allow_close.set()
        await manager.shutdown_all()


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


@pytest.mark.parametrize("method", ["load_session", "resume_session"])
async def test_acp_workspace_handoff_keeps_old_mcp_until_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    workspace = _FakeWorkspace()
    replacement = _FakeWorkspace()
    directory = str(tmp_path / "replacement")
    owner = workspace

    @asynccontextmanager
    async def configure_session(session_id, parameters):
        nonlocal owner
        candidate = (
            replacement
            if parameters.config.workspace_dir == directory
            else workspace
        )
        yield candidate
        owner = candidate

    monkeypatch.setattr(workspace, "configure_session", configure_session)
    monkeypatch.setattr(workspace, "session_workspace", lambda _: owner)
    agent = _TestACPAgent(workspace)
    agent.on_connect(_FakeConn())
    monkeypatch.setattr(agent, "_advertise_commands", AsyncMock())
    await agent.load_session(
        cwd=str(tmp_path),
        session_id="session-1",
        mcp_servers=[_stdio_server()],
    )
    scope = acp_mcp_scope_id("session-1")
    previous = agent._sessions["session-1"]
    restore = getattr(agent, method)
    metadata = {ACP_CONFIG_META_KEY: {"workspace_dir": directory}}
    replacement.driver_manager.fail_replacement = True

    with pytest.raises(RuntimeError, match="registration failed"):
        await restore(
            cwd=str(tmp_path),
            session_id="session-1",
            mcp_servers=[_stdio_server()],
            **metadata,
        )

    assert agent._sessions["session-1"] is previous
    assert owner is workspace
    assert workspace.driver_manager.removals == []

    replacement.driver_manager.fail_replacement = False
    prepared, publish = asyncio.Event(), asyncio.Event()
    prompt_entered, announce_entered = asyncio.Event(), asyncio.Event()
    replace = replacement.driver_manager.replace_transient_drivers
    announced = []

    async def prepare_replacement(scope_id, cards):
        await replace(scope_id, cards)
        prepared.set()
        await publish.wait()

    async def bind_owner(session_id, parameters):
        async with configure_session(session_id, parameters) as candidate:
            return candidate

    async def stream_query(request):
        parameters = current_runtime_parameters.get()
        assert parameters is not None
        selected = await bind_owner(request.session_id, parameters)
        async for event in _FakeWorkspace.stream_query(selected, request):
            yield event

    def available_commands(selected):
        announced.append(selected)
        return []

    async def submit_prompt():
        prompt_entered.set()
        return await agent.prompt([text_block("continue")], "session-1")

    async def announce():
        announce_entered.set()
        await QwenPawACPAgent._advertise_commands(agent, "session-1")

    monkeypatch.setattr(
        replacement.driver_manager,
        "replace_transient_drivers",
        prepare_replacement,
    )
    monkeypatch.setattr(workspace, "for_session", bind_owner)
    monkeypatch.setattr(workspace, "stream_query", stream_query)
    monkeypatch.setattr(agent, "_build_available_commands", available_commands)

    handoff = asyncio.create_task(
        restore(
            cwd=str(tmp_path),
            session_id="session-1",
            mcp_servers=[_stdio_server()],
            **metadata,
        ),
    )
    try:
        await asyncio.wait_for(prepared.wait(), timeout=2)
        prompt = asyncio.create_task(submit_prompt())
        advertisement = asyncio.create_task(announce())
        await asyncio.wait_for(
            asyncio.gather(prompt_entered.wait(), announce_entered.wait()),
            timeout=2,
        )
    finally:
        publish.set()
    _, response, _ = await asyncio.wait_for(
        asyncio.gather(handoff, prompt, advertisement),
        timeout=2,
    )
    assert response.stop_reason == "end_turn"
    assert not workspace.requests and len(replacement.requests) == 1
    assert announced == [replacement]
    assert agent._sessions["session-1"].config.workspace_dir == directory
    assert owner is replacement
    assert workspace.driver_manager.removals == [scope]
    assert replacement.driver_manager.removals == []

    await agent.close_session("session-1")
    assert workspace.driver_manager.removals == [scope]
    assert replacement.driver_manager.removals == [scope]


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
