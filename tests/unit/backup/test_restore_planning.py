# -*- coding: utf-8 -*-
# pylint: disable=consider-using-with,protected-access,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for backup restore planning helpers.

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the restore planning /
validation helpers in ``backup/_ops/restore.py`` and
``backup/_ops/restore_helpers.py``.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.backup import models as backup_models
from qwenpaw.backup._ops import restore as restore_mod
from qwenpaw.backup._ops import restore_helpers as rh


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _request(**kwargs):
    return backup_models.RestoreBackupRequest(**kwargs)


# ---------------------------------------------------------------------------
# _validate_version
# ---------------------------------------------------------------------------


class TestValidateVersion:
    def test_supported_version_ok(self):
        meta = SimpleNamespace(version="1")
        restore_mod._validate_version(meta)  # no raise

    def test_unsupported_version_raises(self):
        meta = SimpleNamespace(version="99")
        with pytest.raises(ValueError, match="Unsupported backup version"):
            restore_mod._validate_version(meta)


# ---------------------------------------------------------------------------
# _zip_has_prefix
# ---------------------------------------------------------------------------


class TestZipHasPrefix:
    def test_prefix_present(self):
        zf = zipfile.ZipFile(
            io.BytesIO(
                _zip_bytes({"data/secrets/k.json": "{}"}),
            ),
        )
        assert restore_mod._zip_has_prefix(zf, "data/secrets/") is True

    def test_prefix_absent(self):
        zf = zipfile.ZipFile(
            io.BytesIO(_zip_bytes({"data/config.json": "{}"})),
        )
        assert restore_mod._zip_has_prefix(zf, "data/secrets/") is False

    def test_directories_ignored(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("data/secrets/", "")  # dir entry
        zf = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
        assert restore_mod._zip_has_prefix(zf, "data/secrets/") is False


# ---------------------------------------------------------------------------
# _dedupe_restore_targets
# ---------------------------------------------------------------------------


class TestDedupeRestoreTargets:
    def test_removes_duplicates(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        b = tmp_path / "b"
        b.mkdir()
        targets = [a, b, a, Path(str(a))]
        result = restore_mod._dedupe_restore_targets(targets)
        assert len(result) == 2

    def test_keeps_distinct(self, tmp_path):
        targets = [tmp_path / "x", tmp_path / "y"]
        assert len(restore_mod._dedupe_restore_targets(targets)) == 2


# ---------------------------------------------------------------------------
# _collect_agent_ids
# ---------------------------------------------------------------------------


class TestCollectAgentIds:
    def test_include_agents_false(self):
        zf = zipfile.ZipFile(io.BytesIO(_zip_bytes({})))
        ids, ws = restore_mod._collect_agent_ids(
            zf,
            _request(include_agents=False),
        )
        assert ids == []
        assert ws == set()

    def test_dedupes_and_keeps_order(self):
        zf = zipfile.ZipFile(
            io.BytesIO(
                _zip_bytes(
                    {
                        "data/workspaces/a1/agent.json": "{}",
                        "data/workspaces/a2/agent.json": "{}",
                    },
                ),
            ),
        )
        ids, ws = restore_mod._collect_agent_ids(
            zf,
            _request(agent_ids=["a1", "a1", "a2"]),
        )
        assert ids == ["a1", "a2"]
        assert ws == {"a1", "a2"}

    def test_unknown_agents_warned_but_returned(self):
        zf = zipfile.ZipFile(
            io.BytesIO(
                _zip_bytes({"data/workspaces/a1/agent.json": "{}"}),
            ),
        )
        ids, ws = restore_mod._collect_agent_ids(
            zf,
            _request(agent_ids=["a1", "ghost"]),
        )
        assert ids == ["a1", "ghost"]
        assert ws == {"a1"}


# ---------------------------------------------------------------------------
# resolve_workspace_dst
# ---------------------------------------------------------------------------


class TestResolveWorkspaceDst:
    def test_existing_workspace_kept(self, tmp_path, monkeypatch):
        ws = tmp_path / "existing"
        ws.mkdir()
        ref = SimpleNamespace(workspace_dir=str(ws))
        dst, is_new = rh.resolve_workspace_dst("a1", ref, None)
        assert dst == ws.resolve()
        assert is_new is False

    def test_missing_workspace_falls_back_to_default(self, tmp_path):
        ref = SimpleNamespace(workspace_dir=str(tmp_path / "gone"))
        default = tmp_path / "ws_root"
        dst, is_new = rh.resolve_workspace_dst("a1", ref, str(default))
        assert dst == (default / "a1").resolve()
        assert is_new is False

    def test_new_agent_uses_default(self, tmp_path):
        default = tmp_path / "ws_root"
        dst, is_new = rh.resolve_workspace_dst("a1", None, str(default))
        assert dst == (default / "a1").resolve()
        assert is_new is True

    def test_new_agent_working_dir_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rh, "WORKING_DIR", tmp_path / "wd")
        dst, is_new = rh.resolve_workspace_dst("a1", None, None)
        assert dst == (tmp_path / "wd" / "workspaces" / "a1").resolve()
        assert is_new is True


# ---------------------------------------------------------------------------
# _plan_agent_destinations
# ---------------------------------------------------------------------------


class TestPlanAgentDestinations:
    def _config(self, profiles):
        return SimpleNamespace(
            agents=SimpleNamespace(profiles=profiles),
        )

    def test_plans_existing_agents(self, tmp_path):
        ws1 = tmp_path / "ws1"
        ws1.mkdir()
        ws2 = tmp_path / "ws2"
        ws2.mkdir()
        config = self._config(
            {
                "a1": SimpleNamespace(workspace_dir=str(ws1)),
                "a2": SimpleNamespace(workspace_dir=str(ws2)),
            },
        )
        result = restore_mod._plan_agent_destinations(
            ["a1", "a2"],
            {"a1", "a2"},
            config,
            _request(default_workspace_dir=str(tmp_path)),
        )
        assert result["a1"] == (ws1.resolve(), False)
        assert result["a2"] == (ws2.resolve(), False)

    def test_skips_agents_not_in_zip(self, tmp_path):
        config = self._config({})
        result = restore_mod._plan_agent_destinations(
            ["ghost"],
            set(),  # not in the archive
            config,
            _request(default_workspace_dir=str(tmp_path)),
        )
        assert result == {}

    def test_same_destination_conflict_raises(self, tmp_path):
        shared = tmp_path / "shared"
        shared.mkdir()
        config = self._config(
            {
                "a1": SimpleNamespace(workspace_dir=str(shared)),
                "a2": SimpleNamespace(workspace_dir=str(shared)),
            },
        )
        with pytest.raises(ValueError, match="destination conflict"):
            restore_mod._plan_agent_destinations(
                ["a1", "a2"],
                {"a1", "a2"},
                config,
                _request(default_workspace_dir=str(tmp_path)),
            )

    def test_new_agent_clobbering_existing_raises(self, tmp_path):
        taken = tmp_path / "ws_root" / "a1"
        taken.mkdir(parents=True)
        config = self._config(
            {
                "keeper": SimpleNamespace(workspace_dir=str(taken)),
            },
        )
        with pytest.raises(ValueError, match="already used"):
            restore_mod._plan_agent_destinations(
                ["a1"],
                {"a1"},
                config,
                _request(default_workspace_dir=str(tmp_path / "ws_root")),
            )


# ---------------------------------------------------------------------------
# resolve_preserve_flag / overlay_local_keys
# ---------------------------------------------------------------------------


class TestResolvePreserveFlag:
    def test_explicit_true(self):
        req = _request(preserve_local_protected_config=True)
        meta = SimpleNamespace(accepted_via_trust=False)
        assert rh.resolve_preserve_flag(req, meta) is True

    def test_explicit_false(self):
        req = _request(preserve_local_protected_config=False)
        meta = SimpleNamespace(accepted_via_trust=True)
        assert rh.resolve_preserve_flag(req, meta) is False

    def test_defaults_to_trust_flag(self):
        req = _request(preserve_local_protected_config=None)
        assert (
            rh.resolve_preserve_flag(
                req,
                SimpleNamespace(accepted_via_trust=True),
            )
            is True
        )
        assert (
            rh.resolve_preserve_flag(
                req,
                SimpleNamespace(accepted_via_trust=False),
            )
            is False
        )


class TestOverlayLocalKeys:
    def test_overlays_protected_keys(self):
        # Protected keys are ("security", "mcp").
        backup_cfg = {
            "security": {"s": 1},
            "mcp": {"m": 1},
            "other": {"o": 1},
        }
        current_cfg = {"security": {"s": 2}}
        merged = rh.overlay_local_keys(backup_cfg, current_cfg)
        # security overlaid from current config
        assert merged["security"] == {"s": 2}
        # mcp absent from current → removed
        assert "mcp" not in merged
        # non-protected keys pass through unchanged
        assert merged["other"] == {"o": 1}

    def test_backup_not_mutated(self):
        backup_cfg = {"security": {"x": 1}}
        rh.overlay_local_keys(backup_cfg, {"security": {"y": 2}})
        assert backup_cfg == {"security": {"x": 1}}


# ---------------------------------------------------------------------------
# collect_workspace_agents_from_zip
# ---------------------------------------------------------------------------


class TestCollectWorkspaceAgentsFromZip:
    def test_collects_agent_ids(self):
        zf = zipfile.ZipFile(
            io.BytesIO(
                _zip_bytes(
                    {
                        "data/workspaces/a1/agent.json": "{}",
                        "data/workspaces/a2/sessions/s.json": "{}",
                        "data/workspaces/a2/": "",
                        "data/config.json": "{}",
                    },
                ),
            ),
        )
        assert rh.collect_workspace_agents_from_zip(zf) == {"a1", "a2"}

    def test_empty_zip(self):
        zf = zipfile.ZipFile(
            io.BytesIO(_zip_bytes({"data/config.json": "{}"})),
        )
        assert rh.collect_workspace_agents_from_zip(zf) == set()


# ---------------------------------------------------------------------------
# rewrite_agent_workspace_dir
# ---------------------------------------------------------------------------


class TestRewriteAgentWorkspaceDir:
    def test_rewrites_workspace_dir(self, tmp_path):
        dst = tmp_path / "agent_ws"
        dst.mkdir()
        agent_json = dst / "agent.json"
        agent_json.write_text(
            json.dumps({"id": "a1", "workspace_dir": "/old/path"}),
            encoding="utf-8",
        )
        rh.rewrite_agent_workspace_dir(dst, "a1")
        data = json.loads(agent_json.read_text(encoding="utf-8"))
        assert data["workspace_dir"] == str(dst)

    def test_missing_agent_json_noop(self, tmp_path):
        dst = tmp_path / "empty"
        dst.mkdir()
        rh.rewrite_agent_workspace_dir(dst, "a1")  # no raise

    def test_invalid_json_warns_not_raises(self, tmp_path):
        dst = tmp_path / "bad"
        dst.mkdir()
        (dst / "agent.json").write_text("{broken", encoding="utf-8")
        rh.rewrite_agent_workspace_dir(dst, "a1")  # no raise
