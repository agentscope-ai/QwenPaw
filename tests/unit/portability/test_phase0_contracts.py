# -*- coding: utf-8 -*-
"""Behavioral contracts that protect the Pawport refactor baseline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.portability.providers.codex import CodexMigrationProvider
from qwenpaw.portability.providers.locator import resolve_source_location
from qwenpaw.portability.providers.qoder import QoderMigrationProvider

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "portability"


class _UnexpectedHarnessRuntime:
    async def adapter(self, provider_id: str, settings: dict[str, Any]):
        del provider_id, settings
        raise AssertionError("explicit source-home must stay local-only")


def _workspace(tmp_path: Path) -> SimpleNamespace:
    root = tmp_path / "workspace"
    root.mkdir()
    return SimpleNamespace(
        workspace_dir=root,
        config=SimpleNamespace(backend="qwenpaw", backend_settings={}),
        harness_runtime=_UnexpectedHarnessRuntime(),
    )


def _copy_fixture(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    shutil.copytree(_FIXTURES / name, target)
    return target


def _history(item: Any) -> dict[str, str]:
    return {
        "kind": item.kind.value,
        "text": item.text,
    }


def _inventory_contract(inventory: Any) -> dict[str, Any]:
    """Keep only stable, user-visible provider output."""
    return {
        "provider": inventory.provider_id,
        "sessions": sorted(
            (
                {
                    "id": item.source_id,
                    "title": item.title,
                    "cwd": item.cwd,
                    "history": [_history(event) for event in item.history],
                }
                for item in inventory.sessions
            ),
            key=lambda item: item["id"],
        ),
        "ignored_sessions": sorted(inventory.ignored_session_ids),
        "skills": sorted(item.name for item in inventory.skills),
        "mcp": sorted(
            (
                {
                    "id": item.source_id,
                    "name": item.name,
                    "transport": item.transport,
                    "command": item.command,
                    "args": item.args,
                    "url": item.url,
                    "plugin": str(item.metadata.get("source_plugin") or ""),
                }
                for item in inventory.mcp_servers
            ),
            key=lambda item: item["id"],
        ),
        "memory": sorted(
            (
                {
                    "id": item.source_id,
                    "cwd": item.cwd,
                    "files": sorted(
                        file.relative_path.as_posix() for file in item.files
                    ),
                }
                for item in inventory.memory_projects
            ),
            key=lambda item: item["id"],
        ),
        "marketplaces": sorted(
            (
                {
                    "id": item.source_id,
                    "name": item.name,
                    "type": item.source_type,
                }
                for item in inventory.marketplaces
            ),
            key=lambda item: item["id"],
        ),
        "plugins": sorted(
            (
                {
                    "id": item.source_id,
                    "name": item.name,
                    "version": item.version,
                    "adapter": str(item.metadata.get("adapter") or ""),
                }
                for item in inventory.plugins
            ),
            key=lambda item: item["id"],
        ),
        "scheduled_tasks": sorted(
            (
                {
                    "id": item.source_id,
                    "name": item.name,
                    "type": item.schedule_type,
                    "cron": item.cron,
                    "timezone": item.timezone,
                    "enabled_at_source": item.enabled,
                }
                for item in inventory.scheduled_tasks
            ),
            key=lambda item: item["id"],
        ),
    }


def _golden_json(name: str) -> dict[str, Any]:
    path = _FIXTURES / "golden" / name
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_codex_mini_home_matches_golden_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "isolated-home"))
    codex_home = _copy_fixture(tmp_path, "codex-mini")
    inventory = await CodexMigrationProvider(
        _workspace(tmp_path),
        source_location=resolve_source_location(
            "codex",
            source_home=codex_home,
        ),
    ).inventory(limit=20)

    assert _inventory_contract(inventory) == _golden_json(
        "codex-mini-inventory.json",
    )


@pytest.mark.asyncio
async def test_qoder_mini_home_matches_golden_inventory(
    tmp_path: Path,
) -> None:
    qoder_home = _copy_fixture(tmp_path, "qoder-mini")
    user_data = _copy_fixture(tmp_path, "qoder-user-data-mini")
    ledger = qoder_home / "plugins" / "installed_plugins_v2.json"
    ledger.write_text(
        ledger.read_text(encoding="utf-8").replace(
            "__QODER_HOME__",
            str(qoder_home),
        ),
        encoding="utf-8",
    )

    inventory = await QoderMigrationProvider(
        SimpleNamespace(workspace_dir=tmp_path / "workspace"),
        qoder_home=qoder_home,
        qoder_user_data=user_data,
    ).inventory(limit=20)

    assert _inventory_contract(inventory) == _golden_json(
        "qoder-mini-inventory.json",
    )
