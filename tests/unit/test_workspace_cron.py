# -*- coding: utf-8 -*-
"""Unit tests for Phase 7: Multi-workspace management + Cron enhancement."""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from copaw.app.crons.history import CronJobHistory, HistoryRepo
from copaw.app.crons.manager import CronManager
from copaw.app.crons.models import CronJobState, JobRuntimeSpec
from copaw.constant import (
    WORKING_DIR,
    get_active_skills_dir,
    get_custom_channels_dir,
    get_customized_skills_dir,
    get_memory_dir,
    get_sessions_dir,
    get_workspace_dir,
    set_workspace_dir,
)
from copaw.workspace.manager import WorkspaceManager
from copaw.workspace.migration import ensure_workspace_layout
from copaw.workspace.models import WorkspaceInfo, WorkspacesFile


# ---------------------------------------------------------------------------
# Workspace models
# ---------------------------------------------------------------------------


class TestWorkspaceInfo:
    def test_default_id_prefix(self):
        ws = WorkspaceInfo()
        assert ws.id.startswith("ws_")
        assert len(ws.id) == 15  # "ws_" + 12 hex chars

    def test_custom_name(self):
        ws = WorkspaceInfo(name="my-project")
        assert ws.name == "my-project"
        assert ws.is_active is False

    def test_unique_ids(self):
        ids = {WorkspaceInfo().id for _ in range(50)}
        assert len(ids) == 50


class TestWorkspacesFile:
    def test_empty_default(self):
        wf = WorkspacesFile()
        assert wf.workspaces == []
        assert wf.active_id is None

    def test_roundtrip_json(self):
        ws = WorkspaceInfo(name="test")
        wf = WorkspacesFile(workspaces=[ws], active_id=ws.id)
        data = json.loads(wf.model_dump_json())
        restored = WorkspacesFile.model_validate(data)
        assert restored.active_id == ws.id
        assert len(restored.workspaces) == 1
        assert restored.workspaces[0].name == "test"


# ---------------------------------------------------------------------------
# WorkspaceManager
# ---------------------------------------------------------------------------


class TestWorkspaceManager:
    def test_create_workspace(self, tmp_path):
        mgr = WorkspaceManager(root=tmp_path)
        ws = mgr.create(name="dev")
        assert ws.name == "dev"
        assert ws.is_active is True  # first workspace auto-activates
        assert (tmp_path / "workspaces" / ws.id).is_dir()

    def test_list_workspaces(self, tmp_path):
        mgr = WorkspaceManager(root=tmp_path)
        mgr.create(name="a")
        mgr.create(name="b")
        lst = mgr.list_workspaces()
        assert len(lst) == 2
        names = {w.name for w in lst}
        assert names == {"a", "b"}

    def test_get_active(self, tmp_path):
        mgr = WorkspaceManager(root=tmp_path)
        ws = mgr.create(name="main")
        active = mgr.get_active()
        assert active is not None
        assert active.id == ws.id

    def test_get_active_path(self, tmp_path):
        mgr = WorkspaceManager(root=tmp_path)
        ws = mgr.create(name="main")
        path = mgr.get_active_path()
        assert path == tmp_path / "workspaces" / ws.id

    def test_activate_workspace(self, tmp_path):
        mgr = WorkspaceManager(root=tmp_path)
        ws1 = mgr.create(name="first")
        ws2 = mgr.create(name="second")
        assert mgr.get_active().id == ws1.id

        mgr.activate(ws2.id)
        assert mgr.get_active().id == ws2.id

    def test_activate_nonexistent(self, tmp_path):
        mgr = WorkspaceManager(root=tmp_path)
        mgr.create(name="main")
        assert mgr.activate("nonexistent") is False

    def test_delete_workspace(self, tmp_path):
        mgr = WorkspaceManager(root=tmp_path)
        ws1 = mgr.create(name="first")
        ws2 = mgr.create(name="second")
        mgr.activate(ws2.id)

        # Can delete non-active workspace
        assert mgr.delete(ws1.id) is True
        assert len(mgr.list_workspaces()) == 1

    def test_delete_active_workspace_fails(self, tmp_path):
        mgr = WorkspaceManager(root=tmp_path)
        ws = mgr.create(name="main")
        assert mgr.delete(ws.id) is False

    def test_is_migrated(self, tmp_path):
        mgr = WorkspaceManager(root=tmp_path)
        assert mgr.is_migrated() is False
        mgr.create(name="test")
        assert mgr.is_migrated() is True

    def test_persistence(self, tmp_path):
        mgr1 = WorkspaceManager(root=tmp_path)
        ws = mgr1.create(name="persisted")

        # Load from disk
        mgr2 = WorkspaceManager(root=tmp_path)
        lst = mgr2.list_workspaces()
        assert len(lst) == 1
        assert lst[0].name == "persisted"
        assert mgr2.get_active().id == ws.id

    def test_get_active_fallback(self, tmp_path):
        """No workspace => get_active_path returns root."""
        mgr = WorkspaceManager(root=tmp_path)
        assert mgr.get_active_path() == tmp_path


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class TestMigration:
    def test_fresh_install(self, tmp_path):
        """No legacy files — just creates default workspace."""
        mgr = ensure_workspace_layout(tmp_path)
        assert mgr.is_migrated()
        active = mgr.get_active()
        assert active is not None
        assert active.name == "default"

    def test_migrates_legacy_config(self, tmp_path):
        """Legacy config.json at root is moved into workspace."""
        (tmp_path / "config.json").write_text('{"test": true}')
        (tmp_path / "jobs.json").write_text(
            '{"version": 1, "jobs": []}',
        )

        mgr = ensure_workspace_layout(tmp_path)
        ws = mgr.get_active()
        ws_path = tmp_path / "workspaces" / ws.path

        assert (ws_path / "config.json").exists()
        assert (ws_path / "jobs.json").exists()
        # Original should be moved (not exist at root anymore)
        assert not (tmp_path / "config.json").exists()
        assert not (tmp_path / "jobs.json").exists()

    def test_migrates_legacy_dirs(self, tmp_path):
        """Legacy memory/ dir at root is moved into workspace."""
        (tmp_path / "memory").mkdir()
        (tmp_path / "memory" / "test.md").write_text("hello")

        mgr = ensure_workspace_layout(tmp_path)
        ws = mgr.get_active()
        ws_path = tmp_path / "workspaces" / ws.path

        assert (ws_path / "memory" / "test.md").exists()
        assert not (tmp_path / "memory").exists()

    def test_migrates_global_files(self, tmp_path):
        """providers.json/tokens.json are moved to global/."""
        (tmp_path / "providers.json").write_text("{}")
        (tmp_path / "tokens.json").write_text("{}")

        ensure_workspace_layout(tmp_path)
        assert (tmp_path / "global" / "providers.json").exists()
        assert (tmp_path / "global" / "tokens.json").exists()
        assert not (tmp_path / "providers.json").exists()
        assert not (tmp_path / "tokens.json").exists()

    def test_idempotent(self, tmp_path):
        """Second call is a no-op."""
        mgr1 = ensure_workspace_layout(tmp_path)
        ws1 = mgr1.get_active()

        mgr2 = ensure_workspace_layout(tmp_path)
        ws2 = mgr2.get_active()

        assert ws1.id == ws2.id
        assert len(mgr2.list_workspaces()) == 1


# ---------------------------------------------------------------------------
# constant.py workspace helpers
# ---------------------------------------------------------------------------


class TestConstantHelpers:
    def test_default_workspace_dir(self):
        """Before set_workspace_dir, falls back to WORKING_DIR."""
        import copaw.constant as c

        old = c._active_workspace_dir
        try:
            c._active_workspace_dir = None
            assert get_workspace_dir() == WORKING_DIR
        finally:
            c._active_workspace_dir = old

    def test_set_workspace_dir(self, tmp_path):
        import copaw.constant as c

        old = c._active_workspace_dir
        try:
            set_workspace_dir(tmp_path / "ws1")
            assert get_workspace_dir() == tmp_path / "ws1"
            assert (
                get_active_skills_dir() == tmp_path / "ws1" / "active_skills"
            )
            assert (
                get_customized_skills_dir()
                == tmp_path / "ws1" / "customized_skills"
            )
            assert get_memory_dir() == tmp_path / "ws1" / "memory"
            assert (
                get_custom_channels_dir()
                == tmp_path / "ws1" / "custom_channels"
            )
            assert get_sessions_dir() == tmp_path / "ws1" / "sessions"
        finally:
            c._active_workspace_dir = old


# ---------------------------------------------------------------------------
# Cron history
# ---------------------------------------------------------------------------


class TestCronJobHistory:
    def test_default_fields(self):
        h = CronJobHistory(job_id="j1")
        assert h.job_id == "j1"
        assert h.status == "running"
        assert h.attempt == 1
        assert h.error is None
        assert len(h.id) == 12

    def test_json_roundtrip(self):
        h = CronJobHistory(
            job_id="j1",
            status="success",
            attempt=2,
        )
        data = json.loads(h.model_dump_json())
        restored = CronJobHistory.model_validate(data)
        assert restored.job_id == "j1"
        assert restored.status == "success"
        assert restored.attempt == 2


class TestHistoryRepo:
    def test_append_and_list(self, tmp_path):
        repo = HistoryRepo(tmp_path / "history.jsonl")
        repo.append(CronJobHistory(job_id="j1", status="success"))
        repo.append(CronJobHistory(job_id="j2", status="error"))
        repo.append(CronJobHistory(job_id="j1", status="error"))

        records = repo.list_by_job("j1")
        assert len(records) == 2
        # Newest first
        assert records[0].status == "error"
        assert records[1].status == "success"

    def test_list_empty(self, tmp_path):
        repo = HistoryRepo(tmp_path / "history.jsonl")
        assert not repo.list_by_job("nonexistent")

    def test_list_limit(self, tmp_path):
        repo = HistoryRepo(tmp_path / "history.jsonl")
        for _ in range(10):
            repo.append(
                CronJobHistory(job_id="j1", status="success"),
            )
        records = repo.list_by_job("j1", limit=3)
        assert len(records) == 3


# ---------------------------------------------------------------------------
# Cron models — retry fields
# ---------------------------------------------------------------------------


class TestJobRuntimeSpecRetry:
    def test_default_retry_fields(self):
        rt = JobRuntimeSpec()
        assert rt.max_retries == 0
        assert rt.retry_delay == 5.0
        assert rt.auto_pause_after == 3

    def test_custom_retry_fields(self):
        rt = JobRuntimeSpec(
            max_retries=3,
            retry_delay=10.0,
            auto_pause_after=5,
        )
        assert rt.max_retries == 3
        assert rt.retry_delay == 10.0
        assert rt.auto_pause_after == 5


class TestCronJobStateConsecutiveFailures:
    def test_default_zero(self):
        st = CronJobState()
        assert st.consecutive_failures == 0


# ---------------------------------------------------------------------------
# CronManager retry + auto-pause (integration-style with mocks)
# ---------------------------------------------------------------------------


def _make_job(max_retries=0, retry_delay=0.01, auto_pause_after=3):
    from copaw.app.crons.models import (
        CronJobRequest,
        CronJobSpec,
        DispatchSpec,
        DispatchTarget,
        ScheduleSpec,
    )

    return CronJobSpec(
        id="test-job",
        name="Test Job",
        schedule=ScheduleSpec(cron="0 * * * *"),
        task_type="agent",
        request=CronJobRequest(
            input="hello",
            session_id="s1",
            user_id="u1",
        ),
        dispatch=DispatchSpec(
            target=DispatchTarget(user_id="u1", session_id="s1"),
        ),
        runtime=JobRuntimeSpec(
            max_retries=max_retries,
            retry_delay=retry_delay,
            auto_pause_after=auto_pause_after,
        ),
    )


class TestCronManagerRetry:
    @pytest.fixture
    def mock_repo(self):
        repo = MagicMock()
        repo.load = AsyncMock(
            return_value=MagicMock(jobs=[]),
        )
        repo.list_jobs = AsyncMock(return_value=[])
        repo.get_job = AsyncMock(return_value=None)
        repo.upsert_job = AsyncMock()
        repo.delete_job = AsyncMock(return_value=True)
        return repo

    @pytest.fixture
    def mock_runner(self):
        return MagicMock()

    @pytest.fixture
    def mock_channel_manager(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_execute_once_success(
        self,
        tmp_path,
        mock_repo,
        mock_runner,
        mock_channel_manager,
    ):
        history = HistoryRepo(tmp_path / "h.jsonl")
        mgr = CronManager(
            repo=mock_repo,
            runner=mock_runner,
            channel_manager=mock_channel_manager,
            history_repo=history,
        )
        mgr._executor = MagicMock()
        mgr._executor.execute = AsyncMock()

        job = _make_job()
        await mgr._execute_once(job)

        st = mgr.get_state("test-job")
        assert st.last_status == "success"
        assert st.consecutive_failures == 0

        records = history.list_by_job("test-job")
        assert len(records) == 1
        assert records[0].status == "success"

    @pytest.mark.asyncio
    async def test_execute_once_failure_no_retry(
        self,
        tmp_path,
        mock_repo,
        mock_runner,
        mock_channel_manager,
    ):
        history = HistoryRepo(tmp_path / "h.jsonl")
        mgr = CronManager(
            repo=mock_repo,
            runner=mock_runner,
            channel_manager=mock_channel_manager,
            history_repo=history,
        )
        mgr._executor = MagicMock()
        mgr._executor.execute = AsyncMock(
            side_effect=RuntimeError("boom"),
        )

        job = _make_job(max_retries=0)
        with pytest.raises(RuntimeError, match="boom"):
            await mgr._execute_once(job)

        st = mgr.get_state("test-job")
        assert st.last_status == "error"
        assert st.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_retry_with_backoff(
        self,
        tmp_path,
        mock_repo,
        mock_runner,
        mock_channel_manager,
    ):
        """Fail twice, succeed on 3rd attempt."""
        history = HistoryRepo(tmp_path / "h.jsonl")
        mgr = CronManager(
            repo=mock_repo,
            runner=mock_runner,
            channel_manager=mock_channel_manager,
            history_repo=history,
        )
        call_count = 0

        async def flaky_execute(**_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError(f"fail #{call_count}")

        mgr._executor = MagicMock()
        mgr._executor.execute = AsyncMock(side_effect=flaky_execute)

        job = _make_job(max_retries=2, retry_delay=0.01)
        await mgr._execute_once(job)

        assert call_count == 3
        st = mgr.get_state("test-job")
        assert st.last_status == "success"
        assert st.consecutive_failures == 0

        records = history.list_by_job("test-job")
        assert len(records) == 3

    @pytest.mark.asyncio
    async def test_auto_pause_after_consecutive_failures(
        self,
        tmp_path,
        mock_repo,
        mock_runner,
        mock_channel_manager,
    ):
        history = HistoryRepo(tmp_path / "h.jsonl")
        mgr = CronManager(
            repo=mock_repo,
            runner=mock_runner,
            channel_manager=mock_channel_manager,
            history_repo=history,
        )
        mgr._executor = MagicMock()
        mgr._executor.execute = AsyncMock(
            side_effect=RuntimeError("always fail"),
        )
        # Mock the scheduler
        mgr._scheduler = MagicMock()

        job = _make_job(auto_pause_after=2)

        # First failure
        with pytest.raises(RuntimeError):
            await mgr._execute_once(job)
        assert mgr.get_state("test-job").consecutive_failures == 1
        mgr._scheduler.pause_job.assert_not_called()

        # Second failure => auto-pause
        with pytest.raises(RuntimeError):
            await mgr._execute_once(job)
        assert mgr.get_state("test-job").consecutive_failures == 2
        mgr._scheduler.pause_job.assert_called_once_with("test-job")

    @pytest.mark.asyncio
    async def test_success_resets_consecutive_failures(
        self,
        tmp_path,
        mock_repo,
        mock_runner,
        mock_channel_manager,
    ):
        history = HistoryRepo(tmp_path / "h.jsonl")
        mgr = CronManager(
            repo=mock_repo,
            runner=mock_runner,
            channel_manager=mock_channel_manager,
            history_repo=history,
        )

        # Fail once
        mgr._executor = MagicMock()
        mgr._executor.execute = AsyncMock(
            side_effect=RuntimeError("fail"),
        )
        job = _make_job(auto_pause_after=5)
        with pytest.raises(RuntimeError):
            await mgr._execute_once(job)
        assert mgr.get_state("test-job").consecutive_failures == 1

        # Succeed => resets counter
        mgr._executor.execute = AsyncMock()
        await mgr._execute_once(job)
        assert mgr.get_state("test-job").consecutive_failures == 0
