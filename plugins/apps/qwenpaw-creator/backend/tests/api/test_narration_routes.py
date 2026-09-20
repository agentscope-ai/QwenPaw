# -*- coding: utf-8 -*-
"""Narration regeneration HTTP surface: direct TTS re-synthesis + rebind."""

from __future__ import annotations

from datetime import datetime, timezone
import asyncio

import pytest
from fastapi import FastAPI

from api.dependencies import creator_error_handler, project_file_services
from api.router import router
from domain.errors import CreatorError
from services.media_files import audio_execution
from services.project_files.commit import ProjectCommitBoundary
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project

PROJECT_ID = "project-1"
TIMELINE_ID = "timeline:main"


def _app(tmp_path):
    services = CreatorFileServices.create(tmp_path.resolve())
    snapshot = services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Narration Project"),
    )
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    app.dependency_overrides[project_file_services] = lambda: services
    return app, services, snapshot


def _source_version(version_id: str, metadata: dict) -> dict:
    return {
        "version_id": version_id,
        "logical_asset_id": "asset-narration",
        "name": f"旁白 {version_id}",
        "file_id": f"file-{version_id}",
        "checksum": "b" * 64,
        "media_kind": "audio",
        "media_type": "audio/mpeg",
        "duration_seconds": 3.2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
    }


def _commit_narration_element(
    services,
    snapshot,
    *,
    character_voice=False,
) -> None:
    raw = snapshot.project.model_dump(mode="json")
    for version_id in ("audio-v1", "audio-v2"):
        raw["assets"]["files_by_id"][f"file-{version_id}"] = {
            "file_id": f"file-{version_id}",
            "kind": "source_original",
            "relative_uri": f"assets/sources/{version_id}.mp3",
            "sha256": "b" * 64,
            "size_bytes": 64,
            "media_type": "audio/mpeg",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        raw["assets"]["source_versions_by_id"][version_id] = _source_version(
            version_id,
            {
                "voice": "longxiaochun",
                "model": "cosyvoice-v2",
                "characterEntityId": "narrator" if character_voice else "",
            },
        )
    if character_voice:
        raw["visual"]["entities"] = {
            "order": ["narrator"],
            "items": {
                "narrator": {
                    "entity_id": "narrator",
                    "kind": "character",
                    "name": "旁白角色",
                    "required_variant_ids": [],
                    "voice": {
                        "voice_id": "voice-original",
                        "target_model": "cosyvoice-v2",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
            },
        }
    raw["timelines"]["items"][TIMELINE_ID]["elements_by_id"] = {
        "el-narr": {
            "element_id": "el-narr",
            "label": "开场旁白",
            "enabled": True,
            "span": {"start_tick": 0, "duration_tick": 3200},
            "location": None,
            "z_index": 0,
            "creation": {
                "type": "audio",
                "source_asset_version_id": "audio-v1",
                "role": "narration",
                "script": "十年之后，雾山的雨又下了起来。",
                "gain_db": 0,
                "pan": 0,
            },
            "outputs": {},
            "render_source": None,
            "provenance_refs": [],
        },
    }
    ProjectCommitBoundary(services.projects).commit(
        base=snapshot,
        candidate=raw,
        origin="runtime_task",
    )


@pytest.mark.usefixtures("api_runtime_root")
def test_regenerate_narration_rejects_non_audio_element(
    tmp_path,
    run_scenario,
):
    app, _services, _snapshot = _app(tmp_path)

    async def scenario(client):
        response = await client.post(
            f"/projects/{PROJECT_ID}/timelines/{TIMELINE_ID}"
            "/elements/el-missing/narration",
        )
        assert response.status_code == 404

    run_scenario(app, scenario)


@pytest.mark.usefixtures("api_runtime_root")
def test_regenerate_narration_rejects_snapshot_timeline(
    tmp_path,
    run_scenario,
):
    app, _services, _snapshot = _app(tmp_path)

    async def scenario(client):
        response = await client.post(
            f"/projects/{PROJECT_ID}/timelines/snapshot:timeline:main:1"
            "/elements/el-narr/narration",
        )
        assert response.status_code in (400, 422)

    run_scenario(app, scenario)


@pytest.mark.usefixtures("api_runtime_root")
def test_regenerate_narration_resynthesizes_and_rebinds(
    tmp_path,
    run_scenario,
    monkeypatch,
):
    app, services, snapshot = _app(tmp_path)
    _commit_narration_element(services, snapshot)
    captured: dict = {}

    async def fake_tts(
        _services,
        *,
        project_id,
        target_ref,
        arguments,
        idempotency_key,
    ):
        captured.update(
            project_id=project_id,
            target_ref=target_ref,
            arguments=dict(arguments),
            idempotency_key=idempotency_key,
        )
        return audio_execution.FileTtsExecutionResult(
            source_asset_version_id="audio-v2",
            logical_asset_id="asset-narration",
            file_id="file-audio-v2",
            duration_seconds=3.4,
            voice="longxiaochun",
            model="cosyvoice-v2",
            project_etag="sha256:x",
            project_generation=2,
            replayed=False,
        )

    monkeypatch.setattr(
        audio_execution,
        "execute_file_tts_command",
        fake_tts,
    )

    async def scenario(client):
        path = (
            f"/projects/{PROJECT_ID}/timelines/{TIMELINE_ID}"
            "/elements/el-narr/narration"
        )
        headers = {"Idempotency-Key": "same-request"}
        response = await client.post(path, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["audioVersionId"] == "audio-v2"
        assert body["rebound"] is True
        replay = await client.post(path, headers=headers)
        assert replay.status_code == 200
        assert not replay.json()["rebound"] and not replay.json()["stale"]
        _edit(
            services,
            lambda raw: raw["timelines"]["items"][TIMELINE_ID][
                "elements_by_id"
            ]["el-narr"]["creation"].update(script="新文稿"),
        )
        rejected = await client.post(path, headers=headers)
        assert rejected.status_code == 409

    run_scenario(app, scenario)

    # Synthesis inputs come from the element + the current version's voice.
    assert captured["arguments"]["text"] == "十年之后，雾山的雨又下了起来。"
    assert captured["arguments"]["voice"] == "longxiaochun"
    fresh = services.projects.read(PROJECT_ID)
    element = fresh.project.timelines.items[TIMELINE_ID].elements_by_id[
        "el-narr"
    ]
    assert element.creation.source_asset_version_id == "audio-v2"


def _edit(services, mutate):
    snapshot = services.projects.read(PROJECT_ID)
    candidate = snapshot.project.model_dump(mode="json")
    mutate(candidate)
    return services.commits.commit(
        base=snapshot,
        candidate=candidate,
        origin="runtime_task",
    )


def _tts_result(version="audio-v2"):
    return audio_execution.FileTtsExecutionResult(
        source_asset_version_id=version,
        logical_asset_id="asset-narration",
        file_id=f"file-{version}",
        duration_seconds=3.4,
        voice="longxiaochun",
        model="cosyvoice-v2",
        project_etag="sha256:x",
        project_generation=2,
        replayed=False,
    )


@pytest.mark.usefixtures("api_runtime_root")
@pytest.mark.parametrize(
    "field,value,stale",
    [
        ("script", "用户刚刚改成的新台词", True),
        ("speech_rate", 1.5, True),
        ("source_asset_version_id", "audio-v2", True),
        ("character_voice", "voice-updated", True),
        ("unrelated", "新的项目名", False),
    ],
)
def test_narration_validates_inputs_after_tts(
    tmp_path,
    run_scenario,
    monkeypatch,
    field,
    value,
    stale,
):
    app, services, snapshot = _app(tmp_path)
    _commit_narration_element(
        services,
        snapshot,
        character_voice=field == "character_voice",
    )

    async def scenario(client):
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_tts(*_args, **_kwargs):
            started.set()
            await release.wait()
            return _tts_result()

        monkeypatch.setattr(
            audio_execution,
            "execute_file_tts_command",
            fake_tts,
        )
        request = asyncio.create_task(
            client.post(
                f"/projects/{PROJECT_ID}/timelines/{TIMELINE_ID}"
                "/elements/el-narr/narration",
            ),
        )
        await asyncio.wait_for(started.wait(), 5)

        def mutate(raw):
            if field == "unrelated":
                raw["name"] = value
            elif field == "character_voice":
                raw["visual"]["entities"]["items"]["narrator"]["voice"][
                    "voice_id"
                ] = value
            else:
                raw["timelines"]["items"][TIMELINE_ID]["elements_by_id"][
                    "el-narr"
                ]["creation"][field] = value

        _edit(services, mutate)
        release.set()
        response = await request
        assert response.status_code == 200, response.text
        assert response.json()["stale"] is stale
        assert response.json()["rebound"] is not stale
        creation = (
            services.projects.read(PROJECT_ID)
            .project.timelines.items[TIMELINE_ID]
            .elements_by_id["el-narr"]
            .creation
        )
        if stale:
            if field != "character_voice":
                assert getattr(creation, field) == value
            assert creation.source_asset_version_id == (
                value if field == "source_asset_version_id" else "audio-v1"
            )
        else:
            assert creation.source_asset_version_id == "audio-v2"

    run_scenario(app, scenario)


@pytest.mark.usefixtures("api_runtime_root")
@pytest.mark.parametrize("newer_first", [True, False])
@pytest.mark.parametrize("changed_text", [True, False])
def test_narration_latest_request_wins_in_either_completion_order(
    tmp_path,
    run_scenario,
    monkeypatch,
    newer_first,
    changed_text,
):
    app, services, snapshot = _app(tmp_path)
    _commit_narration_element(services, snapshot)

    def add_version(raw):
        raw["assets"]["files_by_id"]["file-audio-v3"] = {
            **raw["assets"]["files_by_id"]["file-audio-v2"],
            "file_id": "file-audio-v3",
        }
        raw["assets"]["source_versions_by_id"]["audio-v3"] = _source_version(
            "audio-v3",
            {"voice": "longxiaochun", "model": "cosyvoice-v2"},
        )

    _edit(services, add_version)

    async def scenario(client):
        started = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]
        calls = []

        async def fake_tts(*_args, **kwargs):
            index = len(calls)
            calls.append(kwargs)
            started[index].set()
            await release[index].wait()
            return _tts_result("audio-v2" if index == 0 else "audio-v3")

        monkeypatch.setattr(
            audio_execution,
            "execute_file_tts_command",
            fake_tts,
        )
        path = (
            f"/projects/{PROJECT_ID}/timelines/{TIMELINE_ID}"
            "/elements/el-narr/narration"
        )
        older = asyncio.create_task(client.post(path))
        await asyncio.wait_for(started[0].wait(), 5)
        if changed_text:

            def mutate(raw):
                raw["timelines"]["items"][TIMELINE_ID]["elements_by_id"][
                    "el-narr"
                ]["creation"]["script"] = "新版台词"

            _edit(services, mutate)
        newer = asyncio.create_task(client.post(path))
        await asyncio.wait_for(started[1].wait(), 5)
        first = 1 if newer_first else 0
        release[first].set()
        first_response = await (newer if newer_first else older)
        assert first_response.status_code == 200, first_response.text
        if not newer_first:
            assert first_response.json()["rebound"] is False
            assert first_response.json()["staleReason"] == "SUPERSEDED"
        release[1 - first].set()
        second_response = await (older if newer_first else newer)
        assert second_response.status_code == 200, second_response.text
        fresh = services.projects.read(PROJECT_ID).project
        assert (
            fresh.timelines.items[TIMELINE_ID]
            .elements_by_id["el-narr"]
            .creation.source_asset_version_id
            == "audio-v3"
        )

    run_scenario(app, scenario)
