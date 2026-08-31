# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Work-graph scheduler: parallel fan-out with fuses, not a retry cannon."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from domain.enums import TaskStatus
from services.file_agent_runtime.work_graph import WorkNode, WorkNodeStatus
from services.file_agent_runtime.work_scheduler import (
    WorkGraphScheduler,
    _blocked_by_active_media_review,
    _blocked_by_active_sync_review,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    Project,
    VisualEntity,
    VisualVariant,
)

pytestmark = pytest.mark.unit

PROJECT_ID = "scheduler-project"


@pytest.mark.parametrize(
    ("kind", "blocked"),
    [
        ("visual", False),
        ("lineup", False),
        ("storyboard", True),
        ("video", True),
        ("compose", True),
    ],
)
def test_async_media_review_fences_only_dependent_billed_work(
    kind,
    blocked,
) -> None:
    node = WorkNode(
        node_id=f"{kind}:one",
        kind=kind,
        label=kind,
        status=WorkNodeStatus.READY,
    )
    assert (
        _blocked_by_active_media_review(
            node,
            frozenset({"element:e:storyboard"}),
        )
        is blocked
    )
    assert _blocked_by_active_media_review(node, frozenset()) is False


@pytest.mark.parametrize(
    ("kind", "blocked"),
    [
        ("visual", False),
        ("lineup", False),
        ("storyboard", True),
        ("video", True),
        ("compose", True),
    ],
)
def test_sync_review_is_a_pre_generation_scheduler_gate(
    kind,
    blocked,
) -> None:
    node = WorkNode(
        node_id=f"{kind}:sync",
        kind=kind,
        label=kind,
        status=WorkNodeStatus.READY,
    )
    assert (
        _blocked_by_active_sync_review(
            node,
            sync_review_pending=True,
        )
        is blocked
    )
    assert not _blocked_by_active_sync_review(
        node,
        sync_review_pending=False,
    )


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
        records: list | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self._fail = fail
        self._error = error
        # Mirrors real executors' admission-then-failure record order.
        self._records = records
        self.started = asyncio.Event()

    async def __call__(self, services, **kwargs):
        self.calls.append(kwargs)
        self.started.set()
        if self._fail and self._records is not None:
            self._records.append(
                SimpleNamespace(
                    kind="image_generation",
                    status=TaskStatus.FAILED,
                    error={
                        "code": "IMAGE_GENERATION_FAILED",
                        "message": self._error,
                    },
                    result=None,
                    metadata={"targetRef": kwargs["target_ref"]},
                    input_refs=[kwargs["target_ref"]],
                    idempotency_key=kwargs["idempotency_key"],
                    updated_at=(f"2026-08-12T00:00:{len(self.calls):02d}Z"),
                ),
            )
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


def _failed_record(dispatch: _RecordingDispatch, *, error: str):
    """The durable FAILED record a real executor leaves after admission."""
    call = dispatch.calls[0]
    return SimpleNamespace(
        kind="image_generation",
        status=TaskStatus.FAILED,
        error={"code": "IMAGE_GENERATION_FAILED", "message": error},
        result=None,
        metadata={"targetRef": call["target_ref"]},
        input_refs=[call["target_ref"]],
        idempotency_key=call["idempotency_key"],
        updated_at="2026-08-12T00:00:01Z",
    )


def test_same_inputs_are_never_redispatched(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch(fail=True)
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()
        record = _failed_record(dispatch, error="provider down")
        monkeypatch.setattr(
            scheduler.executions,
            "list_tasks",
            lambda _project_id: [record],
        )
        # Second tick: the durable record locks the ledger; inputs
        # unchanged.
        await scheduler.tick(PROJECT_ID)
        await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert len(dispatch.calls) == 1


def test_changed_prompt_reopens_dispatch(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    records: list = []
    dispatch = _RecordingDispatch(fail=True, records=records)
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)
    monkeypatch.setattr(
        scheduler.executions,
        "list_tasks",
        lambda _project_id: list(records),
    )

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()
        # Quiesce the failure-woken background loop so the reopen below
        # is attributable to the fingerprint change alone (the ledger
        # and retry budgets live on the instance and survive shutdown).
        await scheduler.shutdown()
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


def test_transient_budget_reopens_after_the_cooldown(tmp_path, monkeypatch):
    """Field run 2026-08-12 (27dc): provider weather outlived the
    immediate retry budget and every storyboard FAILED terminally.
    After the immediate budget, one retry per cooldown window re-enters
    up to the hard cap."""
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch(
        fail=True,
        error="Image generation timed out after 240s",
    )
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    def age_past_cooldown() -> None:
        # Rewind the recorded retry stamps instead of freezing the global
        # monotonic clock (asyncio's loop shares it).
        stamps = scheduler._transient_last  # pylint: disable=protected-access
        for key in list(stamps):
            stamps[key] -= 301.0

    async def scenario():
        for _ in range(4):  # initial + 2 immediate retries, then locked
            await scheduler.tick(PROJECT_ID)
            await _drain()
        assert len(dispatch.calls) == 3
        # Cooldown not elapsed: still locked.
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(dispatch.calls) == 3
        # The cooldown elapses: exactly one more bounded retry.
        age_past_cooldown()
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(dispatch.calls) == 4
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(dispatch.calls) == 4
        # Cooldown windows keep granting retries only up to the hard cap.
        for _ in range(8):
            age_past_cooldown()
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    # initial + hard cap of 6 noted retries, then permanently locked.
    assert len(dispatch.calls) == 7


def test_prespend_rejection_never_poisons_the_ledger(tmp_path, monkeypatch):
    """A ValidationError raised before any task record must not strand
    the node READY-but-undispatchable (field run 2026-08-12, project
    27dc: the execution gate refused a storyboard the graph derived
    READY, and only a restart cleared the ledger). The reopen stays
    bounded by the transient budget so a persistent graph/executor
    mismatch cannot hot-loop."""
    from domain.errors import ValidationError

    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)

    calls: list[dict] = []

    async def rejecting_dispatch(inner_services, **kwargs):  # noqa: ARG001
        del inner_services
        calls.append(kwargs)
        raise ValidationError("视觉设定尚未完成，分镜图未开始")

    scheduler = WorkGraphScheduler(services, image_dispatch=rejecting_dispatch)

    async def scenario():
        # Initial dispatch + bounded no-record reopens, then locked by
        # the cooldown — never a permanent READY-but-undispatchable stall.
        for _ in range(5):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert len(calls) == 3


def test_cancel_project_does_not_resurrect_dispatch_and_wake_rearms(
    tmp_path,
    monkeypatch,
) -> None:
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocking_dispatch(inner_services, **kwargs):  # noqa: ARG001
        del inner_services, kwargs
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    scheduler = WorkGraphScheduler(
        services,
        image_dispatch=blocking_dispatch,
    )

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await asyncio.wait_for(started.wait(), timeout=1)
        scheduler.cancel_project(PROJECT_ID)
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        await asyncio.sleep(0)
        assert PROJECT_ID not in scheduler._loops
        assert PROJECT_ID not in scheduler._dispatch_tasks
        assert PROJECT_ID in scheduler._cancelled_projects

        scheduler.wake(PROJECT_ID)
        assert PROJECT_ID not in scheduler._cancelled_projects
        scheduler.cancel_project(PROJECT_ID)
        await scheduler.shutdown()

    asyncio.run(scenario())


def _node_ledger_keys(scheduler, node_id):
    """Deterministic-ledger keys for one node (ledger is fingerprint-keyed)."""
    return [
        key
        for key in scheduler._deterministic_failure_nodes
        if key[0] == PROJECT_ID and key[1] == node_id
    ]


@pytest.mark.parametrize(
    "error_code",
    [
        "IMAGE_REFERENCE_BUDGET_EXCEEDED",
        "VIDEO_MODEL_CAPABILITY_UNKNOWN",
    ],
)
def test_deterministic_error_blocks_retries(
    tmp_path,
    monkeypatch,
    error_code,
):
    """Errors with specific codes (e.g., IMAGE_REFERENCE_BUDGET_EXCEEDED)
    must block all further retries until the project is modified and the
    node succeeds. This prevents hot-looping on structural errors that
    require explicit agent intervention."""
    from domain.errors import ValidationError

    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)

    calls: list[dict] = []

    class BudgetExceededError(ValidationError):
        code = error_code

    async def rejecting_dispatch(inner_services, **kwargs):  # noqa: ARG001
        del inner_services
        calls.append(kwargs)
        raise BudgetExceededError("4 张参考图超过模型限制 3 张")

    scheduler = WorkGraphScheduler(services, image_dispatch=rejecting_dispatch)

    async def scenario():
        for _ in range(10):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    # Only 1 dispatch — the deterministic error blocks all retries.
    assert len(calls) == 1
    # The node is recorded as deterministically failed (keyed by the
    # inputs fingerprint, so an unchanged project keeps it locked).
    assert _node_ledger_keys(scheduler, "visual:char:a:var:0")


def test_deterministic_failure_cleared_on_success(tmp_path, monkeypatch):
    """A successful dispatch clears the deterministic failure record,
    allowing the node to be dispatched again if needed."""
    from domain.errors import ValidationError

    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)

    calls: list[dict] = []
    records: list = []
    fail_first = True

    class BudgetExceededError(ValidationError):
        code = "IMAGE_REFERENCE_BUDGET_EXCEEDED"

    async def conditional_dispatch(inner_services, **kwargs):  # noqa: ARG001
        del inner_services
        calls.append(kwargs)
        nonlocal fail_first
        if fail_first:
            fail_first = False
            raise BudgetExceededError("4 张参考图超过模型限制 3 张")
        # Real executors leave the durable record behind, so the node is no
        # longer recordless once it succeeds.
        records.append(
            SimpleNamespace(
                kind="image_generation",
                status=TaskStatus.SUCCEEDED,
                error=None,
                result={"outputRef": "artifact-version:ok"},
                metadata={"targetRef": kwargs["target_ref"]},
                input_refs=[kwargs["target_ref"]],
                idempotency_key=kwargs["idempotency_key"],
                updated_at="2026-08-12T00:00:01Z",
            ),
        )
        return SimpleNamespace(status="SUCCEEDED")

    scheduler = WorkGraphScheduler(
        services,
        image_dispatch=conditional_dispatch,
    )
    monkeypatch.setattr(
        scheduler.executions,
        "list_tasks",
        lambda _project_id: list(records),
    )
    # The ticks below are the whole schedule: the post-dispatch wake would add
    # background ticks whose timing, not the ledger, decides the dispatch
    # count.
    monkeypatch.setattr(scheduler, "wake", lambda _project_id: None)

    async def scenario():
        # First tick: fails with deterministic error.
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(calls) == 1
        assert _node_ledger_keys(scheduler, "visual:char:a:var:0")

        # More ticks should NOT dispatch again (blocked by deterministic).
        for _ in range(5):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        assert len(calls) == 1

        # Manually clear the deterministic failure to simulate project fix.
        for key in _node_ledger_keys(scheduler, "visual:char:a:var:0"):
            scheduler._deterministic_failure_nodes.pop(key, None)
        scheduler._dispatched.clear()

        # Next tick: succeeds and clears the record.
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(calls) == 2
        assert not _node_ledger_keys(scheduler, "visual:char:a:var:0")

        # Later ticks must not pay for the node twice: the durable record
        # left by the successful dispatch keeps the recordless reopen from
        # re-arming the ledger.
        for _ in range(3):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        assert len(calls) == 2

        await scheduler.shutdown()

    asyncio.run(scenario())


def test_deterministic_failure_unlocks_when_inputs_change(
    tmp_path,
    monkeypatch,
):
    """Fixing the node's inputs must re-enable dispatch without manual
    ledger surgery: the deterministic ledger is fingerprint-keyed, so a
    prompt rewrite (new fingerprint) escapes the lock. Field run
    2026-08-24, project db7d: four storyboards stayed undispatchable for
    20+ minutes after the agent had already fixed the reference budget,
    because the ledger ignored the changed inputs."""
    from domain.errors import ValidationError

    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)

    calls: list[dict] = []

    class BudgetExceededError(ValidationError):
        code = "IMAGE_REFERENCE_BUDGET_EXCEEDED"

    async def rejecting_dispatch(inner_services, **kwargs):  # noqa: ARG001
        del inner_services
        calls.append(kwargs)
        raise BudgetExceededError("4 张参考图超过模型限制 3 张")

    scheduler = WorkGraphScheduler(services, image_dispatch=rejecting_dispatch)
    monkeypatch.setattr(scheduler, "wake", lambda _project_id: None)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(calls) == 1
        # Unchanged inputs stay locked.
        for _ in range(3):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        assert len(calls) == 1
        # The agent fixes the inputs: fingerprint moves, dispatch reopens
        # without anyone touching the ledger.
        snapshot = services.projects.read(PROJECT_ID)
        candidate = snapshot.project.model_dump(mode="json")
        candidate["visual"]["entities"]["items"]["char:a"]["variants"][
            "items"
        ]["var:0"]["prompt"] = "trimmed references prompt"
        candidate["generation"] = snapshot.project.generation + 1
        services.projects.replace(
            PROJECT_ID,
            Project.model_validate(candidate),
            expected_etag=snapshot.etag,
        )
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(calls) == 2
        await scheduler.shutdown()

    asyncio.run(scenario())


def test_deterministic_failure_unlocks_when_media_model_changes(
    tmp_path,
    monkeypatch,
):
    """Switching the configured media model is an input change too: a
    reference-budget rejection under a small-budget model must not keep
    the node locked after the operator configures a roomier model."""
    from domain.errors import ValidationError
    from services.file_agent_runtime import work_scheduler as scheduler_mod

    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)

    calls: list[dict] = []

    class BudgetExceededError(ValidationError):
        code = "IMAGE_REFERENCE_BUDGET_EXCEEDED"

    async def rejecting_dispatch(inner_services, **kwargs):  # noqa: ARG001
        del inner_services
        calls.append(kwargs)
        raise BudgetExceededError("4 张参考图超过模型限制 3 张")

    monkeypatch.setattr(
        scheduler_mod,
        "get_image_model_name",
        lambda: "small-budget-model",
    )
    scheduler = WorkGraphScheduler(services, image_dispatch=rejecting_dispatch)
    monkeypatch.setattr(scheduler, "wake", lambda _project_id: None)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(calls) == 1
        # Same model, same inputs: locked.
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(calls) == 1
        # New model → new ledger fingerprint → dispatch reopens without
        # anyone touching the ledger or the in-memory dispatch record.
        monkeypatch.setattr(
            scheduler_mod,
            "get_image_model_name",
            lambda: "large-budget-model",
        )
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(calls) == 2
        await scheduler.shutdown()

    asyncio.run(scenario())
