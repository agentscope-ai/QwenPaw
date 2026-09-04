# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Work-graph scheduler: parallel fan-out with fuses, not a retry cannon."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from domain.enums import TaskStatus
from services.file_agent_runtime.work_graph import (
    WorkGraph,
    WorkNode,
    WorkNodeStatus,
)
from services.file_agent_runtime import work_scheduler
from services.file_agent_runtime.work_scheduler import (
    WorkGraphScheduler,
    _blocked_by_active_media_review,
    _blocked_by_active_sync_review,
)
from services.runtime_files.path_safety import require_safe_runtime_segment
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
            frozenset({"element:e"}),
        )
        is blocked
    )
    assert (
        _blocked_by_active_media_review(node, frozenset(), frozenset())
        is False
    )


@pytest.mark.parametrize(
    ("kind", "target_ref", "active_slots", "active_owners", "blocked"),
    [
        # visual/lineup without target_ref: never blocked
        (
            "visual",
            None,
            {"asset:hero:variant:v1:image"},
            {"asset:hero"},
            False,
        ),
        ("lineup", None, {"lineup:cast:image"}, {"lineup:cast"}, False),
        # visual/lineup with non-matching target_ref: not blocked
        (
            "visual",
            "asset:hero",
            {"asset:villain:variant:v1:image"},
            {"asset:villain"},
            False,
        ),
        (
            "lineup",
            "lineup:cast-a",
            {"lineup:cast-b:image"},
            {"lineup:cast-b"},
            False,
        ),
        # visual/lineup whose owner is under review: blocked
        (
            "visual",
            "asset:hero",
            {"asset:hero:variant:v1:image"},
            {"asset:hero"},
            True,
        ),
        (
            "lineup",
            "lineup:cast",
            {"lineup:cast:image"},
            {"lineup:cast"},
            True,
        ),
        # storyboard/video/compose: always blocked when any slot is active
        (
            "storyboard",
            None,
            {"asset:hero:variant:v1:image"},
            {"asset:hero"},
            True,
        ),
        ("video", None, {"asset:hero:variant:v1:image"}, {"asset:hero"}, True),
        (
            "compose",
            None,
            {"asset:hero:variant:v1:image"},
            {"asset:hero"},
            True,
        ),
        # storyboard/video/compose: not blocked when no slots are active
        ("storyboard", None, set(), set(), False),
        ("video", None, set(), set(), False),
        ("compose", None, set(), set(), False),
    ],
)
def test_media_review_blocking_considers_target_ref(
    kind: str,
    target_ref: str | None,
    active_slots: set[str],
    active_owners: set[str],
    blocked: bool,
) -> None:
    node = WorkNode(
        node_id=f"{kind}:test",
        kind=kind,
        label=kind,
        status=WorkNodeStatus.READY,
        target_ref=target_ref,
    )
    assert (
        _blocked_by_active_media_review(
            node,
            frozenset(active_slots),
            frozenset(active_owners),
        )
        is blocked
    )


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
    # The key travels on to the Task as caused_by_request_id, so it has to be
    # a legal path segment; a prefix check alone let "|model" separators
    # through and every dispatch was rejected.
    require_safe_runtime_segment(key, label="caused_by_request_id")


def test_idempotency_key_survives_provider_qualified_model_names(
    tmp_path,
    monkeypatch,
):
    """Model names feed the fingerprint and may contain "/"."""
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    monkeypatch.setattr(
        work_scheduler,
        "get_image_model_name",
        lambda: "provider/gpt-image-2",
    )
    monkeypatch.setattr(
        work_scheduler,
        "get_video_model_name",
        lambda: "provider/kling-v2",
    )
    dispatch = _RecordingDispatch()
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()

    asyncio.run(scenario())

    key = dispatch.calls[0]["idempotency_key"]
    require_safe_runtime_segment(key, label="caused_by_request_id")
    assert "/" not in key


def test_ledger_fingerprint_still_reopens_on_model_change():
    """Switching model must mint a new ledger identity."""
    node = SimpleNamespace(
        node_id="visual:char:a:var:0",
        dispatch_fingerprint="a1b2c3d4e5f60718",
    )

    def fingerprint_for(image_model: str, video_model: str) -> str:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                work_scheduler,
                "get_image_model_name",
                lambda: image_model,
            )
            patch.setattr(
                work_scheduler,
                "get_video_model_name",
                lambda: video_model,
            )
            return WorkGraphScheduler._ledger_fingerprint(node)

    baseline = fingerprint_for("image-a", "video-a")
    assert baseline == fingerprint_for("image-a", "video-a")
    assert baseline != fingerprint_for("image-b", "video-a")
    assert baseline != fingerprint_for("image-a", "video-b")


def test_idempotency_key_is_a_safe_runtime_segment(tmp_path, monkeypatch):
    """Regression: the ledger fingerprint carries "|img:<model>|vid:<model>"
    and "|" is rejected by require_safe_runtime_segment. Media executors
    persist the dispatch key verbatim as Task idempotency_key /
    caused_by_request_id, so a raw fingerprint in the key failed every
    work-graph dispatch ("caused_by_request_id is not a safe path
    segment") and media generation never started."""
    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch()
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()

    asyncio.run(scenario())

    key = dispatch.calls[0]["idempotency_key"]
    assert "|" not in key
    assert (
        require_safe_runtime_segment(key, label="caused_by_request_id") == key
    )


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
    """A ValidationError raised before any task record is a deterministic
    failure: the node is marked as such and never retried (field run
    2026-08-12, project 27dc: the execution gate refused a storyboard the
    graph derived READY, and only a restart cleared the ledger). The
    deterministic failure is exposed to the driver so the model is
    invoked to handle it."""
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

    assert len(calls) == 1


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
        work_scheduler,
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
            work_scheduler,
            "get_image_model_name",
            lambda: "large-budget-model",
        )
        await scheduler.tick(PROJECT_ID)
        await _drain()
        assert len(calls) == 2
        await scheduler.shutdown()

    asyncio.run(scenario())


def test_idle_exit_confirms_the_graph_is_drained_first(tmp_path, monkeypatch):
    """Field run 2026-08-26: three storyboards reached READY after the agent
    turn ended. wake() only fires from agent turns and media review, so the
    project loop idled out and returned with that work undispatched; 43% of
    the timeline then had no media and the live preview stayed black there.
    The idle exit must confirm the graph is drained before giving up.
    """

    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    dispatch = _RecordingDispatch()
    scheduler = WorkGraphScheduler(services, image_dispatch=dispatch)
    monkeypatch.setattr(work_scheduler, "_IDLE_EXIT_SECONDS", 0.05)

    async def scenario():
        # Start the loop without ever setting the wake event, so the only
        # path to dispatch is the idle-timeout drain check.
        loop_task = asyncio.create_task(scheduler._project_loop(PROJECT_ID))
        for _ in range(60):
            await asyncio.sleep(0.05)
            if dispatch.calls:
                break
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        await _drain()

    asyncio.run(scenario())

    assert (
        dispatch.calls
    ), "idle exit abandoned a READY node instead of dispatching it"


# -- notification bus emission -------------------------------------------


class _RecordingBus:
    def __init__(self) -> None:
        self.events: list[SimpleNamespace] = []

    async def notify(
        self,
        project_id,
        *,
        kind,
        request_id,
        text,
        payload=None,
    ) -> None:
        self.events.append(
            SimpleNamespace(
                project_id=project_id,
                kind=kind,
                request_id=request_id,
                text=text,
                payload=dict(payload or {}),
            ),
        )

    def kinds(self) -> list:
        return [event.kind for event in self.events]


def test_dispatch_start_and_image_success_emit_quiet(tmp_path, monkeypatch):
    from services.file_agent_runtime.notifications import RuntimeEventKind

    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    bus = _RecordingBus()
    dispatch = _RecordingDispatch()
    scheduler = WorkGraphScheduler(
        services,
        image_dispatch=dispatch,
        notifications=bus,
    )

    async def scenario():
        await scheduler.tick(PROJECT_ID)
        await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert bus.kinds() == [
        RuntimeEventKind.NODE_DISPATCH_STARTED,
        RuntimeEventKind.NODE_SUCCEEDED,
    ]
    assert bus.events[0].payload["nodeId"] == bus.events[1].payload["nodeId"]


def test_r2v_submit_does_not_emit_success(tmp_path, monkeypatch):
    from domain.enums import CreatorCommandType
    from services.file_agent_runtime.notifications import RuntimeEventKind

    services = _services(tmp_path, monkeypatch, ready_variants=0)
    bus = _RecordingBus()

    async def submitting_r2v(inner_services, **kwargs):  # noqa: ARG001
        del inner_services, kwargs
        return SimpleNamespace(task_id="task-r2v-1")

    scheduler = WorkGraphScheduler(
        services,
        r2v_dispatch=submitting_r2v,
        notifications=bus,
    )
    node = WorkNode(
        node_id="video:e1",
        kind="video",
        label="视频 e1",
        status=WorkNodeStatus.READY,
        command=CreatorCommandType.GENERATE_R2V_VIDEO.value,
        target_ref="element:e1",
        dispatch_fingerprint="fp-r2v",
    )

    asyncio.run(scheduler._dispatch(PROJECT_ID, node, "fp-r2v"))

    assert bus.kinds() == [RuntimeEventKind.NODE_DISPATCH_STARTED]


def test_deterministic_failure_emits_steer(tmp_path, monkeypatch):
    from domain.errors import ValidationError
    from services.file_agent_runtime.notifications import RuntimeEventKind

    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    bus = _RecordingBus()

    class BudgetExceededError(ValidationError):
        code = "IMAGE_REFERENCE_BUDGET_EXCEEDED"

    async def rejecting_dispatch(inner_services, **kwargs):  # noqa: ARG001
        del inner_services, kwargs
        raise BudgetExceededError("4 张参考图超过模型限制 3 张")

    scheduler = WorkGraphScheduler(
        services,
        image_dispatch=rejecting_dispatch,
        notifications=bus,
    )

    async def scenario():
        for _ in range(3):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    failures = [
        event
        for event in bus.events
        if event.kind is RuntimeEventKind.NODE_DETERMINISTIC_FAILURE
    ]
    assert len(failures) == 1
    assert "IMAGE_REFERENCE_BUDGET_EXCEEDED" in failures[0].request_id
    assert "参考图" in failures[0].text
    assert failures[0].payload["errorCode"] == (
        "IMAGE_REFERENCE_BUDGET_EXCEEDED"
    )


def test_transient_hard_cap_emits_steer_once(tmp_path, monkeypatch):
    from services.file_agent_runtime.notifications import RuntimeEventKind

    services = _services(tmp_path, monkeypatch, ready_variants=1)
    _enable_yolo(monkeypatch)
    bus = _RecordingBus()
    dispatch = _RecordingDispatch(
        fail=True,
        error="Image generation timed out after 240s",
    )
    scheduler = WorkGraphScheduler(
        services,
        image_dispatch=dispatch,
        notifications=bus,
    )

    def age_past_cooldown() -> None:
        stamps = scheduler._transient_last
        for key in list(stamps):
            stamps[key] -= 301.0

    async def scenario():
        for _ in range(4):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        for _ in range(10):
            age_past_cooldown()
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    exhausted = [
        event
        for event in bus.events
        if event.kind is RuntimeEventKind.NODE_TRANSIENT_CAP_EXHAUSTED
    ]
    assert len(exhausted) == 1


def _graph_sequence(monkeypatch, graphs: list[WorkGraph]) -> None:
    state = {"index": 0}

    def fake_derive(_project, tasks=()):
        del tasks
        index = min(state["index"], len(graphs) - 1)
        state["index"] += 1
        return graphs[index]

    monkeypatch.setattr(work_scheduler, "derive_work_graph", fake_derive)


@pytest.mark.parametrize(
    ("node_kind", "node_id", "label", "milestone"),
    [
        ("video", "video:e1", "视频 e1", "node_succeeded"),
        ("compose", "compose:final", "成片", "compose_completed"),
    ],
)
def test_done_edge_emits_milestone_once_across_ticks(
    tmp_path,
    monkeypatch,
    node_kind,
    node_id,
    label,
    milestone,
):
    from services.file_agent_runtime.notifications import RuntimeEventKind

    services = _services(tmp_path, monkeypatch, ready_variants=0)
    _enable_yolo(monkeypatch)
    bus = _RecordingBus()
    running = WorkNode(
        node_id=node_id,
        kind=node_kind,
        label=label,
        status=WorkNodeStatus.RUNNING,
    )
    done = WorkNode(
        node_id=node_id,
        kind=node_kind,
        label=label,
        status=WorkNodeStatus.DONE,
    )
    _graph_sequence(
        monkeypatch,
        [
            WorkGraph(nodes=(running,), generation=1),
            WorkGraph(nodes=(done,), generation=2),
            WorkGraph(nodes=(done,), generation=2),
        ],
    )
    scheduler = WorkGraphScheduler(services, notifications=bus)

    async def scenario():
        for _ in range(3):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert bus.kinds() == [
        RuntimeEventKind(milestone),
        RuntimeEventKind.GRAPH_ALL_DONE,
    ]


def test_gated_node_emits_quiet_with_missing(tmp_path, monkeypatch):
    from services.file_agent_runtime.notifications import RuntimeEventKind

    services = _services(tmp_path, monkeypatch, ready_variants=0)
    _enable_yolo(monkeypatch)
    bus = _RecordingBus()
    running = WorkNode(
        node_id="video:e1",
        kind="video",
        label="视频 e1",
        status=WorkNodeStatus.RUNNING,
    )
    gated = WorkNode(
        node_id="video:e1",
        kind="video",
        label="视频 e1",
        status=WorkNodeStatus.GATED,
        missing=("缺少 Shot 台词原文",),
    )
    _graph_sequence(
        monkeypatch,
        [
            WorkGraph(nodes=(running,), generation=5),
            WorkGraph(nodes=(gated,), generation=6),
        ],
    )
    scheduler = WorkGraphScheduler(services, notifications=bus)

    async def scenario():
        for _ in range(2):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert bus.kinds() == [RuntimeEventKind.NODE_GATED]
    assert "缺少 Shot 台词原文" in bus.events[0].text


def test_restart_scheduler_does_not_duplicate_milestone(
    tmp_path,
    monkeypatch,
):
    """The milestone fires on the unfinished→done edge exactly once.

    An all-DONE baseline (previous is None: restart, or first wake of a
    long-completed project) must stay silent — otherwise every historical
    completed project would replay a NEXT_STEP message and a paid model
    run after each deploy.
    """

    from services.file_agent_runtime.notifications import (
        NOTIFICATION_SOURCE,
        RuntimeNotificationBus,
    )

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())

    def initialize(staged_root) -> None:
        services.sessions.initialize_staged_project(
            staged_root,
            PROJECT_ID,
            session_id="session-restart",
            conversation_id="conversation-restart",
            initial_goal="build",
            goal_id="goal-restart",
            initial_message_id="message-initial",
            initial_client_message_id="client-initial",
        )

    services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Restart"),
        initialize_staged_project=initialize,
    )
    _enable_yolo(monkeypatch)
    running = WorkNode(
        node_id="video:e1",
        kind="video",
        label="视频 e1",
        status=WorkNodeStatus.RUNNING,
    )
    done = WorkNode(
        node_id="video:e1",
        kind="video",
        label="视频 e1",
        status=WorkNodeStatus.DONE,
    )
    _graph_sequence(
        monkeypatch,
        [
            WorkGraph(nodes=(running,), generation=1),
            WorkGraph(nodes=(done,), generation=1),
        ],
    )

    async def scenario():
        first = WorkGraphScheduler(
            services,
            notifications=RuntimeNotificationBus(
                services,
                wake_dispatcher=lambda _project_id: None,
            ),
        )
        await first.tick(PROJECT_ID)  # baseline: RUNNING, silent
        await first.tick(PROJECT_ID)  # edge: unfinished -> all done
        await first.shutdown()
        # Process restart: fresh scheduler + bus, same durable stores. The
        # all-DONE baseline must stay silent and the request-id history
        # keeps the milestone from re-landing either way.
        second = WorkGraphScheduler(
            services,
            notifications=RuntimeNotificationBus(
                services,
                wake_dispatcher=lambda _project_id: None,
            ),
        )
        await second.tick(PROJECT_ID)
        await second.tick(PROJECT_ID)
        await second.shutdown()

    asyncio.run(scenario())

    notifications = [
        item
        for item in services.sessions.list_messages(
            PROJECT_ID,
            "session-restart",
            after_seq=0,
            limit=None,
        )
        if item.role == "user" and item.source == NOTIFICATION_SOURCE
    ]
    assert len(notifications) == 1


def test_all_done_baseline_emits_no_milestone(tmp_path, monkeypatch):
    """A historical completed project must not replay GRAPH_ALL_DONE."""

    from services.file_agent_runtime.notifications import RuntimeEventKind

    services = _services(tmp_path, monkeypatch, ready_variants=0)
    _enable_yolo(monkeypatch)
    bus = _RecordingBus()
    done = WorkNode(
        node_id="video:e1",
        kind="video",
        label="视频 e1",
        status=WorkNodeStatus.DONE,
    )
    _graph_sequence(
        monkeypatch,
        [WorkGraph(nodes=(done,), generation=7)],
    )

    async def scenario():
        scheduler = WorkGraphScheduler(services, notifications=bus)
        await scheduler.tick(PROJECT_ID)
        await scheduler.tick(PROJECT_ID)
        await scheduler.shutdown()

    asyncio.run(scenario())

    assert not [
        event
        for event in bus.events
        if event.kind is RuntimeEventKind.GRAPH_ALL_DONE
    ]


def test_stuck_failed_node_emits_steer_even_on_baseline_tick(
    tmp_path,
    monkeypatch,
):
    """A durably FAILED node needs the Agent even right after a restart."""

    from services.file_agent_runtime.notifications import RuntimeEventKind

    services = _services(tmp_path, monkeypatch, ready_variants=0)
    _enable_yolo(monkeypatch)
    bus = _RecordingBus()
    failed = WorkNode(
        node_id="storyboard:e4",
        kind="storyboard",
        label="第四幕 · 分镜",
        status=WorkNodeStatus.FAILED,
        error="image provider call was interrupted; refusing resubmission",
    )
    _graph_sequence(
        monkeypatch,
        [
            WorkGraph(nodes=(failed,), generation=9),
            WorkGraph(nodes=(failed,), generation=9),
        ],
    )
    scheduler = WorkGraphScheduler(services, notifications=bus)

    async def scenario():
        for _ in range(2):
            await scheduler.tick(PROJECT_ID)
            await _drain()
        await scheduler.shutdown()

    asyncio.run(scenario())

    failures = [
        event
        for event in bus.events
        if event.kind is RuntimeEventKind.NODE_DETERMINISTIC_FAILURE
    ]
    assert (
        len(failures) == 1
    ), "baseline tick must report, later ticks must not"
    assert "provider call was interrupted" in failures[0].text
