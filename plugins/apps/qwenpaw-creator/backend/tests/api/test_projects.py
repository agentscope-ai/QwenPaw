# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

from services.project_files.facade import creator_file_services
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


def test_project_create_keeps_the_subtitle_policy_off_unless_asked(
    app,
    api_runtime_root,
    run_scenario,
):
    """No subtitle is the default on every side of the wire.

    The model default, the create route's ``or "off"`` and the launch form
    must agree; a silent drift would start burning captions into cuts that
    users never asked for.
    """

    async def scenario(client):
        omitted = await client.post(
            "/projects",
            json=_create_payload("policy-omitted", "默认策略"),
        )
        explicit_off = await client.post(
            "/projects",
            json=_create_payload(
                "policy-explicit-off",
                "显式关闭",
                subtitlePolicy="off",
            ),
        )
        auto = await client.post(
            "/projects",
            json=_create_payload(
                "policy-auto",
                "智能策略",
                subtitlePolicy="auto",
            ),
        )
        return omitted, explicit_off, auto

    omitted, explicit_off, auto = run_scenario(app, scenario)

    def policy(response) -> str:
        project = Project.model_validate_json(
            (
                api_runtime_root
                / response.json()["projectId"]
                / "project.json"
            ).read_text(encoding="utf-8"),
        )
        return project.settings.subtitle_policy

    assert policy(omitted) == "off"
    assert policy(explicit_off) == "off"
    assert policy(auto) == "auto"


def test_project_create_persists_the_subtitle_template_pack(
    app,
    api_runtime_root,
    run_scenario,
):
    """The JianYing-like style pack rides the create request end to end."""

    async def scenario(client):
        packed = await client.post(
            "/projects",
            json=_create_payload(
                "pack-cinematic",
                "电影叙事包",
                subtitlePolicy="auto",
                subtitleTemplate="cinematic",
            ),
        )
        plain = await client.post(
            "/projects",
            json=_create_payload("pack-none", "智能推荐"),
        )
        return packed, plain

    packed, plain = run_scenario(app, scenario)

    def template(response) -> str | None:
        project = Project.model_validate_json(
            (
                api_runtime_root
                / response.json()["projectId"]
                / "project.json"
            ).read_text(encoding="utf-8"),
        )
        return project.settings.subtitle_template

    assert template(packed) == "cinematic"
    assert template(plain) is None


def test_project_create_persists_the_subtitle_style_overrides(
    app,
    api_runtime_root,
    run_scenario,
):
    """Colour / font-size / outline / plate overrides ride the create."""

    async def scenario(client):
        styled = await client.post(
            "/projects",
            json=_create_payload(
                "style-gold",
                "金色大字幕",
                subtitlePolicy="auto",
                subtitleStyle={
                    "color": "#FFE066",
                    "fontScale": 1.25,
                    "strokeScale": 0,
                    "backgroundOpacity": 0.3,
                },
            ),
        )
        plain = await client.post(
            "/projects",
            json=_create_payload("style-none", "默认样式"),
        )
        return styled, plain

    styled, plain = run_scenario(app, scenario)

    def style(response):
        project = Project.model_validate_json(
            (
                api_runtime_root
                / response.json()["projectId"]
                / "project.json"
            ).read_text(encoding="utf-8"),
        )
        return project.settings.subtitle_style

    assert style(plain) is None
    persisted = style(styled)
    assert persisted is not None
    assert persisted.color == "#FFE066"
    assert persisted.font_scale == 1.25
    assert persisted.stroke_scale == 0.0
    assert persisted.background_opacity == 0.3
    # The header mirrors the setting in camelCase for the UI contract.
    header = styled.json()["header"]["subtitleStyle"]
    assert header == {
        "color": "#FFE066",
        "fontScale": 1.25,
        "strokeScale": 0.0,
        "backgroundOpacity": 0.3,
        "fontFamily": None,
    }


def test_project_create_persists_the_subtitle_animation_default(
    app,
    api_runtime_root,
    run_scenario,
):
    """The creation form's entrance / exit / loop ride the create request."""

    async def scenario(client):
        moved = await client.post(
            "/projects",
            json=_create_payload(
                "motion-slide",
                "滑入字幕",
                subtitlePolicy="auto",
                subtitleAnimation={"entrance": "slide", "loop": True},
            ),
        )
        plain = await client.post(
            "/projects",
            json=_create_payload("motion-none", "跟随风格包"),
        )
        return moved, plain

    moved, plain = run_scenario(app, scenario)

    def animation(response):
        project = Project.model_validate_json(
            (
                api_runtime_root
                / response.json()["projectId"]
                / "project.json"
            ).read_text(encoding="utf-8"),
        )
        return project.settings.subtitle_animation

    assert animation(plain) is None
    persisted = animation(moved)
    assert persisted is not None
    assert persisted.entrance == "slide"
    assert persisted.exit is None
    assert persisted.loop is True


def _overlay_element(
    element_id: str,
    *,
    text: str,
    vibe: str = "chill",
    caption_role: str | None = None,
    enabled: bool = True,
    prompt: str = "",
) -> dict:
    creation = {
        "type": "overlay",
        "text": text,
        "vibe": vibe,
        "prompt": prompt,
    }
    if caption_role is not None:
        creation["caption_role"] = caption_role
    return {
        "element_id": element_id,
        "label": element_id,
        "enabled": enabled,
        "span": {"start_tick": 0, "duration_tick": 2000},
        "creation": creation,
        # Every visual Element needs a box; this one sits inside the caption
        # safe area so the toggle test is not accidentally about geometry.
        "location": {
            "x": 0.5,
            "y": 0.86,
            "width": 0.8,
            "height": 0.18,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
        },
    }


def test_subtitle_toggle_follows_the_subtitle_definition(
    app,
    api_runtime_root,
    run_scenario,
):
    """The batch switch claims subtitles and nothing else.

    A pet-OS bubble carries no caption_role on purpose, so it keeps its
    dedicated layout and must stay visible when the user hides subtitles.
    The final cut bakes captions in, so even a switch that changes nothing
    still refreshes the render instead of leaving the old burn-in standing.
    """

    async def scenario(client):
        created = await client.post(
            "/projects",
            json=_create_payload(
                "toggle-project",
                "字幕开关",
                contentType="pet_video",
            ),
        )
        project_id = created.json()["projectId"]
        services = creator_file_services(api_runtime_root)
        snapshot = services.projects.read(project_id)
        candidate = snapshot.project.model_dump(mode="json")
        candidate["timelines"]["items"]["timeline:main"]["elements_by_id"] = {
            "caption": _overlay_element(
                "caption",
                text="这句要烧进成片",
                caption_role="dialogue",
            ),
            "bubble": _overlay_element("bubble", text="本喵要发光"),
            "decoration": _overlay_element(
                "decoration",
                text="",
                prompt="呼应台词的装饰动效",
            ),
        }
        # One selected final render, not stale, so the switch's only way to
        # reach the cut is the impact pass.
        checksum = hashlib.sha256(b"final").hexdigest()
        root = api_runtime_root / project_id
        (root / "assets").mkdir(exist_ok=True)
        (root / "assets/final.mp4").write_bytes(b"final")
        candidate["assets"]["files_by_id"]["final-file"] = {
            "file_id": "final-file",
            "kind": "artifact_payload",
            "relative_uri": "assets/final.mp4",
            "sha256": checksum,
            "size_bytes": 5,
            "media_type": "video/mp4",
            "created_at": "2026-09-17T00:00:00Z",
        }
        candidate["assets"]["artifact_slots_by_id"][
            "timeline:timeline:main:render"
        ] = {
            "slot_id": "timeline:timeline:main:render",
            "kind": "final_video",
            "owner_ref": "timeline:timeline:main",
            "version_ids": ["final"],
            "selected_version_id": "final",
        }
        candidate["assets"]["artifact_versions_by_id"]["final"] = {
            "version_id": "final",
            "name": "final",
            "slot_id": "timeline:timeline:main:render",
            "kind": "final_video",
            "owner_ref": "timeline:timeline:main",
            "file_id": "final-file",
            "checksum": checksum,
            "based_on_generation": 0,
            "stale": False,
            "stale_reason": None,
            "created_at": "2026-09-17T00:00:00Z",
        }
        await services.commit_candidate(
            base=snapshot,
            candidate=candidate,
            origin="frontend_edit",
            review_policy="auto_fix",
        )
        url = f"/projects/{project_id}/subtitles/toggle"
        no_op = await client.patch(url, json={"enabled": True})
        hidden = await client.patch(url, json={"enabled": False})
        return project_id, no_op, hidden

    project_id, no_op, hidden = run_scenario(app, scenario)
    project_path = api_runtime_root / project_id / "project.json"

    def stored() -> Project:
        return Project.model_validate_json(
            project_path.read_text(encoding="utf-8"),
        )

    # Every subtitle is already enabled, so this switch changes no Element.
    assert no_op.status_code == 200
    assert no_op.json()["toggled"] == 0
    assert stored().assets.artifact_versions_by_id["final"].stale is True

    assert hidden.status_code == 200
    assert hidden.json()["toggled"] == 1
    elements = stored().timelines.items["timeline:main"].elements_by_id
    assert elements["caption"].enabled is False
    # The bubble and the text-free decoration are not subtitles.
    assert elements["bubble"].enabled is True
    assert elements["decoration"].enabled is True
    # A switch is not a policy edit.
    assert stored().settings.subtitle_policy == "off"


def test_subtitle_style_patch_redraws_prompts_and_documents(
    app,
    api_runtime_root,
    run_scenario,
):
    """Picking a style pack must reach settings, 动效描述 and the pixels.

    One call owns the whole triangle: the project setting, the canonical
    sentence in every subtitle's description (authored wording kept, never
    overwritten) and the deterministic caption document the renderer draws.
    A free-form design belongs to the model that made it and stays put.
    """

    async def scenario(client):
        from services.media_files.motion_design import build_caption_document
        from services.project_files.models import ElementLocation

        created = await client.post(
            "/projects",
            json=_create_payload(
                "style-pack",
                "风格包项目",
                subtitlePolicy="auto",
            ),
        )
        project_id = created.json()["projectId"]
        services = creator_file_services(api_runtime_root)
        snapshot = services.projects.read(project_id)
        candidate = snapshot.project.model_dump(mode="json")
        free_form = _overlay_element(
            "free",
            text="花字保留自己的设计",
            caption_role="narration",
        )
        free_form["creation"]["motion"] = {
            "format": "html_css",
            "html": (
                '<html><body><div class="card">'
                + "x" * 64
                + "</div></body></html>"
            ),
            "motif": "custom",
            "loop": False,
        }
        authored = _overlay_element(
            "authored",
            text="用户自己写过的字幕",
            caption_role="dialogue",
            prompt="手写意图：这里要安静一点",
        )
        # The design pass already drew this caption from the template with no
        # pack selected, which is exactly the document a later pick rewrites.
        caption = _overlay_element(
            "caption",
            text="这条要跟着风格包变",
            caption_role="dialogue",
        )
        drawn, _concept = build_caption_document(
            text="这条要跟着风格包变",
            location=ElementLocation(
                x=0.5,
                y=0.86,
                width=0.8,
                height=0.18,
                anchor_x=0.5,
                anchor_y=0.5,
            ),
            pack_id=None,
            style=None,
            animation=None,
        )
        caption["creation"]["motion"] = drawn.model_dump(mode="json")
        candidate["timelines"]["items"]["timeline:main"]["elements_by_id"] = {
            "caption": caption,
            "authored": authored,
            "free": free_form,
            "bubble": _overlay_element("bubble", text="本喵不属字幕"),
        }
        await services.commit_candidate(
            base=snapshot,
            candidate=candidate,
            origin="frontend_edit",
            review_policy="auto_fix",
        )

        def durable() -> str:
            """The committed ``project.json`` text at this exact step."""

            return (
                api_runtime_root / project_id / "project.json"
            ).read_text(encoding="utf-8")

        unknown = await client.patch(
            f"/projects/{project_id}/subtitles/style",
            json={"subtitleTemplate": "nope"},
        )
        # A style pack is a project-wide promise: addressing it at single
        # captions would leave the rest describing the previous look.
        mixed = await client.patch(
            f"/projects/{project_id}/subtitles/style",
            json={"subtitleTemplate": "clean_talk", "elementIds": ["caption"]},
        )
        picked = await client.patch(
            f"/projects/{project_id}/subtitles/style",
            json={
                "subtitleTemplate": "variety_pop",
                "subtitleStyle": {
                    "color": "#FFE066",
                    "fontScale": 1.2,
                    "backgroundOpacity": 0.4,
                },
            },
        )
        after_pick = durable()
        # An animation pick aimed at a caption this pipeline never drew has to
        # be reported, not quietly swallowed behind a success message.
        declined = await client.patch(
            f"/projects/{project_id}/subtitles/style",
            json={
                "elementIds": ["free"],
                "animation": {"entrance": "type_on"},
            },
        )
        after_decline = durable()
        # Element-scoped animation pick: only the addressed caption moves.
        moved = await client.patch(
            f"/projects/{project_id}/subtitles/style",
            json={
                "elementIds": ["caption"],
                "animation": {"entrance": "slide", "loop": False},
            },
        )
        after_move = durable()
        # Going back to smart recommend clears settings and wording alike.
        cleared = await client.patch(
            f"/projects/{project_id}/subtitles/style",
            json={"subtitleTemplate": None, "subtitleStyle": None},
        )
        after_clear = durable()
        return (
            project_id,
            unknown,
            mixed,
            picked,
            declined,
            moved,
            cleared,
            (after_pick, after_decline, after_move, after_clear),
        )

    (
        project_id,
        unknown,
        mixed,
        picked,
        declined,
        moved,
        cleared,
        (after_pick, after_decline, after_move, after_clear),
    ) = run_scenario(app, scenario)
    root = api_runtime_root / project_id

    def stored(text: str) -> Project:
        return Project.model_validate_json(text)

    def document_html(project: Project, motion) -> str:
        """Read one caption document back the way the renderer does."""

        assert motion is not None
        indexed = project.assets.files_by_id[motion.html_file_id]
        return (root / indexed.relative_uri).read_text(encoding="utf-8")

    # An unknown pack is a domain validation error, not a silent fallback.
    assert unknown.status_code == 422
    assert "未知的字幕风格包" in unknown.text
    # A pack cannot be addressed at single captions.
    assert mixed.status_code == 422
    assert "elementIds" in mixed.text
    assert picked.status_code == 200, picked.text
    assert picked.json()["subtitleTemplate"] == "variety_pop"
    # The UI echoes this sentence instead of keeping its own copy of it.
    assert picked.json()["styleLine"].startswith("综艺花字：")
    assert "文字颜色" in picked.json()["styleLine"]
    picked_project = stored(after_pick)
    settings = picked_project.settings
    assert settings.subtitle_template == "variety_pop"
    assert settings.subtitle_style is not None
    assert settings.subtitle_style.color == "#FFE066"
    assert settings.subtitle_style.background_opacity == 0.4
    elements = picked_project.timelines.items["timeline:main"].elements_by_id

    # 1) The empty description got exactly the sentence the renderer obeys.
    caption = elements["caption"].creation
    assert caption.prompt.startswith("【字幕风格：综艺花字】综艺花字：")
    assert "用户覆盖样式：文字颜色 #FFE066" in caption.prompt
    # 综艺花字 draws no background block, so the plate pick is never
    # promised in wording the pixels cannot keep: it re-inks a block, it
    # never adds one.
    assert "底板" not in caption.prompt
    assert "入场 弹入／出场 淡出／循环 开" in caption.prompt
    assert caption.motion.motif == "caption_card"
    html = document_html(picked_project, caption.motion)
    # The renderer normalises colours to lower case.
    assert "#ffe066" in html.lower()
    assert caption.motion.entrance == "pop"
    assert 'data-caption-entrance="pop"' in html
    assert "caption_animation=pop/soft_fade/1" in caption.motion.design_notes
    # 2) An authored description keeps its own text under the new clause.
    authored_prompt = elements["authored"].creation.prompt
    assert authored_prompt.endswith("手写意图：这里要安静一点")
    assert authored_prompt.startswith("【字幕风格：综艺花字】")
    # A caption without a document burns the pack fallback, so the motion the
    # fallback plays belongs in its description too.
    assert "入场 弹入／出场 淡出／循环 开" in authored_prompt
    # 3) A free-form design is never flattened by a project style switch.
    free_motion = elements["free"].creation.motion
    assert free_motion is not None and free_motion.motif == "custom"
    assert "x" * 64 in (free_motion.html or "")
    # ...and its description is not promised a look its pixels never keep.
    assert elements["free"].creation.prompt == ""
    # 4) The pet-OS bubble is not a subtitle.
    assert elements["bubble"].creation.motion is None

    # 4b) A motion pick aimed at an independently designed caption reports
    # that nothing moved instead of claiming a silent success.
    assert declined.status_code == 200, declined.text
    assert declined.json()["skippedNonTemplate"] == 1
    assert declined.json()["redrawnDocuments"] == 0
    declined_elements = stored(after_decline).timelines.items[
        "timeline:main"
    ].elements_by_id
    assert declined_elements["free"].creation.prompt == ""
    assert "x" * 64 in (declined_elements["free"].creation.motion.html or "")

    # 5) An element-scoped animation choice rewrites just that caption.
    assert moved.status_code == 200, moved.text
    assert moved.json()["redrawnDocuments"] == 1
    assert moved.json()["syncedPrompts"] == 1
    moved_project = stored(after_move)
    moved_elements = moved_project.timelines.items[
        "timeline:main"
    ].elements_by_id
    moved_caption = moved_elements["caption"].creation
    assert "入场 滑入／出场 淡出／循环 关" in moved_caption.prompt
    assert moved_caption.motion.entrance == "slide"
    assert 'data-caption-loop="0"' in document_html(
        moved_project,
        moved_caption.motion,
    )
    # Untouched elements keep the wording the pack switch wrote for them.
    assert moved_elements["authored"].creation.prompt == authored_prompt

    # 6) Switching back to smart recommend leaves no style wording behind.
    assert cleared.status_code == 200, cleared.text
    back = stored(after_clear)
    assert back.settings.subtitle_template is None
    assert back.settings.subtitle_style is None
    back_elements = back.timelines.items["timeline:main"].elements_by_id
    assert back_elements["caption"].creation.prompt == ""
    assert back_elements["authored"].creation.prompt == "手写意图：这里要安静一点"
    back_motion = back_elements["caption"].creation.motion
    assert back_motion.entrance == "soft_fade"
    assert "caption_animation=soft_fade/none/0" in back_motion.design_notes


def test_subtitle_style_patch_keeps_the_caption_box_legal(
    app,
    api_runtime_root,
    run_scenario,
):
    """The style route must not freeze an unusable caption box.

    A document the route bakes carries the same stamp as a designed one, which
    tells the next design pass this caption is settled.  Without the safe-area
    gate here, a narrow tall box would be locked into the final cut (CJK copy
    turns vertical) and nothing would ever repair it.  An unknown pack is also
    refused on the way in, so a project cannot store a setting every reader
    interprets as smart recommend.
    """

    async def scenario(client):
        created = await client.post(
            "/projects",
            json=_create_payload(
                "narrow-caption",
                "窄框字幕",
                subtitlePolicy="auto",
            ),
        )
        project_id = created.json()["projectId"]
        refused = await client.post(
            "/projects",
            json=_create_payload(
                "unknown-pack",
                "未知风格包",
                subtitleTemplate="vaporware",
            ),
        )
        services = creator_file_services(api_runtime_root)
        snapshot = services.projects.read(project_id)
        candidate = snapshot.project.model_dump(mode="json")
        narrow = _overlay_element(
            "narrow",
            text="这条字幕的位置框太窄太高",
            caption_role="dialogue",
        )
        narrow["location"] = {
            "x": 0.9,
            "y": 0.3,
            "width": 0.12,
            "height": 0.4,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
        }
        candidate["timelines"]["items"]["timeline:main"]["elements_by_id"] = {
            "narrow": narrow,
        }
        await services.commit_candidate(
            base=snapshot,
            candidate=candidate,
            origin="frontend_edit",
            review_policy="auto_fix",
        )
        # A pack alone leaves an undesigned caption to its design pass; the
        # element-scoped motion pick is what bakes a document right here.
        await client.patch(
            f"/projects/{project_id}/subtitles/style",
            json={"subtitleTemplate": "variety_pop"},
        )
        baked = await client.patch(
            f"/projects/{project_id}/subtitles/style",
            json={
                "elementIds": ["narrow"],
                "animation": {"entrance": "pop"},
            },
        )
        return (
            project_id,
            refused,
            baked,
            (api_runtime_root / project_id / "project.json").read_text(
                encoding="utf-8",
            ),
        )

    project_id, refused, baked, durable = run_scenario(app, scenario)
    assert refused.status_code == 422, refused.text
    assert "未知的字幕风格包" in refused.text
    assert baked.status_code == 200, baked.text
    assert baked.json()["redrawnDocuments"] == 1

    element = (
        Project.model_validate_json(durable)
        .timelines.items["timeline:main"]
        .elements_by_id["narrow"]
    )
    # The route retreated to the dialogue preset — the box the template was
    # measured for — and persisted it instead of painting into the illegal one.
    assert element.location.width == 0.8
    assert element.location.height == 0.18
    from services.media_files.motion_templates import (
        caption_box_out_of_safe_area,
    )

    # The preset is bottom-anchored, so its edges (not its centre) are what the
    # safe area judges.
    assert not caption_box_out_of_safe_area(
        element.location.model_dump(mode="json"),
    )
    assert element.creation.motion is not None
    assert element.creation.motion.entrance == "pop"
    assert "caption_style=variety_pop" in element.creation.motion.design_notes
