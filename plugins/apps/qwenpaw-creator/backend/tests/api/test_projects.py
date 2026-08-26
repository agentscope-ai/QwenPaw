# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,use-implicit-booleaness-not-comparison
from __future__ import annotations

from services.project_files.models import Project
from services.runtime_files import ProjectRuntimeSessionStore
from services.runtime_files.errors import RuntimeFileValidationError


def _create_payload(request_id: str, name: str, **overrides) -> dict:
    payload = {
        "clientRequestId": request_id,
        "name": name,
        "scenario": "general",
        "aspectRatio": "16:9",
        "resolution": "720P",
    }
    payload.update(overrides)
    return payload


def test_project_create_is_atomic_file_native_and_has_no_goal(
    app,
    api_runtime_root,
    run_scenario,
):
    payload = _create_payload(
        "project-create-request-1",
        "雪夜公路",
        description="一条完整短片",
        scenario="short_drama",
        contentType=None,
    )

    async def scenario(client):
        created = await client.post("/projects", json=payload)
        listed = await client.get("/projects")
        return created, listed

    created, listed = run_scenario(app, scenario)
    assert created.status_code == 201
    body = created.json()
    project_id = body["projectId"]
    assert body["header"]["name"] == "雪夜公路"
    assert [item["projectId"] for item in listed.json()["items"]] == [
        project_id,
    ]

    project = Project.model_validate_json(
        (api_runtime_root / project_id / "project.json").read_text(
            encoding="utf-8",
        ),
    )
    assert project.name == "雪夜公路"
    assert project.settings.aspect_ratio == "16:9"
    runtime = ProjectRuntimeSessionStore(api_runtime_root)
    session = runtime.get_project_session(project_id)
    assert session.session_id == body["creatorSessionId"]
    assert session.active_goal_id is None
    assert not list(api_runtime_root.rglob("*.sqlite*"))


def test_project_create_rejects_payload_drift_and_delete_is_idempotent(
    app,
    api_runtime_root,
    run_scenario,
):
    base = _create_payload("project-create-request-2", "A")

    async def scenario(client):
        created = await client.post("/projects", json=base)
        conflict = await client.post("/projects", json={**base, "name": "B"})
        delete_url = f"/projects/{created.json()['projectId']}"
        missing_key = await client.delete(delete_url)
        headers = {"Idempotency-Key": "delete-project-request"}
        deleted = await client.delete(delete_url, headers=headers)
        replay = await client.delete(delete_url, headers=headers)
        listed = await client.get("/projects")
        return conflict, missing_key, deleted, replay, listed

    conflict, missing_key, deleted, replay, listed = run_scenario(
        app,
        scenario,
    )
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
    api_request,
):
    def fail_bootstrap(*_args, **_kwargs):
        raise RuntimeFileValidationError("injected bootstrap failure")

    monkeypatch.setattr(
        ProjectRuntimeSessionStore,
        "initialize_staged_project",
        fail_bootstrap,
    )

    result = api_request(
        app,
        "POST",
        "/projects",
        json=_create_payload("bootstrap-must-rollback", "Must not exist"),
    )
    assert result.status_code == 503
    assert result.json()["code"] == "STORAGE_INTEGRITY_ERROR"
    assert list(api_runtime_root.rglob("project.json")) == []


def test_project_copy_replays_one_durable_result_and_rejects_key_drift(
    app,
    api_runtime_root,
    run_scenario,
) -> None:
    async def scenario(client):
        source = await client.post(
            "/projects",
            json=_create_payload("copy-source-a", "Source A"),
        )
        other = await client.post(
            "/projects",
            json=_create_payload("copy-source-b", "Source B"),
        )
        source_id = source.json()["projectId"]
        other_id = other.json()["projectId"]
        copy_url = f"/projects/{source_id}/copy"
        headers = {"Idempotency-Key": "copy-retry-1"}
        first = await client.post(copy_url, headers=headers)
        replay = await client.post(copy_url, headers=headers)
        drift = await client.post(
            f"/projects/{other_id}/copy",
            headers=headers,
        )
        listed = await client.get("/projects")
        return source_id, other_id, first, replay, drift, listed

    (
        source_id,
        other_id,
        first,
        replay,
        drift,
        listed,
    ) = run_scenario(app, scenario)

    assert first.status_code == replay.status_code == 201
    assert replay.json() == first.json()
    assert drift.status_code == 409
    assert drift.json()["code"] == "CONFLICT"
    assert {item["projectId"] for item in listed.json()["items"]} == {
        source_id,
        other_id,
        first.json()["projectId"],
    }


def test_work_graph_get_dispatch_unknown_and_missing_project(
    app,
    api_runtime_root,
    run_scenario,
):
    async def scenario(client):
        created = await client.post(
            "/projects",
            json=_create_payload(
                "wg-project-1",
                "工作图",
                scenario="short_drama",
            ),
        )
        project_id = created.json()["projectId"]
        graph = await client.get(f"/projects/{project_id}/work-graph")
        missing_project = await client.get(
            "/projects/project-none/work-graph",
        )
        return project_id, graph, missing_project

    project_id, graph, missing_project = run_scenario(
        app,
        scenario,
    )
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["projectId"] == project_id
    assert payload["counts"]["total"] == 0
    assert payload["nodes"] == []
    assert missing_project.status_code == 404
    body = missing_project.json()
    assert "message" in body.get("error", body)


def test_project_routes_translate_store_addressing_failures(
    app,
    run_scenario,
) -> None:
    """Addressing failures keep their HTTP meaning at every route boundary.

    ProjectNotFound and InvalidProjectId are ProjectStoreError subclasses
    rather than CreatorError, so without an explicit translation a route
    either folds them into a 503 storage fault or lets the generic handler
    report a 500. work-graph translates the malformed id nowhere itself and
    so covers the global fallback.
    """

    expected = {
        "project-nonexistent-12345": (404, "NOT_FOUND"),
        "a%20b": (400, "BAD_REQUEST"),
    }

    async def scenario(client):
        pairs = []
        for project_id in expected:
            base = f"/projects/{project_id}"
            copy_key = {"Idempotency-Key": f"addr-copy-{project_id}"}
            export_key = {"Idempotency-Key": f"addr-export-{project_id}"}
            for response in (
                await client.get(f"{base}/recreate-params"),
                await client.post(f"{base}/copy", headers=copy_key),
                await client.get(f"{base}/export", headers=export_key),
                await client.get(f"{base}/work-graph"),
            ):
                pairs.append((project_id, response))
        return pairs

    for project_id, response in run_scenario(app, scenario):
        status_code, code = expected[project_id]
        assert response.status_code == status_code
        assert response.json()["code"] == code
