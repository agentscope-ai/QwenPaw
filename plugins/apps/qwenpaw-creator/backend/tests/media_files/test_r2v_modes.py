# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=unused-argument
"""r2v_generation mode plumbing through the durable execution service."""
from __future__ import annotations

import asyncio
import hashlib

import pytest

from domain.errors import ValidationError
from models import config as model_config
from services.media_files.image_execution import FileImageExecutionService
from services.media_files.r2v_execution import (
    FileR2VExecutionService,
    VideoModelCapabilityError,
    VideoReferenceBudgetError,
    _assert_r2v_reference_budget,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ElementLocation,
    I2VCreation,
    Project,
    S2VCreation,
    TimelineElement,
    TimelineSpan,
)

# pylint: disable=no-name-in-module
from utils.paths import unique_task_work_path

# pylint: enable=no-name-in-module

from .conftest import (
    accept_pending_reviews,
    make_r2v_element,
    r2v_project_services,
)


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"mode-storyboard" * 16
_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"mode-video" * 64

PROJECT_ID = "r2v-mode-project"
ELEMENT_ID = "r2v-mode-1"
# Second element carries the mode-specific creation type under test.
MODE_ELEMENT_ID = "video-mode-1"


class _ImageProvider:
    async def generate(self, **_kwargs):
        return {"content": _PNG, "media_type": "image/png"}


class _CapturingR2VProvider:
    """Succeeds immediately and records the submit kwargs it received."""

    def __init__(self) -> None:
        self.submits: list[dict] = []

    async def submit(self, **kwargs) -> str:
        self.submits.append(dict(kwargs))
        return f"provider-task-{len(self.submits)}"

    async def poll(self, provider_task_id: str):
        path = unique_task_work_path("video", ".mp4", prefix="mode-test-")
        path.write_bytes(_MP4)
        return {
            "task_id": provider_task_id,
            "status": "SUCCEEDED",
            "result_url": path.resolve().as_uri(),
            "media_type": "video/mp4",
            "durationSeconds": 4,
        }

    async def submit_s2v(self, **kwargs) -> str:
        self.submits.append({"s2v": True, **kwargs})
        return f"provider-s2v-{len(self.submits)}"

    async def poll_s2v(self, provider_task_id: str):
        return await self.poll(provider_task_id)


def _project_with_image_references(count: int) -> tuple[Project, list[str]]:
    project = Project.new(project_id="reference-budget", name="Budget")
    candidate = project.model_dump(mode="json")
    created_at = project.created_at.isoformat()
    version_ids = [f"reference-{index}" for index in range(count)]
    for version_id in version_ids:
        url = f"https://cdn.test/{version_id}.png"
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
    return Project.model_validate(candidate), version_ids


@pytest.mark.parametrize(
    ("model_name", "backend", "count", "limit"),
    [
        ("wan2.7-r2v", "wan", 6, 5),
        ("happyhorse-1.1-r2v", "wan", 10, 9),
        ("doubao-seedance-2.0-pro", "seedance2", 10, 9),
    ],
)
def test_execution_rejects_resolved_video_reference_budget(
    monkeypatch,
    model_name,
    backend,
    count,
    limit,
) -> None:
    project, version_ids = _project_with_image_references(count)
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: model_name,
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: backend)

    with pytest.raises(VideoReferenceBudgetError) as captured:
        _assert_r2v_reference_budget(project, version_ids)

    error = captured.value
    assert error.code == "VIDEO_REFERENCE_BUDGET_EXCEEDED"
    assert error.details["imageCount"] == count
    assert error.details["maxReferenceImages"] == limit
    assert error.details["documentationUrl"].startswith("https://")


@pytest.mark.parametrize("model_name", ["", "private-video-gateway"])
def test_execution_fails_closed_for_unknown_video_model(
    monkeypatch,
    model_name,
) -> None:
    project, version_ids = _project_with_image_references(1)
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: model_name,
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")

    with pytest.raises(VideoModelCapabilityError) as captured:
        _assert_r2v_reference_budget(project, version_ids)

    assert captured.value.code == "VIDEO_MODEL_CAPABILITY_UNKNOWN"
    assert captured.value.details["knownModelRequired"] is True


def _services(tmp_path, monkeypatch, extra_creation=None):
    elements = [make_r2v_element(ELEMENT_ID, video_prompt="动画，猫从左向右追逐老鼠，动作连续")]
    if extra_creation is not None:
        elements.append(
            TimelineElement(
                element_id=MODE_ELEMENT_ID,
                label="模式镜头",
                span=TimelineSpan(start_tick=4_000, duration_tick=4_000),
                location=ElementLocation(),
                creation=extra_creation,
            ),
        )
    return r2v_project_services(
        tmp_path,
        monkeypatch,
        project_id=PROJECT_ID,
        name="R2V Modes",
        elements=elements,
    )


def _generate_storyboard(services: CreatorFileServices) -> str:
    """Create one storyboard ArtifactVersion and return its version id."""

    execution = asyncio.run(
        FileImageExecutionService(services, provider=_ImageProvider()).execute(
            project_id=PROJECT_ID,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref=f"element:{ELEMENT_ID}",
            arguments={},
            idempotency_key="storyboard-mode-1",
        ),
    )
    accept_pending_reviews(services, PROJECT_ID)
    return execution.artifact_version_id


def _run_video(
    services,
    provider,
    *,
    arguments,
    idempotency_key,
    s2v=False,
    element_id=ELEMENT_ID,
):
    async def scenario():
        worker = FileR2VExecutionService(
            services,
            provider=provider,
            poll_interval_seconds=0.01,
            poll_lease_seconds=0.1,
        )
        dispatched = await worker.dispatch(
            project_id=PROJECT_ID,
            target_ref=f"element:{element_id}",
            arguments=arguments,
            idempotency_key=idempotency_key,
            s2v=s2v,
        )
        task = await worker.wait_for_task(
            PROJECT_ID,
            dispatched.task_id,
            timeout_seconds=5,
        )
        await worker.shutdown()
        return task

    return asyncio.run(scenario())


def test_i2v_dispatch_resolves_first_frame_version(tmp_path, monkeypatch):
    services = _services(
        tmp_path,
        monkeypatch,
        extra_creation=I2VCreation(video_prompt="猫从首帧开始奔跑"),
    )
    storyboard_version_id = _generate_storyboard(services)
    provider = _CapturingR2VProvider()
    task = _run_video(
        services,
        provider,
        element_id=MODE_ELEMENT_ID,
        arguments={
            "mode": "i2v",
            "firstFrameRef": storyboard_version_id,
            "durationSeconds": 5,
            "ratio": "16:9",
            "resolution": "720P",
        },
        idempotency_key="video-i2v-1",
    )

    assert task.status.value == "SUCCEEDED"
    submitted = provider.submits[0]
    assert submitted["mode"] == "i2v"
    assert submitted["first_frame_url"].startswith("file://")


def test_video_edit_rejected_for_wan_models(tmp_path, monkeypatch) -> None:
    services = _services(tmp_path, monkeypatch)
    monkeypatch.setenv("VIDEO_MODEL_NAME", "wan2.7-r2v")
    with pytest.raises(ValidationError, match="不支持 mode=video_edit"):
        _run_video(
            services,
            _CapturingR2VProvider(),
            arguments={
                "mode": "video_edit",
                "videoRef": "missing-version",
                "durationSeconds": 5,
            },
            idempotency_key="video-edit-rejected",
        )


def test_i2v_requires_first_frame_ref(tmp_path, monkeypatch) -> None:
    services = _services(
        tmp_path,
        monkeypatch,
        extra_creation=I2VCreation(video_prompt="猫从首帧开始奔跑"),
    )
    with pytest.raises(ValidationError, match="firstFrameRef"):
        _run_video(
            services,
            _CapturingR2VProvider(),
            element_id=MODE_ELEMENT_ID,
            arguments={"mode": "i2v", "durationSeconds": 5},
            idempotency_key="video-i2v-missing",
        )


def _register_tts_audio(services: CreatorFileServices, monkeypatch) -> str:
    """Land one fake TTS audio SourceAssetVersion and return its id."""

    from models import tts_model
    from services.media_files.audio_execution import execute_file_tts_command

    async def fake_synthesize(text, **_kwargs):
        return tts_model.TTSSynthesis(
            audio_bytes=b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 2048,
            media_type="audio/wav",
            model="qwen3-tts-flash",
            voice="Cherry",
            characters=len(text),
        )

    monkeypatch.setattr(tts_model, "synthesize", fake_synthesize)
    result = asyncio.run(
        execute_file_tts_command(
            services,
            project_id=PROJECT_ID,
            target_ref=f"element:{ELEMENT_ID}",
            arguments={"text": "你好，数字人"},
            idempotency_key="tts-s2v-1",
        ),
    )
    return result.source_asset_version_id


def test_s2v_dispatch_consumes_tts_audio_and_character_image(
    tmp_path,
    monkeypatch,
) -> None:
    """s2v rides the same durable poller with exact image + audio versions."""

    services = _services(
        tmp_path,
        monkeypatch,
        extra_creation=S2VCreation(script="你好，数字人"),
    )
    image_version_id = _generate_storyboard(services)
    audio_version_id = _register_tts_audio(services, monkeypatch)
    provider = _CapturingR2VProvider()
    task = _run_video(
        services,
        provider,
        element_id=MODE_ELEMENT_ID,
        arguments={
            "characterImageRef": image_version_id,
            "audioAssetRef": audio_version_id,
            "resolution": "480P",
        },
        idempotency_key="s2v-1",
        s2v=True,
    )

    assert task.status.value == "SUCCEEDED"
    submitted = provider.submits[-1]
    assert submitted["s2v"] is True
    assert submitted["image_url"].startswith("file://")
    assert submitted["audio_url"].startswith("file://")
    finished = services.projects.read(PROJECT_ID).project
    element = finished.timelines.items["timeline:main"].elements_by_id[
        MODE_ELEMENT_ID
    ]
    assert element.outputs["main"].slot_id == f"element:{MODE_ELEMENT_ID}:main"


def test_s2v_preflight_face_detect_gate(tmp_path, monkeypatch) -> None:
    """Face-detect preflight blocks unsuitable images and passes portraits."""

    from models import s2v_model
    from services.media_files.r2v_execution import preflight_s2v_face_detect

    services = _services(tmp_path, monkeypatch)
    image_version_id = _generate_storyboard(services)

    def run_preflight():
        return asyncio.run(
            preflight_s2v_face_detect(
                services,
                project_id=PROJECT_ID,
                arguments={"characterImageRef": image_version_id},
            ),
        )

    async def failing_detect(image_url: str):
        return s2v_model.FaceDetectResult(
            passed=False,
            reason="[InvalidFace.SideFace] side face detected",
        )

    monkeypatch.setattr(s2v_model, "detect_face", failing_detect)
    with pytest.raises(ValidationError, match="人像检测未通过"):
        run_preflight()

    async def passing_detect(image_url: str):
        return s2v_model.FaceDetectResult(passed=True, humanoid=True)

    monkeypatch.setattr(s2v_model, "detect_face", passing_detect)
    run_preflight()
