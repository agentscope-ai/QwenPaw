# -*- coding: utf-8 -*-
"""Tests for mode-independent project directory resolution."""

from pathlib import Path

import pytest

from qwenpaw.config.config import migrate_project_directory_config
from qwenpaw.services.project_directory import (
    resolve_effective_project_dir,
    session_project_dir,
)


def test_resolver_priority(tmp_path: Path) -> None:
    """Fork, request, Session, Agent, then workspace define precedence."""
    values = {
        "workspace_dir": tmp_path / "workspace",
        "agent_project_dir": str(tmp_path / "agent"),
        "session_override": str(tmp_path / "session"),
        "trusted_override": str(tmp_path / "request"),
        "active_mode_override": str(tmp_path / "mode"),
        "fork_project_dir": str(tmp_path / "fork"),
    }

    assert resolve_effective_project_dir(**values) == (
        (tmp_path / "fork").resolve(),
        "fork",
    )
    values["fork_project_dir"] = None
    assert resolve_effective_project_dir(**values)[1] == "active_mode"
    values["active_mode_override"] = None
    assert resolve_effective_project_dir(**values)[1] == "request"
    values["trusted_override"] = None
    assert resolve_effective_project_dir(**values)[1] == "session"
    values["session_override"] = None
    assert resolve_effective_project_dir(**values)[1] == "agent"
    values["agent_project_dir"] = None
    assert resolve_effective_project_dir(**values)[1] == "workspace_fallback"


def test_session_project_dir_uses_controlled_namespace() -> None:
    """Unrelated Chat metadata cannot become a directory override."""
    assert session_project_dir({"project_dir": "/wrong"}) is None
    assert (
        session_project_dir(
            {"runtime_context": {"project_dir": "/project"}},
        )
        == "/project"
    )


@pytest.mark.parametrize(
    ("top_level", "legacy", "expected"),
    [
        (None, "/legacy", "/legacy"),
        ("/top", "/legacy", "/top"),
        (None, None, None),
        (None, r"C:\Users\Alice\Project", r"C:\Users\Alice\Project"),
        (None, r"\\server\share\Project", r"\\server\share\Project"),
        (None, "~/Project", "~/Project"),
    ],
)
def test_legacy_project_directory_migration(
    top_level: str | None,
    legacy: str | None,
    expected: str | None,
) -> None:
    """Migration preserves a top-level value and removes the old field."""
    data = {
        "coding_mode": {
            "enabled": False,
            "project_dir": legacy,
        },
    }
    if top_level is not None:
        data["project_dir"] = top_level

    assert migrate_project_directory_config(data) is True
    assert data["project_dir"] == expected
    assert "project_dir" not in data["coding_mode"]
    assert migrate_project_directory_config(data) is False
