# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Transient image failures reopen a retry slot; deterministic ones stay walls.

Reproduces the 2026-08 production deadlock: a network blip failed the image
Task terminally, and because identical retries derive the same durable slot,
every same-argument resend hit "图片 Task 已终止: FAILED" forever.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
from pathlib import Path

import pytest

from domain.enums import CreatorCommandType
from domain.errors import ConflictError, ValidationError
from services.media_files import image_execution
from services.media_files.image_execution import (
    FileImageExecutionService,
    ImageModelCapabilityError,
    ImageReferenceBudgetError,
    _append_storyboard_panel_aspect_contract,
    _resolve_request,
    _storyboard_panel_aspect_contract,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.project_files.store import ProjectSnapshot
from services.runtime_files.models import (
    ChangeOrigin,
    ReviewPolicy,
    ReviewStatus,
)
from utils.exceptions import ModelError

from .conftest import make_r2v_element, r2v_project_services

pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"retry-image" * 16

PROJECT_ID = "image-resilience-project"
ELEMENT_ID = "r2v-1"

_SAFETY_MESSAGE = (
    "Image generation failed with status 400: "
    "Your request was rejected by the safety system"
)
_PHOTO_URL = "https://example.com/messi-photo.jpg"


def test_storyboard_panel_aspect_contract_preserves_each_video_frame() -> None:
    contract = _storyboard_panel_aspect_contract("9:16", 5)
    assert "target video aspect ratio is 9:16" in contract
    assert "EVERY individual storyboard panel" in contract
    assert "outer storyboard delivery canvas is also 9:16" in contract
    # ceil(sqrt(5)) == 3, and only a square grid keeps cells at 9:16.
    assert "3 columns by 3 rows grid" in contract
    assert "Leave the remaining 4 grid cell(s)" in contract
    assert "never draw, frame or fill a placeholder panel" in contract
    assert "Do not use masonry, a hero panel or mixed-size frames" in contract
    assert "Do not add a title, header, footer" in contract
    assert "Never stretch, squash, crop, merge, skew" in contract
    assert "exactly one visual instance of each named character" in contract
    assert "never be duplicated or cloned inside one panel" in contract

    # Six panels used to be laid out 3 columns by 2 rows, which scales every
    # cell by rows/columns and yields 32:27 cells on a 16:9 sheet.
    six = _storyboard_panel_aspect_contract("16:9", 6)
    assert "3 columns by 3 rows grid" in six
    assert "columns by 2 rows" not in six
    assert "Leave the remaining 3 grid cell(s)" in six

    # A perfect square fills the grid, so there is no whitespace clause.
    four = _storyboard_panel_aspect_contract("16:9", 4)
    assert "2 columns by 2 rows grid" in four
    assert "Leave the remaining" not in four

    appended = _append_storyboard_panel_aspect_contract(
        "legacy storyboard prompt",
        "9:16",
    )
    assert appended.startswith("legacy storyboard prompt")
    assert appended.count("STORYBOARD PANEL ASPECT CONTRACT") == 1
    assert (
        _append_storyboard_panel_aspect_contract(appended, "9:16") == appended
    )


def test_storyboard_resolution_appends_project_panel_ratio_before_spend(
    tmp_path,
    monkeypatch,
) -> None:
    services = _services(tmp_path, monkeypatch)
    snapshot = services.projects.read(PROJECT_ID)
    snapshot.project.settings.aspect_ratio = "9:16"
    resolved = _resolve_request(
        snapshot=snapshot,
        project_root=services.projects.project_root(PROJECT_ID),
        command=CreatorCommandType.GENERATE_STORYBOARD_IMAGE,
        target_ref=f"element:{ELEMENT_ID}",
        arguments={"prompt": "legacy prompt without a panel ratio"},
    )
    assert "EVERY individual storyboard panel's inner picture frame" in (
        resolved.prompt
    )
    assert "exactly 9:16" in resolved.prompt
    assert "columns by" not in resolved.prompt
    assert "placeholder panel" not in resolved.prompt
    assert resolved.aspect_ratio == "9:16"


class _CountingProvider:
    # Safety behaviour is exercised after the model-capability preflight, so
    # this test provider must identify the documented model contract it mocks.
    model_name = "qwen-image-2.0-pro"

    def __init__(self, *, fail_with: str | None = None) -> None:
        self.calls = 0
        self._fail_with = fail_with

    async def generate(self, **_kwargs):
        self.calls += 1
        if self._fail_with is not None:
            raise RuntimeError(self._fail_with)
        return {"content": _PNG, "media_type": "image/png"}


def _services(tmp_path, monkeypatch) -> CreatorFileServices:
    return r2v_project_services(
        tmp_path,
        monkeypatch,
        project_id=PROJECT_ID,
        name="Image Resilience",
        elements=(
            make_r2v_element(
                ELEMENT_ID,
                label="并肩入场",
                narrative="两位球员并肩走向球场",
                storyboard_prompt="动画分镜：两位球员并肩入场",
            ),
        ),
    )


def _execute(services, provider, key="storyboard-key"):
    return asyncio.run(
        FileImageExecutionService(services, provider=provider).execute(
            project_id=PROJECT_ID,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key=key,
        ),
    )


@pytest.mark.parametrize("contention", ["read", "write", "cancel"])
def test_materialized_image_lock_retry_preserves_output_and_cancellation(
    tmp_path,
    monkeypatch,
    contention,
):
    from domain.enums import TaskStatus
    from services.runtime_files.errors import LockTimeoutError

    services = _services(tmp_path, monkeypatch)
    provider = _CountingProvider()
    worker = FileImageExecutionService(services, provider=provider)
    # Observe the boundary after bytes exist, before their Task record write.
    # pylint: disable-next=protected-access
    original_materialize = worker._materialize_and_publish
    original_get = worker.executions.get_task
    original_transition = worker.executions.transition_task
    materialized = False
    injected = False

    async def materialize(*, base, resolved, task, ids, output):
        nonlocal materialized
        result = await original_materialize(
            base=base,
            resolved=resolved,
            task=task,
            ids=ids,
            output=output,
        )
        materialized = True
        return result

    def get_task(project_id, task_id, **kwargs):
        nonlocal injected
        if materialized and not injected and contention == "read":
            injected = True
            raise LockTimeoutError(tmp_path / "project.lock", 10)
        return original_get(project_id, task_id, **kwargs)

    def transition(project_id, task_id, **kwargs):
        nonlocal injected
        if (
            materialized
            and not injected
            and contention != "read"
            and kwargs.get("updates", {}).get("result") is not None
        ):
            injected = True
            if contention == "cancel":
                original_transition(
                    project_id,
                    task_id,
                    expected_status=TaskStatus.RUNNING,
                    status=TaskStatus.CANCELLED,
                )
            raise LockTimeoutError(tmp_path / "project.lock", 10)
        return original_transition(project_id, task_id, **kwargs)

    monkeypatch.setattr(worker, "_materialize_and_publish", materialize)
    monkeypatch.setattr(worker.executions, "get_task", get_task)
    monkeypatch.setattr(worker.executions, "transition_task", transition)
    request = {
        "project_id": PROJECT_ID,
        "command": "GENERATE_STORYBOARD_IMAGE",
        "target_ref": f"element:{ELEMENT_ID}",
        "arguments": {},
        "idempotency_key": "materialized-lock-retry",
    }
    if contention == "cancel":
        with pytest.raises(ConflictError, match="取消"):
            asyncio.run(worker.execute(**request))
        project = services.projects.read(PROJECT_ID).project
        assert not project.assets.artifact_versions_by_id
    else:
        result = asyncio.run(worker.execute(**request))
        replay = asyncio.run(worker.execute(**request))
        assert result.artifact_version_id == replay.artifact_version_id
        assert replay.replayed
        project = services.projects.read(PROJECT_ID).project
        assert (
            result.artifact_version_id
            in project.assets.artifact_versions_by_id
        )
    assert injected and provider.calls == 1


def test_transient_failure_reopens_a_retry_slot(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match="All connection attempts failed"):
        _execute(
            services,
            _CountingProvider(fail_with="All connection attempts failed"),
        )

    # The identical retry must run again instead of hitting the wall.
    result = _execute(services, _CountingProvider())
    assert result.replayed is False and result.artifact_version_id


def test_unclaimed_running_task_recovers_into_a_retry_slot(
    tmp_path,
    monkeypatch,
):
    """An executor死于 claim 前留下的 RUNNING 记录必须可自愈重派。

    2026-09-10 现场：四个场景空镜在 claim_sync 的 lifecycle 锁超时后停在
    RUNNING（无 provider-claim.json），节点被判 RUNNING 永不重派。无 claim
    即无消费，超过宽限期后清为 retryable FAILED，重试槽只再付费一次。
    """

    from domain.enums import TaskStatus
    from services.runtime_files.errors import LockTimeoutError

    services = _services(tmp_path, monkeypatch)
    provider = _CountingProvider()
    worker = FileImageExecutionService(services, provider=provider)

    async def dead_claim(task):
        del task
        raise LockTimeoutError(tmp_path / "project.lock", 10)

    monkeypatch.setattr(worker, "_claim_provider", dead_claim)
    request = {
        "project_id": PROJECT_ID,
        "command": "GENERATE_STORYBOARD_IMAGE",
        "target_ref": f"element:{ELEMENT_ID}",
        "arguments": {},
        "idempotency_key": "scene-anchor",
    }
    with pytest.raises(LockTimeoutError):
        asyncio.run(worker.execute(**request))

    executions = worker.executions
    stuck = executions.list_tasks(PROJECT_ID)[0]
    claim = image_execution.provider_claim_path(
        services.projects.project_root(PROJECT_ID),
        stuck.task_id,
    )
    assert stuck.status.value == "RUNNING"
    assert not claim.exists()
    assert provider.calls == 0

    # Within the grace window the record stays walled: a live executor may
    # legitimately sit between admission and its provider claim.
    fresh_worker = FileImageExecutionService(services, provider=provider)
    with pytest.raises(ConflictError, match="已由另一个执行者领取"):
        asyncio.run(fresh_worker.execute(**request))

    # Past the grace the zombie closes as retryable; the next slot runs and
    # pays the provider exactly once.
    monkeypatch.setattr(
        image_execution,
        "_UNCLAIMED_RUNNING_GRACE_SECONDS",
        0.0,
    )
    result = asyncio.run(fresh_worker.execute(**request))
    assert provider.calls == 1
    assert result.artifact_version_id
    swept = executions.get_task(PROJECT_ID, stuck.task_id)
    assert swept.status is TaskStatus.FAILED
    assert swept.error["retryable"] is True
    assert "timed out" in swept.error["message"]
    # The zombie's SpecialistRun must reach a terminal state too, or the
    # UI keeps deriving background activity forever.
    from domain.enums import SpecialistRunStatus

    assert (
        executions.get_run(PROJECT_ID, swept.run_id).status
        is SpecialistRunStatus.FAILED
    )
    # Recovery tombstones the claim boundary: a still-alive zombie executor
    # that wakes up later loses the claim race and aborts before paying.
    assert claim.exists()
    # pylint: disable-next=protected-access
    assert asyncio.run(fresh_worker._claim_provider(swept)) is False

    # The scheduler sweep shares the predicate: a claimed RUNNING record is
    # provider spend in flight and must never be touched.
    claimed = stuck.model_copy(update={"task_id": "task-claimed"})
    claim_file = image_execution.provider_claim_path(
        services.projects.project_root(PROJECT_ID),
        claimed.task_id,
    )
    claim_file.parent.mkdir(parents=True, exist_ok=True)
    claim_file.write_text("{}", encoding="utf-8")
    assert (
        image_execution.recover_unclaimed_image_tasks(
            services,
            PROJECT_ID,
            [claimed],
        )
        is False
    )


@pytest.mark.parametrize("terminal_status", ["cancelled", "failed"])
# pylint: disable-next=too-many-statements
def test_manual_workgraph_retry_reuses_one_new_media_task(
    tmp_path,
    monkeypatch,
    terminal_status,
):
    import httpx
    from fastapi import FastAPI

    from api import work_graph_routes
    from api.file_session_routes import _cancel_active_project_tasks_sync
    from domain.enums import TaskStatus
    from services.file_agent_runtime.work_graph import derive_work_graph
    from services.file_agent_runtime.work_scheduler import WorkGraphScheduler
    from services.runtime_files.execution_store import ProjectExecutionStore

    services = _services(tmp_path, monkeypatch)

    # pylint: disable-next=too-many-statements
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        provider = _CountingProvider()
        generate = provider.generate
        fail_first = terminal_status == "failed"

        async def controlled_generate(**kwargs):
            started.set()
            await release.wait()
            if fail_first:
                raise RuntimeError("reference preparation failed")
            return await generate(**kwargs)

        provider.generate = controlled_generate
        monkeypatch.setattr(
            image_execution,
            "ExistingImageProvider",
            lambda: provider,
        )
        executions = ProjectExecutionStore(services.root)
        snapshot = services.projects.read(PROJECT_ID)
        node = next(
            node
            for node in derive_work_graph(snapshot.project).nodes
            if node.kind == "storyboard"
        )
        first = asyncio.create_task(
            WorkGraphScheduler(services).dispatch_node(PROJECT_ID, node),
        )
        await asyncio.wait_for(started.wait(), timeout=3)
        if fail_first:
            release.set()
            with pytest.raises(RuntimeError, match="reference preparation"):
                await first
            # Automatic dispatch must retain the failure barrier. Only the
            # manual HTTP route below grants a fresh attempt.
            with pytest.raises(ConflictError, match="FAILED"):
                await WorkGraphScheduler(services).dispatch_node(
                    PROJECT_ID,
                    node,
                )
        else:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            _cancel_active_project_tasks_sync(services, PROJECT_ID)
        previous = executions.list_tasks(PROJECT_ID)[0]
        expected = TaskStatus.FAILED if fail_first else TaskStatus.CANCELLED
        assert previous.status is expected
        fail_first = False
        release.clear()

        app = FastAPI()
        app.include_router(work_graph_routes.router)
        app.dependency_overrides[
            work_graph_routes.project_file_services
        ] = lambda: services
        started.clear()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            path = (
                f"/projects/{PROJECT_ID}/work-graph/nodes/"
                f"{node.node_id}/dispatch"
            )
            retry = asyncio.create_task(client.post(path))
            await asyncio.wait_for(started.wait(), timeout=3)
            repeated = await client.post(path)
            assert repeated.status_code == 200
            assert repeated.json()["dispatched"] is False
            release.set()
            response = await retry
            assert response.status_code == 200
            assert response.json()["dispatched"] is True
            # DONE nodes now re-roll on explicit request (same-prompt
            # regeneration is a user right); with the fresh result still
            # awaiting review, the re-roll is refused loudly instead of
            # being swallowed as "already up to date".
            completed = await client.post(path)
            assert completed.status_code == 409
            assert completed.json()["code"] == "WAITING_REVIEW"
        tasks = executions.list_tasks(PROJECT_ID)
        assert len(tasks) == 2
        assert provider.calls == 1
        assert (
            executions.get_task(
                PROJECT_ID,
                previous.task_id,
            ).status
            is expected
        )
        assert sum(t.status is TaskStatus.SUCCEEDED for t in tasks) == 1

    asyncio.run(scenario())


def test_deterministic_rejection_keeps_the_terminal_wall(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path, monkeypatch)

    # Safety refusals surface as non-retryable ModelError.
    with pytest.raises(ModelError):
        _execute(services, _CountingProvider(fail_with=_SAFETY_MESSAGE))

    with pytest.raises(ConflictError) as caught:
        _execute(services, _CountingProvider())
    message = str(caught.value)
    assert "原失败原因" in message
    assert "rejected by the safety system" in message
    assert "调整 arguments" in message


class _MutatingImageProvider:
    """Commits a Project change mid-render: the fan-out sibling race."""

    def __init__(self, services: CreatorFileServices, mutate) -> None:
        self._services = services
        self._mutate = mutate
        self.calls = 0

    async def generate(self, **_kwargs):
        self.calls += 1
        base = self._services.projects.read(PROJECT_ID)
        candidate = base.project.model_dump(mode="json")
        self._mutate(candidate)
        self._services.commits.commit(
            base=base,
            candidate=candidate,
            origin=ChangeOrigin.RUNTIME_TASK,
            review_policy=ReviewPolicy.AUTO_FIX,
        )
        return {"content": _PNG, "media_type": "image/png"}


def test_sibling_commit_during_render_does_not_quarantine(
    tmp_path,
    monkeypatch,
) -> None:
    """An etag drift that leaves the render inputs intact still publishes."""

    services = _services(tmp_path, monkeypatch)

    def bump_description(candidate: dict) -> None:
        candidate["description"] = "sibling committed while rendering"

    result = _execute(
        services,
        _MutatingImageProvider(services, bump_description),
    )

    assert result.artifact_version_id
    finished = services.projects.read(PROJECT_ID).project
    element = finished.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ]
    assert (
        element.outputs["storyboard"].slot_id
        == f"element:{ELEMENT_ID}:storyboard"
    )


def test_redispatch_rescues_quarantined_stale_result(
    tmp_path,
    monkeypatch,
) -> None:
    """A quarantined-but-paid render is imported, not re-rendered: once
    the render inputs validate again the stored result commits (billed
    once)."""

    services = _services(tmp_path, monkeypatch)
    removed: dict = {}

    def drop_element(candidate: dict) -> None:
        timeline = candidate["timelines"]["items"]["timeline:main"]
        removed["element"] = timeline["elements_by_id"].pop(ELEMENT_ID)

    provider = _MutatingImageProvider(services, drop_element)
    with pytest.raises(ConflictError, match="结果已隔离"):
        _execute(services, provider)
    assert provider.calls == 1

    # Restoring the identical input makes the paid result reusable.
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    timeline = candidate["timelines"]["items"]["timeline:main"]
    timeline["elements_by_id"][ELEMENT_ID] = removed["element"]
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
    )
    result = _execute(services, provider)
    assert provider.calls == 1  # no second render, no second bill
    assert result.replayed is True
    assert result.artifact_version_id


def test_unrescuable_quarantine_allows_fresh_dispatch(
    tmp_path,
    monkeypatch,
) -> None:
    """When a quarantined task's stored result can't be imported (inputs
    changed permanently), the next dispatch creates a fresh task instead
    of raising CONFLICT."""

    services = _services(tmp_path, monkeypatch)

    def permanently_change_inputs(candidate: dict) -> None:
        timeline = candidate["timelines"]["items"]["timeline:main"]
        timeline["elements_by_id"][ELEMENT_ID]["creation"][
            "storyboard_prompt"
        ] = "完全不同的提示词，旧结果无法复用"

    provider = _MutatingImageProvider(services, permanently_change_inputs)
    with pytest.raises(ConflictError, match="结果已隔离"):
        _execute(services, provider)
    assert provider.calls == 1

    result = _execute(services, provider)
    assert provider.calls == 2
    assert not result.replayed
    assert result.artifact_version_id


@pytest.mark.parametrize(
    "field,stale",
    [
        ("storyboard_prompt", True),
        ("narrative", True),
        ("video_prompt", False),
    ],
)
def test_storyboard_rechecks_its_own_inputs_at_publication(
    tmp_path,
    monkeypatch,
    field,
    stale,
):
    services = _services(tmp_path, monkeypatch)

    def mutate(candidate):
        candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
            ELEMENT_ID
        ]["creation"][field] = "新的创作要求：头顶应改成蓝色帽子"

    provider = _MutatingImageProvider(services, mutate)
    if stale:
        with pytest.raises(ConflictError, match="结果已隔离"):
            _execute(services, provider)
        element = (
            services.projects.read(PROJECT_ID)
            .project.timelines.items["timeline:main"]
            .elements_by_id[ELEMENT_ID]
        )
        assert not element.outputs
    else:
        assert _execute(services, provider).artifact_version_id
    assert provider.calls == 1


@pytest.mark.parametrize("change", ["prompt", "references"])
def test_asset_rechecks_variant_prompt_and_reference_order(
    tmp_path,
    monkeypatch,
    change,
):
    services = _services(tmp_path, monkeypatch)
    source = _with_remote_variant_refs(
        _snapshot(
            variants={
                "items": {
                    "var:hero": {
                        "variant_id": "var:hero",
                        "prompt": "头顶橘子的角色设定图",
                    },
                },
                "order": ["var:hero"],
            },
        ),
        "var:hero",
        2,
    )
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    candidate["visual"] = source.project.visual.model_dump(mode="json")
    candidate["assets"]["source_versions_by_id"].update(
        source.project.model_dump(mode="json")["assets"][
            "source_versions_by_id"
        ],
    )
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
    )
    monkeypatch.setattr(
        image_execution,
        "_validate_public_remote_url",
        lambda value: value,
    )

    def mutate(raw):
        variant = raw["visual"]["entities"]["items"]["char:haaland"][
            "variants"
        ]["items"]["var:hero"]
        if change == "prompt":
            variant["prompt"] = "头顶西瓜的角色设定图"
        else:
            variant["reference_asset_version_ids"].reverse()

    provider = _MutatingImageProvider(services, mutate)
    with pytest.raises(ConflictError, match="结果已隔离"):
        asyncio.run(
            FileImageExecutionService(
                services,
                provider=provider,
                image_model_name="qwen-image-2.0-pro",
            ).execute(
                project_id=PROJECT_ID,
                command="GENERATE_ASSET",
                target_ref="asset:char:haaland",
                arguments={"variantId": "var:hero"},
                idempotency_key="asset-input-guard",
            ),
        )
    current = services.projects.read(PROJECT_ID).project
    assert (
        current.visual.entities.items["char:haaland"]
        .variants.items["var:hero"]
        .selected_artifact_version_id
        is None
    )
    # All frozen versions remain available: their mere existence is insufficient.
    assert all(
        version in current.assets.source_versions_by_id
        for version in ("ref-1", "ref-2")
    )
    assert provider.calls == 1


def test_storyboard_rejects_changed_selected_anchor_even_if_old_version_survives(
    tmp_path,
    monkeypatch,
):
    services = _services(tmp_path, monkeypatch)
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    candidate["visual"] = _snapshot(
        variants={
            "items": {
                "hero": {"variant_id": "hero", "prompt": "动画角色身份图"},
            },
            "order": ["hero"],
        },
    ).project.visual.model_dump(mode="json")
    candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        ELEMENT_ID
    ]["creation"]["character_refs"] = ["char:haaland"]
    candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        ELEMENT_ID
    ]["creation"]["storyboard_prompt"] = "[Image 1] 提供角色身份，画出球员入场。"
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
    )
    anchor = asyncio.run(
        FileImageExecutionService(
            services,
            provider=_CountingProvider(),
        ).execute(
            project_id=PROJECT_ID,
            command="GENERATE_ASSET",
            target_ref="asset:char:haaland",
            arguments={"variantId": "hero"},
            idempotency_key="anchor",
        ),
    )
    from .conftest import accept_pending_reviews

    accept_pending_reviews(services, PROJECT_ID)
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    old_version = candidate["assets"]["artifact_versions_by_id"][
        anchor.artifact_version_id
    ]
    candidate["assets"]["artifact_versions_by_id"]["anchor-alternative"] = {
        **old_version,
        "version_id": "anchor-alternative",
    }
    candidate["assets"]["artifact_slots_by_id"][old_version["slot_id"]][
        "version_ids"
    ].append("anchor-alternative")
    candidate["visual"]["entities"]["items"]["char:haaland"]["variants"][
        "items"
    ]["hero"]["generated_artifact_version_ids"].append("anchor-alternative")
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
    )

    def change_selection(raw):
        entity = raw["visual"]["entities"]["items"]["char:haaland"]
        entity["selected_artifact_version_id"] = "anchor-alternative"
        entity["variants"]["items"]["hero"][
            "selected_artifact_version_id"
        ] = "anchor-alternative"
        raw["assets"]["artifact_slots_by_id"][old_version["slot_id"]][
            "selected_version_id"
        ] = "anchor-alternative"

    provider = _MutatingImageProvider(services, change_selection)
    provider.model_name = "qwen-image-2.0-pro"
    with pytest.raises(ConflictError, match="结果已隔离"):
        _execute(services, provider)
    current = services.projects.read(PROJECT_ID).project
    assert anchor.artifact_version_id in current.assets.artifact_versions_by_id
    assert (
        current.assets.artifact_versions_by_id[
            anchor.artifact_version_id
        ].checksum
        == old_version["checksum"]
    )
    assert (
        not current.timelines.items["timeline:main"]
        .elements_by_id[ELEMENT_ID]
        .outputs
    )


def _execute_safety(service, *, key, reference_urls=()):
    arguments = {"variantId": "default"}
    if reference_urls:
        arguments["referenceImageUrls"] = list(reference_urls)
    return asyncio.run(
        service.execute(
            project_id=PROJECT_ID,
            command="GENERATE_ASSET",
            target_ref="asset:illustration",
            arguments=arguments,
            idempotency_key=key,
        ),
    )


def test_safety_rejection_blocks_verbatim_refs_until_dropped(
    tmp_path,
    monkeypatch,
):
    """The refusal names the refs it saw, resending the same refs is
    intercepted locally, and dropping them unblocks generation."""

    services = _services(tmp_path, monkeypatch)
    # Exercise the generic image safety fence. Storyboard references now
    # belong to the persisted project order and reject inline overrides.
    base = services.projects.read(PROJECT_ID)
    candidate = base.project.model_dump(mode="json")
    candidate["visual"]["entities"] = {
        "order": ["illustration"],
        "items": {
            "illustration": {
                "entity_id": "illustration",
                "kind": "character",
                "name": "角色",
                "required_variant_ids": ["default"],
                "variants": {
                    "order": ["default"],
                    "items": {
                        "default": {
                            "variant_id": "default",
                            "prompt": "动画角色身份板",
                        },
                    },
                },
            },
        },
    }
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin=ChangeOrigin.FRONTEND_EDIT,
        review_policy=ReviewPolicy.AUTO_FIX,
    )
    provider = _CountingProvider(fail_with=_SAFETY_MESSAGE)
    service = FileImageExecutionService(services, provider=provider)

    with pytest.raises(ModelError) as caught:
        _execute_safety(service, key="k1", reference_urls=[_PHOTO_URL])
    message = str(caught.value)
    assert _PHOTO_URL in message
    assert "仅修改 prompt 的重试不会成功" in message
    assert caught.value.retryable is False
    assert provider.calls == 1

    # Reworded prompt, identical refs, fresh idempotency key: the provider
    # must not be consulted again.
    with pytest.raises(ConflictError, match="已本地拦截"):
        _execute_safety(service, key="k2", reference_urls=[_PHOTO_URL])
    assert provider.calls == 1

    # Same service, refs removed: the local block must not apply.
    provider._fail_with = None  # pylint: disable=protected-access
    result = _execute_safety(service, key="k3")
    assert result.artifact_version_id
    assert provider.calls == 2


def _snapshot(*, variants: dict | None) -> ProjectSnapshot:
    now = datetime.now(timezone.utc).isoformat()
    variant_collection = variants or {"items": {}, "order": []}
    project = Project.model_validate(
        {
            "project_id": "project-naming",
            "name": "Naming",
            "created_at": now,
            "updated_at": now,
            "visual": {
                "entities": {
                    "items": {
                        "char:haaland": {
                            "entity_id": "char:haaland",
                            "kind": "character",
                            "name": "Erling Haaland (Pixar卡通版)",
                            "description": "Pixar 风格哈兰德",
                            "required_variant_ids": list(
                                variant_collection["order"],
                            ),
                            "variants": variant_collection,
                        },
                    },
                    "order": ["char:haaland"],
                },
            },
        },
    )
    return ProjectSnapshot(project=project, etag="etag-1", generation=1)


def test_generate_asset_artifact_name_includes_the_variant_id(
    tmp_path,
) -> None:
    """Stage variants have independent slots and distinguishable titles."""

    def resolve(snapshot, arguments):
        return _resolve_request(
            snapshot=snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments=arguments,
        )

    snapshot = _snapshot(
        variants={
            "items": {
                "var:haaland-rough": {
                    "variant_id": "var:haaland-rough",
                    "prompt": "rough stage design sheet",
                },
                "var:haaland-idol": {
                    "variant_id": "var:haaland-idol",
                    "prompt": "idol stage design sheet",
                },
            },
            "order": ["var:haaland-rough", "var:haaland-idol"],
        },
    )
    resolved = resolve(snapshot, {"variantId": "var:haaland-idol"})
    assert (
        resolved.artifact_name == "Erling Haaland (Pixar卡通版)（haaland-idol）视觉图"
    )
    assert resolved.variant_id == "var:haaland-idol"
    assert (
        resolved.slot_id == "asset:char:haaland:variant:var:haaland-idol:image"
    )

    with pytest.raises(ValidationError, match="必须提供 variantId"):
        resolve(snapshot, {})


def test_generate_asset_rejects_entity_description_as_paid_prompt_fallback(
    tmp_path,
) -> None:
    snapshot = _snapshot(
        variants={
            "items": {
                "var:empty": {
                    "variant_id": "var:empty",
                    "prompt": "",
                },
            },
            "order": ["var:empty"],
        },
    )

    with pytest.raises(ValidationError, match="不能作为付费生成兜底"):
        _resolve_request(
            snapshot=snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments={"variantId": "var:empty"},
        )


def _with_remote_variant_refs(
    snapshot: ProjectSnapshot,
    variant_id: str,
    count: int,
) -> ProjectSnapshot:
    candidate = snapshot.project.model_dump(mode="json")
    references = [f"ref-{index}" for index in range(1, count + 1)]
    candidate["visual"]["entities"]["items"]["char:haaland"]["variants"][
        "items"
    ][variant_id]["reference_asset_version_ids"] = references
    created_at = datetime.now(timezone.utc).isoformat()
    for version_id in references:
        url = f"https://images.example/{version_id}.png"
        candidate["assets"]["source_versions_by_id"][version_id] = {
            "version_id": version_id,
            "logical_asset_id": f"asset-{version_id}",
            "name": version_id,
            "checksum": hashlib.sha256(url.encode()).hexdigest(),
            "media_kind": "image",
            "media_type": "image/png",
            "created_at": created_at,
            "metadata": {
                "sourceKind": "remote_url",
                "checksumKind": "source_url_sha256",
                "publicSourceUrl": url,
            },
        }
    return ProjectSnapshot(
        project=Project.model_validate(candidate),
        etag="etag-budget",
        generation=1,
    )


@pytest.mark.parametrize(
    ("model_name", "limit"),
    [
        ("qwen-image-3.0", 3),
        ("wan2.7-image-pro", 9),
        ("wan2.7-image", 9),
        ("wan2.6-image", 4),
        ("z-image-turbo", 0),
    ],
)
def test_resolved_reference_budget_reports_automatic_and_explicit_refs(
    tmp_path,
    monkeypatch,
    model_name,
    limit,
) -> None:
    snapshot = _snapshot(
        variants={
            "items": {
                "var:budget": {
                    "variant_id": "var:budget",
                    "prompt": "budget test",
                },
            },
            "order": ["var:budget"],
        },
    )
    budget_snapshot = _with_remote_variant_refs(snapshot, "var:budget", limit)
    monkeypatch.setattr(
        image_execution,
        "_validate_public_remote_url",
        lambda value: value,
    )

    def resolve(model_name, arguments):
        return _resolve_request(
            snapshot=budget_snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments=arguments,
            image_model_name=model_name,
        )

    request = resolve(model_name, {"variantId": "var:budget"})
    assert len(request.reference_image_urls) == limit

    with pytest.raises(ImageReferenceBudgetError) as captured:
        resolve(
            model_name,
            {
                "variantId": "var:budget",
                "referenceImageUrls": ["https://images.example/explicit.png"],
            },
        )

    error = captured.value
    assert error.code == "IMAGE_REFERENCE_BUDGET_EXCEEDED"
    assert error.details["limit"] == limit
    assert error.details["resolvedCount"] == limit + 1
    assert error.details["automaticReferenceVersionIds"] == [
        f"ref-{index}" for index in range(1, limit + 1)
    ]
    assert error.details["explicitReferenceUrls"] == [
        "https://images.example/explicit.png",
    ]
    assert error.details["documentationUrl"].startswith("https://")

    openai_request = resolve("gpt-image-2", {"variantId": "var:budget"})
    assert len(openai_request.reference_image_urls) == limit

    unknown_arguments = {
        "variantId": "var:budget",
        "referenceImageUrls": ["https://images.example/explicit.png"],
    }
    with pytest.raises(ImageModelCapabilityError):
        resolve("private-gateway-alias", unknown_arguments)

    with pytest.raises(ImageModelCapabilityError) as empty_model:
        resolve("", unknown_arguments)
    assert empty_model.value.details["modelName"] == "未配置"


def test_output_moderation_refusal_is_treated_as_deterministic() -> None:
    """Field run 2026-08-26: DashScope refused a rendered character sheet with
    its own wording, which matched none of the request-level markers. The
    refusal was therefore retried against provider quota and the node stalled
    with six dependents gated behind it.
    """
    from services.media_files.image_execution import (
        _is_safety_rejection_message,
    )

    green_net = (
        "Image generation failed with status 400: Green net check failed "
        "for image (output): Output data may contain inappropriate content"
    )
    assert _is_safety_rejection_message(green_net)
    # The request-level variants must keep working.
    assert _is_safety_rejection_message(
        "Image generation failed with status 400: Your request was rejected "
        "by the safety system",
    )
    # A genuinely transient fault must not be misread as a content refusal.
    assert not _is_safety_rejection_message(
        "Image generation failed: rate limited after all retries",
    )


def test_content_refusal_error_carries_advice_not_a_config_hint() -> None:
    """A scheduler-dispatched failure never reaches the agent's tool-result
    recovery path, so the provider message itself is all the agent sees on a
    failed work-graph node. Field run 2026-08-26: it ended in "Check
    creator_image_model configuration", which points at the wrong cause and
    left twelve nodes gated behind an unfixed prompt.
    """
    from models.image.base import (
        CONTENT_REFUSAL_ADVICE,
        is_content_refusal,
    )

    green_net = (
        "Green net check failed for image (output): Output data may contain "
        "inappropriate content"
    )
    assert is_content_refusal(green_net)
    assert is_content_refusal("Your request was rejected by the safety system")
    assert not is_content_refusal("upstream timed out")
    assert not is_content_refusal("")
    # The advice has to name the remedy, not the configuration.
    assert "deterministic" in CONTENT_REFUSAL_ADVICE
    assert "Rewrite the prompt" in CONTENT_REFUSAL_ADVICE
    assert "configuration" in CONTENT_REFUSAL_ADVICE  # says it is *not* one


def test_over_budget_automatic_chain_truncates_instead_of_stalling(
    tmp_path,
    monkeypatch,
) -> None:
    """Field runs 2026-08-26: seven Elements across two projects resolved more
    automatic references than the model accepts. Every dispatch failed the
    budget check identically, so those storyboards never rendered and the
    finished timelines kept holes. Nobody wrote those lists, so keeping the
    highest-priority references beats stalling the node forever.
    """
    snapshot = _snapshot(
        variants={
            "items": {
                "var:budget": {
                    "variant_id": "var:budget",
                    "prompt": "budget test",
                },
            },
            "order": ["var:budget"],
        },
    )
    # Five automatic references against a three-reference model.
    budget_snapshot = _with_remote_variant_refs(snapshot, "var:budget", 5)
    monkeypatch.setattr(
        image_execution,
        "_validate_public_remote_url",
        lambda value: value,
    )

    resolved = _resolve_request(
        snapshot=budget_snapshot,
        project_root=Path(tmp_path),
        command=CreatorCommandType.GENERATE_ASSET,
        target_ref="asset:char:haaland",
        arguments={"variantId": "var:budget"},
        image_model_name="qwen-image-3.0",
        max_reference_images=3,
    )
    assert len(resolved.reference_version_ids) == 3
    # Priority order is preserved: the dropped tail is the least
    # identity-critical, never an arbitrary subset.
    assert list(resolved.reference_version_ids) == ["ref-1", "ref-2", "ref-3"]

    # An explicit list stays a hard error: the author named those images.
    with pytest.raises(ImageReferenceBudgetError):
        _resolve_request(
            snapshot=budget_snapshot,
            project_root=Path(tmp_path),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref="asset:char:haaland",
            arguments={
                "variantId": "var:budget",
                "referenceImageUrls": ["https://images.example/explicit.png"],
            },
            image_model_name="qwen-image-3.0",
            max_reference_images=3,
        )


def test_image_reference_marker_spec_follows_provider_docs() -> None:
    """Verified image guides drive wording, never video dialect guesses."""
    from models.image.base import image_reference_marker_spec

    for model in (
        "qwen-image-3.0-pro",
        "qwen-image-2.0-pro",
        "qwen-image-edit-plus",
    ):
        spec = image_reference_marker_spec(model)
        assert spec is not None, model
        assert spec.render_index(2) == "图2"
        assert "qwen-image-edit-guide" in spec.documentation_url

    for model in ("wan2.7-image-pro", "wan2.7-image", "wan2.6-image"):
        spec = image_reference_marker_spec(model)
        assert spec is not None
        assert spec.render_index(2) == "图2"
        assert "wan-image-generation" in spec.documentation_url

    # gpt-image takes many references but documents array order only, so
    # inventing a marker would be text it has no contract for.
    assert image_reference_marker_spec("gpt-image-2") is None
    assert image_reference_marker_spec("gpt-image-1") is None
    # Nothing to disambiguate at zero or one reference.
    assert image_reference_marker_spec("z-image-turbo") is None
    assert image_reference_marker_spec("qwen-image") is None
    assert image_reference_marker_spec("qwen-mt-image") is None
    assert (
        image_reference_marker_spec("gemini-3-pro-image").render_index(2)
        == "image 2"
    )
    assert image_reference_marker_spec("unknown-alias") is None


def test_multi_reference_image_prompt_is_labelled_and_rendered() -> None:
    """Field gap: image prompts named none of their references, so the model
    had to infer each input's job from its pixels.
    """
    from services.media_files.image_execution import (
        _IMAGE_REFERENCE_ROLE_MARKER,
        _labelled_reference_prompt,
    )
    from services.project_files.models import ArtifactVersion

    project = Project.new(project_id="p-img", name="Img")
    for vid, name in (("art:a", "分镜图"), ("art:b", "角色视觉图")):
        project.assets.artifact_versions_by_id[vid] = ArtifactVersion(
            version_id=vid,
            slot_id=f"visual:{vid}",
            kind="visual_asset_image",
            owner_ref=f"visual:{vid}",
            name=name,
            file_id=f"file-{vid}",
            checksum="0" * 64,
            based_on_generation=1,
            created_at="2026-08-27T00:00:00Z",
        )
    ids = ["art:a", "art:b"]

    qwen = _labelled_reference_prompt(
        "画面参考 [Image 2] 的人物。",
        project,
        ids,
        image_model_name="qwen-image-3.0-pro",
        has_explicit_urls=False,
    )
    assert _IMAGE_REFERENCE_ROLE_MARKER in qwen
    assert "图1 = 分镜图" in qwen and "图2 = 角色视觉图" in qwen
    # The author's inline canonical marker is rendered by the same pass.
    assert "参考 图2 的人物" in qwen
    assert "[Image" not in qwen

    # No documented addressing: ordinal prose, never a literal [Image N].
    openai = _labelled_reference_prompt(
        "画面参考 [Image 2] 的人物。",
        project,
        ids,
        image_model_name="gpt-image-2",
        has_explicit_urls=False,
    )
    assert "第1张参考图 = 分镜图" in openai
    assert "[Image" not in openai

    # A raw URL is not version-backed, so labelling part of the payload would
    # misnumber the rest.
    assert _IMAGE_REFERENCE_ROLE_MARKER not in _labelled_reference_prompt(
        "prompt",
        project,
        ids,
        image_model_name="qwen-image-3.0-pro",
        has_explicit_urls=True,
    )
    # Nothing to disambiguate with one reference.
    assert _IMAGE_REFERENCE_ROLE_MARKER not in _labelled_reference_prompt(
        "prompt",
        project,
        ["art:a"],
        image_model_name="qwen-image-3.0-pro",
        has_explicit_urls=False,
    )


@pytest.mark.parametrize("mode", ["required", "auto_approve"])
def test_media_review_mode_controls_storyboard_publication(
    tmp_path,
    monkeypatch,
    mode,
):
    services = _services(tmp_path, monkeypatch)
    if mode == "auto_approve":
        monkeypatch.setattr(
            "services.media_files.review_admission.get_media_review_mode",
            lambda: mode,
        )
    provider = _CountingProvider()
    result = _execute(services, provider)
    assert provider.calls == 1
    review = services.reviews.active(PROJECT_ID)
    if mode == "required":
        assert review is not None
        assert review.status is ReviewStatus.PENDING
    else:
        assert review is None
        slots = services.projects.read(
            PROJECT_ID,
        ).project.assets.artifact_slots_by_id
        assert any(
            slot.kind == "r2v_storyboard_image"
            and slot.selected_version_id == result.artifact_version_id
            for slot in slots.values()
        )


def test_style_anchor_resolves_to_base_selection_at_dispatch():
    """Dispatch reads the base variant's current image through the anchor;
    a regressed (unselected) base fails closed instead of rendering blind."""

    from services.project_files.models import (
        EntityCollection,
        VisualEntity,
        VisualVariant,
    )

    project = Project.new(project_id="p-anchor", name="Anchor")
    base = VisualVariant(
        variant_id="var:base",
        selected_artifact_version_id="art-base-1",
    )
    dependent = VisualVariant(
        variant_id="var:door",
        reference_artifact_version_ids=[
            "visual:scene:home:var:base",
            "art-plain-9",
        ],
    )
    project.visual.entities = EntityCollection(
        items={
            "scene:home": VisualEntity(
                entity_id="scene:home",
                kind="scene",
                name="家",
                required_variant_ids=["var:base"],
                variants=EntityCollection(
                    items={"var:base": base},
                    order=["var:base"],
                ),
            ),
            "scene:door": VisualEntity(
                entity_id="scene:door",
                kind="scene",
                name="家门口",
                required_variant_ids=["var:door"],
                variants=EntityCollection(
                    items={"var:door": dependent},
                    order=["var:door"],
                ),
            ),
        },
        order=["scene:home", "scene:door"],
    )

    # pylint: disable-next=protected-access
    assert image_execution._resolved_artifact_reference_ids(
        project,
        dependent,
    ) == ["art-base-1", "art-plain-9"]

    base.selected_artifact_version_id = None
    with pytest.raises(ValidationError, match="风格锚点"):
        # pylint: disable-next=protected-access
        image_execution._resolved_artifact_reference_ids(project, dependent)


@pytest.mark.parametrize("start_before_claim", [False, True])
def test_direct_asset_command_waits_for_anchor_before_provider_spend(
    tmp_path,
    monkeypatch,
    start_before_claim,
):
    from domain.enums import TaskStatus
    from services.runtime_files.errors import LockTimeoutError
    from .conftest import accept_pending_reviews

    services = _services(tmp_path, monkeypatch)
    source = _snapshot(
        variants={
            "items": {
                "var:base": {"variant_id": "var:base", "prompt": "角色基准图"},
                "var:door": {
                    "variant_id": "var:door",
                    "prompt": "角色在门口",
                    "reference_artifact_version_ids": [
                        "visual:char:haaland:var:base",
                    ],
                },
            },
            "order": ["var:base", "var:door"],
        },
    )
    snapshot = services.projects.read(PROJECT_ID)
    candidate = snapshot.project.model_dump(mode="json")
    candidate["visual"] = source.project.visual.model_dump(mode="json")
    services.commits.commit(
        base=snapshot,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
    )
    provider = _CountingProvider()
    worker = FileImageExecutionService(services, provider=provider)
    base_request = {
        "project_id": PROJECT_ID,
        "command": "GENERATE_ASSET",
        "target_ref": "asset:char:haaland",
        "arguments": {"variantId": "var:base"},
        "idempotency_key": "initial-anchor",
    }
    asyncio.run(worker.execute(**base_request))
    accept_pending_reviews(services, PROJECT_ID)
    assert provider.calls == 1
    stalled = FileImageExecutionService(services, provider=provider)

    async def dead_claim(_task):
        raise LockTimeoutError(tmp_path / "project.lock", 10)

    monkeypatch.setattr(stalled, "_claim_provider", dead_claim)

    async def start_anchor():
        with pytest.raises(LockTimeoutError):
            await stalled.execute(
                **{**base_request, "idempotency_key": "repaint-anchor"},
            )

    if start_before_claim:
        original_start = worker._start  # pylint: disable=protected-access

        async def start_with_anchor(*, run, task, resolved, ids):
            task = await original_start(
                run=run,
                task=task,
                resolved=resolved,
                ids=ids,
            )
            await start_anchor()
            return task

        monkeypatch.setattr(worker, "_start", start_with_anchor)
    else:
        asyncio.run(start_anchor())

    dependent_request = {
        **base_request,
        "arguments": {"variantId": "var:door"},
        "idempotency_key": "dependent-anchor",
    }
    with pytest.raises(ValidationError, match="风格锚点"):
        asyncio.run(worker.execute(**dependent_request))
    assert provider.calls == 1
    if start_before_claim:
        monkeypatch.setattr(worker, "_start", original_start)
    for task in worker.executions.list_tasks(PROJECT_ID):
        if task.metadata.get("variantId") == "var:door":
            assert task.status is TaskStatus.FAILED
            assert not image_execution.provider_claim_path(
                services.projects.project_root(PROJECT_ID),
                task.task_id,
            ).exists()
        elif task.status is TaskStatus.RUNNING:
            worker.executions.transition_task(
                PROJECT_ID,
                task.task_id,
                expected_status=TaskStatus.RUNNING,
                status=TaskStatus.CANCELLED,
            )
    # Cancelling the repaint settles the selected base; the same request
    # can now retry without duplicating any paid dependent generation.
    result = asyncio.run(worker.execute(**dependent_request))
    assert result.artifact_version_id
    assert provider.calls == 2
