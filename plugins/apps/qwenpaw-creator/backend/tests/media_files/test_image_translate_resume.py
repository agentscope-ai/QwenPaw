# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,unused-argument
"""Restart recovery resumes a billed image translate instead of losing it."""
from __future__ import annotations

import asyncio
import hashlib
import io
from datetime import UTC, datetime

import pytest
from PIL import Image

from domain.enums import CreatorCommandType, TaskStatus
from services.media_files import image_execution
from services.media_files.image_execution import FileImageExecutionService
from services.media_files.r2v_execution import recover_interrupted_image_tasks
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project

# pylint: disable=no-name-in-module
from utils.paths import media_task_scope, media_url_for, unique_task_work_path

# pylint: enable=no-name-in-module

pytestmark = pytest.mark.unit

_TRANSLATED_PNG = b"\x89PNG\r\n\x1a\n" + b"translated-poster" * 32

PROJECT_ID = "translate-resume-project"
ENTITY_ID = "poster-entity"
SOURCE_VERSION_ID = "asset-version-poster"
PROVIDER_TASK_ID = "provider-translate-1"

_SUCCEEDED = {
    "status": "SUCCEEDED",
    "image_url": "https://oss.test/translated.png",
}


@pytest.fixture(autouse=True)
def _clear_image_registry():
    """The per-root registry owns supervisor jobs; isolate every test."""

    image_execution._image_registry.clear()
    yield
    image_execution._image_registry.clear()


def _poster_png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (640, 480), color="white").save(output, format="PNG")
    return output.getvalue()


class _UncalledProvider:
    """Fails the test if a resumed task submits to the provider again."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        raise AssertionError("a resumed task must never resubmit")


async def _fake_download(url: str, model_name: str) -> str:
    path = unique_task_work_path("images", ".png", prefix="resumed-")
    path.write_bytes(_TRANSLATED_PNG)
    return media_url_for(path)


def _patch_poll(monkeypatch, poll, download=_fake_download) -> None:
    monkeypatch.setattr("models.image.poll_image_translate_task", poll)
    monkeypatch.setattr("models.image.base.download_remote_image", download)


def _services(tmp_path, monkeypatch) -> CreatorFileServices:
    """Project with one character entity and one real poster image version."""

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="Translate Resume")
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )
    poster = _poster_png()
    checksum = hashlib.sha256(poster).hexdigest()
    relative = "assets/sources/poster-source.png"
    target = services.projects.project_root(PROJECT_ID) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(poster)
    created = datetime.now(UTC).isoformat()

    snapshot = services.projects.read(PROJECT_ID)
    candidate = snapshot.project.model_dump(mode="json")
    candidate["visual"]["entities"]["items"][ENTITY_ID] = {
        "entity_id": ENTITY_ID,
        "kind": "character",
        "name": "海报",
        "description": "含中文标题的海报",
        "continuity": "",
        "required_variant_ids": [],
        "variants": {"items": {}, "order": []},
        "voice": None,
    }
    candidate["visual"]["entities"]["order"] = [ENTITY_ID]
    candidate["assets"]["files_by_id"]["file-poster"] = {
        "file_id": "file-poster",
        "kind": "source_original",
        "relative_uri": relative,
        "sha256": checksum,
        "size_bytes": len(poster),
        "media_type": "image/png",
        "created_at": created,
    }
    candidate["assets"]["source_versions_by_id"][SOURCE_VERSION_ID] = {
        "version_id": SOURCE_VERSION_ID,
        "logical_asset_id": "asset-poster",
        "name": "poster",
        "file_id": "file-poster",
        "checksum": checksum,
        "media_kind": "image",
        "media_type": "image/png",
        "created_at": created,
    }
    from services.runtime_files.models import ChangeOrigin, ReviewPolicy

    services.commits.commit(
        base=snapshot,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
    )
    return services


_ARGUMENTS = {
    "prompt": "翻译海报文字",
    "mode": "translate",
    "referenceImageRefs": [SOURCE_VERSION_ID],
    "sourceLang": "zh",
    "targetLang": "en",
}


async def _leave_interrupted_translate_task(
    worker: FileImageExecutionService,
    services: CreatorFileServices,
    *,
    idempotency_key: str,
) -> str:
    """Reproduce the durable state a crash leaves mid-translate."""

    from models.provider_tasks import note_provider_task

    base = await asyncio.to_thread(services.projects.read, PROJECT_ID)
    resolved = image_execution._resolve_request(
        snapshot=base,
        project_root=services.projects.project_root(PROJECT_ID),
        command=CreatorCommandType.GENERATE_ASSET,
        target_ref=f"asset:{ENTITY_ID}",
        arguments=dict(_ARGUMENTS),
    )
    ids = worker._ids(PROJECT_ID, idempotency_key)
    run, task = await worker._admit(
        base=base,
        resolved=resolved,
        request_fingerprint=f"sha256:{'a' * 64}",
        command_request_hash=f"sha256:{'b' * 64}",
        idempotency_key=idempotency_key,
        ids=ids,
    )
    task = await worker._start(run=run, task=task, resolved=resolved, ids=ids)
    assert await worker._claim_provider(task)
    # Billed provider task recorded; the process died before the first poll.
    with media_task_scope(task.task_id, project_id=PROJECT_ID):
        note_provider_task(
            provider_task_id=PROVIDER_TASK_ID,
            model="qwen-mt-image",
            kind="image_translate",
        )
    return task.task_id


def _interrupted(worker, services, key: str) -> str:
    return asyncio.run(
        _leave_interrupted_translate_task(
            worker,
            services,
            idempotency_key=key,
        ),
    )


def test_recovery_resumes_and_publishes_a_billed_translate(
    tmp_path,
    monkeypatch,
) -> None:
    services = _services(tmp_path, monkeypatch)
    provider = _UncalledProvider()
    worker = FileImageExecutionService(services, provider=provider)
    task_id = _interrupted(worker, services, "translate-1")
    interrupted = worker.executions.get_task(PROJECT_ID, task_id)
    assert interrupted.status is TaskStatus.RUNNING

    polls: list[str] = []

    async def fake_poll(provider_task_id: str) -> dict:
        polls.append(provider_task_id)
        return dict(_SUCCEEDED)

    _patch_poll(monkeypatch, fake_poll)

    async def recover_and_drain() -> int:
        count = await recover_interrupted_image_tasks(services)
        await image_execution.file_image_execution_service(
            services,
        ).drain_resume_jobs()
        return count

    recovered = asyncio.run(recover_and_drain())

    assert recovered == 1
    # The same paid task was resumed, and nothing was resubmitted.
    assert polls == [PROVIDER_TASK_ID]
    assert provider.calls == 0
    task = worker.executions.get_task(PROJECT_ID, task_id)
    assert task.status is TaskStatus.SUCCEEDED
    published = services.projects.read(PROJECT_ID).project
    versions = [
        version
        for version in published.assets.artifact_versions_by_id.values()
        if version.slot_id == f"asset:{ENTITY_ID}:image"
    ]
    assert versions, "the paid translation must be published as an artifact"
    indexed = published.assets.files_by_id[versions[0].file_id]
    stored = (
        services.projects.project_root(PROJECT_ID) / indexed.relative_uri
    ).read_bytes()
    assert stored == _TRANSLATED_PNG


class _BudgetExpiredProvider:
    """Accepts (bills) the async task, then exhausts the local poll budget."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        from models.provider_tasks import note_provider_task

        note_provider_task(
            provider_task_id=PROVIDER_TASK_ID,
            model="qwen-mt-image",
            kind="image_translate",
        )
        # pylint: disable=no-name-in-module
        from domain.errors import ModelError

        raise ModelError(
            "Image translate did not finish within 60s "
            f"(task_id={PROVIDER_TASK_ID}); the task is billed",
            model_name="qwen-mt-image",
        )


def test_poll_timeout_keeps_the_billed_task_supervised(
    tmp_path,
    monkeypatch,
) -> None:
    """A local budget timeout must not terminalize a paid provider task:
    the provider already returned a task id, so failing the Creator Task
    here would strand the paid result forever."""

    services = _services(tmp_path, monkeypatch)
    provider = _BudgetExpiredProvider()
    worker = FileImageExecutionService(
        services,
        provider=provider,
        resume_poll_interval_seconds=0.0,
        resume_poll_budget_seconds=0.0,
        resume_retry_interval_seconds=0.0,
    )

    polls: list[str] = []

    async def fake_poll(provider_task_id: str) -> dict:
        polls.append(provider_task_id)
        # Still running on the first pass, then finished.
        if len(polls) < 2:
            return {"status": "RUNNING"}
        return dict(_SUCCEEDED)

    _patch_poll(monkeypatch, fake_poll)

    async def scenario() -> None:
        from domain.errors import ConflictError

        with pytest.raises(ConflictError, match="后台轮询已接管"):
            await worker.execute(
                project_id=PROJECT_ID,
                command="GENERATE_ASSET",
                target_ref=f"asset:{ENTITY_ID}",
                arguments={
                    "prompt": "翻译海报文字",
                    "mode": "translate",
                    "referenceImageRefs": [SOURCE_VERSION_ID],
                },
                idempotency_key="translate-timeout",
            )
        # The Task is not FAILED; a supervisor owns it.
        pending = worker.executions.get_task(
            PROJECT_ID,
            worker._ids(PROJECT_ID, "translate-timeout")["task_id"],
        )
        assert pending.status is TaskStatus.RUNNING
        await worker.drain_resume_jobs()

    asyncio.run(scenario())

    task = worker.executions.get_task(
        PROJECT_ID,
        worker._ids(PROJECT_ID, "translate-timeout")["task_id"],
    )
    assert task.status is TaskStatus.SUCCEEDED
    # Re-polled after the first pending pass, and never resubmitted.
    assert len(polls) >= 2
    assert provider.calls == 1


def test_transient_failures_never_terminalize_before_the_horizon(
    tmp_path,
    monkeypatch,
) -> None:
    """5 retryable failures then success must still publish."""

    services = _services(tmp_path, monkeypatch)
    worker = FileImageExecutionService(
        services,
        provider=_UncalledProvider(),
        resume_poll_interval_seconds=0.0,
        resume_poll_budget_seconds=0.0,
        resume_retry_interval_seconds=0.0,
        resume_horizon_seconds=3600.0,
    )
    task_id = _interrupted(worker, services, "translate-many-failures")
    attempts = {"count": 0}

    async def flaky_poll(provider_task_id: str) -> dict:
        attempts["count"] += 1
        if attempts["count"] <= 5:
            raise TimeoutError("transient network failure")
        return dict(_SUCCEEDED)

    _patch_poll(monkeypatch, flaky_poll)

    async def scenario() -> None:
        worker.schedule_resume(worker.executions.get_task(PROJECT_ID, task_id))
        await worker.drain_resume_jobs()

    asyncio.run(scenario())

    assert attempts["count"] == 6
    task = worker.executions.get_task(PROJECT_ID, task_id)
    assert task.status is TaskStatus.SUCCEEDED
    assert services.projects.read(
        PROJECT_ID,
    ).project.assets.artifact_versions_by_id


def test_cancelled_task_is_never_published_by_a_resume(
    tmp_path,
    monkeypatch,
) -> None:
    """Cancel before the resume job runs: no artifact, no orphan file."""

    services = _services(tmp_path, monkeypatch)
    worker = FileImageExecutionService(
        services,
        provider=_UncalledProvider(),
        resume_poll_interval_seconds=0.0,
        resume_poll_budget_seconds=0.0,
        resume_retry_interval_seconds=0.0,
    )
    task_id = _interrupted(worker, services, "translate-cancelled")
    downloads: list[str] = []

    async def succeeded(provider_task_id: str) -> dict:
        return dict(_SUCCEEDED)

    async def recording_download(url: str, model_name: str) -> str:
        downloads.append(url)
        return await _fake_download(url, model_name)

    _patch_poll(monkeypatch, succeeded, download=recording_download)

    async def scenario() -> str:
        # The user cancels while the resume job is still queued.
        worker.executions.transition_task(
            PROJECT_ID,
            task_id,
            expected_status=TaskStatus.RUNNING,
            status=TaskStatus.CANCELLED,
        )
        return await worker.resume_provider_task(
            worker.executions.get_task(PROJECT_ID, task_id),
            poll_interval_seconds=0.0,
            poll_budget_seconds=0.0,
        )

    outcome = asyncio.run(scenario())

    assert outcome == "cancelled"
    # Nothing was downloaded or published for a cancelled Task.
    assert not downloads
    task = worker.executions.get_task(PROJECT_ID, task_id)
    assert task.status is TaskStatus.CANCELLED
    published = services.projects.read(PROJECT_ID).project
    assert not published.assets.artifact_versions_by_id


def test_recovery_terminalizes_scheduler_dispatched_zombies(
    tmp_path,
    monkeypatch,
) -> None:
    """Field run 2026-08-12 (project 27dc): recover the record we iterated.

    A storyboard task admitted by the work-graph scheduler survived a
    restart as a RUNNING zombie: recovery recomputed the file-image stable
    id from the idempotency key, missed the record and left the work-graph
    lane pinned RUNNING forever.
    """

    services = _services(tmp_path, monkeypatch)
    worker = FileImageExecutionService(services, provider=_UncalledProvider())

    async def leave_zombie() -> str:
        base = await asyncio.to_thread(services.projects.read, PROJECT_ID)
        resolved = image_execution._resolve_request(
            snapshot=base,
            project_root=services.projects.project_root(PROJECT_ID),
            command=CreatorCommandType.GENERATE_ASSET,
            target_ref=f"asset:{ENTITY_ID}",
            arguments=dict(_ARGUMENTS),
        )
        # The scheduler admits under its own id scheme: the stored
        # idempotency key cannot reproduce the record's task id.
        ids = worker._ids(PROJECT_ID, "scheduler-slot-1")
        run, task = await worker._admit(
            base=base,
            resolved=resolved,
            request_fingerprint=f"sha256:{'a' * 64}",
            command_request_hash=f"sha256:{'b' * 64}",
            idempotency_key="dag-storyboard:elem:scene3-deadbeef",
            ids=ids,
        )
        task = await worker._start(
            run=run,
            task=task,
            resolved=resolved,
            ids=ids,
        )
        assert await worker._claim_provider(task)
        # One-shot generation: no billed provider-task ledger exists.
        return task.task_id

    task_id = asyncio.run(leave_zombie())

    recovered = asyncio.run(recover_interrupted_image_tasks(services))

    assert recovered == 1
    task = worker.executions.get_task(PROJECT_ID, task_id)
    assert task.status is TaskStatus.FAILED
    assert "IMAGE_PROCESS_RESTARTED" in str(task.error)
