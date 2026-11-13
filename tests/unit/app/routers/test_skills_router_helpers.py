# -*- coding: utf-8 -*-
"""Unit tests for skills router helpers (app/routers/skills.py).

Coverage-driven backfill (batch 4, coverage-first per the 2026-08-24
instruction: upstream PRs are only considered after backend_unit coverage
rises by at least 5 percentage points). Target: the snapshot/rollback,
hub-install task lifecycle, and spec-building helpers which previously
sat at ~36% coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import skills as skills_module


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: d for {name}\n---\n# body\n"


def _write_skill(skill_dir: Path, name: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_skill_md(name), encoding="utf-8")


def _write_workspace_manifest(workspace_dir: Path, skills: dict) -> None:
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "schema_version": "workspace-skill-manifest.v1",
                "version": 0,
                "skills": skills,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _read_manifest(workspace_dir: Path) -> dict:
    return json.loads(
        (workspace_dir / "skill.json").read_text(encoding="utf-8"),
    )


@pytest.fixture()
def skill_env(tmp_path, monkeypatch):
    """Isolated working dir with scan stubbed."""
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        skills_module,
        "scan_skill_dir_or_raise",
        lambda *args, **kwargs: None,
        raising=False,
    )
    workspace_dir = tmp_path / "workspaces" / "agent_x"
    workspace_dir.mkdir(parents=True)
    return tmp_path, workspace_dir


# ---------------------------------------------------------------------------
# _workspace_dir_for_agent
# ---------------------------------------------------------------------------


class TestWorkspaceDirForAgent:
    def test_resolves_known_agent(self, monkeypatch):
        monkeypatch.setattr(
            skills_module,
            "list_workspaces",
            lambda: [
                {"agent_id": "agent_x", "workspace_dir": "/tmp/ws_x"},
            ],
        )
        result = skills_module._workspace_dir_for_agent("agent_x")
        assert result == Path("/tmp/ws_x")

    def test_unknown_agent_404(self, monkeypatch):
        monkeypatch.setattr(skills_module, "list_workspaces", lambda: [])
        with pytest.raises(HTTPException) as excinfo:
            skills_module._workspace_dir_for_agent("ghost")
        assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# snapshot / restore round-trip
# ---------------------------------------------------------------------------


class TestSnapshotRestore:
    def test_snapshot_and_restore_existing_skill(self, skill_env):
        _tmp, workspace_dir = skill_env
        skill_dir = workspace_dir / "skills" / "demo"
        _write_skill(skill_dir, "demo")
        _write_workspace_manifest(
            workspace_dir,
            {"demo": {"enabled": True, "channels": ["all"]}},
        )

        snapshot = skills_module._snapshot_workspace_skill(
            workspace_dir,
            "demo",
        )
        assert snapshot["entry"]["enabled"] is True
        assert snapshot["backup_dir"] is not None

        # Mutate the live skill, then restore.
        (skill_dir / "SKILL.md").write_text("corrupted", encoding="utf-8")
        skills_module._restore_workspace_skill(snapshot)

        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == (
            _skill_md("demo")
        )
        entry = _read_manifest(workspace_dir)["skills"]["demo"]
        assert entry["enabled"] is True

    def test_snapshot_missing_skill_has_no_backup(self, skill_env):
        _tmp, workspace_dir = skill_env
        _write_workspace_manifest(workspace_dir, {})
        snapshot = skills_module._snapshot_workspace_skill(
            workspace_dir,
            "ghost",
        )
        assert snapshot["entry"] is None
        assert snapshot["backup_dir"] is None

    def test_restore_removes_skill_without_backup(self, skill_env):
        _tmp, workspace_dir = skill_env
        skill_dir = workspace_dir / "skills" / "ghost"
        _write_skill(skill_dir, "ghost")
        _write_workspace_manifest(
            workspace_dir,
            {"ghost": {"enabled": True}},
        )
        snapshot = {
            "workspace_dir": workspace_dir,
            "skill_name": "ghost",
            "entry": None,
            "backup_dir": None,
        }
        skills_module._restore_workspace_skill(snapshot)
        assert not skill_dir.exists()
        assert "ghost" not in _read_manifest(workspace_dir)["skills"]


# ---------------------------------------------------------------------------
# hub install task lifecycle helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_task_registries():
    skills_module._hub_install_tasks.clear()
    skills_module._hub_install_runtime_tasks.clear()
    skills_module._hub_install_cancel_events.clear()
    yield
    skills_module._hub_install_tasks.clear()
    skills_module._hub_install_runtime_tasks.clear()
    skills_module._hub_install_cancel_events.clear()


def _new_task(**kwargs) -> skills_module.HubInstallTask:
    return skills_module.HubInstallTask(
        bundle_url="https://hub.example/skill",
        **kwargs,
    )


class TestHubTaskSetStatus:
    async def test_sets_status_and_fields(self):
        task = _new_task()
        skills_module._hub_install_tasks[task.task_id] = task
        await skills_module._hub_task_set_status(
            task.task_id,
            skills_module.HubInstallTaskStatus.COMPLETED,
            result={"name": "demo"},
        )
        assert task.status == skills_module.HubInstallTaskStatus.COMPLETED
        assert task.result == {"name": "demo"}

    async def test_sets_error(self):
        task = _new_task()
        skills_module._hub_install_tasks[task.task_id] = task
        await skills_module._hub_task_set_status(
            task.task_id,
            skills_module.HubInstallTaskStatus.FAILED,
            error="boom",
        )
        assert task.error == "boom"

    async def test_unknown_task_is_noop(self):
        await skills_module._hub_task_set_status(
            "missing",
            skills_module.HubInstallTaskStatus.FAILED,
        )


class TestHubTaskGet:
    async def test_returns_registered_task(self):
        task = _new_task()
        skills_module._hub_install_tasks[task.task_id] = task
        got = await skills_module._hub_task_get(task.task_id)
        assert got is task

    async def test_returns_none_for_unknown(self):
        assert await skills_module._hub_task_get("missing") is None

    async def test_expired_finished_tasks_cleaned(self):
        finished = _new_task(
            status=skills_module.HubInstallTaskStatus.COMPLETED,
        )
        finished.updated_at = time.time() - (
            skills_module._HUB_INSTALL_TASK_TTL_SECONDS + 60
        )
        skills_module._hub_install_tasks[finished.task_id] = finished
        assert await skills_module._hub_task_get(finished.task_id) is None

    async def test_running_tasks_not_cleaned(self):
        running = _new_task(
            status=skills_module.HubInstallTaskStatus.COMPLETED,
        )
        running.updated_at = time.time() - (
            skills_module._HUB_INSTALL_TASK_TTL_SECONDS + 60
        )
        skills_module._hub_install_tasks[running.task_id] = running
        skills_module._hub_install_runtime_tasks[running.task_id] = object()
        assert await skills_module._hub_task_get(running.task_id) is running


class TestHubTaskCleanupLocked:
    def test_history_cap_evicts_oldest(self, monkeypatch):
        monkeypatch.setattr(skills_module, "_HUB_INSTALL_TASK_MAX_HISTORY", 2)
        now = time.time()
        for index in range(4):
            task = _new_task(
                status=skills_module.HubInstallTaskStatus.COMPLETED,
            )
            task.updated_at = now - (10 - index)
            task.created_at = now - (10 - index)
            skills_module._hub_install_tasks[task.task_id] = task

        skills_module._hub_task_cleanup_locked(now=now)

        remaining = list(skills_module._hub_install_tasks)
        assert len(remaining) == 2
        assert skills_module._hub_install_cancel_events == {}

    def test_non_terminal_tasks_kept(self):
        pending = _new_task()
        skills_module._hub_install_tasks[pending.task_id] = pending
        skills_module._hub_task_cleanup_locked(
            now=time.time() + 999999,
        )
        assert pending.task_id in skills_module._hub_install_tasks


class TestHubTaskFinishRuntime:
    async def test_finish_updates_timestamp(self):
        task = _new_task(
            status=skills_module.HubInstallTaskStatus.COMPLETED,
        )
        old_stamp = time.time() - 100
        task.updated_at = old_stamp
        skills_module._hub_install_tasks[task.task_id] = task
        skills_module._hub_install_runtime_tasks[task.task_id] = object()
        skills_module._hub_install_cancel_events[
            task.task_id
        ] = asyncio.Event()

        await skills_module._hub_task_finish_runtime(task.task_id)

        assert task.updated_at > old_stamp
        assert task.task_id not in skills_module._hub_install_runtime_tasks
        assert task.task_id not in skills_module._hub_install_cancel_events

    async def test_finish_unknown_task_is_noop(self):
        await skills_module._hub_task_finish_runtime("missing")


# ---------------------------------------------------------------------------
# zip upload validation
# ---------------------------------------------------------------------------


class _FakeUpload:
    def __init__(self, content_type: str | None, data: bytes):
        self.content_type = content_type
        self._data = data

    async def read(self) -> bytes:
        return self._data


class TestReadValidatedZipUpload:
    async def test_allowed_content_type_passes(self):
        data = await skills_module._read_validated_zip_upload(
            _FakeUpload("application/zip", b"PK\x03\x04data"),
        )
        assert data == b"PK\x03\x04data"

    async def test_no_content_type_passes(self):
        data = await skills_module._read_validated_zip_upload(
            _FakeUpload(None, b"data"),
        )
        assert data == b"data"

    async def test_bad_content_type_400(self):
        with pytest.raises(HTTPException) as excinfo:
            await skills_module._read_validated_zip_upload(
                _FakeUpload("text/plain", b"data"),
            )
        assert excinfo.value.status_code == 400


# ---------------------------------------------------------------------------
# spec builders
# ---------------------------------------------------------------------------


class TestBuildWorkspaceSkillSpecs:
    def test_lists_skills_with_dirs(self, skill_env, monkeypatch):
        _tmp, workspace_dir = skill_env
        _write_skill(workspace_dir / "skills" / "demo", "demo")
        _write_workspace_manifest(
            workspace_dir,
            {"demo": {"enabled": True, "channels": ["all"]}},
        )
        monkeypatch.setattr(
            skills_module,
            "get_pool_builtin_sync_status",
            lambda **kwargs: {},
            raising=False,
        )

        specs = skills_module._build_workspace_skill_specs(workspace_dir)

        assert len(specs) == 1
        assert specs[0].name == "demo"
        assert specs[0].enabled is True

    def test_skips_manifest_only_entries(self, skill_env, monkeypatch):
        _tmp, workspace_dir = skill_env
        _write_workspace_manifest(
            workspace_dir,
            {"ghost": {"enabled": True}},
        )
        specs = skills_module._build_workspace_skill_specs(workspace_dir)
        assert specs == []

    def test_malformed_entry_normalized_and_skipped_on_error(
        self,
        skill_env,
        monkeypatch,
    ):
        _tmp, workspace_dir = skill_env
        _write_skill(workspace_dir / "skills" / "demo", "demo")
        _write_workspace_manifest(
            workspace_dir,
            # malformed: entry is not a dict → normalized, logged
            {"demo": "garbage"},
        )
        specs = skills_module._build_workspace_skill_specs(workspace_dir)
        # normalized entry has no enabled/channels → still builds a spec
        assert len(specs) == 1
        assert specs[0].enabled is False


class TestBuildPoolSkillSpecs:
    def test_lists_pool_skills(self, skill_env, monkeypatch):
        tmp_path, _ws = skill_env
        pool_dir = tmp_path / "skill_pool"
        _write_skill(pool_dir / "demo", "demo")
        (pool_dir / "skill.json").write_text(
            json.dumps(
                {
                    "schema_version": "skill-pool-manifest.v1",
                    "version": 0,
                    "skills": {"demo": {"source": "customized"}},
                    "builtin_skill_names": [],
                },
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            skills_module,
            "get_pool_builtin_sync_status",
            lambda **kwargs: {},
        )

        specs = skills_module._build_pool_skill_specs()

        assert len(specs) == 1
        assert specs[0].name == "demo"
        assert specs[0].external is False

    def test_missing_dir_skipped(self, skill_env, monkeypatch):
        tmp_path, _ws = skill_env
        pool_dir = tmp_path / "skill_pool"
        pool_dir.mkdir(parents=True)
        (pool_dir / "skill.json").write_text(
            json.dumps(
                {
                    "schema_version": "skill-pool-manifest.v1",
                    "version": 0,
                    "skills": {"ghost": {"source": "customized"}},
                    "builtin_skill_names": [],
                },
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            skills_module,
            "get_pool_builtin_sync_status",
            lambda **kwargs: {},
        )
        assert skills_module._build_pool_skill_specs() == []


class TestBuildSkillDetails:
    def test_workspace_detail(self, skill_env):
        _tmp, workspace_dir = skill_env
        _write_skill(workspace_dir / "skills" / "demo", "demo")
        _write_workspace_manifest(
            workspace_dir,
            {
                "demo": {
                    "enabled": True,
                    "channels": ["all"],
                    "config": {"k": "v"},
                },
            },
        )

        detail = skills_module._build_workspace_skill_detail(
            workspace_dir,
            "demo",
        )

        assert detail is not None
        assert detail.name == "demo"
        assert detail.config == {"k": "v"}
        assert "# body" in detail.content

    def test_workspace_detail_unknown_returns_none(self, skill_env):
        _tmp, workspace_dir = skill_env
        _write_workspace_manifest(workspace_dir, {})
        assert (
            skills_module._build_workspace_skill_detail(workspace_dir, "x")
            is None
        )

    def test_pool_detail(self, skill_env, monkeypatch):
        tmp_path, _ws = skill_env
        pool_dir = tmp_path / "skill_pool"
        _write_skill(pool_dir / "demo", "demo")
        (pool_dir / "skill.json").write_text(
            json.dumps(
                {
                    "schema_version": "skill-pool-manifest.v1",
                    "version": 0,
                    "skills": {
                        "demo": {
                            "source": "customized",
                            "tags": ["t"],
                        },
                    },
                    "builtin_skill_names": [],
                },
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            skills_module,
            "get_pool_builtin_sync_status",
            lambda **kwargs: {},
        )

        detail = skills_module._build_pool_skill_detail("demo")

        assert detail is not None
        assert detail.tags == ["t"]
        assert "# body" in detail.content

    def test_pool_detail_unknown_returns_none(self, skill_env, monkeypatch):
        tmp_path, _ws = skill_env
        pool_dir = tmp_path / "skill_pool"
        pool_dir.mkdir(parents=True)
        (pool_dir / "skill.json").write_text(
            json.dumps(
                {
                    "schema_version": "skill-pool-manifest.v1",
                    "version": 0,
                    "skills": {},
                    "builtin_skill_names": [],
                },
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            skills_module,
            "get_pool_builtin_sync_status",
            lambda **kwargs: {},
        )
        assert skills_module._build_pool_skill_detail("ghost") is None


class TestListWorkspaceSkillNames:
    def test_lists_names_with_skill_md(self, skill_env):
        _tmp, workspace_dir = skill_env
        _write_skill(workspace_dir / "skills" / "demo", "demo")
        _write_workspace_manifest(
            workspace_dir,
            {"demo": {}, "ghost": {}},
        )
        names = skills_module._list_workspace_skill_names(workspace_dir)
        assert names == ["demo"]


class TestScanErrorHelpers:
    @staticmethod
    def _scan_error():
        from types import SimpleNamespace

        from qwenpaw.exceptions import SkillScanError

        finding = SimpleNamespace(
            severity=SimpleNamespace(value="high"),
            title="dangerous call",
            description="uses os.system",
            file_path="backend.py",
            line_number=12,
            rule_id="R001",
        )
        result = SimpleNamespace(
            skill_name="blocked_skill",
            max_severity=SimpleNamespace(value="high"),
            findings=[finding],
        )
        return SkillScanError(result)

    def test_scan_error_payload_shape(self):
        payload = skills_module._scan_error_payload(self._scan_error())
        assert payload["type"] == "security_scan_failed"
        assert payload["skill_name"] == "blocked_skill"
        assert payload["max_severity"] == "high"
        assert payload["findings"][0]["rule_id"] == "R001"

    def test_scan_error_response_is_json(self):
        response = skills_module._scan_error_response(self._scan_error())
        assert response.status_code == 422
