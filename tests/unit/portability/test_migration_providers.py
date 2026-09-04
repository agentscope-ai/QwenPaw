# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.harnesses.events import HarnessHistoryItem, HarnessHistoryKind
from qwenpaw.harnesses.codex.rollout_reader import CodexRolloutReader
from qwenpaw.portability.providers.codex import CodexMigrationProvider


class _CodexAdapter:
    async def status(self):
        return SimpleNamespace(
            installed=True,
            error="",
            runtime_path="/usr/local/bin/codex",
        )

    async def list_external_threads(self, *, limit):
        assert limit == 10
        return [
            {
                "id": "thread-1",
                "preview": "Existing task",
                "cwd": "/project",
                "createdAt": 1_700_000_000,
            },
        ]

    async def read_external_thread(self, thread_id):
        assert thread_id == "thread-1"
        return [
            HarnessHistoryItem(
                kind=HarnessHistoryKind.USER,
                text="Keep working",
                item_id="item-1",
            ),
        ]

    async def external_skill_records(self, cwd):
        assert cwd.is_absolute()
        return []

    async def discover_mcp(self, cwd):
        assert cwd.is_absolute()
        return [SimpleNamespace(name="filesystem")]

    async def external_mcp_records(self, cwd):
        assert cwd.is_absolute()
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


class _HarnessRuntime:
    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def adapter(self, provider_id, settings):
        assert provider_id == "codex"
        assert settings == {}
        return self._adapter


class _OfflineCodexAdapter:
    async def status(self):
        return SimpleNamespace(
            installed=False,
            error="codex executable unavailable",
            runtime_path="",
        )


class _UnexpectedHarnessRuntime:
    async def adapter(self, provider_id, settings):
        raise AssertionError("explicit source-home must not use app-server")


def _workspace(tmp_path: Path):
    config = SimpleNamespace(backend="qwenpaw", backend_settings={})
    return SimpleNamespace(
        workspace_dir=tmp_path,
        config=config,
        harness_runtime=_HarnessRuntime(_CodexAdapter()),
    )


@pytest.mark.asyncio
async def test_codex_provider_reuses_runtime_and_normalizes_inventory(
    tmp_path: Path,
) -> None:
    inventory = await CodexMigrationProvider(
        _workspace(tmp_path),
        rollout_reader=CodexRolloutReader(tmp_path / ".codex"),
    ).inventory(limit=10)

    assert inventory.detected is True
    assert inventory.locator == "/usr/local/bin/codex"
    assert inventory.sessions[0].source_id == "thread-1"
    assert inventory.sessions[0].history[0].text == "Keep working"
    assert inventory.mcp_servers[0].command == "npx"
    assert inventory.mcp_servers[0].env == {
        "FILESYSTEM_TOKEN": "${FILESYSTEM_TOKEN}",
    }
    assert inventory.mcp_servers[0].metadata["source_runtime_bound"] is False
    assert any("disabled QwenPaw" in item for item in inventory.warnings)
