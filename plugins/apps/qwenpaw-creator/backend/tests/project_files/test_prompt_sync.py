# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Minimal narrative synchronization checks using real project commits."""

import asyncio
import json

import pytest

from domain.errors import ConflictError
from pydantic import ValidationError
from models import config as model_config
from services.file_agent_runtime.model_client import (
    AgentModelTurn,
    CallbackAgentChatClient,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ElementLocation,
    Project,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
)
from services.prompt_sync_service import PromptSyncService

pytestmark = pytest.mark.unit
PID, TID, EID = "prompt-sync-test", "timeline:main", "scene-one"
SB = "输出9:16分镜图，9格3×3网格，每格内部9:16，清晰分隔边界，依次展示连续动作。"
VD = "[Image 1]提供分镜顺序，生成9:16连续6秒视频，不展示宫格。"
UPDATED = {
    "narrative": "女子左手将钥匙放入包内，轻声说：找到了。",
    "storyboardPrompt": SB + "女子左手将钥匙放入包内，声音意图为“找到了”，不在画面中写台词。",
    "videoPrompt": VD + "女子左手将钥匙放入包内，轻声说：找到了。",
}


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        model_config,
        "get_video_model_name",
        lambda: "wan3.0-video-prime",
    )
    monkeypatch.setattr(model_config, "get_video_backend", lambda: "wan")
    monkeypatch.setattr(
        model_config,
        "get_image_model_name",
        lambda: "qwen-image-3.0-pro",
    )
    services = CreatorFileServices.create(tmp_path)
    project = Project.new(project_id=PID, name="找钥匙")
    project.settings.aspect_ratio = "9:16"
    project.timelines.items[TID].elements_by_id[EID] = TimelineElement(
        element_id=EID,
        label="发现钥匙",
        location=ElementLocation(),
        span=TimelineSpan(start_tick=0, duration_tick=6000),
        creation=R2VCreation(
            narrative="女子拿起钥匙。",
            storyboard_prompt=SB,
            video_prompt=VD,
        ),
    )
    services.projects.create(project)
    return services


def edit(services, field, text):
    base = services.projects.read(PID)
    candidate = base.project.model_dump(mode="json")
    candidate["timelines"]["items"][TID]["elements_by_id"][EID]["creation"][
        field
    ] = text
    return services.commits.commit(
        base=base,
        candidate=candidate,
        origin="frontend_edit",
    )


def sync_service(services):
    async def complete(_messages, _tools):
        return AgentModelTurn(content=json.dumps(UPDATED, ensure_ascii=False))

    return PromptSyncService(
        services,
        client=CallbackAgentChatClient(complete),
    )


@pytest.mark.parametrize(
    "source, field, output",
    [
        ("currentPlan", "narrative", "narrative"),
        ("storyboardPrompt", "storyboard_prompt", "storyboardPrompt"),
        ("videoPrompt", "video_prompt", "videoPrompt"),
    ],
)
def test_sync_preserves_edited_source_and_commits_related_content(
    services,
    source,
    field,
    output,
):
    edit(services, field, UPDATED[output])
    service = sync_service(services)

    async def run():
        before = services.projects.read(PID)
        proposal = await service.propose(PID, TID, EID, source=source)
        assert services.projects.read(PID).etag == before.etag
        result = await service.accept(PID, TID, EID, proposal["proposalId"])
        current = service.status(PID, TID, EID)
        assert current["status"] == "current"
        assert {key: current[key] for key in UPDATED} == UPDATED
        assert result["generation"] == before.generation + 1
        assert (await service.accept(PID, TID, EID, proposal["proposalId"]))[
            "replayed"
        ]

    asyncio.run(run())


def test_stale_sync_cannot_overwrite_later_edit(services):
    edit(services, "narrative", UPDATED["narrative"])
    service = sync_service(services)

    async def run():
        proposal = await service.propose(PID, TID, EID)
        latest = edit(services, "video_prompt", VD + "用户新要求：保持安静。")
        with pytest.raises(ConflictError):
            await service.accept(PID, TID, EID, proposal["proposalId"])
        assert services.projects.read(PID).etag == latest.snapshot.etag

    asyncio.run(run())


def test_legacy_shots_can_be_read_but_cannot_be_written(services):
    creation = R2VCreation.model_validate(
        {
            "narrative": "当前片段内容",
            "shots": {
                "order": ["missing"],
                "items": {"bad": {"duration_seconds": -1}},
            },
            "min_dialogue_ratio": "invalid",
        },
    )
    assert creation == R2VCreation(narrative="当前片段内容")
    with pytest.raises(ValidationError, match="不再支持写入"):
        edit(services, "shots", {"items": {}, "order": []})


def test_storyboard_readiness_does_not_wait_for_video_rewrite(services):
    from fastapi import FastAPI
    import httpx
    from api.dependencies import project_file_services
    from api.prompt_sync_routes import router
    from services.project_files.prompt_sync import prompt_sync_status
    from services.file_agent_runtime.work_graph import derive_work_graph

    edit(services, "narrative", "女子把钥匙放入包内。")
    before = services.projects.read(PID).project
    assert (
        prompt_sync_status(before, TID, EID, stage="storyboard")["status"]
        == "needs_update"
    )
    edit(services, "storyboard_prompt", SB + "女子把钥匙放入包内。")
    project = services.projects.read(PID).project
    assert (
        prompt_sync_status(project, TID, EID, stage="storyboard")["status"]
        == "current"
    )
    assert (
        prompt_sync_status(project, TID, EID, stage="video")["status"]
        == "needs_update"
    )
    graph = derive_work_graph(project)
    assert (
        next(
            node for node in graph.nodes if node.kind == "storyboard"
        ).status.value
        == "ready"
    )

    # The actual workbench HTTP preflight must agree with the graph's
    # ready storyboard, while retaining the pending video/global sync.
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[project_file_services] = lambda: services

    async def preflight():
        path = f"/projects/{PID}/timelines/{TID}/elements/{EID}/prompt-sync"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            assert (await client.get(path)).json()["status"] != "current"
            for stage, expected in (
                ("storyboard", "current"),
                ("video", "needs_update"),
            ):
                response = await client.get(path, params={"stage": stage})
                assert response.status_code == 200
                assert response.json()["status"] == expected
            assert (
                await client.get(path, params={"stage": "invalid"})
            ).status_code == 422

    asyncio.run(preflight())

    edit(services, "video_prompt", VD + "摄影机缓慢推进。")
    project = services.projects.read(PID).project
    assert all(
        prompt_sync_status(project, TID, EID, stage=stage)["status"]
        == "current"
        for stage in ("storyboard", "video")
    )
    edit(services, "storyboard_prompt", SB + "结束时女子转身离开。")
    project = services.projects.read(PID).project
    assert (
        prompt_sync_status(project, TID, EID, stage="storyboard")["status"]
        == "current"
    )
    assert (
        prompt_sync_status(project, TID, EID, stage="video")["status"]
        == "needs_update"
    )


def test_all_authored_bodies_confirm_without_discarded_model_call(services):
    for field, key in (
        ("narrative", "narrative"),
        ("storyboard_prompt", "storyboardPrompt"),
        ("video_prompt", "videoPrompt"),
    ):
        edit(services, field, UPDATED[key])

    async def forbidden(_messages, _tools):
        raise AssertionError(
            "Nothing needs generating when all bodies are authoritative",
        )

    service = PromptSyncService(
        services,
        client=CallbackAgentChatClient(forbidden),
    )

    async def run():
        proposal = await service.propose(PID, TID, EID, source="mixed")
        await service.accept(PID, TID, EID, proposal["proposalId"])
        assert service.status(PID, TID, EID)["status"] == "current"

    asyncio.run(run())


def test_first_prompt_pair_publishes_with_existing_narrative(services):
    """Incremental creation is not an edit of a previously authored prompt."""
    first_id = "first-publication"
    base = services.projects.read(PID)
    candidate = base.project.model_dump(mode="json")
    element = candidate["timelines"]["items"][TID]["elements_by_id"][EID]
    first = json.loads(json.dumps(element))
    first["element_id"] = first_id
    first["creation"].update(storyboard_prompt="", video_prompt="")
    candidate["timelines"]["items"][TID]["elements_by_id"][first_id] = first
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin="agentdock_idle_goal",
    )

    base = services.projects.read(PID)
    candidate = base.project.model_dump(mode="json")
    creation = candidate["timelines"]["items"][TID]["elements_by_id"][
        first_id
    ]["creation"]
    creation.update(storyboard_prompt=SB, video_prompt=VD)
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin="agentdock_idle_goal",
    )
    service = sync_service(services)
    assert service.status(PID, TID, first_id)["status"] == "current"

    # An actual subsequent prompt edit still needs reconciliation.
    base = services.projects.read(PID)
    candidate = base.project.model_dump(mode="json")
    candidate["timelines"]["items"][TID]["elements_by_id"][first_id][
        "creation"
    ]["video_prompt"] = UPDATED["videoPrompt"]
    services.commits.commit(
        base=base,
        candidate=candidate,
        origin="frontend_edit",
    )
    current = service.status(PID, TID, first_id)
    assert current["status"] == "needs_confirmation"
    assert current["changedSources"] == ["videoPrompt"]

    # Clearing old prompts cannot disguise a later rewrite as first creation.
    for fields in (
        {"storyboard_prompt": "", "video_prompt": ""},
        {
            "storyboard_prompt": UPDATED["storyboardPrompt"],
            "video_prompt": UPDATED["videoPrompt"],
        },
    ):
        base = services.projects.read(PID)
        candidate = base.project.model_dump(mode="json")
        candidate["timelines"]["items"][TID]["elements_by_id"][first_id][
            "creation"
        ].update(fields)
        services.commits.commit(
            base=base,
            candidate=candidate,
            origin="frontend_edit",
        )
    assert service.status(PID, TID, first_id)["status"] == "needs_confirmation"
