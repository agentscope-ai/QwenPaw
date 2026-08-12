# -*- coding: utf-8 -*-
"""Tests for configuration-owned path resolution."""

import json

from pathlib import Path

import pytest

from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.config import paths
from qwenpaw.config import utils as config_utils
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    Config,
    save_agent_config,
)
from qwenpaw.config.paths import (
    derive_legacy_workspace_identity,
    migrate_legacy_agent_workspace_profiles,
    resolve_agent_workspace_path,
    resolve_agent_workspace_roots,
    resolve_workspace_child_path,
    resolve_workspace_identity,
    sanitize_agent_path_segment,
)


def test_relative_workspace_path_uses_working_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Resolve relative paths independently from the process CWD."""
    working_dir = tmp_path / "qwenpaw"
    process_dir = tmp_path / "process"
    working_dir.mkdir()
    process_dir.mkdir()
    monkeypatch.setattr(paths, "WORKING_DIR", working_dir)
    monkeypatch.chdir(process_dir)

    result = resolve_agent_workspace_path("relative-workspace", "agent")

    assert result == (working_dir / "relative-workspace").resolve()


def test_workspace_uses_configured_working_dir_for_relative_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Workspace construction must use the shared path resolver."""
    working_dir = tmp_path / "qwenpaw"
    process_dir = tmp_path / "process"
    working_dir.mkdir()
    process_dir.mkdir()
    monkeypatch.setattr(paths, "WORKING_DIR", working_dir)
    monkeypatch.chdir(process_dir)

    workspace = Workspace("agent", "relative-workspace")

    assert (
        workspace.workspace_dir
        == (working_dir / "relative-workspace").resolve()
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


def test_workspace_identity_uses_configured_root(
    tmp_path: Path,
) -> None:
    """Resolve a safe name under a server-configured root."""
    root = tmp_path / "trusted"

    result = resolve_workspace_identity(
        "trusted",
        "analyst",
        {"trusted": str(root)},
        working_dir=tmp_path / "qwenpaw",
    )

    assert result == (root / "analyst").resolve()


def test_workspace_identity_rejects_unknown_root(
    tmp_path: Path,
) -> None:
    """Reject a root ID that was not registered by the server."""
    with pytest.raises(ValueError, match="is not configured"):
        resolve_workspace_identity(
            "missing",
            "analyst",
            {},
            working_dir=tmp_path / "qwenpaw",
        )


def test_workspace_identity_rejects_traversal_name(
    tmp_path: Path,
) -> None:
    """Reject traversal even when the selected root is trusted."""
    with pytest.raises(ValueError, match="valid path segment"):
        resolve_workspace_identity(
            "default",
            "../escape",
            {},
            working_dir=tmp_path / "qwenpaw",
        )


def test_workspace_identity_rejects_symlink_escape(
    tmp_path: Path,
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

    with pytest.raises(ValueError, match="escapes its configured root"):
        resolve_workspace_identity(
            "default",
            "analyst",
            {},
            working_dir=working_dir,
        )


def test_workspace_roots_reject_filesystem_root(
    tmp_path: Path,
) -> None:
    """Never allow a configured root to expose an entire filesystem."""
    filesystem_root = Path(tmp_path.anchor)

    with pytest.raises(ValueError, match="filesystem root"):
        resolve_agent_workspace_roots(
            {"unsafe": str(filesystem_root)},
            working_dir=tmp_path / "qwenpaw",
        )


def test_workspace_child_path_rejects_nested_input(
    tmp_path: Path,
) -> None:
    """Only fixed file names may be joined to a trusted workspace."""
    with pytest.raises(ValueError, match="Invalid workspace file name"):
        resolve_workspace_child_path(tmp_path, "nested/agent.json")


def test_legacy_workspace_identity_preserves_existing_path(
    tmp_path: Path,
) -> None:
    """Represent a legacy custom workspace without moving its files."""
    workspace = tmp_path / "external" / "analyst"
    workspace.mkdir(parents=True)
    marker = workspace / "existing.txt"
    marker.write_text("preserved", encoding="utf-8")
    roots: dict[str, str] = {}

    root_id, workspace_name, resolved = derive_legacy_workspace_identity(
        workspace,
        "analyst",
        roots,
        working_dir=tmp_path / "qwenpaw",
    )

    assert root_id.startswith("legacy-")
    assert workspace_name == "analyst"
    assert resolved == workspace.resolve()
    assert roots[root_id] == str(workspace.parent.resolve())
    assert marker.read_text(encoding="utf-8") == "preserved"


def test_migrate_legacy_workspace_profiles_is_idempotent(
    tmp_path: Path,
) -> None:
    """Migrate legacy profile paths exactly once."""
    workspace = tmp_path / "external" / "analyst"
    data = {
        "agents": {
            "profiles": {
                "analyst": {
                    "id": "analyst",
                    "workspace_dir": str(workspace),
                },
            },
        },
    }

    first = migrate_legacy_agent_workspace_profiles(
        data,
        working_dir=tmp_path / "qwenpaw",
    )
    second = migrate_legacy_agent_workspace_profiles(
        data,
        working_dir=tmp_path / "qwenpaw",
    )

    profile = data["agents"]["profiles"]["analyst"]
    assert first is True
    assert second is False
    assert profile["workspace_name"] == "analyst"
    assert profile["workspace_root_id"].startswith("legacy-")


def test_save_agent_config_ignores_profile_payload_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Never derive the agent.json sink from its request payload."""
    trusted_root = tmp_path / "trusted"
    trusted_workspace = trusted_root / "analyst"
    trusted_workspace.mkdir(parents=True)
    outside = tmp_path / "outside"
    config = Config(
        agent_workspace_roots={"trusted": str(trusted_root)},
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
        workspace_dir=str(outside),
    )
    monkeypatch.setattr(config_utils, "load_config", lambda: config)

    save_agent_config("analyst", payload)

    saved_path = trusted_workspace / "agent.json"
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["workspace_dir"] == str(trusted_workspace.resolve())
    assert not (outside / "agent.json").exists()


def test_load_config_persists_legacy_workspace_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Persist an atomic, backed-up migration of legacy root config."""
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "external" / "analyst"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "active_agent": "analyst",
                    "agent_order": ["analyst"],
                    "profiles": {
                        "analyst": {
                            "id": "analyst",
                            "workspace_dir": str(workspace),
                        },
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_utils, "_config_cache", None)
    monkeypatch.setattr(config_utils, "_config_mtime", None)

    loaded = config_utils.load_config(config_path)

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    profile = persisted["agents"]["profiles"]["analyst"]
    assert loaded.agents.profiles["analyst"].workspace_name == "analyst"
    assert profile["workspace_name"] == "analyst"
    assert profile["workspace_root_id"].startswith("legacy-")
    assert len(list(tmp_path.glob("config.*.workspace-migrate.bak"))) == 1
