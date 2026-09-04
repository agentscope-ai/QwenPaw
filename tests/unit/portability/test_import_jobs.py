# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.portability.import_jobs import (
    ImportRun,
    ImportProviderSnapshot,
    PortabilityImportJobManager,
    _LiveJob,
)
from qwenpaw.portability.models import (
    ImportAssetResult,
    ImportAssetState,
    ImportSelection,
    MigrationAssetPlan,
    MigrationPlan,
)


def _workspace(tmp_path: Path, agent_id: str = "agent-1"):
    return SimpleNamespace(
        workspace_dir=tmp_path / agent_id,
        agent_id=agent_id,
    )


async def _wait_job(manager, workspace, job_id: str) -> None:
    live = await manager._live(workspace, job_id)
    if live.task:
        await live.task


class _FakeServices:
    def __init__(self) -> None:
        self.active_scans = 0
        self.max_active_scans = 0
        self.block_apply = asyncio.Event()
        self.block_apply.set()
        self.apply_started = asyncio.Event()
        self.fail_apply: set[str] = set()
        self.retries: list[tuple[str, ImportSelection]] = []

    def factory(self, workspace):
        owner = self

        class Service:
            async def plan_from(self, source, *, progress=None, **_kwargs):
                owner.active_scans += 1
                owner.max_active_scans = max(
                    owner.max_active_scans,
                    owner.active_scans,
                )
                if progress:
                    await progress(f"正在检测 {source}")
                await asyncio.sleep(0.01)
                owner.active_scans -= 1
                return MigrationPlan(
                    plan_id=f"plan-{source[0] * 32}",
                    source=source,
                    agent_id=workspace.agent_id,
                    created_at=datetime.now(timezone.utc),
                    actions=[
                        MigrationAssetPlan(
                            asset_type="session",
                            source_id=f"{source}-thread",
                            name="Conversation",
                        ),
                        MigrationAssetPlan(
                            asset_type="skill",
                            source_id=f"{source}-skill",
                            name=f"{source.title()} Skill",
                        ),
                        MigrationAssetPlan(
                            asset_type="plugin",
                            source_id=f"{source}-plugin",
                            name=f"{source.title()} Plugin",
                        ),
                    ],
                )

            async def apply_selection(
                self,
                _plan_id,
                selection,
                *,
                progress=None,
            ):
                source = "codex" if _plan_id.endswith("c" * 32) else "qoder"
                assert isinstance(selection, ImportSelection)
                owner.apply_started.set()
                await owner.block_apply.wait()
                if source in owner.fail_apply:
                    raise RuntimeError(f"{source} failed")
                if progress:
                    await progress("正在写入会话：1/2（聊天记录阶段）")
                    await progress(f"正在修复 Skill「{source.title()} Skill」")
                    await progress(
                        f"\x1easset\tskill\tsucceeded\t0\t{source}-skill",
                    )
                    await progress("api_key=sk-test-secret-1234567890")
                return [f"{source}-thread"]

            async def retry_selection(
                self,
                plan_id,
                selection,
                *,
                progress=None,
            ):
                owner.retries.append((plan_id, selection))
                source = "codex" if plan_id.endswith("c" * 32) else "qoder"
                if progress:
                    await progress(f"正在修复 Skill「{source.title()} Skill」")
                    await progress(
                        f"\x1easset\tskill\tsucceeded\t0\t{source}-skill",
                    )
                return (
                    await self.plan_from(source),
                    [],
                )

        return Service()


@pytest.mark.asyncio
async def test_large_progress_is_coalesced_without_losing_asset_states(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    manager = PortabilityImportJobManager()
    provider = ImportProviderSnapshot(
        source="codex",
        assets=[
            ImportAssetResult(
                asset_type="skill",
                source_id=f"skill-{index}",
                name=f"Skill {index}",
            )
            for index in range(100)
        ],
    )
    live = _LiveJob(
        workspace=workspace,
        snapshot=ImportRun(
            job_id="import-" + "a" * 32,
            agent_id=workspace.agent_id,
            state="running",
            providers=[provider],
        ),
    )
    manager._prepare_progress(live)

    for index in range(100):
        await manager._apply_progress(
            live,
            provider,
            f"\x1easset\tskill\tsucceeded\t0\tskill-{index}",
        )

    assert live.snapshot.seq == 20
    assert len(live.events) == 1
    assert all(
        asset.state is ImportAssetState.SUCCEEDED for asset in provider.assets
    )


@pytest.mark.asyncio
async def test_restored_running_job_marks_unfinished_assets_retryable(
    tmp_path: Path,
) -> None:
    services = _FakeServices()
    services.block_apply.clear()
    workspace = _workspace(tmp_path)
    manager = PortabilityImportJobManager(service_factory=services.factory)
    created = await manager.create(workspace, ["codex"])
    await _wait_job(manager, workspace, created.job_id)
    await manager.start(
        workspace,
        created.job_id,
        {"codex": ImportSelection(skills=["codex-skill"])},
    )
    await services.apply_started.wait()

    restored = PortabilityImportJobManager(service_factory=services.factory)
    snapshot = await restored.snapshot(workspace, created.job_id)
    await manager.cancel(workspace, created.job_id)

    assert snapshot.state == "interrupted"
    assert snapshot.providers[0].assets[0].state is ImportAssetState.FAILED


@pytest.mark.asyncio
async def test_scan_is_concurrent_and_persisted(tmp_path: Path) -> None:
    services = _FakeServices()
    workspace = _workspace(tmp_path)
    manager = PortabilityImportJobManager(service_factory=services.factory)

    created = await manager.create(workspace, ["codex", "qoder"])
    await _wait_job(manager, workspace, created.job_id)
    snapshot = await manager.snapshot(workspace, created.job_id)

    assert services.max_active_scans == 2
    assert snapshot.state == "awaiting_selection"
    assert [item.source for item in snapshot.providers] == ["codex", "qoder"]
    assert all(item.sessions_total == 1 for item in snapshot.providers)
    assert all(
        item.assets[0].state is ImportAssetState.PENDING
        for item in snapshot.providers
    )
    assert all(not item.selection.plugins for item in snapshot.providers)
    assert all(
        any(asset.asset_type == "plugin" for asset in item.assets)
        for item in snapshot.providers
    )
    assert (
        workspace.workspace_dir
        / ".qwenpaw/imports/jobs"
        / f"{created.job_id}.json"
    ).is_file()

    restored = PortabilityImportJobManager(service_factory=services.factory)
    assert (
        await restored.snapshot(workspace, created.job_id)
    ).state == "awaiting_selection"
    assert (await restored.current(workspace)).job_id == created.job_id


@pytest.mark.asyncio
async def test_apply_projects_progress_and_replays_terminal_event(
    tmp_path: Path,
) -> None:
    services = _FakeServices()
    workspace = _workspace(tmp_path)
    manager = PortabilityImportJobManager(service_factory=services.factory)
    created = await manager.create(workspace, ["codex"])
    await _wait_job(manager, workspace, created.job_id)

    await manager.start(
        workspace,
        created.job_id,
        {
            "codex": ImportSelection(
                sessions=True,
                skills=["codex-skill"],
            ),
        },
    )
    await _wait_job(manager, workspace, created.job_id)
    snapshot = await manager.snapshot(workspace, created.job_id)
    events = [
        event async for event in manager.subscribe(workspace, created.job_id)
    ]

    assert snapshot.state == "completed"
    assert snapshot.providers[0].sessions_processed == 1
    assert snapshot.providers[0].sessions_imported == 1
    assert snapshot.providers[0].assets[0].state is ImportAssetState.SUCCEEDED
    assert snapshot.providers[0].assets[0].enabled is False
    assert "sk-test-secret" not in "\n".join(snapshot.logs)
    assert events[-1]["snapshot"]["state"] == "completed"
    assert [event["seq"] for event in events] == sorted(
        event["seq"] for event in events
    )


@pytest.mark.asyncio
async def test_only_one_active_import_runs_per_agent(tmp_path: Path) -> None:
    services = _FakeServices()
    services.block_apply.clear()
    workspace = _workspace(tmp_path)
    manager = PortabilityImportJobManager(service_factory=services.factory)
    first = await manager.create(workspace, ["codex"])
    with pytest.raises(RuntimeError, match="already active"):
        await manager.create(workspace, ["qoder"])
    await manager.cancel(workspace, first.job_id)


@pytest.mark.asyncio
async def test_cancel_keeps_draining_mission_job_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    manager = PortabilityImportJobManager()
    release = asyncio.Event()

    async def worker() -> None:
        while not release.is_set():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                continue

    job_id = "import-" + "d" * 32
    live = _LiveJob(
        workspace=workspace,
        snapshot=ImportRun(
            job_id=job_id,
            agent_id=workspace.agent_id,
            state="running",
        ),
        task=asyncio.create_task(worker()),
    )
    manager._jobs[(workspace.agent_id, job_id)] = live
    await asyncio.sleep(0)
    monkeypatch.setattr(
        "qwenpaw.portability.import_jobs._CANCEL_GRACE_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        "qwenpaw.portability.import_jobs.has_draining_workers",
        lambda _workspace: True,
    )

    snapshot = await manager.cancel(workspace, job_id)

    assert snapshot.state == "cancelling"
    assert not live.task.done()
    with pytest.raises(RuntimeError, match="compatibility worker"):
        await manager.create(workspace, ["codex"])
    release.set()
    live.task.cancel()
    await live.task
    assert (await manager.cancel(workspace, job_id)).state == "interrupted"


@pytest.mark.asyncio
async def test_cancel_of_uncooperative_job_is_bounded_and_keeps_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    manager = PortabilityImportJobManager()
    release = asyncio.Event()

    async def worker() -> None:
        while not release.is_set():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                continue

    live = _LiveJob(
        workspace=workspace,
        snapshot=ImportRun(
            job_id="import-" + "e" * 32,
            agent_id=workspace.agent_id,
            state="running",
        ),
    )
    manager._jobs[(workspace.agent_id, live.snapshot.job_id)] = live
    manager._spawn(live, worker)
    await asyncio.sleep(0)
    monkeypatch.setattr(
        "qwenpaw.portability.import_jobs._CANCEL_GRACE_SECONDS",
        0.01,
    )

    snapshot = await asyncio.wait_for(
        manager.cancel(workspace, live.snapshot.job_id),
        timeout=0.2,
    )

    assert snapshot.state == "cancelling"
    with pytest.raises(RuntimeError, match="already active"):
        await manager.create(workspace, ["codex"])
    release.set()
    live.task.cancel()
    await live.task
    assert (await manager.snapshot(workspace, live.snapshot.job_id)).state == (
        "interrupted"
    )


@pytest.mark.asyncio
async def test_shutdown_of_uncooperative_job_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    manager = PortabilityImportJobManager()
    release = asyncio.Event()

    async def worker() -> None:
        while not release.is_set():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                continue

    live = _LiveJob(
        workspace=workspace,
        snapshot=ImportRun(
            job_id="import-" + "f" * 32,
            agent_id=workspace.agent_id,
            state="running",
        ),
    )
    manager._jobs[(workspace.agent_id, live.snapshot.job_id)] = live
    manager._spawn(live, worker)
    await asyncio.sleep(0)
    monkeypatch.setattr(
        "qwenpaw.portability.import_jobs._CANCEL_GRACE_SECONDS",
        0.01,
    )

    await asyncio.wait_for(manager.shutdown(drain_timeout=0.01), timeout=0.2)

    assert live.snapshot.state == "cancelling"
    release.set()
    live.task.cancel()
    await live.task


@pytest.mark.asyncio
async def test_shutdown_cancels_active_jobs_and_rejects_new_ones(
    tmp_path: Path,
) -> None:
    services = _FakeServices()
    services.block_apply.clear()
    workspace = _workspace(tmp_path)
    manager = PortabilityImportJobManager(service_factory=services.factory)
    created = await manager.create(workspace, ["codex"])
    await _wait_job(manager, workspace, created.job_id)
    await manager.start(
        workspace,
        created.job_id,
        {"codex": ImportSelection(skills=["codex-skill"])},
    )
    await services.apply_started.wait()

    await manager.shutdown()

    assert (
        await manager.snapshot(workspace, created.job_id)
    ).state == "interrupted"
    with pytest.raises(RuntimeError, match="shutting down"):
        await manager.create(workspace, ["qoder"])


@pytest.mark.asyncio
async def test_retry_creates_a_new_job_for_selected_failed_tools(
    tmp_path: Path,
) -> None:
    services = _FakeServices()
    services.fail_apply.add("qoder")
    workspace = _workspace(tmp_path)
    manager = PortabilityImportJobManager(service_factory=services.factory)
    original = await manager.create(workspace, ["codex", "qoder"])
    await _wait_job(manager, workspace, original.job_id)
    await manager.start(
        workspace,
        original.job_id,
        {
            source: ImportSelection(sessions=False, skills=[f"{source}-skill"])
            for source in ("codex", "qoder")
        },
    )
    await _wait_job(manager, workspace, original.job_id)

    retry = await manager.retry(
        workspace,
        original.job_id,
        {"qoder": ImportSelection(sessions=False, skills=["qoder-skill"])},
    )
    await _wait_job(manager, workspace, retry.job_id)
    snapshot = await manager.snapshot(workspace, retry.job_id)

    assert retry.job_id != original.job_id
    assert snapshot.state == "completed"
    assert len(snapshot.providers) == 2
    assert snapshot.providers[0].assets[0].state is ImportAssetState.SUCCEEDED
    assert snapshot.providers[1].assets[0].state is ImportAssetState.SUCCEEDED
    assert services.retries == [
        (
            "plan-" + "q" * 32,
            ImportSelection(sessions=False, skills=["qoder-skill"]),
        ),
    ]
