# -*- coding: utf-8 -*-
"""Tests for agent config persistence on shared filesystems."""

# pylint: disable=protected-access

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

import pytest

from qwenpaw.config import config as config_module
from qwenpaw.config import utils as config_utils
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    Config,
    _migrate_access_control_fields,
    load_agent_config,
)
from qwenpaw.config.utils import read_last_dispatch, update_last_dispatch
from qwenpaw.exceptions import AgentConfigConflictError
from qwenpaw.utils.io_utils import write_json_atomic


def _prepare_agent(
    tmp_path: Path,
    monkeypatch,
    *,
    name: str = "Old",
) -> tuple[Path, dict]:
    """Create one isolated agent config and patch the root config loader."""
    workspace_dir = tmp_path / "workspaces" / "agent"
    workspace_dir.mkdir(parents=True)
    agent_config_path = workspace_dir / "agent.json"
    raw = AgentProfileConfig(id="agent", name=name).model_dump(
        exclude_none=True,
    )
    agent_config_path.write_text(json.dumps(raw), encoding="utf-8")
    root_config = Config(
        agents=AgentsConfig(
            active_agent="agent",
            profiles={
                "agent": AgentProfileRef(
                    id="agent",
                    workspace_dir=str(workspace_dir),
                ),
            },
        ),
    )
    monkeypatch.setattr(config_utils, "load_config", lambda: root_config)
    monkeypatch.setattr(config_utils, "_agent_config_cache", {})
    monkeypatch.setattr(config_utils, "_agent_config_lock", Lock())
    return agent_config_path, raw


def test_acl_migration_replaces_long_agent_json_completely(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A shorter migrated config has no bytes left from the old document."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["channels"] = {
        "telegram": {
            "allow_from": [f"user-{index:04d}" for index in range(200)],
        },
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    old_size = agent_path.stat().st_size

    load_agent_config("agent")

    migrated_content = agent_path.read_text(encoding="utf-8")
    migrated = json.loads(migrated_content)
    assert len(migrated_content.encode("utf-8")) < old_size
    assert "allow_from" not in migrated["channels"]["telegram"]


def test_acl_migration_keeps_legacy_field_when_state_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """ACL source data remains when the destination cannot be persisted."""
    channels = {"telegram": {"allow_from": ["user-1"]}}

    class FailingStore:
        def import_allow_from(self, _channel, _users):
            raise OSError("ACL state unavailable")

    monkeypatch.setattr(
        "qwenpaw.app.channels.access_control.get_access_control_store",
        lambda _workspace_dir: FailingStore(),
    )

    migrated = _migrate_access_control_fields(channels, tmp_path)

    assert migrated is False
    assert channels["telegram"]["allow_from"] == ["user-1"]


def test_cache_detects_same_mtime_atomic_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A same-mtime replacement invalidates the cached model."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    assert load_agent_config("agent").name == "Old"
    old_stat = agent_path.stat()
    raw["name"] = "New"
    replacement = agent_path.with_name("replacement.json")
    replacement.write_text(json.dumps(raw), encoding="utf-8")
    os.utime(
        replacement,
        ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns),
    )
    os.replace(replacement, agent_path)

    assert agent_path.stat().st_mtime_ns == old_stat.st_mtime_ns
    assert load_agent_config("agent").name == "New"


def test_cache_returns_an_isolated_config_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Mutating one loaded config cannot change a later cache hit."""
    _agent_path, _raw = _prepare_agent(tmp_path, monkeypatch)
    first = load_agent_config("agent")
    first.description = "updated"

    second = load_agent_config("agent")

    assert second is not first
    assert second.description == ""


def test_stale_loaded_config_cannot_overwrite_external_update(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A loaded model cannot replace a newer external file version."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    stale = load_agent_config("agent")
    raw["name"] = "New"
    write_json_atomic(agent_path, raw)
    stale.description = "stale update"

    with pytest.raises(AgentConfigConflictError, match="changed on disk"):
        config_module.save_agent_config("agent", stale)

    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    assert persisted["name"] == "New"
    assert "agent" not in config_utils._agent_config_cache


def test_loaded_config_cannot_recreate_externally_deleted_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A loaded model cannot silently recreate an externally deleted file."""
    agent_path, _raw = _prepare_agent(tmp_path, monkeypatch)
    stale = load_agent_config("agent")
    agent_path.unlink()

    with pytest.raises(AgentConfigConflictError, match="changed on disk"):
        config_module.save_agent_config("agent", stale)

    assert not agent_path.exists()
    assert "agent" not in config_utils._agent_config_cache


def test_failed_save_evicts_mutated_cached_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A failed write cannot leave a mutated model in the shared cache."""
    _agent_path, _raw = _prepare_agent(tmp_path, monkeypatch)
    loaded = load_agent_config("agent")
    loaded.description = "not persisted"

    def fail_write(*_args, **_kwargs):
        raise OSError("filesystem unavailable")

    monkeypatch.setattr(config_module, "write_json_atomic", fail_write)

    with pytest.raises(OSError, match="filesystem unavailable"):
        config_module.save_agent_config("agent", loaded)

    assert "agent" not in config_utils._agent_config_cache


def test_successful_save_updates_model_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The same loaded model can be saved repeatedly after local changes."""
    agent_path, _raw = _prepare_agent(tmp_path, monkeypatch)
    loaded = load_agent_config("agent")
    loaded.description = "first"
    config_module.save_agent_config("agent", loaded)
    loaded.description = "second"

    config_module.save_agent_config("agent", loaded)

    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    assert persisted["description"] == "second"


def test_last_dispatch_migration_publishes_state_then_removes_legacy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Legacy runtime state moves out of agent.json after publication."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")

    loaded = load_agent_config("agent")

    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    state_path = agent_path.parent / "state" / "last_dispatch.json"
    assert loaded.last_dispatch is None
    assert "last_dispatch" not in persisted
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }


def test_migration_rejects_an_external_update_before_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Migration never replaces a newer external agent configuration."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")

    external = {**raw, "name": "External"}

    def publish_external_update(*_args, **_kwargs):
        write_json_atomic(agent_path, external)

    monkeypatch.setattr(
        config_utils,
        "_migrate_last_dispatch_state",
        publish_external_update,
    )

    with pytest.raises(AgentConfigConflictError):
        load_agent_config("agent")

    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    assert persisted["name"] == "External"
    assert "agent" not in config_utils._agent_config_cache


def test_migration_checks_source_before_publishing_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A stale source is rejected before migration side effects."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    external = {**raw, "name": "External"}
    original_assert = config_module._assert_agent_config_unchanged

    def publish_then_assert(*args, **kwargs):
        write_json_atomic(agent_path, external)
        return original_assert(*args, **kwargs)

    monkeypatch.setattr(
        config_module,
        "_assert_agent_config_unchanged",
        publish_then_assert,
    )

    with pytest.raises(AgentConfigConflictError):
        load_agent_config("agent")

    state_path = agent_path.parent / "state" / "last_dispatch.json"
    assert not state_path.exists()


def test_last_dispatch_migration_keeps_existing_valid_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An existing valid state file wins over the legacy value."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "legacy",
        "user_id": "old-user",
        "session_id": "old-session",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    state_path = agent_path.parent / "state" / "last_dispatch.json"
    write_json_atomic(
        state_path,
        {
            "channel": "current",
            "user_id": "new-user",
            "session_id": "new-session",
        },
    )

    load_agent_config("agent")

    dispatch = read_last_dispatch("agent")
    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    assert dispatch is not None
    assert dispatch.channel == "current"
    assert "last_dispatch" not in persisted


def test_last_dispatch_migration_failure_keeps_legacy_and_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Failed state publication leaves legacy data and skips the cache."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    attempts = 0

    def fail_state_write(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise OSError("state unavailable")

    monkeypatch.setattr(
        config_utils,
        "write_json_atomic",
        fail_state_write,
    )

    first = load_agent_config("agent")
    second = load_agent_config("agent")

    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    assert first.last_dispatch is not None
    assert second.last_dispatch is not None
    assert persisted["last_dispatch"]["channel"] == "telegram"
    assert attempts == 2
    assert "agent" not in config_utils._agent_config_cache


def test_last_dispatch_update_does_not_rewrite_agent_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Runtime dispatch updates do not touch business configuration."""
    agent_path, _raw = _prepare_agent(tmp_path, monkeypatch)
    original_content = agent_path.read_bytes()
    original_mtime = agent_path.stat().st_mtime_ns

    update_last_dispatch(
        "telegram",
        "user-1",
        "session-1",
        agent_id="agent",
    )

    dispatch = read_last_dispatch("agent")
    assert agent_path.read_bytes() == original_content
    assert agent_path.stat().st_mtime_ns == original_mtime
    assert dispatch is not None
    assert dispatch.channel == "telegram"


def test_read_last_dispatch_does_not_fall_back_to_agent_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Runtime reads use only the dedicated state file."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "legacy",
        "user_id": "old-user",
        "session_id": "old-session",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")

    dispatch = read_last_dispatch("agent")

    assert dispatch is None
