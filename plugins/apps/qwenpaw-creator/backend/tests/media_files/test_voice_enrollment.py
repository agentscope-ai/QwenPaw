# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Voice enrollment executor: prompt persistence and audition fallback."""

from __future__ import annotations

import asyncio
import io
import wave

import pytest

from models import tts_model
from domain.errors import ConflictError
from services.media_files import audio_execution
from services.media_files.audio_execution import (
    execute_file_voice_enrollment_command,
)
from services.project_files.models import VisualEntity

from .conftest import r2v_project_services


def _services_with_character(tmp_path, monkeypatch):
    services = r2v_project_services(
        tmp_path,
        monkeypatch,
        project_id="p-voice",
        name="voice project",
    )
    snapshot = services.projects.read("p-voice")
    candidate = snapshot.project.model_dump(mode="json")
    entity = VisualEntity(
        entity_id="hero",
        kind="character",
        name="旅人",
        description="低沉沙哑的中年旅人",
        required_variant_ids=[],
    )
    candidate["visual"]["entities"]["order"] = ["hero"]
    candidate["visual"]["entities"]["items"] = {
        "hero": entity.model_dump(mode="json"),
    }
    from services.runtime_files.models import ChangeOrigin, ReviewPolicy

    commit = services.commits.commit(
        base=snapshot,
        candidate=candidate,
        origin=ChangeOrigin.RUNTIME_TASK,
        review_policy=ReviewPolicy.AUTO_FIX,
        caused_by_request_id="seed-hero",
        round_id="round-seed-hero",
        transaction_id="txn-seed-hero",
        advance_accepted_baseline=True,
    )
    services.poller.note_commit(commit.snapshot)
    return services


def test_video_sample_version_yields_its_extracted_audio_track(
    tmp_path,
    monkeypatch,
):
    """用户把音色参考录在视频里时，样本取其音轨而不是被格式拒绝。

    2026-09-10 现场：一段黑屏 mp4 音色参考被 "must be audio media" 卡死，
    尽管素材理解已确认音轨可用。
    """

    import subprocess

    from api.file_asset_routes import _AssetInput, _ingest_many_sync
    from services.runtime_files.runtime_dependencies import resolve_ffmpeg

    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        pytest.skip("ffmpeg unavailable")
    clip = tmp_path / "voice-ref.mp4"
    generated = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "aac",
            str(clip),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if generated.returncode != 0:
        pytest.skip(f"ffmpeg cannot synthesize fixture: {generated.stderr}")

    services = _services_with_character(tmp_path, monkeypatch)
    ingested, _ = _ingest_many_sync(
        services,
        project_id="p-voice",
        key="voice-ref-video",
        inputs=[
            _AssetInput(
                name="voice-ref.mp4",
                content=clip.read_bytes(),
                media_type="video/mp4",
            ),
        ],
        attach_source=False,
        scope="voice-ref-test",
    )
    version_id = ingested["items"][0]["assetVersionId"]

    (
        payload,
        media_type,
        resolved_id,
    ) = audio_execution._sample_bytes_for_version(
        services,
        project_id="p-voice",
        version_id=version_id,
        idempotency_key="voice-enroll-1",
    )

    assert media_type == "audio/wav"
    with wave.open(io.BytesIO(payload), "rb") as sample:
        assert sample.getnchannels() == 1
        assert sample.getframerate() == 24000
        seconds = sample.getnframes() / sample.getframerate()
    assert 0.8 <= seconds <= 1.3
    # The binding must reference a persisted audio version (downstream R2V
    # voice resolution rejects video-bound samples), provenance-linked to
    # the original video.
    assert resolved_id != version_id
    project = services.projects.read("p-voice").project
    resolved = project.assets.source_versions_by_id[resolved_id]
    assert resolved.media_kind == "audio"
    assert resolved.metadata.get("extractedFromVersionId") == version_id
    # Replays resolve to the same persisted version instead of minting one.
    _, _, replay_id = audio_execution._sample_bytes_for_version(
        services,
        project_id="p-voice",
        version_id=version_id,
        idempotency_key="voice-enroll-1",
    )
    assert replay_id == resolved_id


@pytest.mark.parametrize("failure_stage", [None, "tts", "binding", "commit"])
def test_design_enrollment_persists_voice_and_recovers_audition(
    tmp_path,
    monkeypatch,
    failure_stage,
):
    # pylint: disable=too-many-statements
    services = _services_with_character(tmp_path, monkeypatch)
    calls = {"design": 0, "synthesize": 0}
    expected_syntheses = 2 if failure_stage == "tts" else 1
    attach_sample = audio_execution._attach_voice_sample
    real_commit = services.commits.commit

    def commit(*args, **kwargs):
        if failure_stage == "commit":
            raise RuntimeError("temporary voice publication failure")
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(services.commits, "commit", commit)

    def attach(*args, **kwargs):
        if failure_stage == "binding":
            raise RuntimeError("temporary sample binding failure")
        return attach_sample(*args, **kwargs)

    monkeypatch.setattr(audio_execution, "_attach_voice_sample", attach)

    async def fake_design_voice(*, voice_prompt, preview_text, preferred_name):
        calls["design"] += 1
        assert voice_prompt == "低哑男声，语速缓慢"
        assert len(preview_text) >= tts_model.VOICE_PREVIEW_MIN_CHARS
        assert preferred_name == "旅人"
        return tts_model.VoiceEnrollment(
            voice_id="voice-designed-1",
            target_model="cosyvoice-v3.5-plus",
            origin="design",
        )

    monkeypatch.setattr(tts_model, "design_voice", fake_design_voice)
    monkeypatch.setattr(
        tts_model.config,
        "get_tts_model_name",
        lambda: "cosyvoice-v3.5-plus",
    )

    async def synthesize(text, **_kwargs):
        calls["synthesize"] += 1
        if failure_stage == "tts":
            raise RuntimeError("temporary audition failure")
        data = io.BytesIO()
        with wave.open(data, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 4000)
        return tts_model.TTSSynthesis(
            audio_bytes=data.getvalue(),
            media_type="audio/wav",
            model="cosyvoice-v3.5-plus",
            voice="voice-designed-1",
            characters=len(text),
        )

    monkeypatch.setattr(tts_model, "synthesize", synthesize)
    if failure_stage == "commit":
        with pytest.raises(RuntimeError, match="publication failure"):
            asyncio.run(
                execute_file_voice_enrollment_command(
                    services,
                    project_id="p-voice",
                    target_ref="asset:hero",
                    arguments={"voicePrompt": "低哑男声，语速缓慢"},
                    idempotency_key="voice-key-1",
                ),
            )
        failure_stage = None
    result = asyncio.run(
        execute_file_voice_enrollment_command(
            services,
            project_id="p-voice",
            target_ref="asset:hero",
            arguments={"voicePrompt": "低哑男声，语速缓慢"},
            idempotency_key="voice-key-1",
        ),
    )
    assert result.voice_id == "voice-designed-1"
    assert result.origin == "design"

    snapshot = services.projects.read("p-voice")
    voice = snapshot.project.visual.entities.items["hero"].voice
    assert voice is not None
    assert voice.voice_prompt == "低哑男声，语速缓慢"
    assert bool(voice.sample_source_version_id) is (failure_stage is None)
    assert voice.enrollment_key == "voice-key-1"
    failure_stage = None

    # Idempotent replay: same key returns the same binding, no provider call.
    async def boom(**_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("replay must not re-enroll")

    monkeypatch.setattr(tts_model, "design_voice", boom)
    replay = asyncio.run(
        execute_file_voice_enrollment_command(
            services,
            project_id="p-voice",
            target_ref="asset:hero",
            arguments={"voicePrompt": "低哑男声，语速缓慢"},
            idempotency_key="voice-key-1",
        ),
    )
    assert replay.replayed is True
    assert replay.voice_id == "voice-designed-1"
    assert replay.origin == "design"
    assert replay.sample_source_version_id is not None
    fresh = services.projects.read("p-voice").project
    assert (
        fresh.visual.entities.items["hero"].voice.sample_source_version_id
        == replay.sample_source_version_id
    )
    sample = fresh.assets.source_versions_by_id[
        replay.sample_source_version_id
    ]
    assert sample.metadata["voiceId"] == "voice-designed-1"
    assert sample.file_id in fresh.assets.files_by_id
    assert calls["design"] == 1
    assert calls["synthesize"] == expected_syntheses


@pytest.mark.parametrize("first_completed", ["old", "new"])
def test_later_voice_request_wins_regardless_of_provider_completion_order(
    tmp_path,
    monkeypatch,
    first_completed,
):
    services = _services_with_character(tmp_path, monkeypatch)

    async def scenario():
        started = {key: asyncio.Event() for key in ("old", "new")}
        releases = {key: asyncio.Event() for key in started}
        calls = []

        async def design(*, voice_prompt, **_kwargs):
            calls.append(voice_prompt)
            started[voice_prompt].set()
            await releases[voice_prompt].wait()
            return tts_model.VoiceEnrollment(
                voice_id=f"voice-{voice_prompt}",
                target_model="cosyvoice-v3.5-plus",
                origin="design",
            )

        async def audition(*_args, result, **_kwargs):
            return result

        async def delete(*_args, **_kwargs):
            raise AssertionError("no previously bound voice should be deleted")

        monkeypatch.setattr(tts_model, "design_voice", design)
        monkeypatch.setattr(tts_model, "delete_voice", delete)
        monkeypatch.setattr(audio_execution, "_ensure_voice_sample", audition)

        async def enroll(key):
            return await execute_file_voice_enrollment_command(
                services,
                project_id="p-voice",
                target_ref="asset:hero",
                arguments={"voicePrompt": key},
                idempotency_key=key,
            )

        tasks = {}
        for key in started:
            tasks[key] = asyncio.create_task(enroll(key))
            await asyncio.wait_for(started[key].wait(), timeout=3)
        results = {}
        for key in (
            first_completed,
            "new" if first_completed == "old" else "old",
        ):
            releases[key].set()
            results[key] = (
                await asyncio.gather(tasks[key], return_exceptions=True)
            )[0]
        assert isinstance(results["old"], ConflictError)
        assert results["new"].voice_id == "voice-new"
        assert (
            services.projects.read("p-voice")
            .project.visual.entities.items["hero"]
            .voice.voice_id
            == "voice-new"
        )
        # Retrying the obsolete key must not turn it into the newest intent
        # or pay the provider again.
        with pytest.raises(ConflictError):
            await enroll("old")
        assert calls == ["old", "new"]

    asyncio.run(scenario())
