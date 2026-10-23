# -*- coding: utf-8 -*-
"""Script-only mode is a durable admission boundary, not an agent prompt."""
# pylint: disable=redefined-outer-name,protected-access
import asyncio

import pytest
from fastapi import FastAPI

from api.dependencies import creator_error_handler, project_file_services
from api.project_routes import router
from domain.errors import CreatorError, ValidationError
from services.file_agent_runtime.work_graph import derive_work_graph
from services.media_files.image_execution import FileImageExecutionService
from services.media_files.r2v_execution import FileR2VExecutionService
from services.project_files.commit import ProtectedFieldError
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project, TimelineElement
from services.project_files.production_stage import script_fingerprint

PID = "script-stage"
TID = "timeline:main"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    services = CreatorFileServices.create(tmp_path)
    project = Project.new(project_id=PID, name="Script")
    project.settings.production_stage = "script"
    project.timelines.items[TID].elements_by_id[
        "e"
    ] = TimelineElement.model_validate(
        {
            "element_id": "e",
            "span": {"start_tick": 0, "duration_tick": 4000},
            "location": {},
            "creation": {"type": "r2v", "narrative": "小猫推开窗，看见落雪。"},
        },
    )
    services.projects.create(project)
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(router)
    app.dependency_overrides[project_file_services] = lambda: services
    return app, services


@pytest.mark.parametrize(
    "checkpoints,authorization,review,expected_stage",
    [
        ("required", "required", "required", "script"),
        ("skip", "required", "required", "script"),
        ("skip", "allow_all", "required", "media"),
        ("skip", "allow_all", "auto_approve", "media"),
    ],
    ids=["full-confirmation", "cost-confirmation", "automatic", "yolo"],
)
def test_launch_stage_follows_saved_permission_mode(
    env,
    monkeypatch,
    run_scenario,
    checkpoints,
    authorization,
    review,
    expected_stage,
):
    from models import config

    app, services = env
    settings = {
        "creation_checkpoints": {"mode": checkpoints},
        "execution_authorization": {"mode": authorization},
        "media_review": {"mode": review},
    }
    monkeypatch.setattr(config, "_get_user_config", lambda: settings)

    async def scenario(client):
        payload = {
            "clientRequestId": "mode-derived-launch",
            "name": "小猫看雪",
            "scenario": "short_drama",
        }
        response = await client.post("/projects", json=payload)
        assert response.status_code == 201, response.text
        project_id = response.json()["projectId"]
        assert (
            services.projects.read(
                project_id,
            ).project.settings.production_stage
            == expected_stage
        )
        # Later launches read the latest saved mode. Existing projects
        # retain their stage, including any intentional pause by the user.
        settings["execution_authorization"]["mode"] = (
            "allow_all" if authorization == "required" else "required"
        )
        changed = await client.post(
            "/projects",
            json={
                **payload,
                "clientRequestId": "changed-mode-launch",
                "name": "小猫看雪-切换模式后",
            },
        )
        assert changed.status_code == 201, changed.text
        changed_project = services.projects.read(
            changed.json()["projectId"],
        ).project
        assert changed_project.settings.production_stage == (
            "media" if expected_stage == "script" else "script"
        )
        assert (
            services.projects.read(
                project_id,
            ).project.settings.production_stage
            == expected_stage
        )

    run_scenario(app, scenario)


@pytest.mark.parametrize("scenario_name", ["video_edit", "general"])
def test_confirmation_modes_do_not_add_script_stage_to_other_scenarios(
    env,
    monkeypatch,
    run_scenario,
    scenario_name,
):
    from models import config

    app, services = env
    monkeypatch.setattr(config, "_get_user_config", lambda: {})

    async def scenario(client):
        response = await client.post(
            "/projects",
            json={
                "clientRequestId": "non-script-launch",
                "name": "剪辑素材",
                "scenario": scenario_name,
            },
        )
        assert response.status_code == 201, response.text
        project = services.projects.read(response.json()["projectId"]).project
        assert project.settings.production_stage == "media"

    run_scenario(app, scenario)


@pytest.mark.parametrize(
    "checkpoints,authorization,review",
    [
        ("required", "required", "required"),
        ("skip", "required", "required"),
        ("skip", "allow_all", "required"),
        ("skip", "allow_all", "auto_approve"),
    ],
    ids=["full-confirmation", "cost-confirmation", "automatic", "yolo"],
)
def test_script_only_blocks_both_media_executors(
    env,
    monkeypatch,
    checkpoints,
    authorization,
    review,
):
    from models import config

    _, services = env
    monkeypatch.setattr(
        config,
        "_get_user_config",
        lambda: {
            "creation_checkpoints": {"mode": checkpoints},
            "execution_authorization": {"mode": authorization},
            "media_review": {"mode": review},
        },
    )
    graph = derive_work_graph(services.projects.read(PID).project)
    assert all(
        node.status.value == "gated"
        for node in graph.nodes
        if node.kind
        in {
            "storyboard",
            "video",
            "compose",
        }
    )
    image = FileImageExecutionService(services, provider=object())
    video = FileR2VExecutionService(services, provider=object())
    with pytest.raises(ValidationError, match="仅进行剧本"):
        asyncio.run(
            image.execute(
                project_id=PID,
                target_ref="element:e",
                arguments={},
                command="GENERATE_STORYBOARD_IMAGE",
                idempotency_key="no-image",
            ),
        )
    with pytest.raises(ValidationError, match="仅进行剧本"):
        asyncio.run(
            video.dispatch(
                project_id=PID,
                target_ref="element:e",
                arguments={},
                idempotency_key="no-video",
                start=False,
            ),
        )
    assert not image.executions.list_tasks(PID)


def test_confirmation_is_exact_and_script_edits_pause_again(env, run_scenario):
    app, services = env
    initial = services.projects.read(PID)

    async def scenario(client):
        response = await client.post(
            f"/projects/{PID}/production-stage",
            json={"stage": "media", "projectEtag": f'"{initial.etag}"'},
        )
        assert response.status_code == 200, response.text
        current = services.projects.read(PID)
        assert current.project.settings.production_stage == "media"
        assert (
            current.project.settings.script_approval_fingerprint
            == script_fingerprint(current.project)
        )
        candidate = current.project.model_dump(mode="json")
        creation = candidate["timelines"]["items"][TID]["elements_by_id"]["e"][
            "creation"
        ]
        creation["storyboard_prompt"] = "4格分镜图"
        saved = services.commits.commit(
            base=current,
            candidate=candidate,
            origin="frontend_edit",
        ).snapshot
        assert saved.project.settings.production_stage == "media"
        # Shot planning after confirmation is media-stage work: rewriting a
        # shot's narrative/intent or breaking down a new shot keeps production
        # enabled instead of bouncing the project back to the script stage.
        candidate = saved.project.model_dump(mode="json")
        elements = candidate["timelines"]["items"][TID]["elements_by_id"]
        elements["e"]["creation"]["narrative"] = "小猫关上窗，回到壁炉旁。"
        elements["e"]["creation"]["intent"] = "低角度仰拍，强调窗外雪光"
        elements["e2"] = {
            "element_id": "e2",
            "span": {"start_tick": 4000, "duration_tick": 4000},
            "location": {},
            "creation": {"type": "r2v", "narrative": "壁炉旁的猫打了个哈欠。"},
        }
        planned = services.commits.commit(
            base=saved,
            candidate=candidate,
            origin="agentdock_idle_goal",
        ).snapshot
        assert planned.project.settings.production_stage == "media"
        assert (
            planned.project.settings.script_approval_fingerprint
            == saved.project.settings.script_approval_fingerprint
        )
        candidate = planned.project.model_dump(mode="json")
        candidate["timelines"]["items"][TID]["description"] = "小猫决定出门看雪。"
        edited = services.commits.commit(
            base=planned,
            candidate=candidate,
            origin="frontend_edit",
        ).snapshot
        assert edited.project.settings.production_stage == "script"
        assert edited.project.settings.script_approval_fingerprint is None
        stale = await client.post(
            f"/projects/{PID}/production-stage",
            json={"stage": "media", "projectEtag": f'"{planned.etag}"'},
        )
        assert stale.status_code == 409
        assert (
            services.projects.read(PID).project.settings.production_stage
            == "script"
        )

    run_scenario(app, scenario)


def test_inline_script_can_be_confirmed_without_shot_breakdown(
    env,
    run_scenario,
):
    app, services = env
    initial = services.projects.read(PID)
    candidate = initial.project.model_dump(mode="json")
    timeline = candidate["timelines"]["items"][TID]
    timeline["elements_by_id"] = {}
    timeline["description"] = "小猫坐在窗边看雪，转身回到温暖的壁炉旁。"
    current = services.commits.commit(
        base=initial,
        candidate=candidate,
        origin="frontend_edit",
    ).snapshot

    async def scenario(client):
        response = await client.post(
            f"/projects/{PID}/production-stage",
            json={"stage": "media", "projectEtag": current.etag},
        )
        assert response.status_code == 200, response.text
        assert (
            services.projects.read(PID).project.settings.production_stage
            == "media"
        )

    run_scenario(app, scenario)


def test_agent_and_generic_patch_cannot_grant_media_permission(env):
    _, services = env
    snapshot = services.projects.read(PID)
    candidate = snapshot.project.model_dump(mode="json")
    candidate["settings"]["production_stage"] = "media"
    for origin in ("runtime_task", "frontend_edit"):
        with pytest.raises(ProtectedFieldError):
            services.commits.commit(
                base=snapshot,
                candidate=candidate,
                origin=origin,
            )
