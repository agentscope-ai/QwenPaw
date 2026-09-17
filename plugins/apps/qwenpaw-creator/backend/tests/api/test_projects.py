# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient

from services.project_files.json_pointer import hash_json_value
from services.project_files.models import Project
from services.runtime_files import ProjectRuntimeSessionStore
from services.runtime_files.errors import RuntimeFileValidationError


def test_project_create_is_atomic_file_native_idempotent_and_has_no_goal(
    app,
    api_runtime_root,
):
    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            payload = {
                "clientRequestId": "project-create-request-1",
                "name": "雪夜公路",
                "description": "一条完整短片",
                "scenario": "short_drama",
                "aspectRatio": "16:9",
                "resolution": "720P",
                "contentType": None,
            }
            created = await client.post("/projects", json=payload)
            project_id = created.json()["projectId"]
            snapshot = await client.get(f"/projects/{project_id}/project")
            renamed = await client.patch(
                f"/projects/{project_id}/project",
                headers={"Idempotency-Key": "rename-after-create"},
                json={
                    "clientCommandId": "rename-after-create",
                    "editSessionId": "edit-create-test",
                    "baseGeneration": snapshot.json()["generation"],
                    "baseEtag": snapshot.json()["etag"],
                    "operations": [
                        {
                            "op": "replace",
                            "path": "/name",
                            "value": "创建后改名",
                            "expectedValueHash": hash_json_value("雪夜公路"),
                        },
                    ],
                },
            )
            replay = await client.post("/projects", json=payload)
            listed = await client.get("/projects")
            return created, renamed, replay, listed

    created, renamed, replay, listed = asyncio.run(scenario())
    assert created.status_code == 201
    assert renamed.status_code == 200
    assert replay.status_code == 201
    assert replay.content == created.content
    body = created.json()
    project_id = body["projectId"]
    assert body["header"]["name"] == "雪夜公路"
    assert [item["projectId"] for item in listed.json()["items"]] == [
        project_id,
    ]
    assert listed.json()["items"][0]["name"] == "创建后改名"

    project = Project.model_validate_json(
        (api_runtime_root / project_id / "project.json").read_text(
            encoding="utf-8",
        ),
    )
    assert project.name == "创建后改名"
    assert project.settings.aspect_ratio == "16:9"
    runtime = ProjectRuntimeSessionStore(api_runtime_root)
    session = runtime.get_project_session(project_id)
    conversations = runtime.list_conversations(project_id, session.session_id)
    assert session.session_id == body["creatorSessionId"]
    assert [item.conversation_id for item in conversations] == [
        body["conversationId"],
    ]
    assert session.active_goal_id is None
    assert (
        list(
            (api_runtime_root / project_id / "runtime" / "goals").glob(
                "*.json",
            ),
        )
        == []
    )
    assert not list(api_runtime_root.rglob("*.sqlite*"))


def test_project_create_can_atomically_bootstrap_initial_goal(
    app,
    api_runtime_root,
):
    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/projects",
                json={
                    "clientRequestId": "project-with-initial-goal",
                    "name": "Initial Goal",
                    "scenario": "general",
                    "aspectRatio": "9:16",
                    "resolution": "1080P",
                    "initialGoal": "  制作一条产品短片  ",
                },
            )

    created = asyncio.run(scenario())
    assert created.status_code == 201
    body = created.json()
    runtime = ProjectRuntimeSessionStore(api_runtime_root)
    session = runtime.get_project_session(body["projectId"])
    messages = runtime.list_messages(body["projectId"], session.session_id)
    goal = runtime.get_goal(body["projectId"], session.active_goal_id or "")
    assert len(messages) == 1
    assert messages[0].source == "initial_goal"
    assert messages[0].content_parts[0].text == "制作一条产品短片"
    assert goal.intent == "制作一条产品短片"
    assert goal.root_message_seq == messages[0].message_seq


def test_project_create_rejects_payload_drift_and_delete_is_idempotent(
    app,
    api_runtime_root,
):
    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            base = {
                "clientRequestId": "project-create-request-2",
                "name": "A",
                "scenario": "general",
                "aspectRatio": "16:9",
                "resolution": "720P",
            }
            created = await client.post("/projects", json=base)
            conflict = await client.post(
                "/projects",
                json={**base, "name": "B"},
            )
            delete_url = f"/projects/{created.json()['projectId']}"
            missing_key = await client.delete(delete_url)
            deleted = await client.delete(
                delete_url,
                headers={"Idempotency-Key": "delete-project-request"},
            )
            replay = await client.delete(
                delete_url,
                headers={"Idempotency-Key": "delete-project-request"},
            )
            listed = await client.get("/projects")
            return conflict, missing_key, deleted, replay, listed

    conflict, missing_key, deleted, replay, listed = asyncio.run(scenario())
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CONFLICT"
    assert missing_key.status_code == 422
    assert deleted.status_code == 204
    assert replay.status_code == 204
    assert listed.json()["items"] == []
    assert not list(api_runtime_root.rglob("*.sqlite*"))


def test_project_runtime_bootstrap_failure_never_publishes_half_project(
    app,
    api_runtime_root,
    monkeypatch,
):
    def fail_bootstrap(*_args, **_kwargs):
        raise RuntimeFileValidationError("injected bootstrap failure")

    monkeypatch.setattr(
        ProjectRuntimeSessionStore,
        "initialize_staged_project",
        fail_bootstrap,
    )

    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/projects",
                json={
                    "clientRequestId": "bootstrap-must-rollback",
                    "name": "Must not exist",
                    "scenario": "general",
                    "aspectRatio": "16:9",
                    "resolution": "720P",
                },
            )

    result = asyncio.run(scenario())
    assert result.status_code == 503
    assert result.json()["code"] == "STORAGE_INTEGRITY_ERROR"
    assert list(api_runtime_root.rglob("project.json")) == []


def test_removed_whole_project_put_is_404_and_not_registered(app):
    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            created = await client.post(
                "/projects",
                json={
                    "clientRequestId": "project-put-must-stay-removed",
                    "name": "No whole project PUT",
                    "scenario": "general",
                    "aspectRatio": "16:9",
                    "resolution": "720P",
                },
            )
            project_url = f"/projects/{created.json()['projectId']}"
            removed_put = await client.put(
                project_url,
                json={"name": "legacy"},
            )
            ordinary_method_mismatch = await client.patch(
                project_url,
                json={"name": "unsupported patch"},
            )
            return created, removed_put, ordinary_method_mismatch

    created, removed_put, ordinary_method_mismatch = asyncio.run(scenario())
    assert created.status_code == 201
    assert removed_put.status_code == 404
    assert ordinary_method_mismatch.status_code == 405
    assert "put" not in app.openapi()["paths"]["/projects/{project_id}"]


def test_project_create_rejects_duplicate_name(app, api_runtime_root):
    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            first = await client.post(
                "/projects",
                json={
                    "clientRequestId": "dup-name-first",
                    "name": "同名项目",
                    "scenario": "general",
                    "aspectRatio": "16:9",
                    "resolution": "720P",
                },
            )
            duplicate = await client.post(
                "/projects",
                json={
                    "clientRequestId": "dup-name-second",
                    "name": "同名项目",
                    "scenario": "general",
                    "aspectRatio": "16:9",
                    "resolution": "720P",
                },
            )
            return first, duplicate

    first, duplicate = asyncio.run(scenario())
    assert first.status_code == 201
    assert duplicate.status_code == 422
    assert duplicate.json()["code"] == "VALIDATION_ERROR"
    assert "同名项目" in duplicate.json()["message"]
