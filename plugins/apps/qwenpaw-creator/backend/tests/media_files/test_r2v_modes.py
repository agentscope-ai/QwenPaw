# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""r2v_generation mode plumbing through the durable execution service."""
from __future__ import annotations

import asyncio

import pytest

from domain.errors import ValidationError
from services.media_files.image_execution import FileImageExecutionService
from services.media_files.r2v_execution import FileR2VExecutionService
from services.project_files.facade import CreatorFileServices
from services.project_files.review import ReviewDecisionItem
from services.project_files.models import (
    ElementLocation,
    EntityCollection,
    I2VCreation,
    Project,
    R2VCreation,
    S2VCreation,
    Shot,
    T2VCreation,
    TimelineElement,
    TimelineSpan,
)

# pylint: disable=no-name-in-module
from utils.paths import unique_task_work_path

# pylint: enable=no-name-in-module


pytestmark = pytest.mark.unit

_PNG = b"\x89PNG\r\n\x1a\n" + b"mode-storyboard" * 16
_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"mode-video" * 64

PROJECT_ID = "r2v-mode-project"
ELEMENT_ID = "r2v-mode-1"
# Second element carrying the mode-specific creation type under test; the
# r2v element above keeps producing the storyboard image used as input.
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


def _r2v_element() -> TimelineElement:
    shot = Shot(
        shot_id=f"{ELEMENT_ID}-shot",
        description="猫追逐老鼠",
        camera="→ 横摇右",
        framing="全景",
        duration_seconds=4,
    )
    return TimelineElement(
        element_id=ELEMENT_ID,
        label="猫追老鼠",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="猫发现老鼠后追逐",
            storyboard_prompt="动画分镜：猫发现并追逐老鼠",
            video_prompt="动画，猫从左向右追逐老鼠，动作连续",
            shots=EntityCollection(
                items={shot.shot_id: shot},
                order=[shot.shot_id],
            ),
        ),
    )


def _services(
    tmp_path,
    monkeypatch,
    extra_creation=None,
) -> CreatorFileServices:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path.resolve()))
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="R2V Modes")
    project.timelines.items["timeline:main"].elements_by_id[
        ELEMENT_ID
    ] = _r2v_element()
    if extra_creation is not None:
        project.timelines.items["timeline:main"].elements_by_id[
            MODE_ELEMENT_ID
        ] = TimelineElement(
            element_id=MODE_ELEMENT_ID,
            label="模式镜头",
            span=TimelineSpan(start_tick=4_000, duration_tick=4_000),
            location=ElementLocation(),
            creation=extra_creation,
        )
    services.projects.create(
        Project.model_validate(project.model_dump(mode="json")),
    )
    return services


def _accept_pending_reviews(services: CreatorFileServices) -> None:
    for review in services.reviews.all_pending(PROJECT_ID):
        services.reviews.decide(
            project_id=PROJECT_ID,
            review_id=review.review_id,
            decision_token=review.decision_token,
            decisions=[
                ReviewDecisionItem(
                    operation_id=operation.operation_id,
                    decision="ACCEPT",
                )
                for operation in review.operations
            ],
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
    _accept_pending_reviews(services)
    return execution.artifact_version_id


def _run_video(
    services: CreatorFileServices,
    provider,
    *,
    arguments: dict,
    idempotency_key: str,
    s2v: bool = False,
    element_id: str = ELEMENT_ID,
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


def test_t2v_dispatch_skips_storyboard_and_passes_mode(
    tmp_path,
    monkeypatch,
) -> None:
    """t2v needs no storyboard selection and forwards mode to the provider."""

    services = _services(
        tmp_path,
        monkeypatch,
        extra_creation=T2VCreation(video_prompt="动画，猫从左向右追逐老鼠"),
    )
    provider = _CapturingR2VProvider()
    task = _run_video(
        services,
        provider,
        element_id=MODE_ELEMENT_ID,
        arguments={
            "mode": "t2v",
            "durationSeconds": 5,
            "ratio": "16:9",
            "resolution": "720P",
        },
        idempotency_key="video-t2v-1",
    )

    assert task.status.value == "SUCCEEDED"
    assert provider.submits[0]["mode"] == "t2v"
    assert provider.submits[0]["reference_image_urls"] == ()
    assert provider.submits[0]["first_frame_url"] is None
    assert provider.submits[0]["video_url"] is None


def test_i2v_dispatch_resolves_first_frame_version(
    tmp_path,
    monkeypatch,
) -> None:
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
    assert submitted["reference_image_urls"] == ()


def test_video_edit_dispatch_resolves_video_version(
    tmp_path,
    monkeypatch,
) -> None:
    """video_edit consumes an exact video version (happyhorse only)."""

    services = _services(tmp_path, monkeypatch)
    _generate_storyboard(services)
    provider = _CapturingR2VProvider()
    # First produce a real video ArtifactVersion through a plain r2v run.
    task = _run_video(
        services,
        provider,
        arguments={
            "durationSeconds": 5,
            "ratio": "16:9",
            "resolution": "720P",
        },
        idempotency_key="video-r2v-base",
    )
    assert task.status.value == "SUCCEEDED"
    # The freshly published video waits for user review; accept it so the
    # follow-up video_edit dispatch is admitted.
    _accept_pending_reviews(services)
    project = services.projects.read(PROJECT_ID).project
    video_version_id = next(
        version_id
        for version_id, version in (
            project.assets.artifact_versions_by_id.items()
        )
        if project.assets.files_by_id[version.file_id].media_type.startswith(
            "video/",
        )
    )

    monkeypatch.setenv("VIDEO_MODEL_NAME", "happyhorse-1.1-r2v")
    task = _run_video(
        services,
        provider,
        arguments={
            "mode": "video_edit",
            "videoRef": video_version_id,
            "prompt": "把场景改成黄昏",
            "durationSeconds": 5,
            "ratio": "16:9",
            "resolution": "720P",
        },
        idempotency_key="video-edit-1",
    )

    assert task.status.value == "SUCCEEDED"
    submitted = provider.submits[-1]
    assert submitted["mode"] == "video_edit"
    assert submitted["video_url"].startswith("file://")


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

    async def fake_synthesize(
        text,
        *,
        voice=None,
        voice_id=None,
        voice_model=None,
        speech_rate=None,
    ):
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
    assert submitted["resolution"] == "480P"
    finished = services.projects.read(PROJECT_ID).project
    element = finished.timelines.items["timeline:main"].elements_by_id[
        MODE_ELEMENT_ID
    ]
    assert element.outputs["main"].slot_id == f"element:{MODE_ELEMENT_ID}:main"


def test_s2v_dispatch_requires_audio_ref(tmp_path, monkeypatch) -> None:
    services = _services(
        tmp_path,
        monkeypatch,
        extra_creation=S2VCreation(script="你好，数字人"),
    )
    image_version_id = _generate_storyboard(services)
    with pytest.raises(ValidationError, match="audioAssetRef"):
        _run_video(
            services,
            _CapturingR2VProvider(),
            element_id=MODE_ELEMENT_ID,
            arguments={"characterImageRef": image_version_id},
            idempotency_key="s2v-missing-audio",
            s2v=True,
        )


def test_s2v_preflight_blocks_failed_face_detect(
    tmp_path,
    monkeypatch,
) -> None:
    from models import s2v_model
    from services.media_files.r2v_execution import preflight_s2v_face_detect

    services = _services(tmp_path, monkeypatch)
    image_version_id = _generate_storyboard(services)

    async def failing_detect(image_url: str):
        assert image_url.startswith("file://")
        return s2v_model.FaceDetectResult(
            passed=False,
            reason="[InvalidFace.SideFace] side face detected",
        )

    monkeypatch.setattr(s2v_model, "detect_face", failing_detect)
    with pytest.raises(ValidationError, match="人像检测未通过"):
        asyncio.run(
            preflight_s2v_face_detect(
                services,
                project_id=PROJECT_ID,
                arguments={"characterImageRef": image_version_id},
            ),
        )


def test_s2v_preflight_passes_suitable_portrait(
    tmp_path,
    monkeypatch,
) -> None:
    from models import s2v_model
    from services.media_files.r2v_execution import preflight_s2v_face_detect

    services = _services(tmp_path, monkeypatch)
    image_version_id = _generate_storyboard(services)

    async def passing_detect(image_url: str):
        return s2v_model.FaceDetectResult(passed=True, humanoid=True)

    monkeypatch.setattr(s2v_model, "detect_face", passing_detect)
    asyncio.run(
        preflight_s2v_face_detect(
            services,
            project_id=PROJECT_ID,
            arguments={"characterImageRef": image_version_id},
        ),
    )
