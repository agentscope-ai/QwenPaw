# -*- coding: utf-8 -*-
"""Work-graph scheduler: parallel fan-out with fuses, not a retry cannon.

The scheduler dispatches READY media nodes up to media_parallelism,
never redispatches the same node for the same inputs (FAILED stays
parked until something changes), and stays fully inert outside the
unattended ladder.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from domain.enums import TaskStatus
from services.file_agent_runtime.work_scheduler import WorkGraphScheduler
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    Project,
    VisualEntity,
    VisualVariant,
)


pytestmark = pytest.mark.unit

PROJECT_ID = "scheduler-project"


def _entity(entity_id: str, variants: dict[str, str | None]) -> VisualEntity:
    return VisualEntity(
        entity_id=entity_id,
        kind="character",
        name=entity_id,
        required_variant_ids=list(variants),
        variants={
            "items": {
                variant_id: VisualVariant(
                    variant_id=variant_id,
                    prompt=f"prompt {variant_id}",
                    selected_artifact_version_id=selected,
                )
                for variant_id, selected in variants.items()
            },
            "order": list(variants),
        },
    )


def _services(
    tmp_path,
    monkeypatch,
    *,
    ready_variants: int,
) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="Scheduler")
    variants = {f"var:{index}": None for index in range(ready_variants)}
    project.visual.entities.items["char:a"] = _entity("char:a", variants)
    project.visual.entities.order.append("char:a")
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )
    return services


class _RecordingDispatch:
    def __init__(
        self,
        *,
        fail: bool = False,
        error: str = "provider down",
    ) -> None:
        self.calls: list[dict] = []
        self._fail = fail
        self._error = error
        self.started = asyncio.Event()

    async def __call__(self, services, **kwargs):
        self.calls.append(kwargs)
        self.started.set()
        if self._fail:
            raise RuntimeError(self._error)
        return {"ok": True}


def _enable_yolo(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.file_agent_runtime.work_scheduler."
        "get_execution_authorization_mode",
        lambda: "allow_all",
    )


async def _drain() -> None:
    # Let fire-and-forget dispatch tasks run to completion.
    for _ in range(4):
        await asyncio.sleep(0)


def test_tick_dispatches_up_to_media_parallelism(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch, ready_variants=5)
    _enable_yolo(monkeypatch)
    monkeypatch.setattr(
        "services.file_agent_runtime.work_scheduler.get_media_parallelism",
        lambda: 3,
    )
    dispatch = _RecordingDispatch()
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()

    asyncio.run(scenario())

    assert len(dispatch.calls) == 3
    assert all(call["command"] == "GENERATE_ASSET" for call in dispatch.calls)
    variant_ids = {call["arguments"]["variantId"] for call in dispatch.calls}
    assert len(variant_ids) == 3  # three distinct nodes, no duplicates


def test_same_inputs_are_never_redispatched(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch(fail=True)
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()
        # Second tick: the node is FAILED-by-ledger; inputs unchanged.
        await scheduler.tick(PROJECT_ID)
        await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert len(dispatch.calls) == 1


def test_changed_prompt_reopens_dispatch(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch(fail=True)
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()
        # The model rewrites the prompt: fingerprint moves, dispatch reopens.
        snapshot = services.projects.read(PROJECT_ID)
        candidate = snapshot.project.model_dump(mode="json")
        candidate["visual"]["entities"]["items"]["char:a"]["variants"][
            "items"
        ]["var:0"]["prompt"] = "rewritten prompt"
        candidate["generation"] = snapshot.project.generation + 1
        services.projects.replace(
            PROJECT_ID,
            Project.model_validate(candidate),
            expected_etag=snapshot.etag,
        )
        await scheduler.tick(PROJECT_ID)
        await _drain()
        # Failed dispatches wake a background project loop; stop it so
        # asyncio.run teardown never races a pending 300s idle wait.
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert len(dispatch.calls) == 2


def test_scheduler_is_inert_outside_allow_all(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch, ready_variants=2)
    monkeypatch.setattr(
        "services.file_agent_runtime.work_scheduler."
        "get_execution_authorization_mode",
        lambda: "required",
    )
    dispatch = _RecordingDispatch()
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        result = await scheduler.tick(PROJECT_ID)
        await _drain()
        return result

    graph = asyncio.run(scenario())

    assert graph is None
    assert not dispatch.calls


def test_idempotency_key_is_node_and_fingerprint_stable(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch()
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()

    asyncio.run(scenario())

    key = dispatch.calls[0]["idempotency_key"]
    assert key.startswith("dag-visual:char:a:var:0-")


def test_transient_dispatch_failures_reopen_the_ledger_bounded(
    tmp_path,
    monkeypatch,
):
    """Field run 2026-08-06: five storyboards died of provider timeouts
    and the ledger locked them as if deterministic. Transient faults
    reopen the ledger up to the retry limit; the idempotency slot makes
    the retry resume the same task."""
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch(
        fail=True,
        error="Image generation timed out after 240s",
    )
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        for _ in range(4):  # initial + 2 transient retries + 1 extra tick
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    # 1 initial dispatch + 2 bounded transient retries, then locked.
    assert len(dispatch.calls) == 3


def test_deterministic_failures_stay_locked(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch(fail=True, error="safety system rejected")
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        for _ in range(3):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert len(dispatch.calls) == 1


def test_quarantined_stale_result_reopens_dispatch(tmp_path, monkeypatch):
    """Field run 2026-08-07: the first commit of a four-wide storyboard
    wave staled the other three; their tasks went QUARANTINED (invisible
    to the graph), the nodes re-derived READY, and the ledger parked
    them forever. A quarantined-stale stored result reopens the ledger
    (bounded) so the durable slot can rescue it without a second bill."""
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch()
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()
        target_ref = dispatch.calls[0]["target_ref"]
        stale_task = SimpleNamespace(
            kind="image_generation",
            status=TaskStatus.QUARANTINED,
            error={"code": "PROJECT_INPUT_SNAPSHOT_STALE"},
            result={"outputRef": "artifact-version:paid"},
            metadata={"targetRef": target_ref},
            input_refs=[target_ref],
        )
        monkeypatch.setattr(
            scheduler.executions,
            "list_tasks",
            lambda _project_id: [stale_task],
        )
        for _ in range(4):  # 2 bounded reopens, then locked again
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    # 1 initial dispatch + 2 bounded rescue re-dispatches, then locked.
    assert len(dispatch.calls) == 3


def test_quarantine_without_stored_result_stays_locked(
    tmp_path,
    monkeypatch,
):
    """No stored result means a reopen would pay for a fresh render —
    the ledger stays closed and the node waits for an input change."""
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch()
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()
        target_ref = dispatch.calls[0]["target_ref"]
        stale_task = SimpleNamespace(
            kind="image_generation",
            status=TaskStatus.QUARANTINED,
            error={"code": "PROJECT_INPUT_SNAPSHOT_STALE"},
            result=None,
            metadata={"targetRef": target_ref},
            input_refs=[target_ref],
        )
        monkeypatch.setattr(
            scheduler.executions,
            "list_tasks",
            lambda _project_id: [stale_task],
        )
        await scheduler.tick(PROJECT_ID)
        await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert len(dispatch.calls) == 1
