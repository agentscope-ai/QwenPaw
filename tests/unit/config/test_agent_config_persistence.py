# -*- coding: utf-8 -*-
"""Tests for robust agent config caching and runtime state migration."""

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
from qwenpaw.exceptions import ConfigurationException
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


def test_last_dispatch_migration_is_atomic_and_keeps_legacy_field(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Legacy state is published without breaking downgrade compatibility."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    writes: list[Path] = []
    original_write = config_module.write_json_atomic

    def tracked_write(path, payload, **kwargs):
        writes.append(Path(path))
        original_write(path, payload, **kwargs)

    monkeypatch.setattr(config_module, "write_json_atomic", tracked_write)

    loaded = load_agent_config("agent")

    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    state_path = agent_path.parent / "state" / "last_dispatch.json"
    assert loaded.name == "Old"
    assert persisted["last_dispatch"]["channel"] == "telegram"
    assert agent_path not in writes
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }


def test_last_dispatch_migration_preserves_newer_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An existing valid state file wins over legacy agent.json data."""
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
    assert dispatch is not None
    assert dispatch.channel == "current"
    assert dispatch.user_id == "new-user"
    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    assert persisted["last_dispatch"]["channel"] == "legacy"


def test_read_last_dispatch_falls_back_to_legacy_field(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Legacy state remains readable when the new state file is absent."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")

    dispatch = read_last_dispatch("agent")

    assert dispatch is not None
    assert dispatch.channel == "telegram"


def test_agent_save_preserves_legacy_last_dispatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Unrelated config saves keep the downgrade compatibility field."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = load_agent_config("agent")
    loaded.description = "updated"

    config_module.save_agent_config("agent", loaded)

    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    assert persisted["last_dispatch"]["channel"] == "telegram"


def test_last_dispatch_migration_failure_keeps_legacy_field(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A failed state publication leaves legacy data available for retry."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    raw["last_dispatch"] = {
        "channel": "telegram",
        "user_id": "user-1",
        "session_id": "session-1",
    }
    agent_path.write_text(json.dumps(raw), encoding="utf-8")

    def fail_state_write(*_args, **_kwargs):
        raise OSError("state unavailable")

    monkeypatch.setattr(
        config_utils,
        "write_json_atomic",
        fail_state_write,
    )

    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    with pytest.raises(OSError, match="state unavailable"):
        load_agent_config("agent")

    assert persisted["last_dispatch"]["channel"] == "telegram"


def test_last_dispatch_update_does_not_rewrite_agent_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Runtime dispatch updates leave business configuration untouched."""
    agent_path, _raw = _prepare_agent(tmp_path, monkeypatch)
    original_content = agent_path.read_bytes()
    original_stat = agent_path.stat()

    update_last_dispatch(
        "telegram",
        "user-1",
        "session-1",
        agent_id="agent",
    )

    assert agent_path.read_bytes() == original_content
    assert agent_path.stat().st_mtime_ns == original_stat.st_mtime_ns
    dispatch = read_last_dispatch("agent")
    assert dispatch is not None
    assert dispatch.channel == "telegram"


def test_acl_migration_keeps_legacy_list_when_state_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """ACL source data remains available when its new store cannot persist."""
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


def test_acl_migration_replaces_long_agent_json_with_complete_document(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A shorter migrated config has no trailing bytes from the old file."""
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


def test_cache_detects_same_mtime_atomic_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An inode change invalidates cache even when size and mtime match."""
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
    assert agent_path.stat().st_ino != old_stat.st_ino
    assert load_agent_config("agent").name == "New"


def test_cache_periodically_verifies_content_when_metadata_is_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Digest verification bounds staleness when all metadata is unchanged."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    assert load_agent_config("agent").name == "Old"
    entry = config_utils._agent_config_cache["agent"]
    monkeypatch.setattr(
        config_module,
        "_agent_config_fingerprint",
        lambda _path: entry.fingerprint,
    )
    monkeypatch.setattr(
        config_module.time,
        "monotonic",
        lambda: entry.verified_at + 6.0,
    )
    raw["name"] = "New"
    agent_path.write_text(json.dumps(raw), encoding="utf-8")

    assert load_agent_config("agent").name == "New"


def test_cached_config_is_returned_as_a_deep_copy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Mutating one loaded model cannot poison the shared cache entry."""
    _agent_path, _raw = _prepare_agent(tmp_path, monkeypatch)
    first = load_agent_config("agent")
    first.name = "Mutated"

    second = load_agent_config("agent")

    assert second.name == "Old"


def test_fresh_cache_hit_does_not_read_file_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Normal cache hits use metadata only and avoid full OSSFS reads."""
    _agent_path, _raw = _prepare_agent(tmp_path, monkeypatch)
    assert load_agent_config("agent").name == "Old"

    def fail_snapshot_read(_path):
        raise AssertionError("unexpected content read")

    monkeypatch.setattr(
        config_module,
        "_read_agent_config_snapshot",
        fail_snapshot_read,
    )

    assert load_agent_config("agent").name == "Old"


def test_stale_loaded_config_cannot_overwrite_external_update(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Saving a stale model fails instead of replacing a newer disk version."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    stale = load_agent_config("agent")
    raw["name"] = "New"
    write_json_atomic(agent_path, raw)
    stale.description = "stale update"

    with pytest.raises(ConfigurationException, match="changed on disk"):
        config_module.save_agent_config("agent", stale)

    assert json.loads(agent_path.read_text(encoding="utf-8"))["name"] == "New"


def test_loaded_config_cannot_recreate_externally_deleted_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A loaded model cannot silently replace an externally deleted file."""
    agent_path, _raw = _prepare_agent(tmp_path, monkeypatch)
    stale = load_agent_config("agent")
    agent_path.unlink()

    with pytest.raises(ConfigurationException, match="changed on disk"):
        config_module.save_agent_config("agent", stale)

    assert not agent_path.exists()


def test_external_update_after_save_is_not_adopted_by_stale_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A post-write replacement cannot become a stale model's version."""
    agent_path, raw = _prepare_agent(tmp_path, monkeypatch)
    loaded = load_agent_config("agent")
    loaded.description = "local update"
    original_write = config_module.write_json_atomic

    def replace_after_write(path, payload, **kwargs):
        original_write(path, payload, **kwargs)
        external = dict(raw)
        external["name"] = "External"
        original_write(path, external, **kwargs)

    monkeypatch.setattr(
        config_module,
        "write_json_atomic",
        replace_after_write,
    )

    with pytest.raises(ConfigurationException, match="changed while saving"):
        config_module.save_agent_config("agent", loaded)

    persisted = json.loads(agent_path.read_text(encoding="utf-8"))
    assert persisted["name"] == "External"
