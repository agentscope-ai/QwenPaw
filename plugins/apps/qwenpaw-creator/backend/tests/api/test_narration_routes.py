# -*- coding: utf-8 -*-
"""Narration regeneration HTTP surface: direct TTS re-synthesis + rebind."""
from __future__ import annotations

from datetime import datetime, timezone

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


def _commit_narration_element(services, snapshot) -> None:
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
                "characterEntityId": "",
            },
        )
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
        response = await client.post(
            f"/projects/{PROJECT_ID}/timelines/{TIMELINE_ID}"
            "/elements/el-narr/narration",
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["audioVersionId"] == "audio-v2"
        assert body["rebound"] is True

    run_scenario(app, scenario)

    # Synthesis inputs come from the element + the current version's voice.
    assert captured["arguments"]["text"] == "十年之后，雾山的雨又下了起来。"
    assert captured["arguments"]["voice"] == "longxiaochun"
    fresh = services.projects.read(PROJECT_ID)
    element = fresh.project.timelines.items[TIMELINE_ID].elements_by_id[
        "el-narr"
    ]
    assert element.creation.source_asset_version_id == "audio-v2"
