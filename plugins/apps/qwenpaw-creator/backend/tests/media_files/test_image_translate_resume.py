# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Restart recovery resumes a billed image translate instead of losing it.

A crashed process leaves a RUNNING image Task with a claimed provider call
and no result. The qwen-mt-image task behind it is already billed and its
id is durable, so recovery must resume polling, download the result and
publish it — never discard it and never resubmit.
"""
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


async def _leave_interrupted_translate_task(
    worker: FileImageExecutionService,
    services: CreatorFileServices,
    *,
    idempotency_key: str,
    ledger_kind: str = "image_translate",
) -> str:
    """Reproduce the durable state a crash leaves mid-translate."""

    from models.provider_tasks import note_provider_task

    base = await asyncio.to_thread(services.projects.read, PROJECT_ID)
    arguments = {
        "prompt": "翻译海报文字",
        "mode": "translate",
        "referenceImageRefs": [SOURCE_VERSION_ID],
        "sourceLang": "zh",
        "targetLang": "en",
    }
    resolved = image_execution._resolve_request(
        snapshot=base,
        project_root=services.projects.project_root(PROJECT_ID),
        command=CreatorCommandType.GENERATE_ASSET,
        target_ref=f"asset:{ENTITY_ID}",
        arguments=arguments,
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
    # The provider accepted (and billed) the async translation, recorded it,
    # and the process died before the first poll returned.
    with media_task_scope(task.task_id, project_id=PROJECT_ID):
        note_provider_task(
            provider_task_id=PROVIDER_TASK_ID,
            model="qwen-mt-image",
            kind=ledger_kind,
        )
    return task.task_id


def test_recovery_resumes_and_publishes_a_billed_translate(
    tmp_path,
    monkeypatch,
) -> None:
    services = _services(tmp_path, monkeypatch)
    provider = _UncalledProvider()
    worker = FileImageExecutionService(services, provider=provider)
    task_id = asyncio.run(
        _leave_interrupted_translate_task(
            worker,
            services,
            idempotency_key="translate-1",
        ),
    )
    interrupted = worker.executions.get_task(PROJECT_ID, task_id)
    assert interrupted.status is TaskStatus.RUNNING
    assert interrupted.result is None
    # Publish inputs are frozen on the Task, so recovery needs no re-resolve.
    assert isinstance(interrupted.metadata.get("requestSnapshot"), dict)

    polls: list[str] = []

    async def fake_poll(provider_task_id: str) -> dict:
        polls.append(provider_task_id)
        return {
            "status": "SUCCEEDED",
            "image_url": "https://oss.test/translated.png",
        }

    async def fake_download(url: str, model_name: str) -> str:
        assert url == "https://oss.test/translated.png"
        path = unique_task_work_path("images", ".png", prefix="resumed-")
        path.write_bytes(_TRANSLATED_PNG)
        return media_url_for(path)

    monkeypatch.setattr("models.image.poll_image_translate_task", fake_poll)
    monkeypatch.setattr(
        "models.image.base.download_remote_image",
        fake_download,
    )

    async def recover_and_drain() -> int:
        count = await recover_interrupted_image_tasks(services)
        # Startup only mounts the supervisor, so await it here.
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


def test_recovery_keeps_a_still_running_translate_resumable(
    tmp_path,
    monkeypatch,
) -> None:
    """A task still running upstream stays active for the next pass."""

    services = _services(tmp_path, monkeypatch)
    worker = FileImageExecutionService(services, provider=_UncalledProvider())
    task_id = asyncio.run(
        _leave_interrupted_translate_task(
            worker,
            services,
            idempotency_key="translate-2",
        ),
    )

    async def still_running(provider_task_id: str) -> dict:
        return {"status": "RUNNING"}

    monkeypatch.setattr(
        "models.image.poll_image_translate_task",
        still_running,
    )

    async def recover_and_check() -> None:
        registered = image_execution.file_image_execution_service(services)
        registered.resume_poll_interval_seconds = 0.0
        registered.resume_poll_budget_seconds = 0.0
        # One retry pass, then stop supervising for this test.
        registered.resume_retry_interval_seconds = 0.01
        registered.resume_horizon_seconds = 0.0
        await recover_interrupted_image_tasks(services)
        await registered.drain_resume_jobs()

    asyncio.run(recover_and_check())

    task = worker.executions.get_task(PROJECT_ID, task_id)
    # Never published or lost: the paid task ends up back under supervision
    # (here the shortened horizon terminalizes it with a resumable reason).
    assert task.status in {TaskStatus.RUNNING, TaskStatus.FAILED}
    if task.status is TaskStatus.FAILED:
        assert "did not finish" in str(task.error)


def test_recovery_fails_a_translate_the_provider_rejected(
    tmp_path,
    monkeypatch,
) -> None:
    """A provider-side failure terminalizes with the provider's reason."""

    services = _services(tmp_path, monkeypatch)
    worker = FileImageExecutionService(services, provider=_UncalledProvider())
    task_id = asyncio.run(
        _leave_interrupted_translate_task(
            worker,
            services,
            idempotency_key="translate-3",
        ),
    )

    async def failed(provider_task_id: str) -> dict:
        return {"status": "FAILED", "error": "unsupported language pair"}

    monkeypatch.setattr("models.image.poll_image_translate_task", failed)

    async def recover_and_drain() -> None:
        await recover_interrupted_image_tasks(services)
        await image_execution.file_image_execution_service(
            services,
        ).drain_resume_jobs()

    asyncio.run(recover_and_drain())

    task = worker.executions.get_task(PROJECT_ID, task_id)
    assert task.status is TaskStatus.FAILED
    assert "unsupported language pair" in str(task.error)


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

        # pylint: enable=no-name-in-module
        raise ModelError(
            "Image translate did not finish within 60s "
            f"(task_id={PROVIDER_TASK_ID}); the task is billed",
            model_name="qwen-mt-image",
        )


def test_poll_timeout_keeps_the_billed_task_supervised(
    tmp_path,
    monkeypatch,
) -> None:
    """A local budget timeout must not terminalize a paid provider task.

    The review's case: the provider already returned a task id, so failing
    the Creator Task here would strand the paid result forever because
    recovery only scans QUEUED/RUNNING.
    """

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
        # Still running on the first pass, then finished: the supervisor
        # must come back on its own, without another process restart.
        if len(polls) < 2:
            return {"status": "RUNNING"}
        return {
            "status": "SUCCEEDED",
            "image_url": "https://oss.test/translated.png",
        }

    async def fake_download(url: str, model_name: str) -> str:
        path = unique_task_work_path("images", ".png", prefix="resumed-")
        path.write_bytes(_TRANSLATED_PNG)
        return media_url_for(path)

    monkeypatch.setattr("models.image.poll_image_translate_task", fake_poll)
    monkeypatch.setattr(
        "models.image.base.download_remote_image",
        fake_download,
    )

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
    published = services.projects.read(PROJECT_ID).project
    assert published.assets.artifact_versions_by_id


def test_supervisor_survives_transient_resume_errors(
    tmp_path,
    monkeypatch,
) -> None:
    """A dropped poll or download must not terminalize a paid task."""

    services = _services(tmp_path, monkeypatch)
    worker = FileImageExecutionService(
        services,
        provider=_UncalledProvider(),
        resume_poll_interval_seconds=0.0,
        resume_poll_budget_seconds=0.0,
        resume_retry_interval_seconds=0.0,
    )
    task_id = asyncio.run(
        _leave_interrupted_translate_task(
            worker,
            services,
            idempotency_key="translate-transient",
        ),
    )
    attempts = {"count": 0}

    async def flaky_poll(provider_task_id: str) -> dict:
        attempts["count"] += 1
        if attempts["count"] <= 2:
            raise TimeoutError("connection reset while polling")
        return {
            "status": "SUCCEEDED",
            "image_url": "https://oss.test/translated.png",
        }

    async def fake_download(url: str, model_name: str) -> str:
        path = unique_task_work_path("images", ".png", prefix="resumed-")
        path.write_bytes(_TRANSLATED_PNG)
        return media_url_for(path)

    monkeypatch.setattr("models.image.poll_image_translate_task", flaky_poll)
    monkeypatch.setattr(
        "models.image.base.download_remote_image",
        fake_download,
    )

    async def scenario() -> None:
        task = worker.executions.get_task(PROJECT_ID, task_id)
        worker.schedule_resume(task)
        await worker.drain_resume_jobs()

    asyncio.run(scenario())

    task = worker.executions.get_task(PROJECT_ID, task_id)
    assert attempts["count"] == 3
    assert task.status is TaskStatus.SUCCEEDED


def test_startup_recovery_schedules_instead_of_blocking(
    tmp_path,
    monkeypatch,
) -> None:
    """Recovery mounts the supervisor and returns without polling inline."""

    services = _services(tmp_path, monkeypatch)
    registered = image_execution.file_image_execution_service(services)
    registered.resume_poll_interval_seconds = 0.0
    registered.resume_poll_budget_seconds = 0.0
    registered.resume_retry_interval_seconds = 0.0
    task_id = asyncio.run(
        _leave_interrupted_translate_task(
            registered,
            services,
            idempotency_key="translate-startup",
        ),
    )

    slow_polls: list[str] = []

    async def slow_poll(provider_task_id: str) -> dict:
        slow_polls.append(provider_task_id)
        await asyncio.sleep(0.05)
        return {
            "status": "SUCCEEDED",
            "image_url": "https://oss.test/translated.png",
        }

    async def fake_download(url: str, model_name: str) -> str:
        path = unique_task_work_path("images", ".png", prefix="resumed-")
        path.write_bytes(_TRANSLATED_PNG)
        return media_url_for(path)

    monkeypatch.setattr("models.image.poll_image_translate_task", slow_poll)
    monkeypatch.setattr(
        "models.image.base.download_remote_image",
        fake_download,
    )

    async def scenario() -> tuple[int, bool]:
        recovered = await recover_interrupted_image_tasks(services)
        # Startup did not wait for the provider.
        still_running = (
            registered.executions.get_task(PROJECT_ID, task_id).status
            is TaskStatus.RUNNING
        )
        await registered.drain_resume_jobs()
        return recovered, still_running

    recovered, still_running = asyncio.run(scenario())

    assert recovered == 1
    assert still_running is True
    assert slow_polls == [PROVIDER_TASK_ID]
    assert (
        registered.executions.get_task(PROJECT_ID, task_id).status
        is TaskStatus.SUCCEEDED
    )
    asyncio.run(image_execution.shutdown_file_image_execution_services())


def test_transient_failures_never_terminalize_before_the_horizon(
    tmp_path,
    monkeypatch,
) -> None:
    """The review's reproduction: 5 failures then success must still publish.

    A run of retryable errors may only drive backoff; terminal failure is
    reserved for an explicit provider verdict or the supervision horizon.
    """

    services = _services(tmp_path, monkeypatch)
    worker = FileImageExecutionService(
        services,
        provider=_UncalledProvider(),
        resume_poll_interval_seconds=0.0,
        resume_poll_budget_seconds=0.0,
        resume_retry_interval_seconds=0.0,
        resume_horizon_seconds=3600.0,
    )
    task_id = asyncio.run(
        _leave_interrupted_translate_task(
            worker,
            services,
            idempotency_key="translate-many-failures",
        ),
    )
    attempts = {"count": 0}

    async def flaky_poll(provider_task_id: str) -> dict:
        attempts["count"] += 1
        if attempts["count"] <= 5:
            raise TimeoutError("transient network failure")
        return {
            "status": "SUCCEEDED",
            "image_url": "https://oss.test/translated.png",
        }

    async def fake_download(url: str, model_name: str) -> str:
        path = unique_task_work_path("images", ".png", prefix="resumed-")
        path.write_bytes(_TRANSLATED_PNG)
        return media_url_for(path)

    monkeypatch.setattr("models.image.poll_image_translate_task", flaky_poll)
    monkeypatch.setattr(
        "models.image.base.download_remote_image",
        fake_download,
    )

    async def scenario() -> None:
        worker.schedule_resume(
            worker.executions.get_task(PROJECT_ID, task_id),
        )
        await worker.drain_resume_jobs()

    asyncio.run(scenario())

    assert attempts["count"] == 6
    task = worker.executions.get_task(PROJECT_ID, task_id)
    assert task.status is TaskStatus.SUCCEEDED
    assert services.projects.read(
        PROJECT_ID,
    ).project.assets.artifact_versions_by_id


def test_backoff_grows_and_is_capped() -> None:
    """Failures escalate the wait instead of terminalizing the task."""

    worker = object.__new__(FileImageExecutionService)
    worker.resume_retry_interval_seconds = 15.0
    assert worker._resume_backoff_seconds(0) == 15.0
    assert worker._resume_backoff_seconds(1) == 15.0
    assert worker._resume_backoff_seconds(2) == 30.0
    assert worker._resume_backoff_seconds(3) == 60.0
    assert worker._resume_backoff_seconds(50) == 300.0


def test_cancelled_task_is_never_published_by_a_resume(
    tmp_path,
    monkeypatch,
) -> None:
    """The review's reproduction: cancel before the job runs, expect no file.

    A cancelled Task must not gain an artifact, and no orphan file may be
    left behind in the asset store.
    """

    services = _services(tmp_path, monkeypatch)
    worker = FileImageExecutionService(
        services,
        provider=_UncalledProvider(),
        resume_poll_interval_seconds=0.0,
        resume_poll_budget_seconds=0.0,
        resume_retry_interval_seconds=0.0,
    )
    task_id = asyncio.run(
        _leave_interrupted_translate_task(
            worker,
            services,
            idempotency_key="translate-cancelled",
        ),
    )
    downloads: list[str] = []

    async def succeeded(provider_task_id: str) -> dict:
        return {
            "status": "SUCCEEDED",
            "image_url": "https://oss.test/translated.png",
        }

    async def fake_download(url: str, model_name: str) -> str:
        downloads.append(url)
        path = unique_task_work_path("images", ".png", prefix="resumed-")
        path.write_bytes(_TRANSLATED_PNG)
        return media_url_for(path)

    monkeypatch.setattr("models.image.poll_image_translate_task", succeeded)
    monkeypatch.setattr(
        "models.image.base.download_remote_image",
        fake_download,
    )

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
    artifacts = services.projects.project_root(PROJECT_ID) / "assets/artifacts"
    assert not list(artifacts.glob("*.png"))


def test_cancel_stops_the_image_supervisor(tmp_path, monkeypatch) -> None:
    """Cancelling a Task must stop its background poller."""

    services = _services(tmp_path, monkeypatch)
    worker = FileImageExecutionService(
        services,
        provider=_UncalledProvider(),
        resume_poll_interval_seconds=0.0,
        resume_poll_budget_seconds=0.0,
        resume_retry_interval_seconds=0.05,
    )
    task_id = asyncio.run(
        _leave_interrupted_translate_task(
            worker,
            services,
            idempotency_key="translate-cancel-stop",
        ),
    )

    async def forever_running(provider_task_id: str) -> dict:
        return {"status": "RUNNING"}

    monkeypatch.setattr(
        "models.image.poll_image_translate_task",
        forever_running,
    )

    async def scenario() -> bool:
        task = worker.executions.get_task(PROJECT_ID, task_id)
        worker.schedule_resume(task)
        await asyncio.sleep(0)
        cancelled = worker.executions.transition_task(
            PROJECT_ID,
            task_id,
            expected_status=TaskStatus.RUNNING,
            status=TaskStatus.CANCELLED,
        )
        worker.notify_terminal_task(cancelled)
        await asyncio.sleep(0.05)
        return not worker._resume_jobs

    assert asyncio.run(scenario()) is True


class _AsyncGenerationAcceptedProvider:
    """Accepts (bills) an async *generation* job, then times out locally."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        from models.provider_tasks import note_provider_task

        note_provider_task(
            provider_task_id=PROVIDER_TASK_ID,
            model="wan-image-async",
            kind="image_generation",
        )
        from utils.exceptions import ModelError

        raise ModelError(
            "Image generation did not finish within 60s "
            f"(task_id={PROVIDER_TASK_ID})",
            model_name="wan-image-async",
        )


def test_unresumable_generation_timeout_fails_closed_with_billed_id(
    tmp_path,
    monkeypatch,
) -> None:
    """An accepted kind without a resume implementation must terminalize.

    The supervisor only understands ``image_translate``; deferring an
    ``image_generation`` ledger entry would strand the paid Task in RUNNING
    forever. Fail closed instead, naming the billed id for retrieval.
    """

    services = _services(tmp_path, monkeypatch)
    provider = _AsyncGenerationAcceptedProvider()
    worker = FileImageExecutionService(services, provider=provider)

    async def scenario() -> None:
        from utils.exceptions import ModelError

        with pytest.raises(ModelError):
            await worker.execute(
                project_id=PROJECT_ID,
                command="GENERATE_ASSET",
                target_ref=f"asset:{ENTITY_ID}",
                arguments={
                    "prompt": "翻译海报文字",
                    "mode": "translate",
                    "referenceImageRefs": [SOURCE_VERSION_ID],
                },
                idempotency_key="generation-timeout",
            )

    asyncio.run(scenario())

    task = worker.executions.get_task(
        PROJECT_ID,
        worker._ids(PROJECT_ID, "generation-timeout")["task_id"],
    )
    # Terminal and actionable — not RUNNING behind a poller that would
    # immediately drop the job as "unsupported".
    assert task.status is TaskStatus.FAILED
    assert PROVIDER_TASK_ID in str(task.error)
    assert not worker._resume_jobs


def test_startup_recovery_terminalizes_an_unresumable_generation(
    tmp_path,
    monkeypatch,
) -> None:
    """Restart recovery must not park unresumable kinds in RUNNING."""

    services = _services(tmp_path, monkeypatch)
    provider = _UncalledProvider()
    worker = FileImageExecutionService(services, provider=provider)
    task_id = asyncio.run(
        _leave_interrupted_translate_task(
            worker,
            services,
            idempotency_key="generation-restart",
            ledger_kind="image_generation",
        ),
    )

    async def recover_and_drain() -> None:
        await recover_interrupted_image_tasks(services)
        await image_execution.file_image_execution_service(
            services,
        ).drain_resume_jobs()

    asyncio.run(recover_and_drain())

    task = worker.executions.get_task(PROJECT_ID, task_id)
    assert task.status is TaskStatus.FAILED
    # The billed id stays named for manual retrieval, and nothing was
    # resubmitted to the provider.
    assert PROVIDER_TASK_ID in str(task.error)
    assert provider.calls == 0
