# -*- coding: utf-8 -*-
"""Unit tests for skills router mutation endpoints.

Covers the write-side endpoints and automation-inbox helpers that the
existing read-side test file does not exercise: create/save/upload
endpoints (workspace and pool), batch operations, enable/disable,
skill-config endpoints backed by the workspace manifest, pool
automation updates, pool download preflight, and the auto-sync /
pool-automation inbox event builders.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import skills as skills_module
from qwenpaw.app.routers.skills import router as skills_router
from qwenpaw.exceptions import SkillScanError


def _zip_bytes(names: tuple[str, ...] = ("SKILL.md",)) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name in names:
            zf.writestr(name, "# skill content\n")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _clear_install_registries():
    skills_module._hub_install_tasks.clear()
    skills_module._hub_install_runtime_tasks.clear()
    skills_module._hub_install_cancel_events.clear()
    yield
    skills_module._hub_install_tasks.clear()
    skills_module._hub_install_runtime_tasks.clear()
    skills_module._hub_install_cancel_events.clear()


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.state.multi_agent_manager = MagicMock(name="ManagerStub")
    application.include_router(skills_router, prefix="/api")
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_workspace(tmp_path: Path):
    workspace = MagicMock(name="Workspace")
    workspace.workspace_dir = str(tmp_path)
    workspace.agent_id = "default"
    return workspace


@pytest.fixture
def patch_get_agent(fake_workspace):
    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=AsyncMock(return_value=fake_workspace),
    ) as patched:
        yield patched


@pytest.fixture
def mock_workspace_service():
    service = MagicMock(name="SkillServiceInstance")
    with patch(
        "qwenpaw.app.routers.skills.SkillService",
        return_value=service,
    ):
        yield service


@pytest.fixture
def mock_pool_service():
    service = MagicMock(name="SkillPoolServiceInstance")
    with patch(
        "qwenpaw.app.routers.skills.SkillPoolService",
        return_value=service,
    ):
        yield service


@pytest.fixture
def mock_inbox_append():
    with patch(
        "qwenpaw.app.routers.skills.append_inbox_event",
        new=AsyncMock(return_value=None),
    ) as patched:
        yield patched


@pytest.fixture
def mock_schedule_reload():
    with patch(
        "qwenpaw.app.routers.skills.schedule_agent_reload",
    ) as patched:
        yield patched


def _scan_error() -> SkillScanError:
    finding = MagicMock(name="Finding")
    finding.severity = MagicMock(value="high")
    finding.title = "exec usage"
    finding.description = "runs shell"
    finding.file_path = "scripts/run.sh"
    finding.line_number = 3
    finding.rule_id = "R1"
    result = MagicMock(name="ScanResult")
    result.skill_name = "blocked_skill"
    result.max_severity = MagicMock(value="high")
    result.findings = [finding]
    return SkillScanError(result)


# ---------------------------------------------------------------------------
# automation inbox helpers
# ---------------------------------------------------------------------------


class TestPostAutoSyncInbox:
    async def test_none_result_posts_nothing(self, mock_inbox_append):
        assert await skills_module.post_auto_sync_inbox(None) is False
        mock_inbox_append.assert_not_awaited()

    async def test_empty_result_posts_nothing(self, mock_inbox_append):
        assert await skills_module.post_auto_sync_inbox({}) is False
        mock_inbox_append.assert_not_awaited()

    async def test_synced_without_agents_is_ignored(self, mock_inbox_append):
        result = {"synced": [{"skill": "s1", "agents": []}]}
        assert await skills_module.post_auto_sync_inbox(result) is False
        mock_inbox_append.assert_not_awaited()

    async def test_success_event_for_synced_items(self, mock_inbox_append):
        result = {
            "synced": [
                {"skill": "s1", "agents": ["default", "work"]},
            ],
            "failed": [],
        }
        assert await skills_module.post_auto_sync_inbox(result) is True
        kwargs = mock_inbox_append.await_args.kwargs
        assert kwargs["status"] == "success"
        assert kwargs["severity"] == "info"
        assert "1 skill(s) synced" in kwargs["title"]
        assert "s1 → default, work" in kwargs["body"]

    async def test_failure_event_marks_error(self, mock_inbox_append):
        result = {
            "synced": [],
            "failed": [{"skill": "s2", "agents": []}],
        }
        assert await skills_module.post_auto_sync_inbox(result) is True
        kwargs = mock_inbox_append.await_args.kwargs
        assert kwargs["status"] == "error"
        assert kwargs["severity"] == "error"
        assert "(failed)" in kwargs["body"]

    async def test_inbox_error_returns_false(self):
        with patch(
            "qwenpaw.app.routers.skills.append_inbox_event",
            new=AsyncMock(side_effect=RuntimeError("inbox down")),
        ):
            result = {"synced": [{"skill": "s1", "agents": ["a"]}]}
            assert await skills_module.post_auto_sync_inbox(result) is False


class TestPostPoolAutomationInbox:
    async def test_none_result_posts_nothing(self, mock_inbox_append):
        assert await skills_module.post_pool_automation_inbox(None) is False
        mock_inbox_append.assert_not_awaited()

    async def test_without_pool_fields_delegates_to_auto_sync(
        self,
        mock_inbox_append,
    ):
        result = {"synced": [{"skill": "s1", "agents": ["a"]}], "sync_failed": []}
        assert await skills_module.post_pool_automation_inbox(result) is True
        kwargs = mock_inbox_append.await_args.kwargs
        assert kwargs["event_type"] == "auto_sync"

    async def test_pool_update_success_event(self, mock_inbox_append):
        result = {
            "pool_updated": [
                {"skill": "p1", "from_version": "1", "to_version": "2"},
            ],
            "pool_failed": [],
            "synced": [],
            "sync_failed": [],
        }
        assert await skills_module.post_pool_automation_inbox(result) is True
        kwargs = mock_inbox_append.await_args.kwargs
        assert kwargs["event_type"] == "auto_update"
        assert kwargs["status"] == "success"
        assert "p1: 1 → 2" in kwargs["body"]

    async def test_pool_failure_marks_error(self, mock_inbox_append):
        result = {
            "pool_updated": [],
            "pool_failed": [{"skill": "p2"}],
            "synced": [],
            "sync_failed": [],
        }
        assert await skills_module.post_pool_automation_inbox(result) is True
        kwargs = mock_inbox_append.await_args.kwargs
        assert kwargs["status"] == "error"
        assert "0 updated, 1 failed" in kwargs["title"]


# ---------------------------------------------------------------------------
# POST /api/skills (workspace create)
# ---------------------------------------------------------------------------


class TestCreateSkill:
    def test_created_success(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.create_skill.return_value = "new_skill"
        response = client.post(
            "/api/skills",
            json={"name": "new_skill", "content": "# md", "enable": True},
        )
        assert response.status_code == 200
        assert response.json() == {"created": True, "name": "new_skill"}
        mock_schedule_reload.assert_called_once()

    def test_create_without_enable_skips_reload(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.create_skill.return_value = "new_skill"
        response = client.post(
            "/api/skills",
            json={"name": "new_skill", "content": "# md", "enable": False},
        )
        assert response.status_code == 200
        mock_schedule_reload.assert_not_called()

    def test_conflict_returns_409_with_suggestion(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.create_skill.return_value = None
        with patch(
            "qwenpaw.app.routers.skills.suggest_conflict_name",
            return_value="new_skill_2",
        ):
            response = client.post(
                "/api/skills",
                json={"name": "new_skill", "content": "# md"},
            )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "conflict"
        assert response.json()["detail"]["suggested_name"] == "new_skill_2"

    def test_invalid_name_returns_400(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.create_skill.side_effect = ValueError("bad")
        response = client.post(
            "/api/skills",
            json={"name": "../evil", "content": "# md"},
        )
        assert response.status_code == 400

    def test_scan_error_returns_structured_422(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.create_skill.side_effect = _scan_error()
        response = client.post(
            "/api/skills",
            json={"name": "blocked_skill", "content": "# md"},
        )
        assert response.status_code == 422
        detail = response.json()
        assert detail["type"] == "security_scan_failed"
        assert detail["skill_name"] == "blocked_skill"
        assert detail["findings"][0]["rule_id"] == "R1"


# ---------------------------------------------------------------------------
# POST /api/skills/pool/create
# ---------------------------------------------------------------------------


class TestCreatePoolSkill:
    def test_created_success(self, client, mock_pool_service):
        mock_pool_service.create_skill.return_value = "pool_skill"
        response = client.post(
            "/api/skills/pool/create",
            json={"name": "pool_skill", "content": "# md"},
        )
        assert response.status_code == 200
        assert response.json() == {"created": True, "name": "pool_skill"}

    def test_conflict_returns_409(self, client, mock_pool_service):
        mock_pool_service.create_skill.return_value = None
        with patch(
            "qwenpaw.app.routers.skills.suggest_conflict_name",
            return_value="pool_skill_2",
        ):
            response = client.post(
                "/api/skills/pool/create",
                json={"name": "pool_skill", "content": "# md"},
            )
        assert response.status_code == 409

    def test_scan_error_returns_422(self, client, mock_pool_service):
        mock_pool_service.create_skill.side_effect = _scan_error()
        response = client.post(
            "/api/skills/pool/create",
            json={"name": "blocked_skill", "content": "# md"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/skills/pool/save
# ---------------------------------------------------------------------------


class TestSavePoolSkill:
    def test_save_success_follows_auto_sync(self, client, mock_pool_service):
        mock_pool_service.save_pool_skill.return_value = {
            "success": True,
            "name": "renamed",
        }
        with patch(
            "qwenpaw.app.routers.skills.run_pool_auto_sync",
            return_value=None,
        ) as sync_mock, patch(
            "qwenpaw.app.routers.skills.append_inbox_event",
            new=AsyncMock(return_value=None),
        ):
            response = client.put(
                "/api/skills/pool/save",
                json={"name": "renamed", "content": "# md"},
            )
        assert response.status_code == 200
        assert response.json()["name"] == "renamed"
        sync_mock.assert_called_once()

    def test_save_not_found_returns_404(self, client, mock_pool_service):
        mock_pool_service.save_pool_skill.return_value = {
            "success": False,
            "reason": "not_found",
        }
        response = client.put(
            "/api/skills/pool/save",
            json={"name": "missing", "content": "# md"},
        )
        assert response.status_code == 404

    def test_save_conflict_returns_409(self, client, mock_pool_service):
        mock_pool_service.save_pool_skill.return_value = {
            "success": False,
            "reason": "conflict",
        }
        response = client.put(
            "/api/skills/pool/save",
            json={"name": "dup", "content": "# md"},
        )
        assert response.status_code == 409


# ---------------------------------------------------------------------------
# PUT /api/skills/save (workspace save)
# ---------------------------------------------------------------------------


class TestSaveWorkspaceSkill:
    def test_save_success_reloads_agent(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.save_skill.return_value = {
            "success": True,
            "mode": "updated",
        }
        response = client.put(
            "/api/skills/save",
            json={"name": "s1", "content": "# md"},
        )
        assert response.status_code == 200
        mock_schedule_reload.assert_called_once()

    def test_noop_mode_skips_reload(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.save_skill.return_value = {
            "success": True,
            "mode": "noop",
        }
        response = client.put(
            "/api/skills/save",
            json={"name": "s1", "content": "# md"},
        )
        assert response.status_code == 200
        mock_schedule_reload.assert_not_called()

    def test_conflict_returns_409(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.save_skill.return_value = {
            "success": False,
            "reason": "conflict",
        }
        response = client.put(
            "/api/skills/save",
            json={"name": "s1", "content": "# md"},
        )
        assert response.status_code == 409

    def test_missing_skill_returns_404(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.save_skill.return_value = {
            "success": False,
            "reason": "not_found",
        }
        response = client.put(
            "/api/skills/save",
            json={"name": "ghost", "content": "# md"},
        )
        assert response.status_code == 404

    def test_scan_error_returns_422(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.save_skill.side_effect = _scan_error()
        response = client.put(
            "/api/skills/save",
            json={"name": "blocked_skill", "content": "# md"},
        )
        assert response.status_code == 422
        assert response.json()["type"] == "security_scan_failed"


# ---------------------------------------------------------------------------
# POST /api/skills/upload
# ---------------------------------------------------------------------------


class TestUploadSkillZip:
    def test_rejects_bad_content_type(self, client, patch_get_agent):
        response = client.post(
            "/api/skills/upload",
            files={"file": ("evil.txt", b"not a zip", "text/plain")},
        )
        assert response.status_code == 400
        assert "zip" in response.json()["detail"]

    def test_rejects_invalid_rename_map_json(
        self,
        client,
        patch_get_agent,
    ):
        # ``rename_map`` is a query parameter, not a form field.
        response = client.post(
            "/api/skills/upload?rename_map=%7Bnot%20json",
            files={
                "file": (
                    "skill.zip",
                    _zip_bytes(),
                    "application/zip",
                ),
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "rename_map must be valid JSON"

    def test_rejects_non_object_rename_map(
        self,
        client,
        patch_get_agent,
    ):
        response = client.post(
            "/api/skills/upload?rename_map=%5B1%2C%202%5D",
            files={
                "file": ("skill.zip", _zip_bytes(), "application/zip"),
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == (
            "rename_map must be a JSON object"
        )

    def test_import_success_reloads_agent(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.import_from_zip.return_value = {
            "count": 1,
            "skills": ["s1"],
        }
        response = client.post(
            "/api/skills/upload?enable=true",
            files={
                "file": ("skill.zip", _zip_bytes(), "application/zip"),
            },
        )
        assert response.status_code == 200
        assert response.json()["count"] == 1
        mock_schedule_reload.assert_called_once()

    def test_conflicts_return_409(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.import_from_zip.return_value = {
            "conflicts": ["s1"],
        }
        response = client.post(
            "/api/skills/upload",
            files={
                "file": ("skill.zip", _zip_bytes(), "application/zip"),
            },
        )
        assert response.status_code == 409

    def test_scan_error_returns_422(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.import_from_zip.side_effect = _scan_error()
        response = client.post(
            "/api/skills/upload",
            files={
                "file": ("skill.zip", _zip_bytes(), "application/zip"),
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/skills/pool/upload-zip
# ---------------------------------------------------------------------------


class TestUploadPoolSkillZip:
    def test_import_success_follows_auto_sync(self, client, mock_pool_service):
        mock_pool_service.import_from_zip.return_value = {
            "count": 1,
            "skills": ["p1"],
        }
        with patch(
            "qwenpaw.app.routers.skills.run_pool_auto_sync",
            return_value=None,
        ) as sync_mock, patch(
            "qwenpaw.app.routers.skills.append_inbox_event",
            new=AsyncMock(return_value=None),
        ):
            response = client.post(
                "/api/skills/pool/upload-zip",
                files={
                    "file": ("skill.zip", _zip_bytes(), "application/zip"),
                },
            )
        assert response.status_code == 200
        sync_mock.assert_called_once()

    def test_rejects_invalid_rename_map(self, client):
        response = client.post(
            "/api/skills/pool/upload-zip?rename_map=%7Bbad",
            files={
                "file": ("skill.zip", _zip_bytes(), "application/zip"),
            },
        )
        assert response.status_code == 400

    def test_conflicts_return_409(self, client, mock_pool_service):
        mock_pool_service.import_from_zip.return_value = {"conflicts": ["p"]}
        response = client.post(
            "/api/skills/pool/upload-zip",
            files={
                "file": ("skill.zip", _zip_bytes(), "application/zip"),
            },
        )
        assert response.status_code == 409


# ---------------------------------------------------------------------------
# batch operations
# ---------------------------------------------------------------------------


class TestBatchDeleteSkills:
    def test_per_skill_results(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.delete_skill.side_effect = [True, False]
        response = client.post(
            "/api/skills/batch-delete",
            json=["ok", "bad"],
        )
        assert response.status_code == 200
        results = response.json()["results"]
        assert results["ok"] == {"success": True, "reason": None}
        assert results["bad"]["success"] is False
        assert results["bad"]["reason"] == "delete_failed"

    def test_exception_reported_per_skill(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.delete_skill.side_effect = RuntimeError("io")
        response = client.post(
            "/api/skills/batch-delete",
            json=["boom"],
        )
        results = response.json()["results"]
        assert results["boom"]["success"] is False
        assert "io" in results["boom"]["reason"]


class TestBatchDeletePoolSkills:
    def test_per_skill_results(self, client, mock_pool_service):
        mock_pool_service.delete_skill.return_value = True
        response = client.post(
            "/api/skills/pool/batch-delete",
            json=["p1"],
        )
        assert response.status_code == 200
        assert response.json()["results"]["p1"]["success"] is True


class TestBatchDisableSkills:
    def test_reload_when_any_succeeded(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.disable_skill.side_effect = [
            {"success": True},
            {"success": False},
        ]
        response = client.post(
            "/api/skills/batch-disable",
            json=["a", "b"],
        )
        assert response.status_code == 200
        mock_schedule_reload.assert_called_once()

    def test_no_reload_when_all_failed(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.disable_skill.return_value = {"success": False}
        response = client.post(
            "/api/skills/batch-disable",
            json=["a"],
        )
        assert response.status_code == 200
        mock_schedule_reload.assert_not_called()


class TestBatchEnableSkills:
    def test_partial_success_continues_batch(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.enable_skill.side_effect = [
            {"success": True},
            _scan_error(),
        ]
        response = client.post(
            "/api/skills/batch-enable",
            json=["ok_skill", "blocked_skill"],
        )
        assert response.status_code == 200
        results = response.json()["results"]
        assert results["ok_skill"]["success"] is True
        assert results["blocked_skill"]["reason"] == "security_scan_failed"
        assert results["blocked_skill"]["detail"]["skill_name"] == (
            "blocked_skill"
        )
        mock_schedule_reload.assert_called_once()

    def test_no_reload_when_nothing_enabled(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.enable_skill.return_value = {"success": False}
        response = client.post(
            "/api/skills/batch-enable",
            json=["ghost"],
        )
        assert response.status_code == 200
        mock_schedule_reload.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/skills/{name}/enable
# ---------------------------------------------------------------------------


class TestEnableSkill:
    def test_enable_success_reloads(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.enable_skill.return_value = {"success": True}
        response = client.post("/api/skills/s1/enable")
        assert response.status_code == 200
        assert response.json()["enabled"] is True
        mock_schedule_reload.assert_called_once()

    def test_enable_missing_returns_404(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.enable_skill.return_value = {
            "success": False,
            "reason": "not_found",
        }
        response = client.post("/api/skills/ghost/enable")
        assert response.status_code == 404

    def test_enable_scan_error_returns_422(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.enable_skill.side_effect = _scan_error()
        response = client.post("/api/skills/blocked_skill/enable")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# skill config endpoints (real manifest on tmp workspace)
# ---------------------------------------------------------------------------


class TestSkillConfigEndpoints:
    def _write_manifest(self, workspace_dir: Path, skills: dict):
        manifest = {
            "schema_version": "workspace-skill-manifest.v1",
            "version": 1,
            "skills": skills,
        }
        (workspace_dir / "skill.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

    def test_put_config_updates_existing_entry(
        self,
        client,
        patch_get_agent,
        fake_workspace,
    ):
        self._write_manifest(
            Path(fake_workspace.workspace_dir),
            {"s1": {"name": "s1"}},
        )
        response = client.put(
            "/api/skills/s1/config",
            json={"config": {"api_key": "k1"}},
        )
        assert response.status_code == 200
        assert response.json() == {"updated": True}
        saved = json.loads(
            (Path(fake_workspace.workspace_dir) / "skill.json").read_text(
                encoding="utf-8",
            ),
        )
        assert saved["skills"]["s1"]["config"] == {"api_key": "k1"}

    def test_put_config_unknown_skill_returns_404(
        self,
        client,
        patch_get_agent,
    ):
        response = client.put(
            "/api/skills/ghost/config",
            json={"config": {}},
        )
        assert response.status_code == 404

    def test_delete_config_clears_entry(
        self,
        client,
        patch_get_agent,
        fake_workspace,
    ):
        self._write_manifest(
            Path(fake_workspace.workspace_dir),
            {"s1": {"name": "s1", "config": {"old": True}}},
        )
        response = client.delete("/api/skills/s1/config")
        assert response.status_code == 200
        assert response.json() == {"cleared": True}
        saved = json.loads(
            (Path(fake_workspace.workspace_dir) / "skill.json").read_text(
                encoding="utf-8",
            ),
        )
        assert "config" not in saved["skills"]["s1"]

    def test_delete_config_unknown_skill_returns_404(
        self,
        client,
        patch_get_agent,
    ):
        response = client.delete("/api/skills/ghost/config")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/skills/pool/{name}/automation
# ---------------------------------------------------------------------------


class TestUpdatePoolSkillAutomation:
    def test_rejects_null_auto_update(self, client):
        response = client.put(
            "/api/skills/pool/s1/automation",
            json={"auto_update": None},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == (
            "auto_update must be true or false"
        )

    def test_rejects_empty_body(self, client):
        response = client.put(
            "/api/skills/pool/s1/automation",
            json={},
        )
        assert response.status_code == 422
        assert "At least one automation setting" in response.json()["detail"]

    def test_success_returns_automation_state(
        self,
        client,
        mock_pool_service,
    ):
        mock_pool_service.set_skill_automation.return_value = {
            "success": True,
            "auto_update": True,
            "auto_sync": {"enabled": True, "targets": ["default"]},
            "automation": {
                "pool_updated": [],
                "pool_failed": [],
                "synced": [],
                "sync_failed": [],
            },
        }
        with patch(
            "qwenpaw.app.routers.skills.append_inbox_event",
            new=AsyncMock(return_value=None),
        ):
            response = client.put(
                "/api/skills/pool/s1/automation",
                json={
                    "auto_update": True,
                    "auto_sync": {"enabled": True, "targets": ["default"]},
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["updated"] is True
        assert body["auto_update"] is True
        assert body["auto_sync"]["targets"] == ["default"]

    def test_not_found_returns_404(self, client, mock_pool_service):
        mock_pool_service.set_skill_automation.return_value = {
            "success": False,
            "reason": "not_found",
        }
        response = client.put(
            "/api/skills/pool/ghost/automation",
            json={"auto_update": True},
        )
        assert response.status_code == 404

    def test_not_builtin_returns_400(self, client, mock_pool_service):
        mock_pool_service.set_skill_automation.return_value = {
            "success": False,
            "reason": "not_builtin",
        }
        response = client.put(
            "/api/skills/pool/custom/automation",
            json={"auto_update": True},
        )
        assert response.status_code == 400
        assert "builtin" in response.json()["detail"]

    def test_auto_sync_only_passes_no_targets(
        self,
        client,
        mock_pool_service,
    ):
        mock_pool_service.set_skill_automation.return_value = {
            "success": True,
            "auto_update": False,
            "auto_sync": {"enabled": False},
            "automation": {},
        }
        with patch(
            "qwenpaw.app.routers.skills.append_inbox_event",
            new=AsyncMock(return_value=None),
        ):
            response = client.put(
                "/api/skills/pool/s1/automation",
                json={"auto_sync": {"enabled": False}},
            )
        assert response.status_code == 200
        call_kwargs = mock_pool_service.set_skill_automation.call_args.kwargs
        assert "auto_sync_targets" not in call_kwargs
        assert call_kwargs["auto_sync_enabled"] is False
        assert call_kwargs["auto_update"] is None


# ---------------------------------------------------------------------------
# POST /api/skills/pool/download
# ---------------------------------------------------------------------------


class TestDownloadPoolSkill:
    def test_no_targets_returns_400(self, client):
        with patch(
            "qwenpaw.app.routers.skills.list_workspaces",
            return_value=[],
        ):
            response = client.post(
                "/api/skills/pool/download",
                json={"skill_name": "s1"},
            )
        assert response.status_code == 400
        assert "No workspace targets" in response.json()["detail"]

    def test_preview_only_returns_empty_downloads(
        self,
        client,
        mock_pool_service,
    ):
        with patch(
            "qwenpaw.app.routers.skills._preflight_download_conflicts",
            return_value=[],
        ):
            response = client.post(
                "/api/skills/pool/download",
                json={
                    "skill_name": "s1",
                    "targets": [{"workspace_id": "default"}],
                    "preview_only": True,
                },
            )
        assert response.status_code == 200
        assert response.json() == {"downloaded": []}

    def test_preflight_conflict_returns_409(
        self,
        client,
        mock_pool_service,
    ):
        with patch(
            "qwenpaw.app.routers.skills._preflight_download_conflicts",
            return_value=[{"workspace_id": "default", "skill": "s1"}],
        ):
            response = client.post(
                "/api/skills/pool/download",
                json={
                    "skill_name": "s1",
                    "targets": [{"workspace_id": "default"}],
                },
            )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["downloaded"] == []
        assert detail["conflicts"]

    def test_all_workspaces_flag_resolves_targets(
        self,
        client,
        mock_pool_service,
    ):
        with patch(
            "qwenpaw.app.routers.skills.list_workspaces",
            return_value=[{"agent_id": "default"}, {"agent_id": "work"}],
        ), patch(
            "qwenpaw.app.routers.skills._preflight_download_conflicts",
            return_value=[],
        ), patch(
            "qwenpaw.app.routers.skills._build_download_plan",
            return_value=[],
        ):
            response = client.post(
                "/api/skills/pool/download",
                json={"skill_name": "s1", "all_workspaces": True},
            )
        assert response.status_code == 200
        assert response.json() == {"downloaded": []}
