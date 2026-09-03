# -*- coding: utf-8 -*-
"""Gap-path tests for backup create_helpers.

Complements ``test_create.py`` by covering the secrets / skill-pool /
global-config archive helpers and the scope-based ``add_files_to_zip``
orchestrator.
"""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.backup._ops import create_helpers as ch
from qwenpaw.backup._utils.constants import (
    PREFIX_CONFIG,
    PREFIX_SECRETS,
    PREFIX_SKILL_POOL,
    PREFIX_WORKSPACES,
)


def _zip(tmp_path: Path) -> zipfile.ZipFile:
    return zipfile.ZipFile(tmp_path / "backup.zip", "w")


def _meta(**overrides) -> SimpleNamespace:
    scope = {
        "include_agents": True,
        "include_global_config": False,
        "include_secrets": False,
        "include_skill_pool": False,
    }
    scope.update(overrides)
    return SimpleNamespace(scope=SimpleNamespace(**scope))


# ---------------------------------------------------------------------------
# add_agent_workspaces
# ---------------------------------------------------------------------------


class TestAddAgentWorkspaces:
    def test_adds_workspace_files(self, tmp_path):
        ws = tmp_path / "agent-ws"
        ws.mkdir()
        (ws / "a.txt").write_text("1", encoding="utf-8")
        sub = ws / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("2", encoding="utf-8")

        with _zip(tmp_path) as zf:
            ok = ch.add_agent_workspaces(
                zf,
                [("agent-1", SimpleNamespace(workspace_dir=ws))],
            )
            names = set(zf.namelist())

        assert ok is True
        assert f"{PREFIX_WORKSPACES}agent-1/a.txt" in names
        assert f"{PREFIX_WORKSPACES}agent-1/sub/b.txt" in names

    def test_missing_workspace_dir_skipped(self, tmp_path):
        with _zip(tmp_path) as zf:
            ok = ch.add_agent_workspaces(
                zf,
                [("ghost", SimpleNamespace(workspace_dir=tmp_path / "none"))],
            )
        assert ok is True

    def test_progress_callback_invoked(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        calls = []
        with _zip(tmp_path) as zf:
            ch.add_agent_workspaces(
                zf,
                [("a1", SimpleNamespace(workspace_dir=ws))],
                progress_callback=lambda i, total, aid: calls.append(
                    (i, total, aid),
                ),
            )
        assert calls == [(0, 1, "a1")]

    def test_stop_event_before_start_returns_false(self, tmp_path):
        stop = threading.Event()
        stop.set()
        ws = tmp_path / "ws"
        ws.mkdir()
        with _zip(tmp_path) as zf:
            ok = ch.add_agent_workspaces(
                zf,
                [("a1", SimpleNamespace(workspace_dir=ws))],
                stop_event=stop,
            )
        assert ok is False

    def test_unreadable_file_skipped_not_fatal(self, tmp_path, monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "good.txt").write_text("x", encoding="utf-8")
        locked = ws / "locked.bin"
        locked.write_text("y", encoding="utf-8")

        real_write = zipfile.ZipFile.write

        def flaky_write(self, filename, arcname=None, *args, **kwargs):
            if Path(filename).name == "locked.bin":
                raise PermissionError("locked by backend")
            return real_write(self, filename, arcname, *args, **kwargs)

        monkeypatch.setattr(zipfile.ZipFile, "write", flaky_write)

        with _zip(tmp_path) as zf:
            ok = ch.add_agent_workspaces(
                zf,
                [("a1", SimpleNamespace(workspace_dir=ws))],
            )
            names = set(zf.namelist())

        assert ok is True
        assert f"{PREFIX_WORKSPACES}a1/good.txt" in names
        assert f"{PREFIX_WORKSPACES}a1/locked.bin" not in names


# ---------------------------------------------------------------------------
# add_global_config
# ---------------------------------------------------------------------------


class TestAddGlobalConfig:
    def test_adds_config_when_present(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.json"
        cfg.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(ch, "WORKING_DIR", tmp_path)
        monkeypatch.setattr(ch, "CONFIG_FILE", "config.json")
        with _zip(tmp_path) as zf:
            ch.add_global_config(zf)
            assert PREFIX_CONFIG in zf.namelist()

    def test_missing_config_no_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ch, "WORKING_DIR", tmp_path)
        monkeypatch.setattr(ch, "CONFIG_FILE", "absent.json")
        with _zip(tmp_path) as zf:
            ch.add_global_config(zf)
            assert zf.namelist() == []


# ---------------------------------------------------------------------------
# add_secrets
# ---------------------------------------------------------------------------


class TestAddSecrets:
    def test_missing_dir_returns_true(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ch, "SECRET_DIR", tmp_path / "no-secrets")
        with _zip(tmp_path) as zf:
            assert ch.add_secrets(zf) is True
            assert zf.namelist() == []

    def test_adds_secret_files_recursively(self, tmp_path, monkeypatch):
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        (secret_dir / "a.yaml").write_text("k", encoding="utf-8")
        nested = secret_dir / "nested"
        nested.mkdir()
        (nested / "b.yaml").write_text("k2", encoding="utf-8")
        monkeypatch.setattr(ch, "SECRET_DIR", secret_dir)

        with _zip(tmp_path) as zf:
            assert ch.add_secrets(zf) is True
            names = set(zf.namelist())

        assert f"{PREFIX_SECRETS}a.yaml" in names
        assert f"{PREFIX_SECRETS}nested/b.yaml" in names

    def test_stop_event_cancels(self, tmp_path, monkeypatch):
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        (secret_dir / "a.yaml").write_text("k", encoding="utf-8")
        monkeypatch.setattr(ch, "SECRET_DIR", secret_dir)
        stop = threading.Event()
        stop.set()
        with _zip(tmp_path) as zf:
            assert ch.add_secrets(zf, stop_event=stop) is False


# ---------------------------------------------------------------------------
# add_skill_pool
# ---------------------------------------------------------------------------


class TestAddSkillPool:
    def test_missing_pool_returns_true(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "qwenpaw.agents.skill_system.store.get_skill_pool_dir",
            lambda: tmp_path / "no-pool",
        )
        with _zip(tmp_path) as zf:
            assert ch.add_skill_pool(zf) is True
            assert zf.namelist() == []

    def test_adds_pool_files(self, tmp_path, monkeypatch):
        pool = tmp_path / "skill_pool"
        skill = pool / "demo"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
        monkeypatch.setattr(
            "qwenpaw.agents.skill_system.store.get_skill_pool_dir",
            lambda: pool,
        )

        with _zip(tmp_path) as zf:
            assert ch.add_skill_pool(zf) is True
            names = set(zf.namelist())

        assert f"{PREFIX_SKILL_POOL}demo/SKILL.md" in names

    def test_stop_event_cancels(self, tmp_path, monkeypatch):
        pool = tmp_path / "skill_pool"
        pool.mkdir()
        (pool / "f.txt").write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            "qwenpaw.agents.skill_system.store.get_skill_pool_dir",
            lambda: pool,
        )
        stop = threading.Event()
        stop.set()
        with _zip(tmp_path) as zf:
            assert ch.add_skill_pool(zf, stop_event=stop) is False


# ---------------------------------------------------------------------------
# add_files_to_zip
# ---------------------------------------------------------------------------


class TestAddFilesToZip:
    def test_no_agents_returns_empty_list(self, tmp_path):
        meta = _meta(include_agents=False)
        with _zip(tmp_path) as zf:
            result = ch.add_files_to_zip(zf, meta, valid_agents=[])
        assert result == []

    def test_agents_backed_up_returns_ids(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "a.txt").write_text("1", encoding="utf-8")
        meta = _meta(include_agents=True)
        agents = [("agent-1", SimpleNamespace(workspace_dir=ws))]
        with _zip(tmp_path) as zf:
            result = ch.add_files_to_zip(zf, meta, valid_agents=agents)
        assert result == ["agent-1"]

    def test_cancelled_agents_returns_empty(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        stop = threading.Event()
        stop.set()
        meta = _meta(include_agents=True)
        agents = [("agent-1", SimpleNamespace(workspace_dir=ws))]
        with _zip(tmp_path) as zf:
            result = ch.add_files_to_zip(
                zf,
                meta,
                stop_event=stop,
                valid_agents=agents,
            )
        assert result == []
