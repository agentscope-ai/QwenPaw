# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Unit tests for project_directory.py security and path helpers.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the sensitive-path
validation and project-dir persistence helpers, which previously sat at
~20% coverage.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import project_directory as pd


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


class TestMatchDirSequence:
    def test_contiguous_match(self):
        assert (
            pd._match_dir_sequence(
                ("a", ".config", "gh", "b"),
                (".config", "gh"),
            )
            is True
        )

    def test_no_match(self):
        assert pd._match_dir_sequence(("a", "b"), (".config", "gh")) is False

    def test_seq_longer_than_parts(self):
        assert pd._match_dir_sequence(("a",), ("a", "b", "c")) is False

    def test_empty_seq_matches(self):
        assert pd._match_dir_sequence(("a",), ()) is True


class TestIsSensitiveName:
    @pytest.mark.parametrize(
        "name",
        [".ssh", ".aws", ".SSH", ".env", ".netrc", ".NetRC"],
    )
    def test_sensitive(self, name):
        assert pd._is_sensitive_name(name) is True

    @pytest.mark.parametrize("name", ["src", "main.py", "env", "ssh"])
    def test_not_sensitive(self, name):
        assert pd._is_sensitive_name(name) is False


class TestValidateImportSource:
    def test_outside_home_rejected(self, fake_home, tmp_path):
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        with pytest.raises(HTTPException) as excinfo:
            pd._validate_import_source(outside)
        assert excinfo.value.status_code == 403
        assert "under home" in excinfo.value.detail

    def test_home_itself_rejected(self, fake_home):
        with pytest.raises(HTTPException) as excinfo:
            pd._validate_import_source(fake_home)
        assert excinfo.value.status_code == 403
        assert "entire home directory" in excinfo.value.detail

    def test_sensitive_component_rejected(self, fake_home):
        target = fake_home / ".ssh"
        target.mkdir()
        with pytest.raises(HTTPException) as excinfo:
            pd._validate_import_source(target)
        assert excinfo.value.status_code == 403
        assert "sensitive component" in excinfo.value.detail

    def test_sensitive_sequence_rejected(self, fake_home):
        target = fake_home / "backup" / ".config" / "gh"
        target.mkdir(parents=True)
        with pytest.raises(HTTPException) as excinfo:
            pd._validate_import_source(target)
        assert excinfo.value.status_code == 403
        assert "sequence" in excinfo.value.detail

    def test_normal_path_passes(self, fake_home):
        target = fake_home / "projects" / "demo"
        target.mkdir(parents=True)
        pd._validate_import_source(target)  # no raise


class TestProjectsBase:
    def test_base_under_workspace(self, tmp_path):
        assert pd._projects_base(tmp_path / "ws") == (
            tmp_path / "ws" / pd.CODING_PROJECT_SUBDIR
        )


class TestSaveProjectDir:
    def test_round_trip(self, tmp_path, monkeypatch):
        saved = {}

        class _Cfg:
            id = "agent_x"
            project_dir = None

        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            lambda agent_id: _Cfg(),
        )

        def fake_save(agent_id, config):
            saved["agent_id"] = agent_id
            saved["project_dir"] = config.project_dir

        monkeypatch.setattr(
            "qwenpaw.config.config.save_agent_config",
            fake_save,
        )
        pd._save_project_dir("agent_x", "/tmp/proj")
        assert saved == {"agent_id": "agent_x", "project_dir": "/tmp/proj"}

    def test_reset_to_none(self, monkeypatch):
        saved = {}

        class _Cfg:
            id = "agent_x"
            project_dir = "/old"

        monkeypatch.setattr(
            "qwenpaw.config.config.load_agent_config",
            lambda agent_id: _Cfg(),
        )
        monkeypatch.setattr(
            "qwenpaw.config.config.save_agent_config",
            lambda agent_id, config: saved.update(p=config.project_dir),
        )
        pd._save_project_dir("agent_x", None)
        assert saved["p"] is None


class TestRequestModels:
    def test_set_project_request_defaults(self):
        body = pd.SetProjectRequest()
        assert body.path is None

    def test_set_project_request_with_path(self):
        body = pd.SetProjectRequest(path="/tmp/x")
        assert body.path == "/tmp/x"

    def test_create_project_request_requires_name(self):
        with pytest.raises(Exception):
            pd.CreateProjectRequest()

    def test_clone_request_name_optional(self):
        body = pd.CloneProjectRequest(url="https://x/repo.git")
        assert body.name is None

    def test_create_directory_request(self):
        body = pd.CreateDirectoryRequest(parent="/tmp", name="new")
        assert body.parent == "/tmp"
        assert body.name == "new"
