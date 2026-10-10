# -*- coding: utf-8 -*-
"""Rough-cut HTTP surface: fail-closed 409 and a real 480p mp4 draft.

Covers the wiring the unit tests cannot: the route must exist, resolve
indexed files through the AssetFileStore boundary, map RoughCutError to
409 and stream ``video/mp4`` — all at zero provider cost.
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI

from api.dependencies import creator_error_handler, project_file_services
from api.router import router
from domain.errors import CreatorError
from services.project_files.assets import AssetFileStore
from services.project_files.commit import ProjectCommitBoundary
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="requires ffmpeg on PATH",
)

PROJECT_ID = "project-1"
TIMELINE_ID = "timeline:main"


def _app(tmp_path):
    services = CreatorFileServices.create(tmp_path.resolve())
    snapshot = services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Rough Cut Project"),
    )
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    app.dependency_overrides[project_file_services] = lambda: services
    return app, services, snapshot


def _make_still_bytes(tmp_path) -> bytes:
    target = tmp_path / "storyboard-src.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:d=0.1",
            "-frames:v",
            "1",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target.read_bytes()


def _commit_storyboard_element(services, snapshot, png_bytes: bytes) -> None:
    """One enabled element whose storyboard slot holds a real indexed PNG."""

    store = AssetFileStore(services.projects.project_root(PROJECT_ID))
    published = store.publish(
        store.stage_bytes(png_bytes, staging_id="storyboard"),
        "assets/artifacts/el-1/storyboard.png",
    )
    raw = snapshot.project.model_dump(mode="json")
    raw["assets"]["files_by_id"]["file-storyboard"] = {
        "file_id": "file-storyboard",
        "kind": "artifact_payload",
        "relative_uri": published.relative_uri,
        "sha256": published.sha256,
        "size_bytes": published.size_bytes,
        "media_type": "image/png",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    raw["assets"]["artifact_versions_by_id"]["storyboard-v1"] = {
        "version_id": "storyboard-v1",
        "slot_id": "element:el-1:storyboard",
        "kind": "r2v_storyboard_image",
        "owner_ref": "element:el-1",
        "name": "storyboard",
        "file_id": "file-storyboard",
        "checksum": published.sha256,
        "based_on_generation": snapshot.generation,
        "provenance_refs": [],
        "thumbnail_file_id": None,
        "duration_seconds": None,
        "input_fingerprint": None,
        "stale": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {},
    }
    raw["assets"]["artifact_slots_by_id"]["element:el-1:storyboard"] = {
        "slot_id": "element:el-1:storyboard",
        "kind": "r2v_storyboard_image",
        "owner_ref": "element:el-1",
        "version_ids": ["storyboard-v1"],
        "selected_version_id": "storyboard-v1",
        "metadata": {},
    }
    raw["timelines"]["items"][TIMELINE_ID]["elements_by_id"] = {
        "el-1": {
            "element_id": "el-1",
            "label": "Scene 1",
            "enabled": True,
            "span": {"start_tick": 0, "duration_tick": 1000},
            "location": None,
            "z_index": 0,
            "creation": {
                "type": "t2v",
                "intent": "",
                "video_prompt": "一只猫",
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
def test_rough_cut_unknown_timeline_is_404(tmp_path, run_scenario):
    app, _services, _snapshot = _app(tmp_path)

    async def scenario(client):
        response = await client.get(
            f"/projects/{PROJECT_ID}/timelines/timeline:nope/rough-cut",
        )
        assert response.status_code == 404

    run_scenario(app, scenario)


@pytest.mark.usefixtures("api_runtime_root")
def test_rough_cut_without_material_fails_closed_409(tmp_path, run_scenario):
    app, _services, _snapshot = _app(tmp_path)

    async def scenario(client):
        response = await client.get(
            f"/projects/{PROJECT_ID}/timelines/{TIMELINE_ID}/rough-cut",
        )
        assert response.status_code == 409
        assert "粗剪素材" in response.json()["message"]

    run_scenario(app, scenario)


@requires_ffmpeg
@pytest.mark.usefixtures("api_runtime_root")
def test_rough_cut_with_storyboard_returns_mp4(tmp_path, run_scenario):
    app, services, snapshot = _app(tmp_path)
    _commit_storyboard_element(services, snapshot, _make_still_bytes(tmp_path))

    async def scenario(client):
        response = await client.get(
            f"/projects/{PROJECT_ID}/timelines/{TIMELINE_ID}/rough-cut",
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "video/mp4"
        payload = response.content
        assert len(payload) > 1000
        assert b"ftyp" in payload[:64]

    run_scenario(app, scenario)
