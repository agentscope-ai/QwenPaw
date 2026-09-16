# -*- coding: utf-8 -*-
"""旧 Agent 记忆迁移为公共作用域的非破坏性契约。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from qwenpaw.migrations.memory_scope_migration import (
    MEMORY_SCOPE_MANIFEST,
    migrate_legacy_memory_scopes,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _agent_config(*, needs_reindex: bool = False):
    return SimpleNamespace(
        running=SimpleNamespace(
            reme_light_memory_config=SimpleNamespace(
                needs_reindex=needs_reindex,
            ),
        ),
    )


def test_legacy_markdown_is_registered_in_place_without_content_change(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspaces" / "agent-a"
    memory_file = workspace / "MEMORY.md"
    daily_file = workspace / "daily" / "2026-08-24.md"
    memory_file.parent.mkdir(parents=True)
    daily_file.parent.mkdir(parents=True)
    memory_file.write_text("# legacy memory\n原文不可改写。\n", encoding="utf-8")
    daily_file.write_text("旧日报正文\n", encoding="utf-8")
    before = {_path: _sha256(_path) for _path in (memory_file, daily_file)}
    config = _agent_config()
    saved = []

    result = migrate_legacy_memory_scopes(
        working_dir=tmp_path,
        agent_workspaces={"agent-a": workspace},
        load_agent=lambda _agent_id: config,
        save_agent=lambda agent_id, agent_config: saved.append(
            (agent_id, agent_config)
        ),
    )

    assert result.registered_agents == 1
    assert result.registered_files == 2
    assert result.changed is True
    assert {_path: _sha256(_path) for _path in before} == before
    assert config.running.reme_light_memory_config.needs_reindex is True
    assert [item[0] for item in saved] == ["agent-a"]

    manifest = json.loads(
        (tmp_path / MEMORY_SCOPE_MANIFEST).read_text(encoding="utf-8")
    )
    entry = manifest["agents"]["agent-a"]
    assert entry["scope"] == "public"
    assert entry["index_state"] == "needs_reindex"
    assert [item["path"] for item in entry["files"]] == [
        "MEMORY.md",
        "daily/2026-08-24.md",
    ]
    assert {item["sha256"] for item in entry["files"]} == set(before.values())
    assert all("user_id" not in item for item in entry["files"])


def test_repeated_migration_does_not_duplicate_registration_or_resave(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspaces" / "agent-a"
    workspace.mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("stable\n", encoding="utf-8")
    config = _agent_config()
    saved = []
    arguments = {
        "working_dir": tmp_path,
        "agent_workspaces": {"agent-a": workspace},
        "load_agent": lambda _agent_id: config,
        "save_agent": lambda agent_id, agent_config: saved.append(
            (agent_id, agent_config)
        ),
    }

    first = migrate_legacy_memory_scopes(**arguments)
    manifest_before = (tmp_path / MEMORY_SCOPE_MANIFEST).read_bytes()
    second = migrate_legacy_memory_scopes(**arguments)

    assert first.changed is True
    assert second.changed is False
    assert second.registered_agents == 0
    assert second.registered_files == 0
    assert len(saved) == 1
    assert (tmp_path / MEMORY_SCOPE_MANIFEST).read_bytes() == manifest_before


def test_scan_ignores_private_workspaces_and_index_artifacts(tmp_path) -> None:
    workspace = tmp_path / "workspaces" / "agent-a"
    workspace.mkdir(parents=True)
    (workspace / "MEMORY.md").write_text("public\n", encoding="utf-8")
    (workspace / "memory" / "index").mkdir(parents=True)
    (workspace / "memory" / "index" / "vectors.bin").write_bytes(b"index")
    private_file = (
        tmp_path / "user_workspaces" / "user-a" / "agent-a" / "MEMORY.md"
    )
    private_file.parent.mkdir(parents=True)
    private_file.write_text("private\n", encoding="utf-8")
    config = _agent_config()

    migrate_legacy_memory_scopes(
        working_dir=tmp_path,
        agent_workspaces={"agent-a": workspace},
        load_agent=lambda _agent_id: config,
        save_agent=lambda *_args: None,
    )

    manifest = json.loads(
        (tmp_path / MEMORY_SCOPE_MANIFEST).read_text(encoding="utf-8")
    )
    registered = manifest["agents"]["agent-a"]["files"]
    assert [item["path"] for item in registered] == ["MEMORY.md"]
    assert "private" not in json.dumps(manifest, ensure_ascii=False)
