# -*- coding: utf-8 -*-
"""Project-directory resolution inside ContextVarsSetupHook.

Covers the helper layer that feeds the resolver: trusted request
overrides, client pending picks, and parent-snapshot inheritance — and
that the resolved list/source land in the per-turn ContextVars.
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.agents.acp.meta import ACP_PROJECT_DIR_META_KEY
from qwenpaw.config.context import (
    get_current_project_dir,
    get_current_project_dir_source,
    get_current_project_dirs,
    set_current_project_dir,
    set_current_project_dir_source,
    set_current_project_dirs,
)
from qwenpaw.hooks.request_setup.contextvars_hook import (
    ContextVarsSetupHook,
    _inherited_project_dirs,
    _pending_project_dirs,
    _trusted_request_project_dir,
)


@pytest.fixture(autouse=True)
def _reset():
    set_current_project_dirs(None)
    set_current_project_dir(None)
    set_current_project_dir_source(None)
    yield
    set_current_project_dirs(None)
    set_current_project_dir(None)
    set_current_project_dir_source(None)


class TestTrustedRequestProjectDir:
    def test_acp_meta_key_is_trusted(self, tmp_path):
        rc = {ACP_PROJECT_DIR_META_KEY: str(tmp_path)}
        assert _trusted_request_project_dir(rc) == str(tmp_path)

    def test_cron_key_is_trusted(self, tmp_path):
        rc = {"cron_project_dir": str(tmp_path)}
        assert _trusted_request_project_dir(rc) == str(tmp_path)

    def test_plain_project_dir_is_trusted(self, tmp_path):
        rc = {"project_dir": str(tmp_path)}
        assert _trusted_request_project_dir(rc) == str(tmp_path)

    def test_blank_is_none(self):
        assert _trusted_request_project_dir({"project_dir": "  "}) is None
        assert _trusted_request_project_dir({}) is None


class TestPendingProjectDirs:
    def test_plural_list_is_read(self, tmp_path):
        rc = {"session_project_dirs": [str(tmp_path)]}
        assert _pending_project_dirs(rc) == [
            {"path": str(tmp_path.resolve()), "label": None},
        ]

    def test_singular_fallback_is_wrapped(self, tmp_path):
        rc = {"session_project_dir": str(tmp_path)}
        assert _pending_project_dirs(rc) == [
            {"path": str(tmp_path.resolve()), "label": None},
        ]

    def test_non_directory_is_dropped(self, tmp_path):
        rc = {"session_project_dirs": [str(tmp_path / "missing")]}
        assert _pending_project_dirs(rc) is None

    def test_absent_is_none(self):
        assert _pending_project_dirs({}) is None


class TestInheritedProjectDirs:
    def test_snapshot_is_read(self, tmp_path):
        rc = {
            "inherited_project_dirs": [
                {"path": str(tmp_path), "label": "x"},
            ],
        }
        assert _inherited_project_dirs(rc) == [
            {"path": str(tmp_path.resolve()), "label": "x"},
        ]

    def test_non_directory_is_dropped(self, tmp_path):
        rc = {"inherited_project_dirs": [{"path": str(tmp_path / "no")}]}
        assert _inherited_project_dirs(rc) is None

    def test_absent_is_none(self):
        assert _inherited_project_dirs({}) is None


class TestApplyProjectDirs:
    """The resolver result is pinned into the ContextVars."""

    def _ctx(self, tmp_path):
        return SimpleNamespace(
            workspace_dir=tmp_path / "ws",
            mode_state={},
        )

    def test_session_list_wins_and_source_is_session(self, tmp_path):
        primary = tmp_path / "main"
        primary.mkdir()
        (tmp_path / "ws").mkdir()

        ContextVarsSetupHook._apply_project_dirs(
            self._ctx(tmp_path),
            workspace_dir=tmp_path / "ws",
            agent_project_dir=None,
            session_project_dirs=[{"path": str(primary), "label": None}],
            request_override=None,
            fork_dir=None,
            inherited=False,
        )

        assert get_current_project_dir() == primary.resolve()
        assert get_current_project_dir_source() == "session"
        dirs = get_current_project_dirs()
        assert dirs is not None and len(dirs) == 1

    def test_inherited_marks_the_source(self, tmp_path):
        primary = tmp_path / "main"
        primary.mkdir()
        (tmp_path / "ws").mkdir()

        ContextVarsSetupHook._apply_project_dirs(
            self._ctx(tmp_path),
            workspace_dir=tmp_path / "ws",
            agent_project_dir=None,
            session_project_dirs=[{"path": str(primary), "label": None}],
            request_override=None,
            fork_dir=None,
            inherited=True,
        )

        assert get_current_project_dir_source() == "inherited"

    def test_workspace_fallback_when_nothing_configured(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()

        ContextVarsSetupHook._apply_project_dirs(
            self._ctx(tmp_path),
            workspace_dir=ws,
            agent_project_dir=None,
            session_project_dirs=None,
            request_override=None,
            fork_dir=None,
            inherited=False,
        )

        assert get_current_project_dir() == ws.resolve()
        assert get_current_project_dir_source() == "workspace_fallback"
        assert get_current_project_dirs() == ()

    def test_mission_mode_pin_overrides_session(self, tmp_path):
        pinned = tmp_path / "pinned"
        pinned.mkdir()
        session = tmp_path / "session"
        session.mkdir()
        (tmp_path / "ws").mkdir()

        ctx = SimpleNamespace(
            workspace_dir=tmp_path / "ws",
            mode_state={
                "mission": {
                    "active": True,
                    "loop_dir": "",  # no loop dir: no disk pin
                },
            },
        )
        # Without a readable loop config there is no pin, so the
        # session list still wins.
        ContextVarsSetupHook._apply_project_dirs(
            ctx,
            workspace_dir=tmp_path / "ws",
            agent_project_dir=None,
            session_project_dirs=[{"path": str(session), "label": None}],
            request_override=None,
            fork_dir=None,
            inherited=False,
        )
        assert get_current_project_dir() == session.resolve()
