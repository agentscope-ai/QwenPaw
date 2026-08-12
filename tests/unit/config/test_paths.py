# -*- coding: utf-8 -*-
"""Tests for configuration-owned path resolution."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.exceptions import ConfigurationException
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
    resolve_agent_workspace_roots,
    resolve_workspace_child_path,
    resolve_workspace_identity,
    sanitize_agent_path_segment,
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


def test_unregistered_legacy_workspace_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Do not turn an arbitrary legacy path into a new trusted root."""
    _set_working_dir(monkeypatch, tmp_path / "qwenpaw")

    with pytest.raises(ValueError, match="not registered"):
        derive_legacy_workspace_identity(
            tmp_path / "external" / "analyst",
            "analyst",
        )


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


def test_old_root_mapping_is_removed_during_migration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Discard legacy arbitrary root targets instead of resolving them."""
    _set_working_dir(monkeypatch, tmp_path / "qwenpaw")
    data = {"agent_workspace_roots": {"unsafe": str(tmp_path / "outside")}}

    assert migrate_legacy_agent_workspace_profiles(data) is True
    assert "agent_workspace_roots" not in data


def test_load_config_rejects_unregistered_legacy_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Fail closed without replacing the user's root configuration."""
    working_dir = tmp_path / "qwenpaw"
    _set_working_dir(monkeypatch, working_dir)
    config_path = tmp_path / "config.json"
    raw = {
        "agents": {
            "profiles": {
                "analyst": {
                    "id": "analyst",
                    "workspace_dir": str(tmp_path / "outside" / "analyst"),
                },
            },
        },
        "plugins": {"preserved": {"enabled": True}},
    }
    original = json.dumps(raw)
    config_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(config_utils, "_config_cache", None)
    monkeypatch.setattr(config_utils, "_config_mtime", None)

    with pytest.raises(ConfigurationException, match="not registered"):
        config_utils.load_config(config_path)

    assert config_path.read_text(encoding="utf-8") == original
    assert len(list(tmp_path.glob("config.*.bak"))) == 1


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
