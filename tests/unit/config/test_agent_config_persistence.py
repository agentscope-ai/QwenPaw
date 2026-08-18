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


def test_acl_migration_keeps_legacy_field_when_state_write_fails() -> None:
    """ACL source data remains when the destination cannot be persisted."""
    channels = {"telegram": {"allow_from": ["user-1"]}}

    class FailingStore:
        def import_allow_from(self, _channel, _users, _revision):
            raise OSError("ACL state unavailable")

    migrated, pending = _migrate_access_control_fields(
        channels,
        FailingStore(),
        "source",
    )

    assert migrated is False
    assert pending is False
    assert channels["telegram"]["allow_from"] == ["user-1"]


def test_acl_migration_restores_memory_when_state_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A failed migration publication is not visible through the store."""
    from qwenpaw.app.channels.access_control import AccessControlStore

    store = AccessControlStore(tmp_path / "access_control.json")
    store.add_to_whitelist("telegram", "kept-user")
    monkeypatch.setattr(store, "_save", lambda: False)

    with pytest.raises(OSError, match="Failed to persist"):
        store.import_allow_from(
            "telegram",
            {"new-user"},
            "source",
        )

    whitelist = store.get_acl("telegram")["whitelist"]
    assert set(whitelist) == {"kept-user"}


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


def test_cache_preserves_existing_shared_object_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Repeated cache hits return the same mutable config object."""
    _agent_path, _raw = _prepare_agent(tmp_path, monkeypatch)
    first = load_agent_config("agent")
    first.description = "updated"

    second = load_agent_config("agent")

    assert second is first
    assert second.description == "updated"


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


def test_dispatch_migration_retries_with_newer_legacy_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A published old dispatch cannot hide a newer legacy dispatch."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "old",
        "user_id": "old-user",
        "session_id": "old-session",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")

    external = dict(raw)
    external["last_dispatch"] = {
        "channel": "new",
        "user_id": "new-user",
        "session_id": "new-session",
    }
    original_migrate = config_utils._migrate_last_dispatch_state

    def migrate_then_publish_external(*args, **kwargs):
        result = original_migrate(*args, **kwargs)
        write_json_atomic(agent_path, external)
        return result

    monkeypatch.setattr(
        config_utils,
        "_migrate_last_dispatch_state",
        migrate_then_publish_external,
    )

    with pytest.raises(AgentConfigConflictError):
        load_agent_config("agent")

    monkeypatch.setattr(
        config_utils,
        "_migrate_last_dispatch_state",
        original_migrate,
    )
    load_agent_config("agent")

    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    dispatch = read_last_dispatch("agent")
    assert "last_dispatch" not in persisted
    assert dispatch is not None
    assert dispatch.channel == "new"
    assert dispatch.user_id == "new-user"


def test_acl_migration_removes_revoked_users_after_conflict(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Retry removes only users imported by an obsolete source revision."""
    from qwenpaw.app.channels.access_control import get_access_control_store

    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["channels"] = {
        "telegram": {
            "allow_from": ["old-user"],
        },
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    store = get_access_control_store(agent_path.parent)
    store.add_to_whitelist("telegram", "kept-user")
    external = dict(raw)
    external["channels"] = {
        "telegram": {
            "allow_from": ["new-user"],
        },
    }
    original_assert = config_module._assert_agent_config_unchanged
    injected = False

    def publish_then_assert(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            write_json_atomic(agent_path, external)
        return original_assert(*args, **kwargs)

    monkeypatch.setattr(
        config_module,
        "_assert_agent_config_unchanged",
        publish_then_assert,
    )

    with pytest.raises(AgentConfigConflictError):
        load_agent_config("agent")

    monkeypatch.setattr(
        config_module,
        "_assert_agent_config_unchanged",
        original_assert,
    )
    load_agent_config("agent")

    whitelist = store.get_acl("telegram")["whitelist"]
    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    assert set(whitelist) == {"kept-user", "new-user"}
    assert "allow_from" not in persisted["channels"]["telegram"]


def test_acl_migration_rolls_back_when_latest_source_removes_channels(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Retry removes obsolete imports even when channels are now absent."""
    from qwenpaw.app.channels.access_control import get_access_control_store

    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["channels"] = {
        "telegram": {
            "allow_from": ["old-user"],
        },
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    store = get_access_control_store(agent_path.parent)
    store.add_to_whitelist("telegram", "kept-user")
    external = dict(raw)
    external.pop("channels")
    original_assert = config_module._assert_agent_config_unchanged
    injected = False

    def publish_then_assert(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            write_json_atomic(agent_path, external)
        return original_assert(*args, **kwargs)

    monkeypatch.setattr(
        config_module,
        "_assert_agent_config_unchanged",
        publish_then_assert,
    )

    with pytest.raises(AgentConfigConflictError):
        load_agent_config("agent")

    monkeypatch.setattr(
        config_module,
        "_assert_agent_config_unchanged",
        original_assert,
    )
    load_agent_config("agent")

    whitelist = store.get_acl("telegram")["whitelist"]
    assert set(whitelist) == {"kept-user"}


def test_dispatch_migration_recovers_after_source_cleanup_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A prepared dispatch migration resumes after agent write failure."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    original_write = config_module.write_json_atomic

    def fail_agent_write(path, payload, **kwargs):
        if Path(path) == agent_path:
            raise OSError("agent config unavailable")
        return original_write(path, payload, **kwargs)

    monkeypatch.setattr(
        config_module,
        "write_json_atomic",
        fail_agent_write,
    )
    load_agent_config("agent")

    monkeypatch.setattr(
        config_module,
        "write_json_atomic",
        original_write,
    )
    load_agent_config("agent")

    dispatch = read_last_dispatch("agent")
    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    assert dispatch is not None
    assert dispatch.channel == "telegram"
    assert "last_dispatch" not in persisted


def test_dispatch_migration_recovers_after_finalize_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Committed source cleanup recovers pending destination metadata."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    original_finalize = config_utils._finalize_last_dispatch_migration

    def fail_finalize(*_args, **_kwargs):
        raise OSError("finalize unavailable")

    monkeypatch.setattr(
        config_utils,
        "_finalize_last_dispatch_migration",
        fail_finalize,
    )
    load_agent_config("agent")

    monkeypatch.setattr(
        config_utils,
        "_finalize_last_dispatch_migration",
        original_finalize,
    )
    load_agent_config("agent")

    state_path = agent_path.parent / "state" / "last_dispatch.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "_migration" not in state
    assert state["channel"] == "telegram"


def test_dispatch_migration_replaces_invalid_existing_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Recovery inspection does not block replacement of invalid state."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    state_path = agent_path.parent / "state" / "last_dispatch.json"
    write_json_atomic(state_path, ["invalid"])

    load_agent_config("agent")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["channel"] == "telegram"
    assert "_migration" not in state


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
