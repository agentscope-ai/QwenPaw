# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx


BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_DIR / "scripts" / "seed_demo_projects.py"
SPEC = importlib.util.spec_from_file_location(
    "seed_demo_projects",
    SCRIPT_PATH,
)
assert SPEC and SPEC.loader
seed = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = seed
SPEC.loader.exec_module(seed)


def _project_response() -> dict:
    return {
        "projectId": "project-demo",
        "creatorSessionId": "session-demo",
        "conversationId": "conversation-demo",
        "projectSnapshotId": "snapshot-demo",
        "header": {},
    }


def test_seed_uses_project_asset_and_message_http_boundaries() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/qwenpaw-creator/projects":
            return httpx.Response(201, json=_project_response())
        if (
            request.url.path
            == "/api/qwenpaw-creator/projects/project-demo/assets"
        ):
            return httpx.Response(
                202,
                json={
                    "assetId": "asset-demo",
                    "taskId": "task-demo",
                    "status": "SUCCEEDED",
                    "assetVersionId": "av-demo",
                },
            )
        if (
            request.url.path
            == "/api/qwenpaw-creator/projects/project-demo/messages"
        ):
            return httpx.Response(
                202,
                json={
                    "messageSeq": 1,
                    "eventSeq": 1,
                    "classification": "mutation_instruction",
                    "appendState": "appended",
                    "creatorSessionId": "session-demo",
                    "conversationId": "conversation-demo",
                },
            )
        return httpx.Response(404, json={"detail": "unexpected request"})

    with httpx.Client(
        base_url="http://creator.test/api/qwenpaw-creator",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = seed.seed_one(client, seed.DEMOS[0])

    assert result["projectId"] == "project-demo"
    assert result["assetVersionId"] == "av-demo"
    assert [request.method for request in requests] == ["POST", "POST", "POST"]
    assert [request.url.path for request in requests] == [
        "/api/qwenpaw-creator/projects",
        "/api/qwenpaw-creator/projects/project-demo/assets",
        "/api/qwenpaw-creator/projects/project-demo/messages",
    ]
    assert all(request.headers["idempotency-key"] for request in requests)
    project_body = json.loads(requests[0].content)
    assert (
        project_body["clientRequestId"]
        == requests[0].headers["idempotency-key"]
    )
    assert project_body["scenario"] == "short_drama"
    asset_body = json.loads(requests[1].content)
    assert asset_body["postIngestAction"] == "NONE"
    message_body = json.loads(requests[2].content)
    assert message_body["conversationId"] == "conversation-demo"
    assert message_body["assetVersionRefs"] == ["asset-version:av-demo"]
    assert message_body["content"] == [
        {"type": "text", "text": seed.DEMOS[0].goal},
    ]


def test_seed_polls_persisted_task_when_ingest_is_not_complete() -> None:
    task_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal task_reads
        if request.url.path == "/api/qwenpaw-creator/projects":
            return httpx.Response(201, json=_project_response())
        if request.url.path.endswith("/assets"):
            return httpx.Response(
                202,
                json={
                    "assetId": "asset-demo",
                    "taskId": "task-demo",
                    "status": "RUNNING",
                },
            )
        if request.url.path.endswith("/tasks/task-demo"):
            task_reads += 1
            return httpx.Response(
                200,
                json={
                    "id": "task-demo",
                    "status": "SUCCEEDED",
                    "result": {"items": [{"assetVersionId": "av-from-task"}]},
                },
            )
        if request.url.path.endswith("/messages"):
            body = json.loads(request.content)
            assert body["assetVersionRefs"] == ["asset-version:av-from-task"]
            return httpx.Response(
                202,
                json={
                    "messageSeq": 1,
                    "eventSeq": 1,
                    "classification": "mutation_instruction",
                    "appendState": "appended",
                    "creatorSessionId": "session-demo",
                    "conversationId": "conversation-demo",
                },
            )
        return httpx.Response(404)

    with httpx.Client(
        base_url="http://creator.test/api/qwenpaw-creator",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = seed.seed_one(client, seed.DEMOS[1], poll_interval_seconds=0)

    assert task_reads == 1
    assert result["assetVersionId"] == "av-from-task"


def test_seed_script_has_no_storage_write_boundary() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "data/projects" not in source
    assert "RuntimeDatabase" not in source
    assert "ContentStore" not in source
    assert "sqlalchemy" not in source
    assert ".write_" not in source
