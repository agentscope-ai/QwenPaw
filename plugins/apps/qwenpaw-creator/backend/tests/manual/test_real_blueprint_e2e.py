# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Manual real-key acceptance for the project-blueprint slice.

Drives the REAL HTTP surface (create → v9 snapshot → narrative structure
patch → real Qwen synopsis drafting → work graph → rough-cut
fail-closed gate) against an isolated CREATOR_DATA_ROOT, using the real
DashScope key. Opt-in::

    DASHSCOPE_API_KEY=... pytest tests/manual/test_real_blueprint_e2e.py \\
        -q -m manual_real
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

pytestmark = pytest.mark.manual_real

requires_dashscope_key = pytest.mark.skipif(
    not os.environ.get("DASHSCOPE_API_KEY"),
    reason="requires DASHSCOPE_API_KEY",
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path / "creator-root"))
    monkeypatch.setenv(
        "CREATOR_MODEL_CONFIG_PATH",
        str(tmp_path / "creator-root" / "config" / "model_config.json"),
    )
    monkeypatch.setenv("TEXT_API_KEY", os.environ.get("DASHSCOPE_API_KEY", ""))
    monkeypatch.setenv("TEXT_MODEL_NAME", "qwen-plus")
    monkeypatch.setenv("IMAGE_MODEL", "DASHSCOPE")
    monkeypatch.setenv(
        "DASHSCOPE_IMAGE_API_KEY",
        os.environ.get("DASHSCOPE_API_KEY", ""),
    )
    (tmp_path / "creator-root" / "config").mkdir(parents=True, exist_ok=True)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.dependencies import creator_error_handler
    from api.router import router as creator_router
    from domain.errors import CreatorError
    from services.project_files.facade import (
        clear_creator_file_service_registry,
    )

    clear_creator_file_service_registry()
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(creator_router)
    with TestClient(app) as test_client:
        yield test_client
    clear_creator_file_service_registry()


def _pointer_get(document: dict, pointer: str):
    from services.project_files.json_pointer import MISSING

    node = document
    for token in pointer.strip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return MISSING
            node = node[token]
        elif isinstance(node, list):
            if token == "-" or int(token) >= len(node):
                return MISSING
            node = node[int(token)]
        else:
            return MISSING
    return node


def _op(project: dict, op: str, path: str, value):
    from services.project_files.json_pointer import hash_json_value

    return {
        "op": op,
        "path": path,
        "value": value,
        "expectedValueHash": hash_json_value(_pointer_get(project, path)),
    }


def _patch(api, project_id: str, snapshot: dict, operations: list) -> dict:
    response = api.patch(
        f"/projects/{project_id}/project",
        json={
            "clientCommandId": uuid.uuid4().hex,
            "editSessionId": "e2e",
            "baseGeneration": snapshot["generation"],
            "baseEtag": snapshot["etag"],
            "operations": operations,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _snapshot(api, project_id: str) -> dict:
    response = api.get(f"/projects/{project_id}/project")
    assert response.status_code == 200, response.text
    payload = response.json()
    payload["etag"] = response.headers.get("ETag", "").strip(
        '"',
    ) or payload.get(
        "etag",
        "",
    )
    return payload


@requires_dashscope_key
# pylint: disable-next=too-many-statements
def test_blueprint_slice_end_to_end_with_real_model(client) -> None:
    # 1. Create a story project through the real endpoint.
    created = client.post(
        "/projects",
        json={
            "clientRequestId": uuid.uuid4().hex,
            "name": f"雾山谜案-e2e-{uuid.uuid4().hex[:6]}",
            "description": "互动短剧端到端验收",
            "scenario": "short_drama",
            "aspectRatio": "9:16",
        },
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["projectId"]

    # 2. Snapshot must already be schema v9 with narrative fields.
    snapshot = _snapshot(client, project_id)
    project = snapshot["project"] if "project" in snapshot else snapshot
    assert project["schema_version"] == 9
    primary_id = project["timelines"]["order"][0]

    # 3. Real model call: draft a two-episode structure synopsis.
    import asyncio

    from models.text_model import chat_completion

    draft = asyncio.run(
        chat_completion(
            "为一部两集互动短剧《雾山谜案》分别用一句话写两集梗概，"
            '只输出 JSON：{"ep1": "...", "ep2": "..."}',
            temperature=0.3,
        ),
    )
    start = draft.find("{")
    end = draft.rfind("}")
    synopses = json.loads(draft[start : end + 1])
    assert synopses["ep1"].strip() and synopses["ep2"].strip()

    # 4. Persist the drafted structure through the real patch channel:
    #    title/synopsis on the primary node plus a second timeline.
    second_id = "tl:ep2"
    _patch(
        client,
        project_id,
        snapshot,
        [
            _op(
                project,
                "replace",
                f"/timelines/items/{primary_id}/title",
                "第1集 · 雾夜来信",
            ),
            _op(
                project,
                "replace",
                f"/timelines/items/{primary_id}/synopsis",
                synopses["ep1"].strip(),
            ),
            _op(
                project,
                "add",
                f"/timelines/items/{second_id}",
                {
                    "timeline_id": second_id,
                    "title": "第2集 · 旧宅疑云",
                    "synopsis": synopses["ep2"].strip(),
                },
            ),
            _op(project, "add", "/timelines/order/1", second_id),
        ],
    )
    updated = _snapshot(client, project_id)
    updated_project = updated["project"] if "project" in updated else updated
    assert (
        updated_project["timelines"]["items"][second_id]["synopsis"]
        == synopses["ep2"].strip()
    )

    # 4b. Add one r2v element BEFORE script drafting so the script node
    #     stays fresh when the storyboard later depends on it.
    latest = _snapshot(client, project_id)
    latest_project = latest["project"] if "project" in latest else latest
    element_id = "el:sc01"
    _patch(
        client,
        project_id,
        latest,
        [
            _op(
                latest_project,
                "add",
                f"/timelines/items/{primary_id}/elements_by_id/{element_id}",
                {
                    "element_id": element_id,
                    "label": "SC-01 雨夜山路",
                    "span": {"start_tick": 0, "duration_tick": 4000},
                    "location": {
                        "coordinate_space": "normalized_canvas",
                        "x": 0.5,
                        "y": 0.5,
                        "width": 1,
                        "height": 1,
                        "anchor_x": 0.5,
                        "anchor_y": 0.5,
                        "rotation_degrees": 0,
                        "opacity": 1,
                    },
                    "creation": {
                        "type": "r2v",
                        "intent": "雨夜山路空镜",
                        "storyboard_prompt": (
                            "暴雨夜的盘山公路，远光灯划开浓雾，" "冷蓝色调电影感，9:16 竖幅"
                        ),
                        "video_prompt": "镜头缓慢前推，雨刷摆动",
                        "shots": {
                            "items": {
                                "shot:1": {
                                    "shot_id": "shot:1",
                                    "description": "山路空镜",
                                    "camera": "↑ 推近",
                                    "framing": "全景",
                                    "duration_seconds": 4,
                                },
                            },
                            "order": ["shot:1"],
                        },
                    },
                },
            ),
        ],
    )

    # 5. Work graph derives script nodes for the branching project.
    graph = client.get(f"/projects/{project_id}/work-graph")
    assert graph.status_code == 200, graph.text
    nodes = {node["id"]: node for node in graph.json()["nodes"]}
    script_node_id = f"script:{primary_id}"
    assert script_node_id in nodes, sorted(nodes)
    assert nodes[script_node_id]["status"] in ("ready", "stale")

    # 6. Dispatch the script node: REAL qwen drafts the episode script and
    #    the pipeline persists it as a timeline_script artifact version.
    dispatched = client.post(
        f"/projects/{project_id}/work-graph/nodes/{script_node_id}/dispatch",
    )
    assert dispatched.status_code == 200, dispatched.text

    import time

    slot_id = f"script:{primary_id}"
    deadline = time.time() + 240
    script_markdown = ""
    while time.time() < deadline:
        latest = _snapshot(client, project_id)
        latest_project = latest["project"] if "project" in latest else latest
        slot = latest_project["assets"]["artifact_slots_by_id"].get(slot_id)
        if slot and slot.get("selected_version_id"):
            version = latest_project["assets"]["artifact_versions_by_id"][
                slot["selected_version_id"]
            ]
            indexed = latest_project["assets"]["files_by_id"][
                version["file_id"]
            ]
            root = os.environ["CREATOR_DATA_ROOT"]
            from pathlib import Path

            candidates = list(Path(root).rglob(indexed["relative_uri"]))
            assert candidates, indexed["relative_uri"]
            script_markdown = candidates[0].read_text(encoding="utf-8")
            break
        time.sleep(3)
    assert script_markdown.strip(), "script artifact never materialized"
    assert "场" in script_markdown or "#" in script_markdown
    print("REAL-SCRIPT-DRAFT chars:", len(script_markdown))

    # 8. Rough-cut fails closed (no artifacts yet).
    rough = client.get(
        f"/projects/{project_id}/timelines/{primary_id}/rough-cut",
    )
    assert rough.status_code == 409, rough.text

    # 9b. Dispatch the storyboard node: REAL qwen-image renders it.
    dispatched = client.post(
        f"/projects/{project_id}/work-graph/nodes"
        f"/storyboard:{element_id}/dispatch",
    )
    assert dispatched.status_code == 200, dispatched.text

    storyboard_slot = f"element:{element_id}:storyboard"
    deadline = time.time() + 360
    storyboard_ready = False
    while time.time() < deadline:
        latest = _snapshot(client, project_id)
        latest_project = latest["project"] if "project" in latest else latest
        slot = latest_project["assets"]["artifact_slots_by_id"].get(
            storyboard_slot,
        )
        if slot and slot.get("selected_version_id"):
            storyboard_ready = True
            break
        time.sleep(5)
    assert storyboard_ready, "storyboard artifact never materialized"
    print("REAL-STORYBOARD-OK")

    # 10. Rough-cut now succeeds: a real draft mp4 from the storyboard still.
    rough = client.get(
        f"/projects/{project_id}/timelines/{primary_id}/rough-cut",
    )
    assert rough.status_code == 200, rough.text
    assert rough.headers["content-type"].startswith("video/mp4")
    assert len(rough.content) > 5000
    print("REAL-ROUGH-CUT bytes:", len(rough.content))
