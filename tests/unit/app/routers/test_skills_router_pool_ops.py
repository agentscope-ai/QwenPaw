# -*- coding: utf-8 -*-
"""Unit tests for the skills router pool operations and install worker.

The read-side, mutation-side and helper-side test files already cover
listing, creation and the snapshot/rollback helpers.  What stayed
untested is the wiring that turns failures into API responses:

- ``_run_hub_install_task``: the whole background worker, including the
  cancelled-after-import rollback, every exception mapping onto a task
  status, and the runtime registry cleanup that releases retention
- ``_cleanup_imported_skill`` and the ``_follow_auto_sync`` failure leg
- the pool read/write routes (detail, delete, config get/put/delete,
  tags, auto-sync) and their 404/409/422 mappings
- ``POST /pool/import``, ``POST /pool/upload`` and the download plan:
  preflight conflicts, all-or-nothing rollback and temp dir removal
- builtin import/update routes and the pool refresh endpoints
- the workspace-side routes whose failure legs were untested
  (disable, get, delete, file load, channels, preload, tags, config)

Everything is driven with stub services so no packaged builtin skill,
network call or real workspace is touched.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import asyncio
import json
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from qwenpaw.agents.skill_system.hub import HubInstallResult
from qwenpaw.app.routers import skills as skills_module
from qwenpaw.app.routers.skills import router as skills_router
from qwenpaw.exceptions import (
    AppBaseException,
    SkillConflictError,
    SkillImportCancelled,
    SkillScanError,
)

ZIP_MAGIC = b"PK\x03\x04dummy"


def _scan_error(skill_name: str = "blocked_skill") -> SkillScanError:
    finding = SimpleNamespace(
        severity=SimpleNamespace(value="high"),
        title="exec usage",
        description="runs a shell",
        file_path="scripts/run.sh",
        line_number=3,
        rule_id="R1",
    )
    result = SimpleNamespace(
        skill_name=skill_name,
        max_severity=SimpleNamespace(value="high"),
        findings=[finding],
    )
    return SkillScanError(result)


def _install_result(name: str = "demo") -> HubInstallResult:
    return HubInstallResult(
        name=name,
        enabled=True,
        source_url="https://hub.example/demo",
        installed_from="github",
    )


def _zip_upload() -> dict[str, Any]:
    return {
        "file": ("skill.zip", ZIP_MAGIC, "application/zip"),
    }


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
    with patch.object(
        skills_module,
        "SkillService",
        return_value=service,
    ):
        yield service


@pytest.fixture
def mock_pool_service():
    service = MagicMock(name="SkillPoolServiceInstance")
    with patch.object(
        skills_module,
        "SkillPoolService",
        return_value=service,
    ):
        yield service


@pytest.fixture
def mock_schedule_reload():
    with patch.object(skills_module, "schedule_agent_reload") as patched:
        yield patched


@pytest.fixture
def no_auto_sync():
    """Silence the Auto Sync follow-up so routes stay side-effect free."""
    with patch.object(
        skills_module,
        "_follow_auto_sync",
        new=AsyncMock(return_value=None),
    ) as patched:
        yield patched


@pytest.fixture
def workspace_agent(tmp_path: Path, monkeypatch):
    """Point the request-scoped agent lookup at a real temp workspace."""
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    workspace_dir = tmp_path / "workspaces" / "agent_x"
    workspace_dir.mkdir(parents=True)
    workspace = SimpleNamespace(
        workspace_dir=str(workspace_dir),
        agent_id="agent_x",
    )
    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=AsyncMock(return_value=workspace),
    ):
        yield workspace_dir


def _register_task(
    task_id: str = "task-1",
    status: skills_module.HubInstallTaskStatus = (
        skills_module.HubInstallTaskStatus.PENDING
    ),
) -> skills_module.HubInstallTask:
    task = skills_module.HubInstallTask(
        task_id=task_id,
        bundle_url="https://hub.example/demo.zip",
        status=status,
    )
    skills_module._hub_install_tasks[task_id] = task
    return task


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


def _write_pool_manifest(
    pool_dir: Path,
    skills: dict,
    builtin_names: list[str] | None = None,
) -> None:
    pool_dir.mkdir(parents=True, exist_ok=True)
    (pool_dir / "skill.json").write_text(
        json.dumps(
            {
                "schema_version": "skill-pool-manifest.v1",
                "version": 0,
                "skills": skills,
                "builtin_skill_names": builtin_names or [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_skill(skill_dir: Path, name: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d for {name}\n---\n# body\n",
        encoding="utf-8",
    )


def _read_pool_manifest(pool_dir: Path) -> dict:
    return json.loads((pool_dir / "skill.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# _cleanup_imported_skill
# ---------------------------------------------------------------------------


class TestCleanupImportedSkill:
    def test_empty_name_is_noop(self, tmp_path: Path):
        with patch.object(skills_module, "SkillService") as ctor:
            skills_module._cleanup_imported_skill(tmp_path, "")
        ctor.assert_not_called()

    def test_disables_then_deletes(self, tmp_path: Path):
        service = MagicMock(name="ServiceStub")
        calls: list[tuple[str, str]] = []
        service.disable_skill.side_effect = lambda name: calls.append(
            ("disable", name),
        )
        service.delete_skill.side_effect = lambda name: calls.append(
            ("delete", name),
        )
        with patch.object(
            skills_module,
            "SkillService",
            return_value=service,
        ) as ctor:
            skills_module._cleanup_imported_skill(tmp_path, "demo")

        ctor.assert_called_once_with(tmp_path)
        assert calls == [("disable", "demo"), ("delete", "demo")]

    def test_service_failure_is_swallowed(self, tmp_path: Path):
        with patch.object(
            skills_module,
            "SkillService",
            side_effect=RuntimeError("no pool"),
        ):
            skills_module._cleanup_imported_skill(tmp_path, "demo")


# ---------------------------------------------------------------------------
# _follow_auto_sync
# ---------------------------------------------------------------------------


class TestFollowAutoSync:
    async def test_success_forwards_result_to_inbox(self):
        result = {"synced": [], "failed": []}
        with patch.object(
            skills_module,
            "run_pool_auto_sync",
            return_value=result,
        ) as sync_mock, patch.object(
            skills_module,
            "post_auto_sync_inbox",
            new=AsyncMock(return_value=True),
        ) as post_mock:
            await skills_module._follow_auto_sync("demo")

        sync_mock.assert_called_once_with(skill_name="demo")
        post_mock.assert_awaited_once_with(result)

    async def test_exception_is_logged_not_raised(self):
        with patch.object(
            skills_module,
            "run_pool_auto_sync",
            side_effect=RuntimeError("pool locked"),
        ), patch.object(
            skills_module,
            "post_auto_sync_inbox",
            new=AsyncMock(return_value=True),
        ) as post_mock:
            await skills_module._follow_auto_sync(None)

        post_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# _run_hub_install_task
# ---------------------------------------------------------------------------


class TestRunHubInstallTask:
    @staticmethod
    def _body(**overrides: Any) -> skills_module.HubInstallRequest:
        payload: dict[str, Any] = {
            "bundle_url": "https://hub.example/demo.zip",
            "version": "1.0",
            "enable": True,
            "target_name": "renamed",
        }
        payload.update(overrides)
        return skills_module.HubInstallRequest(**payload)

    @staticmethod
    async def _run(
        task_id: str,
        cancel_event: threading.Event,
        body: Any,
        workspace_dir: Path,
    ) -> None:
        await skills_module._run_hub_install_task(
            task_id=task_id,
            workspace_dir=workspace_dir,
            body=body,
            cancel_event=cancel_event,
        )

    async def test_completed_records_result(self, tmp_path: Path):
        task = _register_task()
        skills_module._hub_install_runtime_tasks[task.task_id] = MagicMock()
        with patch.object(
            skills_module,
            "install_skill_from_hub",
            new=AsyncMock(return_value=_install_result()),
        ) as install_mock:
            await self._run(
                task.task_id,
                threading.Event(),
                self._body(),
                tmp_path,
            )

        kwargs = install_mock.await_args.kwargs
        assert kwargs["bundle_url"] == "https://hub.example/demo.zip"
        assert kwargs["version"] == "1.0"
        assert kwargs["enable"] is True
        assert kwargs["target_name"] == "renamed"
        assert kwargs["workspace_dir"] == tmp_path
        assert callable(kwargs["cancel_checker"])
        assert task.status == skills_module.HubInstallTaskStatus.COMPLETED
        assert task.result == {
            "installed": True,
            "name": "demo",
            "enabled": True,
            "source_url": "https://hub.example/demo",
            "installed_from": "github",
        }
        assert task.task_id not in skills_module._hub_install_runtime_tasks

    async def test_cancel_during_import_cleans_up(self, tmp_path: Path):
        task = _register_task()
        cancel_event = threading.Event()

        async def _cancel_then_return(**_kwargs: Any) -> HubInstallResult:
            cancel_event.set()
            return _install_result()

        with patch.object(
            skills_module,
            "install_skill_from_hub",
            new=AsyncMock(side_effect=_cancel_then_return),
        ), patch.object(
            skills_module,
            "_cleanup_imported_skill",
        ) as cleanup_mock:
            await self._run(task.task_id, cancel_event, self._body(), tmp_path)

        cleanup_mock.assert_called_once_with(tmp_path, "demo")
        assert task.status == skills_module.HubInstallTaskStatus.CANCELLED
        assert task.result == {
            "installed": False,
            "name": "demo",
            "enabled": False,
            "source_url": "https://hub.example/demo",
            "installed_from": "github",
        }
        assert task.task_id not in skills_module._hub_install_runtime_tasks

    async def test_no_cancel_keeps_installed_skill(self, tmp_path: Path):
        task = _register_task()
        with patch.object(
            skills_module,
            "install_skill_from_hub",
            new=AsyncMock(return_value=_install_result()),
        ), patch.object(
            skills_module,
            "_cleanup_imported_skill",
        ) as cleanup_mock:
            await self._run(
                task.task_id,
                threading.Event(),
                self._body(),
                tmp_path,
            )

        cleanup_mock.assert_not_called()

    async def test_import_cancelled_has_no_name_to_clean(
        self,
        tmp_path: Path,
    ):
        task = _register_task()
        with patch.object(
            skills_module,
            "install_skill_from_hub",
            new=AsyncMock(side_effect=SkillImportCancelled()),
        ), patch.object(
            skills_module,
            "_cleanup_imported_skill",
        ) as cleanup_mock:
            await self._run(
                task.task_id,
                threading.Event(),
                self._body(),
                tmp_path,
            )

        # the worker only learns the name from a successful return, so a
        # mid-flight cancellation has nothing registered to roll back
        cleanup_mock.assert_not_called()
        assert task.status == skills_module.HubInstallTaskStatus.CANCELLED
        assert task.error is None

    async def test_cancel_arriving_after_import_rolls_back(
        self,
        tmp_path: Path,
    ):
        """A cancellation raised after the import finished still rolls back.

        ``imported_skill_name`` is only known once the import returns, so
        the guard that deletes the freshly written skill has to fire from
        a later failure inside the worker rather than from the import
        itself.  Whatever raises it, the observable contract is the same:
        the imported skill is removed and the task ends up cancelled.
        """
        task = _register_task()
        original_set_status = skills_module._hub_task_set_status
        calls: list[skills_module.HubInstallTaskStatus] = []

        async def _set_status_then_cancel(
            task_id: str,
            status: skills_module.HubInstallTaskStatus,
            **kwargs: Any,
        ) -> None:
            calls.append(status)
            if status == skills_module.HubInstallTaskStatus.COMPLETED:
                raise SkillImportCancelled()
            await original_set_status(task_id, status, **kwargs)

        with patch.object(
            skills_module,
            "install_skill_from_hub",
            new=AsyncMock(return_value=_install_result("late_demo")),
        ), patch.object(
            skills_module,
            "_hub_task_set_status",
            new=_set_status_then_cancel,
        ), patch.object(
            skills_module,
            "_cleanup_imported_skill",
        ) as cleanup_mock:
            await self._run(
                task.task_id,
                threading.Event(),
                self._body(),
                tmp_path,
            )

        cleanup_mock.assert_called_once_with(tmp_path, "late_demo")
        assert task.status == skills_module.HubInstallTaskStatus.CANCELLED
        assert calls[0] == skills_module.HubInstallTaskStatus.IMPORTING

    async def test_task_cancellation_reraises_and_releases_registry(
        self,
        tmp_path: Path,
    ):
        task = _register_task()
        skills_module._hub_install_runtime_tasks[task.task_id] = MagicMock()
        skills_module._hub_install_cancel_events[
            task.task_id
        ] = threading.Event()
        with patch.object(
            skills_module,
            "install_skill_from_hub",
            new=AsyncMock(side_effect=asyncio.CancelledError()),
        ):
            with pytest.raises(asyncio.CancelledError):
                await self._run(
                    task.task_id,
                    threading.Event(),
                    self._body(),
                    tmp_path,
                )

        assert task.status == skills_module.HubInstallTaskStatus.CANCELLED
        assert task.task_id not in skills_module._hub_install_runtime_tasks
        assert task.task_id not in skills_module._hub_install_cancel_events

    async def test_scan_error_records_structured_payload(
        self,
        tmp_path: Path,
    ):
        task = _register_task()
        with patch.object(
            skills_module,
            "install_skill_from_hub",
            new=AsyncMock(side_effect=_scan_error("bad_skill")),
        ):
            await self._run(
                task.task_id,
                threading.Event(),
                self._body(),
                tmp_path,
            )

        assert task.status == skills_module.HubInstallTaskStatus.FAILED
        assert task.error is not None
        assert task.result is not None
        # Read through model_dump(): pylint cannot narrow the Optional
        # annotations via the asserts above, and this is how the existing
        # suites subscript pydantic payloads too.
        recorded = task.model_dump()
        assert "bad_skill" in recorded["error"]
        assert recorded["result"]["type"] == "security_scan_failed"
        assert recorded["result"]["skill_name"] == "bad_skill"
        assert recorded["result"]["findings"][0]["rule_id"] == "R1"

    async def test_conflict_error_records_detail(self, tmp_path: Path):
        task = _register_task()
        detail = {"reason": "conflict", "skill_name": "demo"}
        with patch.object(
            skills_module,
            "install_skill_from_hub",
            new=AsyncMock(side_effect=SkillConflictError(detail)),
        ):
            await self._run(
                task.task_id,
                threading.Event(),
                self._body(),
                tmp_path,
            )

        assert task.status == skills_module.HubInstallTaskStatus.FAILED
        assert task.result == detail

    @pytest.mark.parametrize(
        "exc,expected_error",
        [
            (ValueError("bad bundle"), "bad bundle"),
            (AppBaseException("app failure"), "app failure"),
            (RuntimeError("hub down"), "hub down"),
        ],
    )
    async def test_other_failures_record_message(
        self,
        tmp_path: Path,
        exc: Exception,
        expected_error: str,
    ):
        task = _register_task()
        with patch.object(
            skills_module,
            "install_skill_from_hub",
            new=AsyncMock(side_effect=exc),
        ):
            await self._run(
                task.task_id,
                threading.Event(),
                self._body(),
                tmp_path,
            )

        assert task.status == skills_module.HubInstallTaskStatus.FAILED
        assert task.error == expected_error
        assert task.result is None

    async def test_evicted_task_status_writes_are_dropped(
        self,
        tmp_path: Path,
    ):
        # The registry may have evicted the task before the worker ran.
        with patch.object(
            skills_module,
            "install_skill_from_hub",
            new=AsyncMock(return_value=_install_result()),
        ):
            await self._run(
                "evicted",
                threading.Event(),
                self._body(),
                tmp_path,
            )

        assert "evicted" not in skills_module._hub_install_tasks
        assert "evicted" not in skills_module._hub_install_runtime_tasks


# ---------------------------------------------------------------------------
# spec/detail builder failure legs
# ---------------------------------------------------------------------------


class TestSpecBuilderFailureLegs:
    def test_workspace_spec_build_error_is_skipped(
        self,
        workspace_agent,
    ):
        workspace_dir = workspace_agent
        _write_skill(workspace_dir / "skills" / "demo", "demo")
        _write_workspace_manifest(workspace_dir, {"demo": {"enabled": True}})
        with patch.object(
            skills_module,
            "build_skill_metadata",
            side_effect=RuntimeError("broken frontmatter"),
        ):
            specs = skills_module._build_workspace_skill_specs(workspace_dir)
        assert specs == []

    def test_pool_spec_malformed_entry_still_builds(
        self,
        workspace_agent,
    ):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_skill(pool_dir / "demo", "demo")
        _write_pool_manifest(pool_dir, {"demo": "garbage"})
        with patch.object(
            skills_module,
            "get_pool_builtin_sync_status",
            lambda **_kwargs: {},
        ):
            specs = skills_module._build_pool_skill_specs()
        assert len(specs) == 1
        assert specs[0].source == "customized"
        assert specs[0].auto_update is False

    def test_pool_spec_build_error_is_skipped(self, workspace_agent):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_skill(pool_dir / "demo", "demo")
        _write_pool_manifest(pool_dir, {"demo": {"source": "customized"}})
        with patch.object(
            skills_module,
            "get_pool_builtin_sync_status",
            lambda **_kwargs: {},
        ), patch.object(
            skills_module,
            "build_skill_metadata",
            side_effect=RuntimeError("unreadable"),
        ):
            assert skills_module._build_pool_skill_specs() == []

    def test_workspace_detail_unsafe_name_returns_none(
        self,
        workspace_agent,
    ):
        workspace_dir = workspace_agent
        _write_workspace_manifest(workspace_dir, {"..": {"enabled": True}})
        with patch.object(
            skills_module,
            "safe_skill_dir",
            side_effect=AppBaseException("unsafe"),
        ):
            detail = skills_module._build_workspace_skill_detail(
                workspace_dir,
                "..",
            )
        assert detail is None

    def test_workspace_detail_without_skill_md_returns_none(
        self,
        workspace_agent,
    ):
        workspace_dir = workspace_agent
        _write_workspace_manifest(workspace_dir, {"ghost": {}})
        detail = skills_module._build_workspace_skill_detail(
            workspace_dir,
            "ghost",
        )
        assert detail is None

    def test_pool_detail_without_dir_returns_none(self, workspace_agent):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_pool_manifest(pool_dir, {"ghost": {"source": "customized"}})
        assert skills_module._build_pool_skill_detail("ghost") is None

    def test_pool_detail_without_skill_md_returns_none(self, workspace_agent):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        (pool_dir / "demo").mkdir(parents=True)
        _write_pool_manifest(pool_dir, {"demo": {"source": "customized"}})
        assert skills_module._build_pool_skill_detail("demo") is None

    def test_pool_detail_skill_md_as_directory_returns_none(
        self,
        workspace_agent,
    ):
        """Discovery accepts ``SKILL.md`` but reading it must not crash.

        ``resolve_pool_skill_dir`` only checks that the path exists, so a
        directory named ``SKILL.md`` passes discovery and then fails the
        reader, which must surface as "no such pool skill" rather than an
        exception escaping into the route.
        """
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        (pool_dir / "demo" / "SKILL.md").mkdir(parents=True)
        _write_pool_manifest(pool_dir, {"demo": {"source": "customized"}})
        assert skills_module._build_pool_skill_detail("demo") is None

    def test_pool_detail_builtin_auto_update_and_languages(
        self,
        workspace_agent,
    ):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_skill(pool_dir / "demo", "demo")
        _write_pool_manifest(
            pool_dir,
            {
                "demo": {
                    "source": "builtin",
                    "external": True,
                    "builtin_language": "en",
                    "available_builtin_languages": ["en", "", "zh"],
                    "automation": {
                        "auto_update": {"enabled": True},
                        "auto_sync": {
                            "enabled": True,
                            "targets": ["default"],
                        },
                    },
                },
            },
            builtin_names=["demo"],
        )
        with patch.object(
            skills_module,
            "get_pool_builtin_sync_status",
            lambda **_kwargs: {
                "demo": {
                    "sync_status": "outdated",
                    "available_languages": ["zh"],
                },
            },
        ):
            detail = skills_module._build_pool_skill_detail("demo")

        assert detail is not None
        assert detail.source == "builtin"
        assert detail.auto_update is True
        assert detail.auto_sync is True
        assert detail.auto_sync_targets == ["default"]
        assert detail.external is True
        assert detail.external_path.endswith("demo")
        assert detail.sync_status == "outdated"
        assert detail.builtin_language == "en"
        # sync-status languages win over the manifest copy, blanks dropped
        assert detail.available_builtin_languages == ["zh"]

    def test_list_names_skips_unsafe_entries(self, workspace_agent):
        workspace_dir = workspace_agent
        _write_skill(workspace_dir / "skills" / "demo", "demo")
        _write_workspace_manifest(workspace_dir, {"demo": {}, "bad": {}})

        def _safe(root: Path, name: str) -> Path:
            if name == "bad":
                raise AppBaseException("unsafe name")
            return root / name

        with patch.object(skills_module, "safe_skill_dir", side_effect=_safe):
            names = skills_module._list_workspace_skill_names(workspace_dir)
        assert names == ["demo"]


# ---------------------------------------------------------------------------
# list / refresh routes
# ---------------------------------------------------------------------------


class TestListAndRefreshRoutes:
    def test_refresh_skills_reconciles_then_lists(
        self,
        client,
        patch_get_agent,
        fake_workspace,
    ):
        order: list[str] = []
        expected_dir = Path(fake_workspace.workspace_dir)
        with patch.object(
            skills_module,
            "reconcile_workspace_manifest",
            side_effect=lambda _dir: order.append("reconcile"),
        ) as reconcile_mock, patch.object(
            skills_module,
            "_build_workspace_skill_specs",
            side_effect=lambda _dir: order.append("build") or [],
        ):
            response = client.post("/api/skills/refresh")

        assert response.status_code == 200
        assert response.json() == []
        reconcile_mock.assert_called_once_with(expected_dir)
        assert order == ["reconcile", "build"]

    def test_list_workspace_skill_sources_maps_names(self, client):
        with patch.object(
            skills_module,
            "list_workspaces",
            return_value=[
                {
                    "agent_id": "default",
                    "agent_name": "Default",
                    "workspace_dir": "/tmp/ws-default",
                },
                {
                    "agent_id": "work",
                    "workspace_dir": "/tmp/ws-work",
                },
            ],
        ), patch.object(
            skills_module,
            "_list_workspace_skill_names",
            side_effect=lambda workspace_dir: [Path(workspace_dir).name],
        ):
            response = client.get("/api/skills/workspaces")

        assert response.status_code == 200
        assert response.json() == [
            {
                "agent_id": "default",
                "agent_name": "Default",
                "skill_names": ["ws-default"],
            },
            {
                "agent_id": "work",
                "agent_name": "",
                "skill_names": ["ws-work"],
            },
        ]

    def test_list_workspace_skill_sources_empty(self, client):
        with patch.object(skills_module, "list_workspaces", return_value=[]):
            response = client.get("/api/skills/workspaces")
        assert response.status_code == 200
        assert response.json() == []

    def test_refresh_pool_skills_posts_inbox_and_lists(self, client):
        result = {
            "pool_updated": [{"skill": "demo"}],
            "pool_failed": [],
            "synced": [],
            "sync_failed": [],
        }
        with patch.object(
            skills_module,
            "refresh_pool_automation",
            return_value=result,
        ) as refresh_mock, patch.object(
            skills_module,
            "post_pool_automation_inbox",
            new=AsyncMock(return_value=True),
        ) as post_mock, patch.object(
            skills_module,
            "_build_pool_skill_specs",
            return_value=[],
        ):
            response = client.post("/api/skills/pool/refresh")

        assert response.status_code == 200
        refresh_mock.assert_called_once_with()
        post_mock.assert_awaited_once_with(result)

    def test_list_pool_builtin_sources_maps_specs(self, client):
        with patch.object(
            skills_module,
            "list_builtin_import_candidates",
            return_value=[
                {
                    "name": "demo",
                    "description": "d",
                    "version_text": "1.0",
                    "available_languages": ["en"],
                    "status": "missing",
                },
            ],
        ):
            response = client.get("/api/skills/pool/builtin-sources")

        assert response.status_code == 200
        body = response.json()
        assert body[0]["name"] == "demo"
        assert body[0]["status"] == "missing"
        assert body[0]["available_languages"] == ["en"]

    def test_get_pool_builtin_notice_maps_all_buckets(self, client):
        notice = {
            "fingerprint": "fp-1",
            "has_updates": True,
            "total_changes": 3,
            "actionable_skill_names": ["demo", ""],
            "added": [{"name": "added"}],
            "missing": [{"name": "missing"}],
            "updated": [{"name": "updated"}],
            "removed": [{"name": "removed"}],
        }
        with patch.object(
            skills_module,
            "get_pool_builtin_update_notice",
            return_value=notice,
        ):
            response = client.get("/api/skills/pool/builtin-notice")

        assert response.status_code == 200
        body = response.json()
        assert body["fingerprint"] == "fp-1"
        assert body["has_updates"] is True
        assert body["total_changes"] == 3
        assert body["actionable_skill_names"] == ["demo"]
        assert body["added"][0]["name"] == "added"
        assert body["removed"][0]["name"] == "removed"

    def test_get_pool_builtin_notice_defaults(self, client):
        with patch.object(
            skills_module,
            "get_pool_builtin_update_notice",
            return_value={},
        ):
            response = client.get("/api/skills/pool/builtin-notice")
        assert response.json() == {
            "fingerprint": "",
            "has_updates": False,
            "total_changes": 0,
            "actionable_skill_names": [],
            "added": [],
            "missing": [],
            "updated": [],
            "removed": [],
        }


# ---------------------------------------------------------------------------
# hub install route legs
# ---------------------------------------------------------------------------


class TestHubInstallRouteLegs:
    def test_cancel_terminal_task_returns_current_status(self, client):
        _register_task(
            "done-1",
            status=skills_module.HubInstallTaskStatus.COMPLETED,
        )
        response = client.post("/api/skills/hub/install/cancel/done-1")
        assert response.status_code == 200
        assert response.json() == {"task_id": "done-1", "status": "completed"}
        # a terminal task must not grow a cancel event
        assert "done-1" not in skills_module._hub_install_cancel_events

    def test_cancel_without_registered_event_still_marks_cancelled(
        self,
        client,
    ):
        task = _register_task("live-1")
        response = client.post("/api/skills/hub/install/cancel/live-1")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert task.status == skills_module.HubInstallTaskStatus.CANCELLED


# ---------------------------------------------------------------------------
# pool read/write routes
# ---------------------------------------------------------------------------


class TestPoolSkillRoutes:
    def test_get_pool_skill_returns_detail(self, client):
        detail = skills_module.PoolSkillDetail(
            name="demo",
            source="customized",
            content="# body",
        )
        with patch.object(
            skills_module,
            "_build_pool_skill_detail",
            return_value=detail,
        ) as build_mock:
            response = client.get("/api/skills/pool/demo")

        assert response.status_code == 200
        assert response.json()["name"] == "demo"
        build_mock.assert_called_once_with("demo")

    def test_get_pool_skill_404(self, client):
        with patch.object(
            skills_module,
            "_build_pool_skill_detail",
            return_value=None,
        ):
            response = client.get("/api/skills/pool/ghost")
        assert response.status_code == 404
        assert response.json()["detail"] == "Pool skill not found"

    def test_delete_pool_skill_success(self, client, mock_pool_service):
        mock_pool_service.delete_skill.return_value = True
        response = client.delete("/api/skills/pool/demo")
        assert response.status_code == 200
        assert response.json() == {"deleted": True}
        mock_pool_service.delete_skill.assert_called_once_with("demo")

    def test_delete_pool_skill_conflict(self, client, mock_pool_service):
        mock_pool_service.delete_skill.return_value = False
        response = client.delete("/api/skills/pool/demo")
        assert response.status_code == 409
        assert "cannot be deleted" in response.json()["detail"]


class TestPoolSkillConfigRoutes:
    def test_get_config_returns_entry_config(self, client, workspace_agent):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_pool_manifest(
            pool_dir,
            {"demo": {"source": "customized", "config": {"k": "v"}}},
        )
        response = client.get("/api/skills/pool/demo/config")
        assert response.status_code == 200
        assert response.json() == {"config": {"k": "v"}}

    def test_get_config_defaults_to_empty(self, client, workspace_agent):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_pool_manifest(pool_dir, {"demo": {"source": "customized"}})
        response = client.get("/api/skills/pool/demo/config")
        assert response.status_code == 200
        assert response.json() == {"config": {}}

    def test_get_config_unknown_skill_404(self, client, workspace_agent):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_pool_manifest(pool_dir, {})
        response = client.get("/api/skills/pool/ghost/config")
        assert response.status_code == 404
        assert response.json()["detail"] == "Pool skill not found"

    def test_put_config_persists(self, client, workspace_agent):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_pool_manifest(
            pool_dir,
            {"demo": {"source": "customized", "config": {"old": 1}}},
        )
        response = client.put(
            "/api/skills/pool/demo/config",
            json={"config": {"new": 2}},
        )
        assert response.status_code == 200
        assert response.json() == {"updated": True}
        saved = _read_pool_manifest(pool_dir)
        assert saved["skills"]["demo"]["config"] == {"new": 2}

    def test_put_config_unknown_skill_404(self, client, workspace_agent):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_pool_manifest(pool_dir, {"demo": {}})
        response = client.put(
            "/api/skills/pool/ghost/config",
            json={"config": {}},
        )
        assert response.status_code == 404

    def test_delete_config_clears_entry(self, client, workspace_agent):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_pool_manifest(
            pool_dir,
            {"demo": {"source": "customized", "config": {"k": "v"}}},
        )
        response = client.delete("/api/skills/pool/demo/config")
        assert response.status_code == 200
        assert response.json() == {"cleared": True}
        saved = _read_pool_manifest(pool_dir)
        assert "config" not in saved["skills"]["demo"]

    def test_delete_config_without_config_still_succeeds(
        self,
        client,
        workspace_agent,
    ):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_pool_manifest(pool_dir, {"demo": {"source": "customized"}})
        response = client.delete("/api/skills/pool/demo/config")
        assert response.status_code == 200
        assert response.json() == {"cleared": True}

    def test_delete_config_unknown_skill_404(self, client, workspace_agent):
        pool_dir = workspace_agent.parent.parent / "skill_pool"
        _write_pool_manifest(pool_dir, {})
        response = client.delete("/api/skills/pool/ghost/config")
        assert response.status_code == 404


class TestValidateTags:
    def test_too_many_tags_422(self):
        tags = ["t"] * (skills_module.MAX_TAGS + 1)
        with pytest.raises(HTTPException) as excinfo:
            skills_module._validate_tags(tags)
        assert excinfo.value.status_code == 422
        assert str(skills_module.MAX_TAGS) in excinfo.value.detail

    def test_exactly_max_tags_allowed(self):
        tags = [f"t{i}" for i in range(skills_module.MAX_TAGS)]
        assert skills_module._validate_tags(tags) == tags

    def test_strips_truncates_and_drops_blank(self):
        long_tag = "x" * (skills_module.MAX_TAG_LENGTH + 5)
        cleaned = skills_module._validate_tags(
            [long_tag, "  padded  ", "", "   "],
        )
        assert cleaned == ["x" * skills_module.MAX_TAG_LENGTH, "padded"]

    def test_empty_list_is_empty(self):
        assert skills_module._validate_tags([]) == []

    def test_route_tags_success(self, client, mock_pool_service):
        mock_pool_service.set_pool_skill_tags.return_value = True
        response = client.put("/api/skills/pool/demo/tags", json=[" alpha "])
        assert response.status_code == 200
        assert response.json() == {"updated": True, "tags": ["alpha"]}
        mock_pool_service.set_pool_skill_tags.assert_called_once_with(
            "demo",
            ["alpha"],
        )

    def test_route_tags_unknown_skill_404(self, client, mock_pool_service):
        mock_pool_service.set_pool_skill_tags.return_value = False
        response = client.put("/api/skills/pool/ghost/tags", json=["a"])
        assert response.status_code == 404

    def test_route_tags_rejects_too_many(self, client, mock_pool_service):
        tags = [f"t{i}" for i in range(skills_module.MAX_TAGS + 1)]
        response = client.put("/api/skills/pool/demo/tags", json=tags)
        assert response.status_code == 422
        mock_pool_service.set_pool_skill_tags.assert_not_called()


class TestPoolAutoSyncRoute:
    def test_success_echoes_request(self, client, mock_pool_service):
        mock_pool_service.set_skill_auto_sync.return_value = {
            "synced": [],
            "failed": [],
        }
        with patch.object(
            skills_module,
            "post_auto_sync_inbox",
            new=AsyncMock(return_value=True),
        ) as post_mock:
            response = client.put(
                "/api/skills/pool/demo/auto-sync",
                json={"enabled": True, "targets": ["default"]},
            )

        assert response.status_code == 200
        assert response.json() == {
            "updated": True,
            "enabled": True,
            "targets": ["default"],
        }
        post_mock.assert_awaited_once()
        kwargs = mock_pool_service.set_skill_auto_sync.call_args.kwargs
        assert kwargs["enabled"] is True
        assert kwargs["targets"] == ["default"]

    def test_deprecated_auto_update_route_shares_handler(
        self,
        client,
        mock_pool_service,
    ):
        mock_pool_service.set_skill_auto_sync.return_value = None
        response = client.put(
            "/api/skills/pool/demo/auto-update",
            json={"enabled": False},
        )
        # a missing pool skill maps to 404 on both spellings
        assert response.status_code == 404
        assert response.json()["detail"] == "Pool skill not found"

    def test_missing_skill_404(self, client, mock_pool_service):
        mock_pool_service.set_skill_auto_sync.return_value = None
        response = client.put(
            "/api/skills/pool/ghost/auto-sync",
            json={"enabled": True},
        )
        assert response.status_code == 404


class TestAutomationInvalidReason:
    def test_unknown_reason_returns_400_invalid(self, client):
        service = MagicMock(name="ServiceStub")
        service.set_skill_automation.return_value = {
            "success": False,
            "reason": "something_else",
        }
        with patch.object(
            skills_module,
            "SkillPoolService",
            return_value=service,
        ):
            response = client.put(
                "/api/skills/pool/demo/automation",
                json={"auto_update": True},
            )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid automation"


# ---------------------------------------------------------------------------
# POST /pool/import
# ---------------------------------------------------------------------------


class TestImportPoolFromHub:
    def test_success_follows_auto_sync(self, client):
        with patch.object(
            skills_module,
            "import_pool_skill_from_hub",
            new=AsyncMock(return_value=_install_result("imported")),
        ) as import_mock, patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ) as follow_mock:
            response = client.post(
                "/api/skills/pool/import",
                json={
                    "bundle_url": "https://hub.example/x.zip",
                    "version": "2.0",
                    "target_name": "renamed",
                },
            )

        assert response.status_code == 200
        assert response.json() == {
            "installed": True,
            "name": "imported",
            "enabled": False,
            "source_url": "https://hub.example/demo",
            "installed_from": "github",
        }
        kwargs = import_mock.await_args.kwargs
        assert kwargs["bundle_url"] == "https://hub.example/x.zip"
        assert kwargs["version"] == "2.0"
        assert kwargs["target_name"] == "renamed"
        follow_mock.assert_awaited_once_with("imported")

    def test_scan_error_returns_422(self, client):
        with patch.object(
            skills_module,
            "import_pool_skill_from_hub",
            new=AsyncMock(side_effect=_scan_error()),
        ):
            response = client.post(
                "/api/skills/pool/import",
                json={"bundle_url": "https://hub.example/x.zip"},
            )
        assert response.status_code == 422
        assert response.json()["type"] == "security_scan_failed"

    def test_conflict_returns_409_with_detail(self, client):
        detail = {"reason": "conflict", "skill_name": "demo"}
        with patch.object(
            skills_module,
            "import_pool_skill_from_hub",
            new=AsyncMock(side_effect=SkillConflictError(detail)),
        ):
            response = client.post(
                "/api/skills/pool/import",
                json={"bundle_url": "https://hub.example/x.zip"},
            )
        assert response.status_code == 409
        assert response.json()["detail"] == detail

    @pytest.mark.parametrize(
        "exc,expected_status",
        [
            (ValueError("bad url"), 400),
            (AppBaseException("app failure"), 400),
            (RuntimeError("hub conflict"), 409),
        ],
    )
    def test_failure_mappings(self, client, exc, expected_status):
        with patch.object(
            skills_module,
            "import_pool_skill_from_hub",
            new=AsyncMock(side_effect=exc),
        ):
            response = client.post(
                "/api/skills/pool/import",
                json={"bundle_url": "https://hub.example/x.zip"},
            )
        assert response.status_code == expected_status
        assert response.json()["detail"] == str(exc)


# ---------------------------------------------------------------------------
# POST /pool/upload (workspace -> pool)
# ---------------------------------------------------------------------------


class TestUploadWorkspaceSkillToPool:
    @staticmethod
    def _one_workspace():
        return patch.object(
            skills_module,
            "list_workspaces",
            return_value=[
                {"agent_id": "default", "workspace_dir": "/tmp/ws-default"},
            ],
        )

    def test_success_follows_auto_sync(self, client, mock_pool_service):
        mock_pool_service.upload_from_workspace.return_value = {
            "success": True,
            "name": "demo",
        }
        with self._one_workspace(), patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ) as follow_mock:
            response = client.post(
                "/api/skills/pool/upload",
                json={"workspace_id": "default", "skill_name": "demo"},
            )

        assert response.status_code == 200
        assert response.json()["success"] is True
        follow_mock.assert_awaited_once_with("demo")
        kwargs = mock_pool_service.upload_from_workspace.call_args.kwargs
        assert kwargs["workspace_dir"] == Path("/tmp/ws-default")
        assert kwargs["skill_name"] == "demo"
        assert kwargs["overwrite"] is False
        assert kwargs["preview_only"] is False

    def test_preview_only_skips_auto_sync(self, client, mock_pool_service):
        mock_pool_service.upload_from_workspace.return_value = {
            "success": True,
            "name": "demo",
        }
        with self._one_workspace(), patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ) as follow_mock:
            response = client.post(
                "/api/skills/pool/upload",
                json={
                    "workspace_id": "default",
                    "skill_name": "demo",
                    "preview_only": True,
                },
            )

        assert response.status_code == 200
        follow_mock.assert_not_awaited()

    def test_unknown_workspace_404(self, client):
        with patch.object(skills_module, "list_workspaces", return_value=[]):
            response = client.post(
                "/api/skills/pool/upload",
                json={"workspace_id": "ghost", "skill_name": "demo"},
            )
        assert response.status_code == 404
        assert "ghost" in response.json()["detail"]

    def test_scan_error_returns_422(self, client, mock_pool_service):
        mock_pool_service.upload_from_workspace.side_effect = _scan_error()
        with self._one_workspace():
            response = client.post(
                "/api/skills/pool/upload",
                json={"workspace_id": "default", "skill_name": "demo"},
            )
        assert response.status_code == 422

    def test_value_error_returns_400(self, client, mock_pool_service):
        mock_pool_service.upload_from_workspace.side_effect = ValueError(
            "bad name",
        )
        with self._one_workspace():
            response = client.post(
                "/api/skills/pool/upload",
                json={"workspace_id": "default", "skill_name": "demo"},
            )
        assert response.status_code == 400
        assert response.json()["detail"] == "bad name"

    def test_not_found_returns_404(self, client, mock_pool_service):
        mock_pool_service.upload_from_workspace.return_value = {
            "success": False,
            "reason": "not_found",
        }
        with self._one_workspace():
            response = client.post(
                "/api/skills/pool/upload",
                json={"workspace_id": "default", "skill_name": "demo"},
            )
        assert response.status_code == 404

    def test_conflict_returns_409(self, client, mock_pool_service):
        mock_pool_service.upload_from_workspace.return_value = {
            "success": False,
            "reason": "conflict",
            "suggested_name": "demo-1",
        }
        with self._one_workspace():
            response = client.post(
                "/api/skills/pool/upload",
                json={"workspace_id": "default", "skill_name": "demo"},
            )
        assert response.status_code == 409
        assert response.json()["detail"]["suggested_name"] == "demo-1"


# ---------------------------------------------------------------------------
# download preflight / plan / execution helpers
# ---------------------------------------------------------------------------


def _target(workspace_id: str = "default"):
    return skills_module.PoolDownloadTarget(workspace_id=workspace_id)


class TestPreflightDownloadConflicts:
    def test_all_success_returns_no_conflicts(self):
        service = MagicMock(name="ServiceStub")
        service.preflight_download_to_workspace.return_value = {
            "success": True,
        }
        with patch.object(
            skills_module,
            "_workspace_dir_for_agent",
            side_effect=lambda agent_id: Path(f"/tmp/{agent_id}"),
        ):
            conflicts = skills_module._preflight_download_conflicts(
                service,
                [_target("a"), _target("b")],
                "demo",
                False,
            )
        assert conflicts == []
        assert service.preflight_download_to_workspace.call_count == 2
        kwargs = service.preflight_download_to_workspace.call_args.kwargs
        assert kwargs["skill_name"] == "demo"
        assert kwargs["overwrite"] is False

    def test_conflict_is_collected_per_target(self):
        service = MagicMock(name="ServiceStub")
        service.preflight_download_to_workspace.side_effect = [
            {"success": True},
            {"success": False, "reason": "conflict", "skill_name": "demo"},
        ]
        with patch.object(
            skills_module,
            "_workspace_dir_for_agent",
            side_effect=lambda agent_id: Path(f"/tmp/{agent_id}"),
        ):
            conflicts = skills_module._preflight_download_conflicts(
                service,
                [_target("a"), _target("b")],
                "demo",
                True,
            )
        assert conflicts == [
            {"success": False, "reason": "conflict", "skill_name": "demo"},
        ]
        last = service.preflight_download_to_workspace.call_args.kwargs
        assert last["workspace_dir"] == Path("/tmp/b")
        assert last["overwrite"] is True

    def test_missing_pool_skill_raises_404(self):
        service = MagicMock(name="ServiceStub")
        service.preflight_download_to_workspace.return_value = {
            "success": False,
            "reason": "not_found",
        }
        with patch.object(
            skills_module,
            "_workspace_dir_for_agent",
            return_value=Path("/tmp/a"),
        ):
            with pytest.raises(HTTPException) as excinfo:
                skills_module._preflight_download_conflicts(
                    service,
                    [_target("a")],
                    "ghost",
                    False,
                )
        assert excinfo.value.status_code == 404

    def test_empty_targets_returns_no_conflicts(self):
        service = MagicMock(name="ServiceStub")
        conflicts = skills_module._preflight_download_conflicts(
            service,
            [],
            "demo",
            False,
        )
        assert conflicts == []
        service.preflight_download_to_workspace.assert_not_called()


class TestResolveAndPreflight:
    @staticmethod
    def _body(**overrides: Any) -> skills_module.DownloadFromPoolRequest:
        payload: dict[str, Any] = {
            "skill_name": "demo",
            "targets": [{"workspace_id": "default"}],
        }
        payload.update(overrides)
        return skills_module.DownloadFromPoolRequest(**payload)

    @pytest.mark.parametrize(
        "exc,expected_detail",
        [
            (ValueError("bad target"), "bad target"),
            (AppBaseException("app failure"), "app failure"),
        ],
    )
    def test_preflight_errors_become_400(self, exc, expected_detail):
        with patch.object(
            skills_module,
            "SkillPoolService",
            return_value=MagicMock(name="ServiceStub"),
        ), patch.object(
            skills_module,
            "_preflight_download_conflicts",
            side_effect=exc,
        ):
            with pytest.raises(HTTPException) as excinfo:
                skills_module._resolve_and_preflight(self._body())
        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == expected_detail

    def test_conflicts_become_409(self):
        conflict = {"workspace_id": "default", "skill_name": "demo"}
        with patch.object(
            skills_module,
            "SkillPoolService",
            return_value=MagicMock(name="ServiceStub"),
        ), patch.object(
            skills_module,
            "_preflight_download_conflicts",
            return_value=[conflict],
        ):
            with pytest.raises(HTTPException) as excinfo:
                skills_module._resolve_and_preflight(self._body())
        assert excinfo.value.status_code == 409
        assert excinfo.value.detail == {
            "downloaded": [],
            "conflicts": [conflict],
        }

    def test_all_workspaces_replaces_explicit_targets(self):
        with patch.object(
            skills_module,
            "list_workspaces",
            return_value=[
                {"agent_id": "a", "workspace_dir": "/tmp/a"},
                {"agent_id": "b", "workspace_dir": "/tmp/b"},
            ],
        ), patch.object(
            skills_module,
            "SkillPoolService",
            return_value=MagicMock(name="ServiceStub"),
        ), patch.object(
            skills_module,
            "_preflight_download_conflicts",
            return_value=[],
        ) as preflight_mock:
            targets, _service = skills_module._resolve_and_preflight(
                self._body(
                    targets=[{"workspace_id": "ignored"}],
                    all_workspaces=True,
                ),
            )

        assert [item.workspace_id for item in targets] == ["a", "b"]
        assert preflight_mock.call_args[0][1] == targets

    def test_no_targets_becomes_400(self):
        with patch.object(skills_module, "list_workspaces", return_value=[]):
            with pytest.raises(HTTPException) as excinfo:
                skills_module._resolve_and_preflight(self._body(targets=[]))
        assert excinfo.value.status_code == 400
        assert "No workspace targets" in excinfo.value.detail


class TestBuildDownloadPlan:
    def test_plan_carries_snapshot_per_target(self, tmp_path: Path):
        workspace_dir = tmp_path / "ws"
        workspace_dir.mkdir()
        snapshot = {
            "workspace_dir": workspace_dir,
            "skill_name": "demo",
            "entry": None,
            "backup_dir": None,
        }
        with patch.object(
            skills_module,
            "_workspace_dir_for_agent",
            return_value=workspace_dir,
        ), patch.object(
            skills_module,
            "_snapshot_workspace_skill",
            return_value=snapshot,
        ) as snapshot_mock:
            plan = skills_module._build_download_plan(
                [_target("default")],
                "demo",
            )

        assert plan == [
            {
                "workspace_id": "default",
                "workspace_dir": workspace_dir,
                "snapshot": snapshot,
            },
        ]
        snapshot_mock.assert_called_once_with(workspace_dir, "demo")

    def test_empty_targets_build_empty_plan(self):
        with patch.object(skills_module, "_snapshot_workspace_skill") as snap:
            assert skills_module._build_download_plan([], "demo") == []
        snap.assert_not_called()


class TestDownloadOneOrRaise:
    @staticmethod
    def _plan(workspace_id: str, tmp_path: Path) -> dict[str, Any]:
        return {
            "workspace_id": workspace_id,
            "workspace_dir": tmp_path / workspace_id,
            "snapshot": {
                "workspace_dir": tmp_path / workspace_id,
                "skill_name": "demo",
            },
        }

    def test_success_maps_result_fields(self):
        service = MagicMock(name="ServiceStub")
        service.download_to_workspace.return_value = {
            "success": True,
            "name": "demo",
            "workspace_name": "Default",
        }
        plan = {"workspace_id": "default", "workspace_dir": Path("/tmp/w")}
        result = skills_module._download_one_or_raise(
            service,
            plan,
            [plan],
            skill_name="demo",
            overwrite=True,
        )
        assert result == {
            "workspace_id": "default",
            "workspace_name": "Default",
            "name": "demo",
        }
        kwargs = service.download_to_workspace.call_args.kwargs
        assert kwargs["workspace_dir"] == Path("/tmp/w")
        assert kwargs["overwrite"] is True

    def test_success_without_workspace_name(self):
        service = MagicMock(name="ServiceStub")
        service.download_to_workspace.return_value = {
            "success": True,
            "name": "demo",
        }
        plan = {"workspace_id": "default", "workspace_dir": Path("/tmp/w")}
        result = skills_module._download_one_or_raise(
            service,
            plan,
            [plan],
            skill_name="demo",
            overwrite=False,
        )
        assert result["workspace_name"] == ""

    def test_conflict_rolls_back_in_reverse_then_409(self, tmp_path: Path):
        service = MagicMock(name="ServiceStub")
        service.download_to_workspace.return_value = {
            "success": False,
            "reason": "conflict",
            "skill_name": "demo",
        }
        first = self._plan("a", tmp_path)
        second = self._plan("b", tmp_path)
        restored: list[str] = []
        with patch.object(
            skills_module,
            "_restore_workspace_skill",
            side_effect=lambda snapshot: restored.append(
                str(snapshot["workspace_dir"].name),
            ),
        ):
            with pytest.raises(HTTPException) as excinfo:
                skills_module._download_one_or_raise(
                    service,
                    second,
                    [first, second],
                    skill_name="demo",
                    overwrite=False,
                )

        assert excinfo.value.status_code == 409
        assert excinfo.value.detail == {
            "downloaded": [],
            "conflicts": [
                {"success": False, "reason": "conflict", "skill_name": "demo"},
            ],
        }
        # the newest workspace is rolled back first
        assert restored == ["b", "a"]

    def test_missing_pool_skill_rolls_back_then_404(self, tmp_path: Path):
        service = MagicMock(name="ServiceStub")
        service.download_to_workspace.return_value = {
            "success": False,
            "reason": "not_found",
        }
        plan = self._plan("a", tmp_path)
        with patch.object(
            skills_module,
            "_restore_workspace_skill",
        ) as restore_mock:
            with pytest.raises(HTTPException) as excinfo:
                skills_module._download_one_or_raise(
                    service,
                    plan,
                    [plan],
                    skill_name="ghost",
                    overwrite=False,
                )
        assert excinfo.value.status_code == 404
        restore_mock.assert_called_once_with(plan["snapshot"])


class TestDownloadPoolSkillRoute:
    @staticmethod
    def _plan(tmp_path: Path, backup_dir: Path | None = None):
        return {
            "workspace_id": "default",
            "workspace_dir": tmp_path,
            "snapshot": {"backup_dir": backup_dir},
        }

    def _patched(self, tmp_path: Path, download_side_effect: Any):
        service = MagicMock(name="ServiceStub")
        plan = self._plan(tmp_path)
        return (
            plan,
            [
                patch.object(
                    skills_module,
                    "_resolve_and_preflight",
                    return_value=([_target("default")], service),
                ),
                patch.object(
                    skills_module,
                    "_build_download_plan",
                    return_value=[plan],
                ),
                patch.object(
                    skills_module,
                    "_download_one_or_raise",
                    side_effect=download_side_effect,
                ),
            ],
        )

    def test_success_returns_downloaded_entries(self, client, tmp_path: Path):
        _plan, patches = self._patched(
            tmp_path,
            lambda *a, **k: {
                "workspace_id": "default",
                "workspace_name": "Default",
                "name": "demo",
            },
        )
        with patches[0], patches[1], patches[2]:
            response = client.post(
                "/api/skills/pool/download",
                json={
                    "skill_name": "demo",
                    "targets": [{"workspace_id": "default"}],
                },
            )

        assert response.status_code == 200
        assert response.json() == {
            "downloaded": [
                {
                    "workspace_id": "default",
                    "workspace_name": "Default",
                    "name": "demo",
                },
            ],
        }

    def test_http_error_propagates_and_removes_backups(
        self,
        client,
        tmp_path: Path,
    ):
        backup_root = tmp_path / "rollback"
        backup_dir = backup_root / "demo"
        backup_dir.mkdir(parents=True)
        service = MagicMock(name="ServiceStub")
        plan = self._plan(tmp_path, backup_dir=backup_dir)
        with patch.object(
            skills_module,
            "_resolve_and_preflight",
            return_value=([_target("default")], service),
        ), patch.object(
            skills_module,
            "_build_download_plan",
            return_value=[plan],
        ), patch.object(
            skills_module,
            "_download_one_or_raise",
            side_effect=HTTPException(status_code=404, detail="gone"),
        ):
            response = client.post(
                "/api/skills/pool/download",
                json={
                    "skill_name": "demo",
                    "targets": [{"workspace_id": "default"}],
                },
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "gone"
        assert not backup_root.exists()

    def test_scan_error_rolls_back_and_returns_422(
        self,
        client,
        tmp_path: Path,
    ):
        plan, patches = self._patched(tmp_path, _scan_error())
        with patches[0], patches[1], patches[2], patch.object(
            skills_module,
            "_restore_workspace_skill",
        ) as restore_mock:
            response = client.post(
                "/api/skills/pool/download",
                json={
                    "skill_name": "demo",
                    "targets": [{"workspace_id": "default"}],
                },
            )

        assert response.status_code == 422
        assert response.json()["type"] == "security_scan_failed"
        restore_mock.assert_called_once_with(plan["snapshot"])

    def test_unexpected_error_rolls_back_and_propagates(
        self,
        client,
        tmp_path: Path,
    ):
        plan, patches = self._patched(tmp_path, RuntimeError("disk full"))
        with patches[0], patches[1], patches[2], patch.object(
            skills_module,
            "_restore_workspace_skill",
        ) as restore_mock:
            with pytest.raises(RuntimeError, match="disk full"):
                client.post(
                    "/api/skills/pool/download",
                    json={
                        "skill_name": "demo",
                        "targets": [{"workspace_id": "default"}],
                    },
                )

        restore_mock.assert_called_once_with(plan["snapshot"])

    def test_real_plan_snapshots_and_removes_temp_dirs(
        self,
        client,
        workspace_agent,
        tmp_path: Path,
        monkeypatch,
    ):
        """Drive the real plan/snapshot/cleanup code against a temp tree."""
        temp_root = tmp_path / "tempdirs"
        temp_root.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(temp_root))
        workspace_dir = workspace_agent
        # an existing skill means the snapshot really copies a backup dir
        _write_skill(workspace_dir / "skills" / "demo", "demo")
        _write_workspace_manifest(
            workspace_dir,
            {"demo": {"enabled": True}},
        )

        service = MagicMock(name="ServiceStub")
        service.preflight_download_to_workspace.return_value = {
            "success": True,
        }
        seen_during_download: list[list[str]] = []

        def _observing_download(**_kwargs: Any) -> dict[str, Any]:
            # captured inside the loop: after the plan snapshot was taken
            # and before the finally leg cleaned it up
            seen_during_download.append(
                sorted(path.name for path in temp_root.iterdir()),
            )
            return {
                "success": True,
                "name": "demo",
                "workspace_name": "Default",
            }

        service.download_to_workspace.side_effect = _observing_download
        with patch.object(
            skills_module,
            "SkillPoolService",
            return_value=service,
        ), patch.object(
            skills_module,
            "_workspace_dir_for_agent",
            return_value=workspace_dir,
        ):
            response = client.post(
                "/api/skills/pool/download",
                json={
                    "skill_name": "demo",
                    "targets": [{"workspace_id": "default"}],
                },
            )

        assert response.status_code == 200
        assert response.json()["downloaded"][0]["name"] == "demo"
        # a rollback dir really existed mid-download (so the empty temp
        # root below is a real cleanup, not a vacuous assertion), and the
        # finally leg removed it again
        assert len(seen_during_download) == 1
        assert len(seen_during_download[0]) == 1
        assert seen_during_download[0][0].startswith(
            "qwenpaw_skill_rollback_demo_",
        )
        assert list(temp_root.iterdir()) == []


# ---------------------------------------------------------------------------
# builtin import / update routes
# ---------------------------------------------------------------------------


class TestImportPoolBuiltins:
    def test_imports_list_is_forwarded(self, client):
        with patch.object(
            skills_module,
            "import_builtin_skills",
            return_value={"imported": ["demo"]},
        ) as import_mock, patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ) as follow_mock:
            response = client.post(
                "/api/skills/pool/import-builtin",
                json={
                    "imports": [{"skill_name": "demo", "language": "zh"}],
                    "overwrite_conflicts": True,
                },
            )

        assert response.status_code == 200
        assert response.json() == {"imported": ["demo"]}
        args, kwargs = import_mock.call_args
        assert args[0] == [{"skill_name": "demo", "language": "zh"}]
        assert kwargs["overwrite_conflicts"] is True
        follow_mock.assert_awaited_once_with()

    def test_legacy_skill_names_fallback(self, client):
        with patch.object(
            skills_module,
            "import_builtin_skills",
            return_value={"imported": []},
        ) as import_mock, patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ):
            response = client.post(
                "/api/skills/pool/import-builtin",
                json={"skill_names": ["demo", "other"]},
            )

        assert response.status_code == 200
        assert import_mock.call_args[0][0] == [
            {"skill_name": "demo"},
            {"skill_name": "other"},
        ]
        assert import_mock.call_args.kwargs["overwrite_conflicts"] is False

    def test_conflicts_without_overwrite_409(self, client):
        result = {"conflicts": [{"skill_name": "demo"}]}
        with patch.object(
            skills_module,
            "import_builtin_skills",
            return_value=result,
        ), patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ) as follow_mock:
            response = client.post(
                "/api/skills/pool/import-builtin",
                json={"skill_names": ["demo"]},
            )

        assert response.status_code == 409
        assert response.json()["detail"] == result
        follow_mock.assert_not_awaited()

    def test_conflicts_with_overwrite_succeed(self, client):
        result = {"conflicts": [{"skill_name": "demo"}], "imported": ["demo"]}
        with patch.object(
            skills_module,
            "import_builtin_skills",
            return_value=result,
        ) as import_mock, patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ):
            response = client.post(
                "/api/skills/pool/import-builtin",
                json={"skill_names": ["demo"], "overwrite_conflicts": True},
            )

        assert response.status_code == 200
        assert response.json() == result
        assert import_mock.call_args.kwargs["overwrite_conflicts"] is True


class TestUpdatePoolBuiltin:
    def test_success_without_body(self, client):
        with patch.object(
            skills_module,
            "update_single_builtin",
            return_value={"updated": "demo"},
        ) as update_mock, patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ) as follow_mock:
            response = client.post("/api/skills/pool/demo/update-builtin")

        assert response.status_code == 200
        assert response.json() == {"updated": "demo"}
        assert update_mock.call_args[0][0] == "demo"
        assert update_mock.call_args.kwargs["language"] is None
        follow_mock.assert_awaited_once_with()

    def test_valid_language_forwarded(self, client):
        language = skills_module.BUILTIN_SKILL_LANGUAGES[0]
        with patch.object(
            skills_module,
            "update_single_builtin",
            return_value={"updated": "demo"},
        ) as update_mock, patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ):
            response = client.post(
                "/api/skills/pool/demo/update-builtin",
                json={"language": language},
            )

        assert response.status_code == 200
        assert update_mock.call_args.kwargs["language"] == language

    def test_invalid_language_400(self, client):
        with patch.object(skills_module, "update_single_builtin") as update:
            response = client.post(
                "/api/skills/pool/demo/update-builtin",
                json={"language": "klingon"},
            )

        assert response.status_code == 400
        assert "klingon" in response.json()["detail"]
        update.assert_not_called()

    def test_empty_language_body_is_treated_as_unset(self, client):
        with patch.object(
            skills_module,
            "update_single_builtin",
            return_value={"updated": "demo"},
        ) as update_mock, patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ):
            response = client.post(
                "/api/skills/pool/demo/update-builtin",
                json={"language": ""},
            )

        assert response.status_code == 200
        assert update_mock.call_args.kwargs["language"] is None

    @pytest.mark.parametrize(
        "exc",
        [ValueError("not builtin"), AppBaseException("app failure")],
    )
    def test_failures_return_400(self, client, exc):
        with patch.object(
            skills_module,
            "update_single_builtin",
            side_effect=exc,
        ), patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ) as follow_mock:
            response = client.post("/api/skills/pool/demo/update-builtin")

        assert response.status_code == 400
        assert response.json()["detail"] == str(exc)
        follow_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# workspace-side route failure legs
# ---------------------------------------------------------------------------


class TestWorkspaceSkillRoutes:
    def test_disable_success_reloads(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.disable_skill.return_value = {
            "success": True,
            "name": "demo",
        }
        response = client.post("/api/skills/demo/disable")
        assert response.status_code == 200
        assert response.json() == {
            "disabled": True,
            "success": True,
            "name": "demo",
        }
        assert mock_schedule_reload.call_args[0][1] == "default"

    def test_disable_missing_skill_404(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.disable_skill.return_value = {
            "success": False,
            "reason": "not_found",
        }
        response = client.post("/api/skills/ghost/disable")
        assert response.status_code == 404
        assert response.json()["detail"] == "Skill not found"
        mock_schedule_reload.assert_not_called()

    def test_get_skill_returns_detail(self, client, patch_get_agent):
        detail = skills_module.SkillDetail(
            name="demo",
            source="customized",
            content="# body",
        )
        with patch.object(
            skills_module,
            "_build_workspace_skill_detail",
            return_value=detail,
        ) as build_mock:
            response = client.get("/api/skills/demo")

        assert response.status_code == 200
        assert response.json()["content"] == "# body"
        assert build_mock.call_args[0][1] == "demo"

    def test_get_skill_404(self, client, patch_get_agent):
        with patch.object(
            skills_module,
            "_build_workspace_skill_detail",
            return_value=None,
        ):
            response = client.get("/api/skills/ghost")
        assert response.status_code == 404
        assert response.json()["detail"] == "Skill not found"

    def test_delete_skill_disables_then_deletes(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.delete_skill.return_value = True
        response = client.delete("/api/skills/demo")
        assert response.status_code == 200
        assert response.json() == {"deleted": True}
        mock_workspace_service.disable_skill.assert_called_once_with("demo")
        mock_workspace_service.delete_skill.assert_called_once_with("demo")

    def test_delete_skill_conflict_when_not_disabled(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.delete_skill.return_value = False
        response = client.delete("/api/skills/demo")
        assert response.status_code == 409
        assert "disabled" in response.json()["detail"]

    def test_load_skill_file_returns_content(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.load_skill_file.return_value = "# body"
        response = client.get("/api/skills/demo/files/SKILL.md")
        assert response.status_code == 200
        assert response.json() == {"content": "# body"}
        kwargs = mock_workspace_service.load_skill_file.call_args.kwargs
        assert kwargs["skill_name"] == "demo"
        assert kwargs["file_path"] == "SKILL.md"

    def test_load_skill_file_404(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.load_skill_file.return_value = None
        response = client.get("/api/skills/demo/files/missing.md")
        assert response.status_code == 404
        assert response.json()["detail"] == "File not found"

    def test_update_channels_success(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.set_skill_channels.return_value = True
        response = client.put(
            "/api/skills/demo/channels",
            json=["console", "dingtalk"],
        )
        assert response.status_code == 200
        assert response.json() == {
            "updated": True,
            "channels": ["console", "dingtalk"],
        }
        mock_workspace_service.set_skill_channels.assert_called_once_with(
            "demo",
            ["console", "dingtalk"],
        )
        mock_schedule_reload.assert_called_once()

    def test_update_channels_404(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.set_skill_channels.return_value = False
        response = client.put("/api/skills/ghost/channels", json=["all"])
        assert response.status_code == 404
        mock_schedule_reload.assert_not_called()

    def test_update_preload_success(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.set_skill_preload.return_value = True
        response = client.put(
            "/api/skills/demo/preload",
            json={"preload": True},
        )
        assert response.status_code == 200
        assert response.json() == {"updated": True, "preload": True}
        mock_workspace_service.set_skill_preload.assert_called_once_with(
            "demo",
            True,
        )
        mock_schedule_reload.assert_called_once()

    def test_update_preload_404(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.set_skill_preload.return_value = False
        response = client.put(
            "/api/skills/ghost/preload",
            json={"preload": False},
        )
        assert response.status_code == 404
        mock_schedule_reload.assert_not_called()

    def test_update_tags_success_no_reload(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.set_skill_tags.return_value = True
        response = client.put(
            "/api/skills/demo/tags",
            json=[" alpha ", "beta"],
        )
        assert response.status_code == 200
        assert response.json() == {"updated": True, "tags": ["alpha", "beta"]}
        mock_workspace_service.set_skill_tags.assert_called_once_with(
            "demo",
            ["alpha", "beta"],
        )
        # tag changes need no agent reload
        mock_schedule_reload.assert_not_called()

    def test_update_tags_404(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.set_skill_tags.return_value = False
        response = client.put("/api/skills/ghost/tags", json=["a"])
        assert response.status_code == 404

    def test_update_tags_rejects_too_many(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        tags = [f"t{i}" for i in range(skills_module.MAX_TAGS + 2)]
        response = client.put("/api/skills/demo/tags", json=tags)
        assert response.status_code == 422
        mock_workspace_service.set_skill_tags.assert_not_called()


class TestWorkspaceSkillConfigRoute:
    def test_get_skill_config_returns_entry(self, client, workspace_agent):
        _write_workspace_manifest(
            workspace_agent,
            {"demo": {"config": {"k": "v"}}},
        )
        response = client.get("/api/skills/demo/config")
        assert response.status_code == 200
        assert response.json() == {"config": {"k": "v"}}

    def test_get_skill_config_defaults_to_empty(self, client, workspace_agent):
        _write_workspace_manifest(workspace_agent, {"demo": {}})
        response = client.get("/api/skills/demo/config")
        assert response.status_code == 200
        assert response.json() == {"config": {}}

    def test_get_skill_config_unknown_404(self, client, workspace_agent):
        _write_workspace_manifest(workspace_agent, {})
        response = client.get("/api/skills/ghost/config")
        assert response.status_code == 404
        assert response.json()["detail"] == "Skill not found"


# ---------------------------------------------------------------------------
# remaining scan/validation legs of the write routes
# ---------------------------------------------------------------------------


class TestWriteRouteFailureLegs:
    def test_save_pool_skill_scan_error(
        self,
        client,
        mock_pool_service,
        no_auto_sync,
    ):
        mock_pool_service.save_pool_skill.side_effect = _scan_error()
        response = client.put(
            "/api/skills/pool/save",
            json={"name": "blocked_skill", "content": "# md"},
        )
        assert response.status_code == 422
        assert response.json()["skill_name"] == "blocked_skill"
        no_auto_sync.assert_not_awaited()

    def test_save_pool_skill_value_error_400(self, client, mock_pool_service):
        mock_pool_service.save_pool_skill.side_effect = ValueError("bad name")
        response = client.put(
            "/api/skills/pool/save",
            json={"name": "demo", "content": "# md"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "bad name"

    def test_save_pool_skill_app_exception_400(
        self,
        client,
        mock_pool_service,
    ):
        mock_pool_service.save_pool_skill.side_effect = AppBaseException("x")
        response = client.put(
            "/api/skills/pool/save",
            json={"name": "demo", "content": "# md"},
        )
        assert response.status_code == 400

    def test_upload_pool_zip_non_object_rename_map(self, client):
        response = client.post(
            "/api/skills/pool/upload-zip?rename_map=%5B1%2C%202%5D",
            files=_zip_upload(),
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "rename_map must be a JSON object"

    def test_upload_pool_zip_scan_error(self, client, mock_pool_service):
        mock_pool_service.import_from_zip.side_effect = _scan_error()
        with patch.object(
            skills_module,
            "_follow_auto_sync",
            new=AsyncMock(return_value=None),
        ):
            response = client.post(
                "/api/skills/pool/upload-zip",
                files=_zip_upload(),
            )
        assert response.status_code == 422

    def test_upload_pool_zip_value_error_400(self, client, mock_pool_service):
        mock_pool_service.import_from_zip.side_effect = ValueError("bad zip")
        response = client.post(
            "/api/skills/pool/upload-zip",
            files=_zip_upload(),
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "bad zip"

    def test_create_pool_skill_value_error_400(
        self,
        client,
        mock_pool_service,
    ):
        mock_pool_service.create_skill.side_effect = ValueError("bad name")
        response = client.post(
            "/api/skills/pool/create",
            json={"name": "demo", "content": "# md"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "bad name"

    def test_create_pool_skill_app_exception_400(self, client):
        service = MagicMock(name="ServiceStub")
        service.create_skill.side_effect = AppBaseException("app failure")
        with patch.object(
            skills_module,
            "SkillPoolService",
            return_value=service,
        ):
            response = client.post(
                "/api/skills/pool/create",
                json={"name": "demo", "content": "# md"},
            )
        assert response.status_code == 400
        assert response.json()["detail"] == "app failure"

    def test_upload_workspace_zip_value_error_400(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.import_from_zip.side_effect = ValueError("bad")
        response = client.post("/api/skills/upload", files=_zip_upload())
        assert response.status_code == 400
        assert response.json()["detail"] == "bad"

    def test_upload_workspace_zip_app_exception_400(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.import_from_zip.side_effect = AppBaseException(
            "app failure",
        )
        response = client.post("/api/skills/upload", files=_zip_upload())
        assert response.status_code == 400

    def test_save_workspace_skill_value_error_400(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.save_skill.side_effect = ValueError("bad name")
        response = client.put(
            "/api/skills/save",
            json={"name": "demo", "content": "# md"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "bad name"

    def test_save_workspace_skill_app_exception_400(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
    ):
        mock_workspace_service.save_skill.side_effect = AppBaseException("x")
        response = client.put(
            "/api/skills/save",
            json={"name": "demo", "content": "# md"},
        )
        assert response.status_code == 400

    def test_create_skill_value_error_400(
        self,
        client,
        patch_get_agent,
        mock_workspace_service,
        mock_schedule_reload,
    ):
        mock_workspace_service.create_skill.side_effect = ValueError("bad")
        response = client.post(
            "/api/skills",
            json={"name": "demo", "content": "# md"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "bad"
        mock_schedule_reload.assert_not_called()

    def test_batch_delete_pool_skills_reports_exception(
        self,
        client,
        mock_pool_service,
    ):
        mock_pool_service.delete_skill.side_effect = RuntimeError("io error")
        response = client.post("/api/skills/pool/batch-delete", json=["boom"])
        assert response.status_code == 200
        results = response.json()["results"]
        assert results["boom"]["success"] is False
        assert "io error" in results["boom"]["reason"]

    def test_batch_delete_pool_skills_delete_failed_reason(
        self,
        client,
        mock_pool_service,
    ):
        mock_pool_service.delete_skill.return_value = False
        response = client.post("/api/skills/pool/batch-delete", json=["lock"])
        assert response.json()["results"]["lock"] == {
            "success": False,
            "reason": "delete_failed",
        }
