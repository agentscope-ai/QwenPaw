# -*- coding: utf-8 -*-
"""Tests for configuration-owned path resolution."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.config import paths
from qwenpaw.config import utils as config_utils
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    save_agent_config,
)
from qwenpaw.config.paths import (
    DEFAULT_AGENT_WORKSPACE_ROOT_ID,
    derive_legacy_workspace_identity,
    migrate_legacy_agent_workspace_profiles,
    register_agent_workspace_root,
    resolve_agent_workspace_roots,
    resolve_workspace_child_path,
    resolve_workspace_identity,
    sanitize_agent_path_segment,
    unregister_agent_workspace_root,
)


def _set_working_dir(monkeypatch, working_dir: Path) -> None:
    """Use one isolated server-managed workspace registry."""
    monkeypatch.setattr(paths, "WORKING_DIR", working_dir)


def test_default_workspace_identity_uses_working_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Resolve the default root below the configured working directory."""
    working_dir = tmp_path / "qwenpaw"
    _set_working_dir(monkeypatch, working_dir)

    result = resolve_workspace_identity("default", "agent")

    assert result == (working_dir / "workspaces" / "agent").resolve()


def test_registry_enumerates_only_server_owned_roots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Expose ordinary registry directories by opaque root ID."""
    working_dir = tmp_path / "qwenpaw"
    trusted = working_dir / "workspace-roots" / "trusted"
    trusted.mkdir(parents=True)
    (working_dir / "workspace-roots" / "ignored.txt").write_text(
        "not a root",
        encoding="utf-8",
    )
    _set_working_dir(monkeypatch, working_dir)

    roots = resolve_agent_workspace_roots()

    assert set(roots) == {DEFAULT_AGENT_WORKSPACE_ROOT_ID, "trusted"}
    assert roots["trusted"] == trusted.resolve()


def test_registry_accepts_symlink_alias(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Resolve a registered symlink alias to its external directory."""
    working_dir = tmp_path / "qwenpaw"
    target = tmp_path / "external"
    target.mkdir()
    registry = working_dir / "workspace-roots"
    registry.mkdir(parents=True)
    try:
        (registry / "external").symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks are unavailable: {exc}")
    _set_working_dir(monkeypatch, working_dir)

    assert (
        resolve_workspace_identity("external", "agent")
        == (target / "agent").resolve()
    )


def test_persistent_registry_resolves_external_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Register external roots without requiring links or junctions."""
    working_dir = tmp_path / "qwenpaw"
    target = tmp_path / "external"
    target.mkdir()
    _set_working_dir(monkeypatch, working_dir)

    registered = register_agent_workspace_root("external", target)

    assert registered == target.resolve()
    assert resolve_agent_workspace_roots()["external"] == target.resolve()
    registry = json.loads(
        (working_dir / "workspace-roots" / "registry.json").read_text(
            encoding="utf-8",
        ),
    )
    assert registry["roots"]["external"] == str(target.resolve())


def test_persistent_registry_resolves_relative_to_working_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Match the desktop resolver for a manually stored relative root."""
    working_dir = tmp_path / "qwenpaw"
    target = working_dir / "external"
    target.mkdir(parents=True)
    registry_file = working_dir / "workspace-roots" / "registry.json"
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        json.dumps({"version": 1, "roots": {"external": "external"}}),
        encoding="utf-8",
    )
    _set_working_dir(monkeypatch, working_dir)

    assert resolve_agent_workspace_roots()["external"] == target.resolve()


def test_unregister_root_preserves_external_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Removing a root registration must never remove user files."""
    working_dir = tmp_path / "qwenpaw"
    target = tmp_path / "external"
    target.mkdir()
    _set_working_dir(monkeypatch, working_dir)
    register_agent_workspace_root("external", target)

    assert unregister_agent_workspace_root("external") is True
    assert unregister_agent_workspace_root("external") is False
    assert target.is_dir()
    assert "external" not in resolve_agent_workspace_roots()


def test_registry_mutation_rejects_corrupt_registry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Never overwrite unknown registrations after a parse failure."""
    working_dir = tmp_path / "qwenpaw"
    external = tmp_path / "external"
    external.mkdir()
    registry_file = working_dir / "workspace-roots" / "registry.json"
    registry_file.parent.mkdir(parents=True)
    registry_file.write_text("{broken", encoding="utf-8")
    _set_working_dir(monkeypatch, working_dir)

    with pytest.raises(ValueError, match="unreadable"):
        register_agent_workspace_root("external", external)

    assert registry_file.read_text(encoding="utf-8") == "{broken"


def test_registry_mutation_rejects_invalid_entries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Preserve parseable registries whose entry schema is invalid."""
    working_dir = tmp_path / "qwenpaw"
    external = tmp_path / "external"
    external.mkdir()
    registry_file = working_dir / "workspace-roots" / "registry.json"
    registry_file.parent.mkdir(parents=True)
    original = json.dumps({"version": 1, "roots": {"bad": 123}})
    registry_file.write_text(original, encoding="utf-8")
    _set_working_dir(monkeypatch, working_dir)

    with pytest.raises(ValueError, match="invalid"):
        register_agent_workspace_root("external", external)

    assert registry_file.read_text(encoding="utf-8") == original


def test_persistent_registry_cannot_override_directory_alias(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Keep Python and desktop precedence identical for duplicate IDs."""
    working_dir = tmp_path / "qwenpaw"
    alias = working_dir / "workspace-roots" / "external"
    other = tmp_path / "other"
    alias.mkdir(parents=True)
    other.mkdir()
    _set_working_dir(monkeypatch, working_dir)

    with pytest.raises(ValueError, match="already registered"):
        register_agent_workspace_root("external", other)

    assert resolve_agent_workspace_roots()["external"] == alias.resolve()

    with pytest.raises(ValueError, match="managed by directory alias"):
        unregister_agent_workspace_root("external")


@pytest.mark.parametrize(
    "agent_id",
    ["", ".", "..", "../escape", "nested/agent", "nested\\agent"],
)
def test_agent_path_segment_rejects_unsafe_values(agent_id: str) -> None:
    """Reject every agent ID that can affect path structure."""
    with pytest.raises(ValueError, match="valid path segment"):
        sanitize_agent_path_segment(agent_id)


def test_agent_path_segment_accepts_historical_builtin_id() -> None:
    """Keep dots used by historical built-in agent identifiers."""
    agent_id = "QwenPaw_QA_Agent_0.2"

    assert sanitize_agent_path_segment(agent_id) == agent_id


def test_workspace_identity_rejects_unknown_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject a root ID that was not registered by the server."""
    _set_working_dir(monkeypatch, tmp_path / "qwenpaw")

    with pytest.raises(ValueError, match="is not registered"):
        resolve_workspace_identity("missing", "analyst")


def test_workspace_identity_rejects_traversal_name(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject traversal even when the selected root is trusted."""
    _set_working_dir(monkeypatch, tmp_path / "qwenpaw")

    with pytest.raises(ValueError, match="valid path segment"):
        resolve_workspace_identity("default", "../escape")


def test_workspace_identity_rejects_symlink_escape(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject a workspace symlink that resolves outside its root."""
    working_dir = tmp_path / "qwenpaw"
    root = working_dir / "workspaces"
    outside = tmp_path / "outside"
    root.mkdir(parents=True)
    outside.mkdir()
    try:
        (root / "analyst").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks are unavailable: {exc}")
    _set_working_dir(monkeypatch, working_dir)

    with pytest.raises(ValueError, match="escapes its configured root"):
        resolve_workspace_identity("default", "analyst")


def test_workspace_child_path_rejects_nested_input(tmp_path: Path) -> None:
    """Only fixed file names may be joined to a trusted workspace."""
    with pytest.raises(ValueError, match="Invalid workspace file name"):
        resolve_workspace_child_path(tmp_path, "nested/agent.json")


def test_unregistered_legacy_workspace_is_registered_locally(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Preserve an existing custom workspace during an upgrade."""
    working_dir = tmp_path / "qwenpaw"
    workspace = tmp_path / "external" / "analyst"
    workspace.mkdir(parents=True)
    _set_working_dir(monkeypatch, working_dir)

    root_id, name, resolved = derive_legacy_workspace_identity(
        workspace,
        "analyst",
    )

    assert root_id.startswith("legacy-")
    assert name == "analyst"
    assert resolved == workspace.resolve()
    assert resolve_agent_workspace_roots()[root_id] == workspace.parent


def test_legacy_default_workspace_migrates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Migrate a legacy default path to the fixed default root."""
    working_dir = tmp_path / "qwenpaw"
    (working_dir / "workspaces" / "analyst").mkdir(parents=True)
    _set_working_dir(monkeypatch, working_dir)
    data = {
        "agents": {
            "profiles": {
                "analyst": {
                    "id": "analyst",
                    "workspace_dir": str(
                        working_dir / "workspaces" / "analyst",
                    ),
                },
            },
        },
    }

    assert migrate_legacy_agent_workspace_profiles(data) is True
    profile = data["agents"]["profiles"]["analyst"]
    assert profile["workspace_root_id"] == "default"
    assert profile["workspace_name"] == "analyst"


def test_complete_workspace_identity_does_not_fallback_to_legacy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Treat a missing persisted root as an error, not a new migration."""
    working_dir = tmp_path / "qwenpaw"
    legacy_workspace = tmp_path / "external" / "analyst"
    legacy_workspace.mkdir(parents=True)
    _set_working_dir(monkeypatch, working_dir)
    data = {
        "agents": {
            "profiles": {
                "analyst": {
                    "id": "analyst",
                    "workspace_dir": str(legacy_workspace),
                    "workspace_root_id": "missing",
                    "workspace_name": "analyst",
                },
            },
        },
    }

    with pytest.raises(ValueError, match="is not registered"):
        migrate_legacy_agent_workspace_profiles(data)

    assert not (working_dir / "workspace-roots" / "registry.json").exists()


def test_legacy_registry_alias_migrates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Migrate a legacy path that points at a registered alias target."""
    working_dir = tmp_path / "qwenpaw"
    target = tmp_path / "external"
    target.mkdir()
    registry = working_dir / "workspace-roots"
    registry.mkdir(parents=True)
    try:
        (registry / "trusted").symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks are unavailable: {exc}")
    _set_working_dir(monkeypatch, working_dir)

    root_id, name, resolved = derive_legacy_workspace_identity(
        target / "analyst",
        "analyst",
    )

    assert (root_id, name) == ("trusted", "analyst")
    assert resolved == (target / "analyst").resolve()


def test_old_root_mapping_is_persisted_during_migration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Move a legacy local root mapping into the persistent registry."""
    working_dir = tmp_path / "qwenpaw"
    outside = tmp_path / "outside"
    outside.mkdir()
    _set_working_dir(monkeypatch, working_dir)
    data = {"agent_workspace_roots": {"external": str(outside)}}

    assert migrate_legacy_agent_workspace_profiles(data) is True
    assert "agent_workspace_roots" not in data
    assert resolve_agent_workspace_roots()["external"] == outside.resolve()


def test_old_root_mapping_accepts_matching_directory_alias(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Accept mixed-version state when both registrations agree."""
    working_dir = tmp_path / "qwenpaw"
    alias = working_dir / "workspace-roots" / "external"
    alias.mkdir(parents=True)
    _set_working_dir(monkeypatch, working_dir)
    data = {"agent_workspace_roots": {"external": str(alias)}}

    assert migrate_legacy_agent_workspace_profiles(data) is True
    assert "agent_workspace_roots" not in data
    assert resolve_agent_workspace_roots()["external"] == alias.resolve()


def test_load_config_migrates_unregistered_legacy_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Load and persist a legacy external workspace without links."""
    working_dir = tmp_path / "qwenpaw"
    workspace = tmp_path / "outside" / "analyst"
    workspace.mkdir(parents=True)
    _set_working_dir(monkeypatch, working_dir)
    config_path = tmp_path / "config.json"
    raw = {
        "agents": {
            "profiles": {
                "analyst": {
                    "id": "analyst",
                    "workspace_dir": str(workspace),
                },
            },
        },
        "plugins": {"preserved": {"enabled": True}},
    }
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(config_utils, "_config_cache", None)
    monkeypatch.setattr(config_utils, "_config_mtime", None)

    config = config_utils.load_config(config_path)

    profile = config.agents.profiles["analyst"]
    assert profile.workspace_dir == str(workspace.resolve())
    assert profile.workspace_root_id.startswith("legacy-")
    assert len(list(tmp_path.glob("config.*.workspace-migrate.bak"))) == 1


def test_save_agent_config_uses_registered_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Never derive the agent.json sink from its payload workspace path."""
    working_dir = tmp_path / "qwenpaw"
    trusted_root = working_dir / "workspace-roots" / "trusted"
    trusted_workspace = trusted_root / "analyst"
    trusted_workspace.mkdir(parents=True)
    _set_working_dir(monkeypatch, working_dir)
    config = SimpleNamespace(
        agents=AgentsConfig(
            profiles={
                "analyst": AgentProfileRef(
                    id="analyst",
                    workspace_dir=str(trusted_workspace),
                    workspace_root_id="trusted",
                    workspace_name="analyst",
                ),
            },
            agent_order=["analyst"],
        ),
    )
    payload = AgentProfileConfig(
        id="analyst",
        name="Analyst",
        workspace_dir=str(tmp_path / "outside"),
    )
    monkeypatch.setattr(config_utils, "load_config", lambda: config)

    save_agent_config("analyst", payload)

    saved = json.loads(
        (trusted_workspace / "agent.json").read_text(encoding="utf-8"),
    )
    assert saved["workspace_dir"] == str(trusted_workspace.resolve())
    assert not (tmp_path / "outside" / "agent.json").exists()
