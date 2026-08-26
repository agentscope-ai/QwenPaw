# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access
"""Transient R2V failures reopen a retry slot; deterministic ones stay walls."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from domain.errors import ConflictError
from services.media_files import r2v_execution
from services.media_files.image_execution import FileImageExecutionService
from services.media_files.r2v_execution import FileR2VExecutionService
from services.project_files.facade import CreatorFileServices
from services.runtime_files.execution_store import ProjectExecutionStore
from services.runtime_files.models import ChangeOrigin, ReviewPolicy
from utils.paths import unique_task_work_path

from .conftest import (
    accept_pending_reviews,
    make_r2v_element,
    r2v_project_services,
)

pytestmark = pytest.mark.unit

_PNG_RETRY = b"\x89PNG\r\n\x1a\n" + b"retry-storyboard" * 16
_VIDEO_PROMPT = "动画，猫从左向右追逐老鼠，动作连续"

PROJECT_ID = "r2v-resilience-project"
ELEMENT_ID = "r2v-1"


class _ImageProvider:
    async def generate(self, **_kwargs):
        return {"content": _PNG_RETRY, "media_type": "image/png"}


def _services(tmp_path, monkeypatch) -> CreatorFileServices:
    """Project with one r2v element and a committed storyboard image."""

    services = r2v_project_services(
        tmp_path,
        monkeypatch,
        project_id=PROJECT_ID,
        name="R2V Resilience",
        elements=(make_r2v_element(ELEMENT_ID, video_prompt=_VIDEO_PROMPT),),
    )
    asyncio.run(
        FileImageExecutionService(services, provider=_ImageProvider()).execute(
            project_id=PROJECT_ID,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key="storyboard-1",
        ),
    )
    accept_pending_reviews(services, PROJECT_ID)
    return services


def _dispatch(services, key="video-retry-key"):
    async def scenario():
        worker = FileR2VExecutionService(services)
        try:
            return await worker.dispatch(
                project_id=PROJECT_ID,
                target_ref=f"element:{ELEMENT_ID}",
                arguments={},
                idempotency_key=key,
                start=False,
            )
        finally:
            await worker.shutdown()

    return asyncio.run(scenario())


def _fail_task(services, task_id: str, message: str) -> None:
    ProjectExecutionStore(services.root).transition_task(
        PROJECT_ID,
        task_id,
        expected_status="QUEUED",
        status="FAILED",
        updates={
            "error": {
                "code": "R2V_SUPERVISOR_FAILED",
                "message": message,
                "retryable": False,
            },
        },
    )


def test_transient_failures_reopen_bounded_retry_slots(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)

    seen: set[str] = set()
    for _ in range(4):  # original slot + 3 retry slots
        result = _dispatch(services)
        # Each identical retry opens a fresh slot instead of replaying
        # the FAILED task.
        assert result.replayed is False
        assert result.task_id not in seen
        seen.add(result.task_id)
        _fail_task(services, result.task_id, "connection timeout")

    with pytest.raises(ConflictError, match="瞬态重试槽位已用尽"):
        _dispatch(services)


def test_deterministic_failure_keeps_the_terminal_wall(tmp_path, monkeypatch):
    services = _services(tmp_path, monkeypatch)

    first = _dispatch(services)
    _fail_task(
        services,
        first.task_id,
        "provider status=FAILED: input storyboard contains a real human face",
    )

    with pytest.raises(ConflictError) as caught:
        _dispatch(services)
    message = str(caught.value)
    assert "原失败原因" in message
    assert "real human face" in message
    assert "调整 arguments" in message


def _r2v_task_count(services) -> int:
    return len(
        [
            task
            for task in ProjectExecutionStore(services.root).list_tasks(
                PROJECT_ID,
            )
            if task.kind.value == "r2v_generation"
        ],
    )


def test_different_command_conflicts_while_target_is_in_flight(
    tmp_path,
    monkeypatch,
) -> None:
    """Different content for one in-flight Element fails closed; the old
    contract double-billed exactly this way on field run 2026-08-11."""

    services = _services(tmp_path, monkeypatch)

    async def scenario():
        worker = FileR2VExecutionService(services)
        first = await worker.dispatch(
            project_id=PROJECT_ID,
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key="video-plain",
            start=False,
        )
        try:
            with pytest.raises(ConflictError, match="不同内容的视频任务"):
                await worker.dispatch(
                    project_id=PROJECT_ID,
                    target_ref=f"element:{ELEMENT_ID}",
                    arguments={"prompt": "另一版：慢动作追逐"},
                    idempotency_key="video-slowmo",
                    start=False,
                )
        finally:
            await worker.shutdown()
        return first

    first = asyncio.run(scenario())

    assert first.replayed is False
    assert _r2v_task_count(services) == 1


def _mat_worker(tmp_path, monkeypatch) -> FileR2VExecutionService:
    services = r2v_project_services(
        tmp_path,
        monkeypatch,
        project_id=PROJECT_ID,
        name="Materialize Retry",
    )
    return FileR2VExecutionService(
        services,
        materialize_retry_delays=(0.0, 0.0, 0.0),
    )


def _run_materialize(worker, monkeypatch, stub, provider_result=None):
    monkeypatch.setattr(r2v_execution, "materialize_r2v_video", stub)

    async def live_claim(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        FileR2VExecutionService,
        "_require_live_materialize_claim",
        live_claim,
    )
    task = SimpleNamespace(project_id=PROJECT_ID, task_id="task-materialize")
    claim = SimpleNamespace(
        provider_result=provider_result or {"result_url": "https://x/v.mp4"},
    )

    async def scenario():
        try:
            return await worker._materialize_video_with_retry(task, claim)
        finally:
            await worker.shutdown()

    return asyncio.run(scenario())


def test_transient_download_failures_are_retried(tmp_path, monkeypatch):
    sentinel = object()
    calls = []

    async def stub(*_args, **_kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("All connection attempts failed")
        return sentinel

    result = _run_materialize(
        _mat_worker(tmp_path, monkeypatch),
        monkeypatch,
        stub,
    )
    assert result is sentinel
    assert len(calls) == 3


def test_veo_download_auth_is_resolved_only_for_materialization(
    tmp_path,
    monkeypatch,
) -> None:
    from models import config as model_config

    sentinel = object()
    captured: dict = {}
    durable = r2v_execution._durable_provider_result(
        {
            "status": "SUCCEEDED",
            "result_url": "https://video.example/v.mp4?key=old-secret&alt=media",
            "download_auth": "x-goog-api-key",
        },
    )
    monkeypatch.setattr(
        model_config,
        "get_video_api_key",
        lambda: "new-secret",
    )

    async def stub(output, **kwargs):
        captured.update(output=output, kwargs=kwargs)
        return sentinel

    result = _run_materialize(
        _mat_worker(tmp_path, monkeypatch),
        monkeypatch,
        stub,
        provider_result=durable,
    )

    assert result is sentinel
    assert durable["result_url"] == "https://video.example/v.mp4?alt=media"
    assert "old-secret" not in repr(durable)
    assert "new-secret" not in repr(captured["output"])
    assert captured["kwargs"]["request_headers"] == {
        "x-goog-api-key": "new-secret",
    }


_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"stale-video" * 64


class _MutatingR2VProvider:
    """Commits a Project change before polling: the mid-render race."""

    def __init__(self, services: CreatorFileServices, mutate) -> None:
        self._services = services
        self._mutate = mutate
        self.mutated = False

    async def submit(self, **_kwargs) -> str:
        return "provider-task-stale"

    async def poll(self, provider_task_id: str):
        if not self.mutated:
            self.mutated = True
            base = self._services.projects.read(PROJECT_ID)
            candidate = base.project.model_dump(mode="json")
            self._mutate(candidate)
            self._services.commits.commit(
                base=base,
                candidate=candidate,
                origin=ChangeOrigin.RUNTIME_TASK,
                review_policy=ReviewPolicy.AUTO_FIX,
            )
        path = unique_task_work_path("video", ".mp4", prefix="stale-test-")
        path.write_bytes(_MP4)
        return {
            "task_id": provider_task_id,
            "status": "SUCCEEDED",
            "result_url": path.resolve().as_uri(),
            "media_type": "video/mp4",
            "durationSeconds": 4,
        }


def _run_video(services: CreatorFileServices, provider):
    async def scenario():
        worker = FileR2VExecutionService(
            services,
            provider=provider,
            poll_interval_seconds=0.01,
            poll_lease_seconds=0.1,
        )
        dispatched = await worker.dispatch(
            project_id=PROJECT_ID,
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key="video-1",
        )
        task = await worker.wait_for_task(
            PROJECT_ID,
            dispatched.task_id,
            timeout_seconds=5,
        )
        await worker.shutdown()
        return task

    return asyncio.run(scenario())


def test_unrelated_commit_during_render_does_not_quarantine(
    tmp_path,
    monkeypatch,
) -> None:
    """Incident regression: approving a review mid-render must publish,
    not quarantine, a finished video whose render inputs are intact."""

    services = _services(tmp_path, monkeypatch)

    def bump_description(candidate: dict) -> None:
        candidate["description"] = "updated while the video was rendering"

    task = _run_video(
        services,
        _MutatingR2VProvider(services, bump_description),
    )

    assert task.status.value == "SUCCEEDED"
    finished = services.projects.read(PROJECT_ID).project
    element = finished.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ]
    assert element.outputs["main"].slot_id == f"element:{ELEMENT_ID}:main"


def test_changed_render_inputs_during_render_still_quarantine(
    tmp_path,
    monkeypatch,
) -> None:
    """Losing the storyboard selection mid-render keeps fail-closed."""

    services = _services(tmp_path, monkeypatch)

    def clear_storyboard_selection(candidate: dict) -> None:
        slot = candidate["assets"]["artifact_slots_by_id"][
            f"element:{ELEMENT_ID}:storyboard"
        ]
        slot["selected_version_id"] = None

    task = _run_video(
        services,
        _MutatingR2VProvider(services, clear_storyboard_selection),
    )

    assert task.status.value == "QUARANTINED"
    assert (task.error or {}).get("code") == "PROJECT_INPUT_SNAPSHOT_STALE"
