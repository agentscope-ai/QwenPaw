# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from services.project_files.json_pointer import hash_json_value
from services.project_files.models import Project
from services.runtime_files import ProjectRuntimeSessionStore
from services.runtime_files.errors import RuntimeFileValidationError


def _sqlite_files(root: Path) -> list[str]:
    """Return leaked sqlite files without racing deletion cleanup.

    Deleting a Project stages its tree as ``.deleted-<id>-<uuid>`` and removes
    it in the background, so a plain ``rglob`` can descend into that tree and
    fail when it disappears mid-walk. Prune the staging dirs and ignore walk
    errors: the assertion only cares that the store leaks no sqlite file.
    """

    found: list[str] = []
    for current, dirs, files in os.walk(root, onerror=lambda _error: None):
        dirs[:] = [name for name in dirs if not name.startswith(".deleted-")]
        found.extend(
            os.path.join(current, name) for name in files if ".sqlite" in name
        )
    return found


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
    assert not _sqlite_files(api_runtime_root)


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
    assert not _sqlite_files(api_runtime_root)


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


def test_project_list_degrades_corrupt_session_instead_of_500(
    app,
    api_runtime_root,
    run_scenario,
):
    """A single Project whose Session record fails the integrity check must
    surface as ``status: null`` in the listing instead of turning the whole
    ``GET /projects`` into a 500 (field incident: one stale test Project hid
    every other Project from the UI).
    """
    import json

    async def scenario(client):
        healthy = await client.post(
            "/projects",
            json=_create_payload("list-degrade-request-1", "健康项目"),
        )
        corrupt = await client.post(
            "/projects",
            json=_create_payload("list-degrade-request-2", "损坏项目"),
        )
        healthy_id = healthy.json()["projectId"]
        corrupt_id = corrupt.json()["projectId"]

        session_file = next(
            (api_runtime_root / corrupt_id / "runtime" / "sessions").glob(
                "*/session.json",
            ),
        )
        record = json.loads(session_file.read_text(encoding="utf-8"))
        record["project_id"] = healthy_id
        session_file.write_text(
            json.dumps(record, ensure_ascii=False),
            encoding="utf-8",
        )

        listed = await client.get("/projects")
        return healthy_id, corrupt_id, listed

    healthy_id, corrupt_id, listed = run_scenario(app, scenario)
    assert listed.status_code == 200
    by_id = {item["projectId"]: item for item in listed.json()["items"]}
    assert set(by_id) == {healthy_id, corrupt_id}
    assert by_id[corrupt_id]["status"] is None
    assert by_id[healthy_id]["status"] is not None


def test_parallel_creates_and_copies_never_hit_lock_timeouts(
    app,
    run_scenario,
):
    """Concurrent lifecycle writes must not serialize behind a global lock."""

    async def scenario(client):
        source = await client.post(
            "/projects",
            json=_create_payload("request-source", "Source"),
        )
        assert source.status_code == 201
        source_id = source.json()["projectId"]

        responses = await asyncio.gather(
            *[
                client.post(
                    "/projects",
                    json=_create_payload(f"request-{index}", f"Storm {index}"),
                )
                for index in range(6)
            ],
            *[
                client.post(
                    f"/projects/{source_id}/copy",
                    headers={"Idempotency-Key": f"copy-{index}"},
                )
                for index in range(2)
            ],
            *[client.get("/projects") for _ in range(10)],
        )
        listed = await client.get("/projects")
        return responses, listed

    responses, listed = run_scenario(app, scenario)
    for response in responses:
        assert response.status_code < 500, response.text
    creates, copies = responses[:6], responses[6:8]
    assert all(item.status_code == 201 for item in creates)
    assert all(item.status_code == 201 for item in copies)
    assert len({item.json()["projectId"] for item in copies}) == 2
    items = listed.json()["items"]
    names = {item["name"] for item in items}
    assert {"Source", "Source copy"} <= names
    assert {f"Storm {index}" for index in range(6)} <= names
    # Publishing outside the global name lock means simultaneous copies (and
    # simultaneous creates) can pick the same display name: the suffix scan
    # cannot see a sibling that has not published yet.  Names are never an
    # addressing key, and this buys a name lock that never spans the asset
    # tree copy — which used to cause routine 10s lock timeouts.
    copied = [item for item in items if item["name"].startswith("Source copy")]
    assert len({item["projectId"] for item in copied}) == 2


def test_snapshot_polling_during_edits_never_returns_busy(app, run_scenario):
    """Lock-free reads: polling stays 200 while edits keep committing."""

    async def scenario(client):
        created = await client.post(
            "/projects",
            json=_create_payload("request-edit", "Edited"),
        )
        assert created.status_code == 201
        project_url = f"/projects/{created.json()['projectId']}/project"

        async def edit_loop() -> list[int]:
            statuses: list[int] = []
            name = "Edited"
            for index in range(10):
                current = await client.get(project_url)
                assert current.status_code == 200
                snapshot = current.json()
                new_name = f"Edited {index}"
                response = await client.patch(
                    project_url,
                    json={
                        "clientCommandId": f"command-{index}",
                        "editSessionId": "edit",
                        "baseGeneration": snapshot["generation"],
                        "baseEtag": snapshot["etag"],
                        "operations": [
                            {
                                "op": "replace",
                                "path": "/name",
                                "value": new_name,
                                "expectedValueHash": hash_json_value(name),
                            },
                        ],
                    },
                )
                statuses.append(response.status_code)
                if response.status_code == 200:
                    name = new_name
            return statuses

        async def poll_loop() -> list[int]:
            return [
                (await client.get(project_url)).status_code for _ in range(60)
            ]

        edit_statuses, *poll_statuses = await asyncio.gather(
            edit_loop(),
            poll_loop(),
            poll_loop(),
            poll_loop(),
        )
        final = await client.get(project_url)
        return edit_statuses, poll_statuses, final

    edit_statuses, poll_statuses, final = run_scenario(app, scenario)
    assert edit_statuses == [200] * 10
    assert {status for loop in poll_statuses for status in loop} == {200}
    assert final.json()["project"]["name"] == "Edited 9"
