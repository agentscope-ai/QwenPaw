# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI

from api.dependencies import creator_error_handler, project_file_services
from api.file_execution_routes import router as execution_router
from api.file_session_routes import router as session_router
from domain.enums import SpecialistRole, TaskKind, TaskStatus
from domain.errors import CreatorError
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files.execution_models import (
    ExecutionAuthorizationRecord,
    ExecutionAuthorizationStatus,
    SpecialistRunRecord,
    TaskRecord,
)
from services.runtime_files.execution_store import ProjectExecutionStore
from services.runtime_files.session_store import ProjectRuntimeSessionStore


def _run(coro):
    return asyncio.run(coro)


def _app(tmp_path):
    services = CreatorFileServices.create(tmp_path.resolve())
    snapshot = services.projects.create(
        Project.new(project_id="project-1", name="One"),
    )
    sessions = ProjectRuntimeSessionStore(services.root)
    bootstrap = sessions.create_project_runtime(
        "project-1",
        session_id="session-1",
        conversation_id="conversation-1",
    )
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(session_router)
    app.include_router(execution_router)
    app.dependency_overrides[project_file_services] = lambda: services
    return app, services, snapshot, bootstrap


def test_file_session_message_is_idempotent_and_visible(tmp_path) -> None:
    app, services, _snapshot, bootstrap = _app(tmp_path)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            session = await client.get("/projects/project-1/session")
            first = await client.post(
                "/projects/project-1/messages",
                headers={"Idempotency-Key": "message-1"},
                json={
                    "clientMessageId": "message-1",
                    "conversationId": "conversation-1",
                    "message": "完善故事结构",
                },
            )
            replay = await client.post(
                "/projects/project-1/messages",
                headers={"Idempotency-Key": "message-1"},
                json={
                    "clientMessageId": "message-1",
                    "conversationId": "conversation-1",
                    "message": "完善故事结构",
                },
            )
            messages = await client.get(
                "/projects/project-1/conversations/conversation-1/messages",
            )
        return session, first, replay, messages

    session, first, replay, messages = _run(scenario())
    assert session.status_code == 200
    assert session.json()["session"]["id"] == bootstrap.session.session_id
    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.headers["x-idempotent-replay"] == "true"
    assert replay.json() == first.json()
    assert [item["messageSeq"] for item in messages.json()["items"]] == [1]

    runtime = ProjectRuntimeSessionStore(services.root)
    refreshed = runtime.get_project_session("project-1")
    assert refreshed.active_goal_id is not None
    assert refreshed.last_event_seq == 1


def test_interrupt_is_persisted_before_process_local_cancellation(
    tmp_path,
    monkeypatch,
) -> None:
    app, services, snapshot, _bootstrap = _app(tmp_path)
    observed_statuses: list[str] = []
    executions = ProjectExecutionStore(services.root)
    executions.create_task(
        TaskRecord(
            task_id="task-stop-1",
            project_id="project-1",
            kind=TaskKind.COMPOSE,
            request_fingerprint="stop-task-fingerprint",
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            input_refs=["project:story"],
        ),
    )

    async def observe_interrupt(project_id, *, superseded, reason):
        del superseded, reason
        session = services.sessions.get_project_session(project_id)
        observed_statuses.append(session.status.value)
        services.sessions.mark_messages_consumed(
            project_id,
            session.session_id,
            through_seq=session.last_message_seq,
        )
        services.sessions.set_session_status(
            project_id,
            session.session_id,
            "CANCELLED",
        )
        return True

    monkeypatch.setattr(
        "api.file_session_routes.interrupt_creator_agent_runtime",
        observe_interrupt,
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/projects/project-1/interrupt",
                headers={"Idempotency-Key": "interrupt-1"},
                json={},
            )

    response = _run(scenario())
    assert response.status_code == 202
    assert observed_statuses == ["INTERRUPT_REQUESTED"]
    assert response.json()["status"] == "CANCELLED"
    cancelled_task = executions.get_task("project-1", "task-stop-1")
    assert cancelled_task.status is TaskStatus.CANCELLED
    assert cancelled_task.error == {
        "code": "USER_CANCELLED",
        "message": "用户停止了当前项目的所有 Agent 活动",
    }


def test_file_conversation_create_replays_by_idempotency_key(tmp_path) -> None:
    app, _services, _snapshot, _bootstrap = _app(tmp_path)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.post(
                "/projects/project-1/conversations",
                headers={"Idempotency-Key": "conversation-create-1"},
                json={"title": "第二轮"},
            )
            replay = await client.post(
                "/projects/project-1/conversations",
                headers={"Idempotency-Key": "conversation-create-1"},
                json={"title": "第二轮"},
            )
            listing = await client.get("/projects/project-1/conversations")
        return first, replay, listing

    first, replay, listing = _run(scenario())
    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert len(listing.json()["items"]) == 2


def test_file_execution_routes_list_and_cancel(tmp_path) -> None:
    app, services, snapshot, _bootstrap = _app(tmp_path)
    executions = ProjectExecutionStore(services.root)
    run = executions.create_specialist_run(
        SpecialistRunRecord(
            run_id="run-1",
            project_id="project-1",
            round_id="round-1",
            role=SpecialistRole.VISUAL_DEVELOPMENT,
            target_refs=["project:assets"],
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
        ),
    )
    executions.create_task(
        TaskRecord(
            task_id="task-1",
            project_id="project-1",
            round_id=run.round_id,
            run_id=run.run_id,
            kind=TaskKind.COMPOSE,
            request_fingerprint="fingerprint-1",
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            input_refs=["project:story"],
            metadata={
                "targetRef": "timeline:timeline:main",
                "completedElements": 3,
                "totalElements": 10,
            },
        ),
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            runs = await client.get("/projects/project-1/specialist-runs")
            tasks = await client.get("/projects/project-1/tasks")
            cancelled = await client.post(
                "/projects/project-1/tasks/task-1/cancel",
                headers={"Idempotency-Key": "cancel-1"},
                json={"reason": "不再需要"},
            )
            replay = await client.post(
                "/projects/project-1/tasks/task-1/cancel",
                headers={"Idempotency-Key": "cancel-1"},
                json={"reason": "不再需要"},
            )
        return runs, tasks, cancelled, replay

    runs, tasks, cancelled, replay = _run(scenario())
    assert runs.status_code == 200
    assert runs.json()["items"][0]["taskRefs"] == ["task-1"]
    assert tasks.status_code == 200
    assert tasks.json()["items"][0]["status"] == "QUEUED"
    assert tasks.json()["items"][0]["completedElements"] == 3
    assert tasks.json()["items"][0]["totalElements"] == 10
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "CANCELLED"
    assert replay.status_code == 202
    assert replay.json() == cancelled.json()


def test_timeline_render_dispatches_once_and_returns_before_completion(
    tmp_path,
    monkeypatch,
) -> None:
    app, _services, _snapshot, _bootstrap = _app(tmp_path)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls: list[tuple[str, str]] = []

        async def fake_execute(
            _services,
            *,
            project_id,
            target_ref,
            **_kwargs,
        ):
            calls.append((project_id, target_ref))
            started.set()
            await release.wait()

        monkeypatch.setattr(
            "services.media_files.local_execution.execute_file_local_media_command",
            fake_execute,
        )
        monkeypatch.setattr(
            "services.media_files.local_execution.file_local_media_task_id",
            lambda _project_id, _key: "task-compose-1",
        )
        # This case only verifies dispatch semantics; the synchronous
        # precheck's structural validation of the fixture project is covered
        # separately.
        monkeypatch.setattr(
            "services.media_files.local_execution.validate_local_media_execution",
            lambda *_args, **_kwargs: None,
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            first = await client.post(
                "/projects/project-1/timelines/timeline%3Amain/render",
                headers={"Idempotency-Key": "render-1"},
            )
            # The 202 response has already returned even though the renderer
            # is deliberately blocked.
            await asyncio.wait_for(started.wait(), timeout=1)
            second = await client.post(
                "/projects/project-1/timelines/timeline%3Amain/render",
                headers={"Idempotency-Key": "render-2"},
            )
            release.set()
            await asyncio.sleep(0)
        return first, second, calls

    first, second, calls = _run(scenario())
    assert first.status_code == 202
    assert first.json()["taskId"] == "task-compose-1"
    assert first.json()["replayed"] is False
    assert second.status_code == 202
    assert second.json()["taskId"] == "task-compose-1"
    assert second.json()["replayed"] is True
    assert calls == [("project-1", "timeline:timeline:main")]


def test_file_session_status_bar_projects_task_progress(tmp_path) -> None:
    app, services, _snapshot, _bootstrap = _app(tmp_path)
    executions = ProjectExecutionStore(services.root)
    executions.create_task(
        TaskRecord(
            task_id="task-ingest-1",
            project_id="project-1",
            kind=TaskKind.ASSET_INGEST,
            request_fingerprint="fingerprint-ingest-1",
            input_refs=["project:assets"],
        ),
    )
    executions.transition_task(
        "project-1",
        "task-ingest-1",
        expected_status=TaskStatus.QUEUED,
        status=TaskStatus.RUNNING,
        updates={"progress": 0.42},
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/projects/project-1/session")

    response = _run(scenario())
    assert response.status_code == 200
    status_bar = response.json()["agentStatusBar"]
    assert status_bar["progress"]["label"] == "附件入库中 · 42%"
    assert status_bar["progress"]["completed"] == 42
    assert status_bar["progress"]["total"] == 100
    assert status_bar["activity"]["runningTaskCount"] == 1


def test_file_execution_authorization_can_be_polled_and_approved(
    tmp_path,
) -> None:
    app, services, snapshot, _bootstrap = _app(tmp_path)
    executions = ProjectExecutionStore(services.root)
    executions.create_specialist_run(
        SpecialistRunRecord(
            run_id="run-image-1",
            project_id="project-1",
            round_id="round-1",
            role=SpecialistRole.VISUAL_DEVELOPMENT,
            target_refs=["asset:hero"],
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
        ),
    )
    executions.create_execution_authorization(
        ExecutionAuthorizationRecord(
            authorization_id="authorization-1",
            project_id="project-1",
            round_id="round-1",
            run_id="run-image-1",
            execution_request_id="request-image-1",
            operation="image_generation",
            target_scope=["asset:hero"],
            authorization_token="exact-token-1",
            summary="生成角色图",
            requested_provider="creator-image",
            requested_model="configured-image-model",
            requested_candidates=1,
        ),
    )

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            pending = await client.get(
                "/projects/project-1/execution-authorizations?status=PENDING",
            )
            approved = await client.post(
                "/projects/project-1/execution-authorizations/authorization-1/approve",
                headers={"Idempotency-Key": "approve-1"},
                json={
                    "authorizationToken": "exact-token-1",
                    "provider": "creator-image",
                    "model": "configured-image-model",
                    "maxCost": 0,
                    "maxCandidates": 1,
                },
            )
            replay = await client.post(
                "/projects/project-1/execution-authorizations/authorization-1/approve",
                headers={"Idempotency-Key": "approve-1"},
                json={
                    "authorizationToken": "exact-token-1",
                    "provider": "creator-image",
                    "model": "configured-image-model",
                    "maxCost": 0,
                    "maxCandidates": 1,
                },
            )
        return pending, approved, replay

    pending, approved, replay = _run(scenario())
    assert pending.status_code == 200
    assert pending.json()["items"][0]["targetRef"] == "asset:hero"
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert replay.json() == approved.json()
    record = executions.get_execution_authorization(
        "project-1",
        "authorization-1",
    )
    assert record.status is ExecutionAuthorizationStatus.APPROVED
