# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from qwenpaw.plugins.harnesses import HarnessHistoryItem, HarnessHistoryKind
from qwenpaw.portability.providers.codex_rollout_reader import (
    CodexRolloutReader,
)
from qwenpaw.portability.providers.codex import (
    CodexMigrationProvider,
    _merge_threads,
)


class _CodexAdapter:
    async def status(self):
        return SimpleNamespace(
            installed=True,
            error="",
            runtime_path="/usr/local/bin/codex",
        )

    async def list_external_threads(self, *, limit, archived=False):
        assert limit in (1, 10)
        return [
            {
                "id": "archived-thread" if archived else "thread-1",
                "archived": archived,
                "preview": "Existing task",
                "cwd": "/project",
                "createdAt": 1_700_000_000 + int(archived),
            },
        ]

    async def read_external_thread(self, thread_id):
        assert thread_id in {"thread-1", "archived-thread"}
        return [
            HarnessHistoryItem(
                kind=HarnessHistoryKind.USER,
                text="Keep working",
                item_id="item-1",
            ),
        ]

    async def external_skill_records(self):
        return []

    async def external_mcp_records(self):
        return [
            {
                "name": "filesystem",
                "enabled": True,
                "auth_status": "unsupported",
                "transport": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["server-filesystem"],
                    "env_vars": ["FILESYSTEM_TOKEN"],
                },
            },
        ]


class _BackendRuntime:
    def __init__(self, adapter) -> None:
        self._adapter = adapter
        self.entered = self.closed = False

    async def call(self, provider_id, operation, settings):
        assert provider_id == "codex"
        assert operation == "status"
        assert settings == {}
        return await self._adapter.status()

    @asynccontextmanager
    async def archive(self, provider_id, settings):
        assert provider_id == "codex"
        assert settings == {}
        self.entered = True
        try:
            yield self._adapter
        finally:
            self.closed = True


def _workspace(tmp_path: Path):
    config = SimpleNamespace(backend="qwenpaw", backend_settings={})
    return SimpleNamespace(
        agent_id="test-agent",
        workspace_dir=tmp_path,
        config=config,
        backend_runtime=_BackendRuntime(_CodexAdapter()),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1, 10])
async def test_codex_provider_reuses_runtime_and_normalizes_inventory(
    tmp_path: Path,
    limit: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)

    async def load(agent_id):
        assert agent_id == "test-agent"
        return workspace.config

    monkeypatch.setattr(
        "qwenpaw.portability.providers.codex.load_agent_config_async",
        load,
    )
    inventory = await CodexMigrationProvider(
        workspace,
        rollout_reader=CodexRolloutReader(tmp_path / ".codex"),
    ).inventory(limit=limit)

    assert (
        workspace.backend_runtime.entered and workspace.backend_runtime.closed
    )
    assert inventory.detected is True
    assert inventory.locator == "/usr/local/bin/codex"
    assert [
        (item.source_id, item.archived) for item in inventory.sessions
    ] == [
        ("archived-thread", True),
        ("thread-1", False),
    ][
        :limit
    ]
    assert inventory.sessions[0].history[0].text == "Keep working"
    assert inventory.mcp_servers[0].command == "npx"
    assert inventory.mcp_servers[0].env == {
        "FILESYSTEM_TOKEN": "${FILESYSTEM_TOKEN}",
    }
    assert inventory.mcp_servers[0].metadata["source_runtime_bound"] is False
    assert any("disabled QwenPaw" in item for item in inventory.warnings)


def test_codex_online_archive_state_overrides_offline_copies() -> None:
    offline = [{"id": "thread-1", "archived": None}]
    online = [{"threadId": "thread-1", "archived": False}]
    assert _merge_threads(online, offline, 10)[0]["archived"] is False

    # A move between the two API queries is ambiguous too.
    online.append({"threadId": "thread-1", "archived": True})
    merged = _merge_threads(online, offline, 10)
    assert len(merged) == 1
    assert merged[0]["id"] == "thread-1"
    assert merged[0]["archived"] is None


@pytest.mark.parametrize(
    "kind,text,readable",
    [
        (HarnessHistoryKind.USER, "Recovered question", True),
        (HarnessHistoryKind.MESSAGE, "Recovered answer", True),
        (HarnessHistoryKind.MESSAGE, "   ", False),
        (HarnessHistoryKind.TOOL_CALL, "Only tool activity", False),
    ],
)
@pytest.mark.asyncio
async def test_codex_recovers_dialogue_before_accepting_tool_only_history(
    tmp_path: Path,
    kind: HarnessHistoryKind,
    text: str,
    readable: bool,
) -> None:
    reader = CodexRolloutReader(tmp_path / ".codex")
    provider = CodexMigrationProvider(_workspace(tmp_path), reader)
    recovered_history = [HarnessHistoryItem(kind=kind, text=text)]
    reader.read_thread = Mock(return_value=recovered_history)
    adapter = SimpleNamespace(
        read_external_thread=AsyncMock(
            return_value=[
                HarnessHistoryItem(kind=HarnessHistoryKind.TOOL_CALL),
            ],
        ),
    )

    progress = AsyncMock()
    # pylint: disable-next=protected-access
    sessions, warnings, recovered = await provider._read_sessions(
        adapter,
        reader,
        [{"id": "thread-1"}],
        installed=True,
        progress=progress,
    )

    reader.read_thread.assert_called_once_with("thread-1")
    assert bool(sessions) is readable
    assert recovered == int(readable)
    if readable:
        assert sessions[0].history == recovered_history
        assert warnings == []
        if kind == HarnessHistoryKind.USER:
            assert sessions[0].title == text
    else:
        assert "no readable user or assistant messages" in warnings[0]
        progress.assert_any_await(warnings[0])
