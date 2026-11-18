# -*- coding: utf-8 -*-
# flake8: noqa: E501
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from api import file_session_routes
from api.dependencies import creator_error_handler, project_file_services
from api.file_execution_routes import router as execution_router
from api.file_session_routes import router as session_router, stream_events
from api.project_file_routes import router as project_router
from domain.enums import (
    SpecialistRole,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
)
from domain.errors import CreatorError
from services.project_files import frontend_edit_hold
from services.project_files.json_pointer import hash_json_value
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
from services.runtime_files.models import ReviewBoundary


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
    app.include_router(project_router)
    app.dependency_overrides[project_file_services] = lambda: services
    return app, services, snapshot, bootstrap


def test_file_session_message_is_idempotent_and_visible(
    tmp_path,
    run_scenario,
) -> None:
    app, services, _snapshot, bootstrap = _app(tmp_path)
    payload = {
        "clientMessageId": "message-1",
        "conversationId": "conversation-1",
        "message": "完善故事结构",
    }

    async def scenario(client):
        headers = {"Idempotency-Key": "message-1"}
        session = await client.get("/projects/project-1/session")
        first = await client.post(
            "/projects/project-1/messages",
            headers=headers,
            json=payload,
        )
        replay = await client.post(
            "/projects/project-1/messages",
            headers=headers,
            json=payload,
        )
        messages = await client.get(
            "/projects/project-1/conversations/conversation-1/messages",
        )
        return session, first, replay, messages

    session, first, replay, messages = run_scenario(app, scenario)
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


@pytest.mark.parametrize(
    "change",
    ["append", "replace", "truncate", "remove", "corrupt"],
)
def test_event_stream_replays_pages_and_handles_file_changes(
    tmp_path,
    monkeypatch,
    change,
):
    # Uses a lifecycle type, not a streaming delta: the replay filter drops
    # historical deltas on purpose, and this test is about cursor progress
    # and fail-closed behaviour when the durable file changes underneath it.
    # The plugin logger does not propagate to the root logger, so caplog
    # can never see it; record the warning at its call site instead.
    notices: list[str] = []

    # pylint: disable-next=unused-argument
    def record_warning(message, *args, **kwargs):
        notices.append(message % args if args else str(message))

    monkeypatch.setattr(file_session_routes.logger, "warning", record_warning)
    _app_value, services, _snapshot, _bootstrap = _app(tmp_path)
    store = services.sessions

    def append(value):
        store.append_event(
            "project-1",
            "session-1",
            event_type="workspace.head_changed",
            actor="agent",
            payload={"value": value},
        )

    for value in range(1, 206):
        append(value)
    event_path = store.event_reader("project-1", "session-1").store.path

    class Connection:
        polls = 0

        async def is_disconnected(self):
            self.polls += 1
            return self.polls > 2

    async def scenario():
        response = await stream_events(
            "project-1",
            Connection(),
            after=1,
            last_event_id="3",
            services=services,
        )
        ids = []
        async for chunk in response.body_iterator:
            ids.append(int(chunk.split("\n", 1)[0].removeprefix("id: ")))
            if len(ids) == 1:
                if change == "append":
                    append(206)
                elif change == "replace":
                    replacement = event_path.with_suffix(".replacement")
                    replacement.write_bytes(event_path.read_bytes())
                    replacement.replace(event_path)
                elif change == "truncate":
                    event_path.write_bytes(b"")
                elif change == "remove":
                    event_path.unlink()
                else:
                    with event_path.open("ab") as handle:
                        handle.write(b"{invalid json}\n")
        return ids

    assert asyncio.run(scenario()) == list(
        range(4, 207 if change == "append" else 204),
    )
    if change != "append":
        assert any("Event replay stopped" in line for line in notices)


def test_live_streaming_delta_past_the_replay_boundary_is_delivered(
    tmp_path,
) -> None:
    """A live delta must survive a long-lived SSE connection.

    Review #243 blocking #1: ``replay_noise_line`` was passed to the
    reader without a boundary, so it kept dropping every streaming
    delta for the whole life of the connection -- a returning user saw
    the replay up to the tail seq, then silence while a fresh reply
    generated in front of them. The fix scopes the filter to the tail
    at connect time; anything appended after that point reaches the
    client verbatim.
    """

    _app_value, services, _snapshot, _bootstrap = _app(tmp_path)
    store = services.sessions

    def append(event_type, payload):
        return store.append_event(
            "project-1",
            "session-1",
            event_type=event_type,
            actor="agent",
            payload=payload,
        )

    # Pre-replay: a lifecycle event + an old delta that the filter is
    # allowed to drop. Boundary is the tail at connect time (=2).
    append("agent.run.started", {"runId": "run-old"})
    append(
        "agent.message_delta",
        {
            "runId": "run-old",
            "messageId": "m-old",
            "deltaIndex": 0,
            "delta": "旧",
        },
    )

    class Connection:
        polls = 0

        async def is_disconnected(self):
            self.polls += 1
            # Keep the SSE loop open past the initial replay so the
            # live append below has a chance to be picked up; the
            # body exits as soon as the test's iteration stops.
            return self.polls > 40

    async def scenario() -> list[tuple[int, str]]:
        response = await stream_events(
            "project-1",
            Connection(),
            after=0,
            last_event_id=None,
            services=services,
        )

        seen: list[tuple[int, str]] = []
        iterator = response.body_iterator.__aiter__()
        # Drain the replay (lifecycle event) before firing the live append
        # so the reader has definitely crossed the boundary.
        first = await iterator.__anext__()
        seq, kind = _parse_sse_id_type(first)
        seen.append((seq, kind))

        append(
            "agent.message_delta",
            {
                "runId": "run-live",
                "messageId": "m-live",
                "deltaIndex": 0,
                "delta": "live",
            },
        )
        try:
            while True:
                chunk = await iterator.__anext__()
                seq, kind = _parse_sse_id_type(chunk)
                seen.append((seq, kind))
                if kind.startswith("agent.message_delta"):
                    break
        except StopAsyncIteration:
            pass
        return seen

    events = asyncio.run(scenario())
    # The historical delta at seq 2 stayed filtered (replay), but the live
    # delta at seq 3 must reach the client even though it is the same
    # event type the filter is trained to drop.
    kinds = [kind for _, kind in events]
    assert (
        "agent.message_delta" in kinds
    ), f"live streaming delta was filtered out of the SSE body: {events}"
    assert kinds[0] == "agent.run.started"


def _parse_sse_id_type(chunk: str) -> tuple[int, str]:
    seq = 0
    kind = ""
    for line in chunk.splitlines():
        if line.startswith("id: "):
            seq = int(line.removeprefix("id: "))
        elif line.startswith("event: "):
            kind = line.removeprefix("event: ")
    return seq, kind


def test_replay_deltas_of_an_active_run_survive_the_byte_layer_filter(
    tmp_path,
    monkeypatch,
) -> None:
    """A pre-connect delta of an in-flight run must reach the client.

    Review #243 follow-up P2: the replay-boundary fix stopped the filter
    from eating live deltas, but on the pre-boundary side the classifier
    still dropped every delta before the post-parse exemption could
    see it -- a returning user watched the reply missing its opening
    stretch until ``message.completed`` arrived. Both layers must
    agree: the byte-level classifier spares deltas whose ``runId`` is
    in the active set, and the parse-time filter spares the same set.

    The active-run delta here is the reviewer's exact shape (seq 1 =
    ``run.started``, seq 2 = delta with the prefix), and a sibling
    delta from a settled run at seq 3 stays filtered to prove the
    exemption is bounded by ``active_run_ids``.
    """

    _app_value, services, _snapshot, _bootstrap = _app(tmp_path)
    store = services.sessions

    def append(event_type, payload):
        return store.append_event(
            "project-1",
            "session-1",
            event_type=event_type,
            actor="agent",
            payload=payload,
        )

    append(
        "agent.run.started",
        {"runId": "run-active"},
    )
    append(
        "agent.message_delta",
        {
            "runId": "run-active",
            "messageId": "m-active",
            "deltaIndex": 0,
            "delta": "prefix",
        },
    )
    # Same boundary-internal delta from a run that is NOT in the active
    # set at connect -- still should be dropped as replay noise.
    append(
        "agent.message_delta",
        {
            "runId": "run-settled",
            "messageId": "m-settled",
            "deltaIndex": 0,
            "delta": "should-stay-dropped",
        },
    )

    monkeypatch.setattr(
        file_session_routes,
        "_active_specialist_run_ids",
        lambda *_args, **_kwargs: {"run-active"},
    )

    class Connection:
        polls = 0

        async def is_disconnected(self):
            self.polls += 1
            return self.polls > 4

    async def scenario() -> list[tuple[int, str, str]]:
        response = await stream_events(
            "project-1",
            Connection(),
            after=0,
            last_event_id=None,
            services=services,
        )
        seen: list[tuple[int, str, str]] = []
        async for chunk in response.body_iterator:
            seq, kind = _parse_sse_id_type(chunk)
            data = ""
            for line in chunk.splitlines():
                if line.startswith("data: "):
                    data = line.removeprefix("data: ")
            seen.append((seq, kind, data))
        return seen

    events = asyncio.run(scenario())
    seqs = [seq for seq, _, _ in events]
    assert 1 in seqs  # run.started, always kept
    # The active run's delta is delivered (fix). Without the change,
    # seq 2 was filtered here while the parse-time exemption never
    # got to run.
    active_delta = next(
        (data for seq, kind, data in events if seq == 2),
        None,
    )
    assert active_delta is not None, (
        f"active-run delta was dropped before the parse-time filter "
        f"could exempt it: {events}"
    )
    assert "prefix" in active_delta
    # The settled run's delta at seq 3 stays filtered -- the exemption
    # is scoped to ``active_run_ids``, not a blanket "keep every
    # delta" reversal.
    assert 3 not in seqs


def test_lifecycle_event_embedding_an_event_record_survives_the_filter(
    tmp_path,
    monkeypatch,
) -> None:
    """A tool_completed whose result carries a whole event is delivered.

    Review #243 r4548690038 follow-up: the byte-level classifier used to
    substring-match ``"event_type":"<type>"`` (then even with an adjacent
    ``message_id``), so a ``subagent.tool_completed`` whose ``result``
    legitimately embeds an event record -- the reviewer's exact probe:
    ``{"event_type":"agent.message_delta","message_id":"nested-example"}``
    -- was dropped as noise at the byte layer, before the parse-time
    filter (which reads the real outer event type and would have kept
    it) ever ran. The client lost the persistent tool state it rebuilds
    its ToolCallCard from. The classifier now inspects only the
    envelope's own record at depth 1.
    """

    _app_value, services, _snapshot, _bootstrap = _app(tmp_path)
    store = services.sessions

    def append(event_type, payload):
        return store.append_event(
            "project-1",
            "session-1",
            event_type=event_type,
            actor="agent",
            payload=payload,
        )

    append("agent.run.started", {"runId": "run-1"})
    append(
        "subagent.tool_completed",
        {
            "runId": "run-1",
            "toolCallId": "call-1",
            # A result that embeds a full event record, so the line
            # reproduces both keys in canonical order -- the exact
            # shape the loose matcher used to fall for.
            "result": {
                "event_seq": 99,
                "event_type": "agent.message_delta",
                "message_id": "nested-example",
                "delta": "copied",
            },
        },
    )
    append("agent.run.completed", {"runId": "run-1"})
    # A genuine historical delta with no active run is still dropped,
    # proving the fix did not just disable the classifier.
    append(
        "agent.message_delta",
        {"runId": "run-settled", "messageId": "m", "delta": "gone"},
    )

    monkeypatch.setattr(
        file_session_routes,
        "_active_specialist_run_ids",
        lambda *_args, **_kwargs: set(),
    )

    class Connection:
        polls = 0

        async def is_disconnected(self):
            self.polls += 1
            return self.polls > 4

    async def scenario() -> list[tuple[int, str]]:
        response = await stream_events(
            "project-1",
            Connection(),
            after=0,
            last_event_id=None,
            services=services,
        )
        seen: list[tuple[int, str]] = []
        async for chunk in response.body_iterator:
            seq, kind = _parse_sse_id_type(chunk)
            seen.append((seq, kind))
        return seen

    events = asyncio.run(scenario())
    kinds = [kind for _, kind in events]
    assert "subagent.tool_completed" in kinds, (
        f"a tool_completed embedding an event record was dropped as "
        f"replay noise: {events}"
    )
    # The genuine settled-run delta with no active run is still filtered.
    assert "agent.message_delta" not in kinds


def test_interrupt_is_persisted_before_process_local_cancellation(
    tmp_path,
    monkeypatch,
    api_request,
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

    response = api_request(
        app,
        "POST",
        "/projects/project-1/interrupt",
        headers={"Idempotency-Key": "interrupt-1"},
        json={},
    )
    assert response.status_code == 202
    assert observed_statuses == ["INTERRUPT_REQUESTED"]
    assert response.json()["status"] == "CANCELLED"
    deadline = time.monotonic() + 2
    cancelled_task = executions.get_task("project-1", "task-stop-1")
    while (
        cancelled_task.status is not TaskStatus.CANCELLED
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
        cancelled_task = executions.get_task("project-1", "task-stop-1")
    assert cancelled_task.status is TaskStatus.CANCELLED
    assert cancelled_task.error["code"] == "USER_CANCELLED"


def test_interrupt_response_does_not_wait_for_terminal_task_cleanup(
    tmp_path,
    monkeypatch,
    api_request,
) -> None:
    app, services, _snapshot, _bootstrap = _app(tmp_path)
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()

    def blocking_cleanup(_services, project_id):
        assert project_id == "project-1"
        cleanup_started.set()
        release_cleanup.wait(timeout=5)

    monkeypatch.setattr(
        "api.file_session_routes._cancel_active_project_tasks_sync",
        blocking_cleanup,
    )

    response = api_request(
        app,
        "POST",
        "/projects/project-1/interrupt",
        headers={"Idempotency-Key": "interrupt-nowait"},
        json={},
    )
    assert cleanup_started.wait(timeout=1)
    assert response.status_code == 202
    assert response.json()["status"] == "CANCELLED"
    stopped = services.sessions.get_project_session("project-1")
    assert stopped.status.value == "CANCELLED"
    release_cleanup.set()


@pytest.mark.parametrize(
    "task_status",
    [TaskStatus.RUNNING, TaskStatus.CANCELLED],
)
def test_stop_cleanup_settles_media_run_after_worker_is_gone(
    tmp_path,
    task_status,
) -> None:
    from api.file_session_routes import _cancel_active_project_tasks_sync

    _app_instance, services, snapshot, _bootstrap = _app(tmp_path)
    executions = ProjectExecutionStore(services.root)
    run = executions.create_run(
        SpecialistRunRecord(
            run_id="run-stopped-image",
            project_id="project-1",
            round_id="round-image",
            role=SpecialistRole.R2V_GENERATION_DIRECTOR,
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            metadata={"commandType": "GENERATE_STORYBOARD_IMAGE"},
        ),
    )
    executions.transition_run(
        "project-1",
        run.run_id,
        expected_status=SpecialistRunStatus.QUEUED,
        status=SpecialistRunStatus.RUNNING_MODEL,
    )
    executions.transition_run(
        "project-1",
        run.run_id,
        expected_status=SpecialistRunStatus.RUNNING_MODEL,
        status=SpecialistRunStatus.WAITING_RUNTIME,
    )
    task = executions.create_task(
        TaskRecord(
            task_id="task-stopped-image",
            project_id="project-1",
            run_id=run.run_id,
            round_id=run.round_id,
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            kind=TaskKind.IMAGE_GENERATION,
            request_fingerprint="stopped-image",
        ),
    )
    executions.transition_task(
        "project-1",
        task.task_id,
        expected_status=TaskStatus.QUEUED,
        status=task_status,
    )

    # No worker remains to execute its finally block. Repeated stop must also
    # repair a Task already cancelled by a previous interrupted cleanup.
    _cancel_active_project_tasks_sync(services, "project-1")
    _cancel_active_project_tasks_sync(services, "project-1")

    assert (
        executions.get_task("project-1", task.task_id).status
        is TaskStatus.CANCELLED
    )
    stopped_run = executions.get_run("project-1", run.run_id)
    assert stopped_run.status is SpecialistRunStatus.CANCELLED
    assert stopped_run.final_marker == "CANCELLED"
    assert services.projects.read("project-1").etag == snapshot.etag


def test_message_history_pages_backward_with_tail_and_before(
    tmp_path,
    run_scenario,
) -> None:
    app, _services, _snapshot, _bootstrap = _app(tmp_path)

    async def scenario(client):
        for index in range(1, 8):
            posted = await client.post(
                "/projects/project-1/messages",
                headers={"Idempotency-Key": f"message-{index}"},
                json={
                    "clientMessageId": f"message-{index}",
                    "conversationId": "conversation-1",
                    "message": f"第 {index} 条消息",
                },
            )
            assert posted.status_code == 202
        base = "/projects/project-1/conversations/conversation-1/messages"
        tail = await client.get(base, params={"tail": "true", "limit": 3})
        middle = await client.get(base, params={"before": 5, "limit": 3})
        head = await client.get(base, params={"before": 2, "limit": 3})
        forward = await client.get(base, params={"after": 0, "limit": 3})
        mixed = await client.get(base, params={"after": 3, "tail": "true"})
        return tail, middle, head, forward, mixed

    tail, middle, head, forward, mixed = run_scenario(app, scenario)

    # tail=true returns the newest page plus a backward cursor.
    assert tail.status_code == 200
    assert [item["messageSeq"] for item in tail.json()["items"]] == [5, 6, 7]
    assert tail.json()["nextBefore"] == 5
    assert tail.json().get("nextAfter") is None

    # before pages strictly older history, ascending inside the page.
    assert middle.status_code == 200
    assert [item["messageSeq"] for item in middle.json()["items"]] == [2, 3, 4]
    assert middle.json()["nextBefore"] == 2

    # The oldest page has no further backward cursor.
    assert head.status_code == 200
    assert [item["messageSeq"] for item in head.json()["items"]] == [1]
    assert head.json().get("nextBefore") is None

    # Forward pagination keeps its original contract.
    assert forward.status_code == 200
    assert [item["messageSeq"] for item in forward.json()["items"]] == [
        1,
        2,
        3,
    ]
    assert forward.json()["nextAfter"] == 3

    # Mixing directions has no coherent cursor and is rejected.
    assert mixed.status_code >= 400


def test_file_execution_routes_list_and_cancel(tmp_path, run_scenario) -> None:
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
            metadata={"targetRef": "timeline:timeline:main"},
        ),
    )

    async def scenario(client):
        cancel = {
            "headers": {"Idempotency-Key": "cancel-1"},
            "json": {"reason": "不再需要"},
        }
        runs = await client.get("/projects/project-1/specialist-runs")
        tasks = await client.get("/projects/project-1/tasks")
        cancelled = await client.post(
            "/projects/project-1/tasks/task-1/cancel",
            **cancel,
        )
        replay = await client.post(
            "/projects/project-1/tasks/task-1/cancel",
            **cancel,
        )
        return runs, tasks, cancelled, replay

    runs, tasks, cancelled, replay = run_scenario(app, scenario)
    assert runs.status_code == 200
    assert runs.json()["items"][0]["taskRefs"] == ["task-1"]
    assert tasks.status_code == 200
    assert tasks.json()["items"][0]["status"] == "QUEUED"
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "CANCELLED"
    assert replay.status_code == 202
    assert replay.json() == cancelled.json()


def test_timeline_render_dispatches_once_and_returns_before_completion(
    tmp_path,
    monkeypatch,
    run_scenario,
) -> None:
    app, _services, _snapshot, _bootstrap = _app(tmp_path)

    async def scenario(client):
        started = asyncio.Event()
        release = asyncio.Event()
        calls: list[tuple[str, str]] = []
        prechecks: list[dict] = []

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
        monkeypatch.setattr(
            "services.media_files.local_execution.validate_local_media_execution",
            lambda _services, **kwargs: prechecks.append(kwargs),
        )

        first = await client.post(
            "/projects/project-1/timelines/timeline%3Amain/render",
            headers={"Idempotency-Key": "render-1"},
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        second = await client.post(
            "/projects/project-1/timelines/timeline%3Amain/render",
            headers={"Idempotency-Key": "render-2"},
        )
        release.set()
        await asyncio.sleep(0)
        return first, second, calls, prechecks

    first, second, calls, prechecks = run_scenario(app, scenario)
    assert first.status_code == 202
    assert first.json()["taskId"] == "task-compose-1"
    assert first.json()["replayed"] is False
    assert second.status_code == 202
    assert second.json()["taskId"] == "task-compose-1"
    assert second.json()["replayed"] is True
    assert calls == [("project-1", "timeline:timeline:main")]
    # The precheck must not enforce the scene gate: stale locks are
    # repaired by the auto-rereview inside the dispatch it precedes.
    assert prechecks
    assert all(
        precheck["enforce_scene_gate"] is False for precheck in prechecks
    )


def test_file_execution_authorization_can_be_polled_and_approved(
    tmp_path,
    run_scenario,
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

    async def scenario(client):
        approve = {
            "headers": {"Idempotency-Key": "approve-1"},
            "json": {
                "authorizationToken": "exact-token-1",
                "provider": "creator-image",
                "model": "configured-image-model",
                "maxCost": 0,
                "maxCandidates": 1,
            },
        }
        pending = await client.get(
            "/projects/project-1/execution-authorizations?status=PENDING",
        )
        approved = await client.post(
            "/projects/project-1/execution-authorizations/authorization-1/approve",
            **approve,
        )
        replay = await client.post(
            "/projects/project-1/execution-authorizations/authorization-1/approve",
            **approve,
        )
        return pending, approved, replay

    pending, approved, replay = run_scenario(app, scenario)
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
    assert record.decision == {
        "provider": "creator-image",
        "model": "configured-image-model",
        "maxCost": 0,
        "maxCandidates": 1,
    }


def test_legacy_specialist_uses_saved_prompt_instead_of_old_tool_argument(
    tmp_path,
    run_scenario,
):
    from domain.errors import ConflictError
    from services.project_files.approved_prompt import (
        approved_specialist_arguments,
    )
    from services.project_files.models import TimelineElement

    app, services, snapshot, _ = _app(tmp_path)
    candidate = snapshot.project.model_dump(mode="json")
    candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
        "e"
    ] = TimelineElement.model_validate(
        {
            "element_id": "e",
            "span": {"start_tick": 0, "duration_tick": 4000},
            "location": {},
            "creation": {
                "type": "r2v",
                "narrative": "猫走到窗边。",
                "storyboard_prompt": "用户保存的提示词B",
            },
        },
    ).model_dump(
        mode="json",
    )
    current = services.commits.commit(
        base=snapshot,
        candidate=candidate,
        origin="frontend_edit",
    ).snapshot
    executions = ProjectExecutionStore(services.root)
    authorization = executions.create_execution_authorization(
        ExecutionAuthorizationRecord(
            authorization_id="legacy-prompt",
            project_id="project-1",
            round_id="round-1",
            run_id="run-1",
            execution_request_id="legacy-request",
            operation="image_generation",
            target_scope=["element:e"],
            authorization_token="token",
            requested_provider="provider",
            requested_model="model",
            requested_candidates=1,
            summary="Generate the saved storyboard prompt",
            scope={
                "operation": "image_generation",
                "parameters": {"prompt": "旧工具参数A", "ratio": "16:9"},
            },
        ),
    )

    async def scenario(client):
        result = await client.post(
            "/projects/project-1/execution-authorizations/legacy-prompt/approve",
            headers={"Idempotency-Key": "approve-legacy"},
            json={
                "authorizationToken": authorization.authorization_token,
                "provider": "provider",
                "model": "model",
                "maxCost": 0,
                "maxCandidates": 1,
                "projectEtag": f'"{current.etag}"',
                "promptPointer": (
                    "/timelines/items/timeline:main/elements_by_id/e"
                    "/creation/storyboard_prompt"
                ),
            },
        )
        assert result.status_code == 200, result.text
        approved = executions.get_execution_authorization(
            "project-1",
            "legacy-prompt",
        )
        arguments = {
            "targetRef": "element:e",
            "arguments": {"prompt": "旧工具参数A", "ratio": "16:9"},
        }
        rebound = approved_specialist_arguments(current, approved, arguments)
        assert rebound["arguments"] == {
            "prompt": "用户保存的提示词B",
            "ratio": "16:9",
        }
        assert arguments["arguments"]["prompt"] == "旧工具参数A"
        # An unrelated write moves the ETag but not the approved prompt: the
        # approval stays usable instead of re-asking the user.
        changed = current.project.model_dump(mode="json")
        changed["name"] = "changed"
        newer = services.commits.commit(
            base=current,
            candidate=changed,
            origin="frontend_edit",
        ).snapshot
        assert newer.etag != current.etag
        assert approved_specialist_arguments(newer, approved, arguments)[
            "arguments"
        ] == {"prompt": "用户保存的提示词B", "ratio": "16:9"}
        edited = newer.project.model_dump(mode="json")
        edited["timelines"]["items"]["timeline:main"]["elements_by_id"]["e"][
            "creation"
        ]["storyboard_prompt"] = "用户又改了的提示词C"
        rewritten = services.commits.commit(
            base=newer,
            candidate=edited,
            origin="frontend_edit",
        ).snapshot
        with pytest.raises(ConflictError):
            approved_specialist_arguments(rewritten, approved, arguments)

    run_scenario(app, scenario)


@pytest.mark.parametrize(
    "change",
    [
        "prompt",
        "unchanged",
        "quoted-etag",
        "weak-etag",
        "stale-etag",
        "not-ready",
        "review",
        "duration",
        "ratio",
        "resolution",
        "provider",
        "model",
        "extra-parameter",
        "missing-scope",
        "missing-node",
        "bad-node",
        "wrong-node",
        "wrong-target",
        "wrong-operation",
        "bad-fingerprint",
        "wrong-scope-provider",
        "unsupported-node",
        "client-fingerprint",
        "empty-etag",
        "non-string-etag",
    ],
)
def test_workgraph_saved_snapshot_approval_fails_closed(
    tmp_path,
    run_scenario,
    monkeypatch,
    change,
):
    # Keep the parameterized fail-closed matrix and its assertions together.
    # pylint: disable=too-many-statements
    from services.file_agent_runtime import driver as dm
    from services.file_agent_runtime.work_scheduler import WorkGraphScheduler
    from services.file_agent_runtime.workgraph_execution import (
        ready_request_context,
        requested_work_node,
    )
    from services.project_files.models import TimelineElement

    app, services, _, _ = _app(tmp_path)
    executions = ProjectExecutionStore(services.root)
    monkeypatch.setattr(frontend_edit_hold, "_holds", {})
    monkeypatch.setattr(
        dm,
        "_execution_provider_model",
        lambda *_: ("provider", "model"),
    )

    async def scenario(client):
        # Each branch exercises a distinct authorization rejection condition.
        # pylint: disable=too-many-branches,too-many-statements
        base = services.projects.read("project-1")
        project = base.project.model_copy(deep=True)
        project.timelines.items["timeline:main"].elements_by_id[
            "e1"
        ] = TimelineElement.model_validate(
            {
                "element_id": "e1",
                "label": "Sunset",
                "span": {"start_tick": 0, "duration_tick": 4000},
                "location": {},
                "creation": {
                    "type": "t2v",
                    "video_prompt": "A quiet sunset.",
                },
            },
        )
        elements = project.timelines.items["timeline:main"].elements_by_id
        elements["e2"] = elements["e1"].model_copy(
            deep=True,
            update={"element_id": "e2"},
        )
        await services.commit_candidate(
            base=base,
            candidate=project.model_dump(mode="json"),
            origin="frontend_edit",
            review_policy="auto_fix",
            caused_by_request_id="setup",
        )
        snapshot, _, graph, _ = await ready_request_context(
            services,
            executions,
            "project-1",
            check_media_budget=False,
        )
        node = next(
            n
            for n in graph.nodes
            if n.kind == "video" and n.target_ref == "element:e1"
        )
        plan = requested_work_node(snapshot, node)
        scope = {
            "operation": plan.spec.name,
            "targetRefs": [node.target_ref],
            "parameters": dict(plan.parameters),
            "workGraph": {
                "nodeId": node.node_id,
                "fingerprint": plan.fingerprint,
                "provider": "provider",
                "model": "model",
            },
        }
        target = node.target_ref
        operation = plan.spec.name
        if change == "missing-scope":
            scope.pop("workGraph")
        elif change == "missing-node":
            scope["workGraph"].pop("nodeId")
        elif change == "bad-node":
            scope["workGraph"]["nodeId"] = [node.node_id]
        elif change == "wrong-node":
            scope["workGraph"]["nodeId"] = "video:missing"
        elif change == "wrong-target":
            target = "element:other"
            scope["targetRefs"] = [target]
        elif change == "wrong-operation":
            operation = scope["operation"] = "image_generation"
        elif change == "bad-fingerprint":
            scope["workGraph"]["fingerprint"] = "not-a-server-fingerprint"
        elif change == "wrong-scope-provider":
            scope["workGraph"]["provider"] = "other-provider"
        elif change == "unsupported-node":
            scope["workGraph"]["nodeId"] = next(
                n.node_id for n in graph.nodes if n.kind == "compose"
            )
        elif change == "extra-parameter":
            scope["parameters"]["seed"] = 42
        record = executions.create_execution_authorization(
            ExecutionAuthorizationRecord(
                authorization_id="saved-auth",
                project_id="project-1",
                round_id="round-1",
                run_id="run-1",
                execution_request_id="request-1",
                operation=operation,
                target_scope=[target],
                authorization_token="exact-token",
                scope=scope,
                summary="Generate the authorized video.",
                requested_provider="provider",
                requested_model="model",
                requested_candidates=1,
            ),
        )
        candidate = snapshot.project.model_dump(mode="json")
        element = candidate["timelines"]["items"]["timeline:main"][
            "elements_by_id"
        ]["e1"]
        element["creation"]["video_prompt"] += " Warm golden lighting."
        candidate["timelines"]["items"]["timeline:main"]["elements_by_id"][
            "e2"
        ]["creation"]["video_prompt"] += " Another edit."
        if change == "not-ready":
            element["creation"]["video_prompt"] = ""
        elif change == "duration":
            element["span"]["duration_tick"] = 6000
        elif change == "ratio":
            candidate["settings"]["aspect_ratio"] = "9:16"
        elif change == "resolution":
            candidate["settings"]["resolution"] = "1080p"
        elif change in {"provider", "model"}:
            monkeypatch.setattr(
                dm,
                "_execution_provider_model",
                lambda *_: (
                    ("other-provider", "model")
                    if change == "provider"
                    else ("provider", "other-model")
                ),
            )
        pointers = [
            "/timelines/items/timeline:main/elements_by_id/e1/creation/video_prompt",
            "/timelines/items/timeline:main/elements_by_id/e2/creation/video_prompt",
        ]
        if change == "duration":
            pointers.append(
                "/timelines/items/timeline:main/elements_by_id/e1/span/duration_tick",
            )
        elif change in {"ratio", "resolution"}:
            field = "aspect_ratio" if change == "ratio" else "resolution"
            pointers.append(f"/settings/{field}")
        operations = []
        for pointer in pointers:
            before = snapshot.project.model_dump(mode="json")
            after = candidate
            for part in pointer.strip("/").split("/"):
                before, after = before[part], after[part]
            operations.append(
                {
                    "op": "replace",
                    "path": pointer,
                    "value": after,
                    "expectedValueHash": hash_json_value(before),
                },
            )
        if change != "unchanged":
            saved = await client.patch(
                "/projects/project-1/project",
                json={
                    "clientCommandId": "save-prompt",
                    "editSessionId": "prompt-editor",
                    "baseGeneration": snapshot.generation,
                    "baseEtag": snapshot.etag,
                    "operations": operations,
                },
            )
            assert saved.status_code == 200, saved.text
            assert frontend_edit_hold.hold_remaining("project-1", "e1") > 0
            assert frontend_edit_hold.hold_remaining("project-1", "e2") > 0
        if change == "review":
            review_base = services.projects.read("project-1")
            review_candidate = review_base.project.model_dump(mode="json")
            review_candidate["description"] = "Awaiting human review."
            await services.commit_candidate(
                base=review_base,
                candidate=review_candidate,
                origin="agentdock_idle_goal",
                review_policy="require_review",
                review_boundary=ReviewBoundary(
                    request_message_seq=2,
                    request_id="pending-review",
                    accepted_generation=review_base.generation,
                    accepted_etag=review_base.etag,
                ),
                caused_by_request_id="pending-review",
                caused_by_message_seq=2,
            )
        fresh, _, current_graph, blocked = await ready_request_context(
            services,
            executions,
            "project-1",
            check_media_budget=False,
        )
        if change not in {"unchanged", "review"}:
            assert blocked[node.node_id] == "EDIT_IN_PROGRESS"
        if change == "prompt":
            # Both fields were PATCHed, but only the exact node and snapshot
            # may ignore grace; ordinary/unattended reads remain blocked.
            for confirmation in (
                {},
                {"confirmed_project_etag": fresh.etag},
                {"confirmed_node_id": node.node_id},
                {
                    "confirmed_project_etag": snapshot.etag,
                    "confirmed_node_id": node.node_id,
                },
                {
                    "confirmed_project_etag": fresh.etag,
                    "confirmed_node_id": "video:missing",
                },
                {
                    "confirmed_project_etag": fresh.etag,
                    "confirmed_node_id": node.node_id,
                },
            ):
                _, _, _, gates = await ready_request_context(
                    services,
                    executions,
                    "project-1",
                    check_media_budget=False,
                    **confirmation,
                )
                matches = confirmation == {
                    "confirmed_project_etag": fresh.etag,
                    "confirmed_node_id": node.node_id,
                }
                assert (node.node_id not in gates) is matches
                other = next(
                    n
                    for n in current_graph.nodes
                    if n.kind == "video" and n.target_ref == "element:e2"
                )
                assert gates[other.node_id] == "EDIT_IN_PROGRESS"
            assert frontend_edit_hold.hold_remaining("project-1", "e1") > 0
            assert frontend_edit_hold.hold_remaining("project-1", "e2") > 0
        payload = {
            "authorizationToken": record.authorization_token,
            "provider": "provider",
            "model": "model",
            "maxCost": 0,
            "maxCandidates": 1,
            "projectEtag": (
                snapshot.etag if change == "stale-etag" else fresh.etag
            ),
        }
        if change == "client-fingerprint":
            payload["workGraph"] = {"fingerprint": plan.fingerprint}
        elif change == "empty-etag":
            payload["projectEtag"] = ""
        elif change == "non-string-etag":
            payload["projectEtag"] = 123
        elif change in {"quoted-etag", "weak-etag"}:
            # Use the public HTTP snapshot representation, including a 304.
            fetched = await client.get("/projects/project-1/project")
            conditional = await client.get(
                "/projects/project-1/project",
                headers={"If-None-Match": fetched.headers["etag"]},
            )
            assert conditional.status_code == 304
            payload["projectEtag"] = (
                "W/" if change == "weak-etag" else ""
            ) + conditional.headers["etag"]
        response = await client.post(
            "/projects/project-1/execution-authorizations/saved-auth/approve",
            headers={"Idempotency-Key": "saved-approval"},
            json=payload,
        )
        current = executions.get_execution_authorization(
            "project-1",
            "saved-auth",
        )
        if change in {"prompt", "unchanged", "quoted-etag", "weak-etag"}:
            assert response.status_code == 200, response.text
            current_node = current_graph.by_id[node.node_id]
            approved_plan = requested_work_node(fresh, current_node)
            assert current.decision["workGraph"] == {
                "nodeId": node.node_id,
                "etag": fresh.etag,
                "fingerprint": approved_plan.fingerprint,
                # pylint: disable-next=protected-access
                "ledgerFingerprint": WorkGraphScheduler._ledger_fingerprint(
                    current_node,
                ),
            }
            assert (approved_plan.fingerprint == plan.fingerprint) is (
                change == "unchanged"
            )
        else:
            assert response.status_code == (
                422
                if change
                in {"client-fingerprint", "empty-etag", "non-string-etag"}
                else 409
            ), response.text
            assert current.status is ExecutionAuthorizationStatus.PENDING
            assert current.decision is None
            if change == "stale-etag":
                payload["projectEtag"] = fresh.etag
                retried = await client.post(
                    "/projects/project-1/execution-authorizations/saved-auth/approve",
                    headers={"Idempotency-Key": "fresh-approval"},
                    json=payload,
                )
                assert retried.status_code == 200, retried.text
                assert (
                    executions.get_execution_authorization(
                        "project-1",
                        "saved-auth",
                    ).decision["workGraph"]["etag"]
                    == fresh.etag
                )
        assert executions.list_tasks("project-1") == []

    run_scenario(app, scenario)


def test_sse_replay_drops_historical_deltas_and_keeps_lifecycle(tmp_path):
    """The replay exists to rebuild lifecycle state (CR #7), but streaming
    deltas inside it are discarded by the client by design. The endpoint must
    stop shipping the noise without ever losing a lifecycle event."""
    _app_value, services, _snapshot, _bootstrap = _app(tmp_path)
    store = services.sessions
    for event_type, payload in (
        ("agent.run.started", {"runId": "run-1"}),
        ("agent.message_delta", {"runId": "run-1", "delta": "x"}),
        ("subagent.message_delta", {"runId": "run-1", "delta": "y"}),
        ("message.completed", {"runId": "run-1", "text": "xy"}),
        ("agent.tool_completed", {"runId": "run-1", "toolCallId": "c-1"}),
    ):
        store.append_event(
            "project-1",
            "session-1",
            event_type=event_type,
            actor="agent",
            payload=payload,
        )

    class Connection:
        polls = 0

        async def is_disconnected(self):
            self.polls += 1
            return self.polls > 2

    async def scenario():
        response = await stream_events(
            "project-1",
            Connection(),
            after=0,
            last_event_id=None,
            services=services,
        )
        types, seqs = [], []
        async for chunk in response.body_iterator:
            for line in chunk.splitlines():
                if line.startswith("event: "):
                    types.append(line[len("event: ") :])
                elif line.startswith("id: "):
                    seqs.append(int(line[len("id: ") :]))
        return types, seqs

    types, seqs = asyncio.run(scenario())
    assert types == [
        "agent.run.started",
        "message.completed",
        "agent.tool_completed",
    ]
    # Gaps are expected and safe: the client cursor compares with `>`.
    assert seqs == [1, 4, 5]


def test_preflight_scene_review_surfaces_a_failed_repair(
    monkeypatch,
) -> None:
    """A repair that cannot finish must answer the caller, not the log.

    Review #243: the route answered 202 with a Task id that never came into
    existence, because the repair runs later and its failure had nowhere to
    go -- polling that id returns 404 forever.
    """

    # pylint: disable=protected-access
    import api.file_execution_routes as routes
    from services.render_review import scene_review

    calls: list[str] = []

    class _Projects:
        def read(self, _project_id):
            return SimpleNamespace(
                project=SimpleNamespace(
                    timelines=SimpleNamespace(items={"main": object()}),
                ),
            )

    services = SimpleNamespace(projects=_Projects())
    monkeypatch.setattr(
        scene_review,
        "collect_scene_review_targets",
        lambda _timeline: (["scene:hall"], []),
    )

    async def failing(*_args, **_kwargs):
        calls.append("reviewed")
        raise RuntimeError("VLM unavailable")

    monkeypatch.setattr(scene_review, "auto_review_stale_scenes", failing)

    with pytest.raises(RuntimeError, match="VLM unavailable"):
        asyncio.run(
            routes._preflight_scene_review(services, "project-1", "main"),
        )
    assert calls == ["reviewed"]

    # Nothing stale means no repair call: the precheck must not add work to
    # an export that does not need it.
    calls.clear()
    monkeypatch.setattr(
        scene_review,
        "collect_scene_review_targets",
        lambda _timeline: ([], []),
    )
    asyncio.run(routes._preflight_scene_review(services, "project-1", "main"))
    assert not calls

    # An exhausted budget now also refuses admission (review #243 P1-3
    # remaining half): wait_for cancels ``auto_review_stale_scenes``, so
    # the scenes it had not reached stay blocked, the drive's scene gate
    # still rejects the export, and no Task exists to carry that later
    # failure. Admitting anyway reproduced the 202-plus-phantom-Task
    # defect the whole preflight was introduced to close.
    monkeypatch.setattr(
        scene_review,
        "collect_scene_review_targets",
        lambda _timeline: (["scene:hall"], []),
    )

    async def slow(*_args, **_kwargs):
        calls.append("slow")
        await asyncio.sleep(30)

    monkeypatch.setattr(scene_review, "auto_review_stale_scenes", slow)
    monkeypatch.setattr(routes, "ADMISSION_REVIEW_BUDGET_SECONDS", 0.01)
    from domain.errors import ConflictError

    with pytest.raises(ConflictError) as timeout_refusal:
        asyncio.run(
            routes._preflight_scene_review(services, "project-1", "main"),
        )
    assert calls == ["slow"]
    assert timeout_refusal.value.details["code"] == "SCENE_REVIEW_TIMEOUT"
    assert timeout_refusal.value.details["scenes"] == ["scene:hall"]


def test_preflight_scene_review_refuses_when_scenes_are_still_blocked(
    monkeypatch,
) -> None:
    """``auto_review`` returning a non-empty list is also a refusal.

    The repair gathers per-scene work with ``return_exceptions=True``, so a
    VLM outage that used to escape as an exception now lands in the returned
    ``remaining`` list. The route used to discard that value, and the drive's
    scene gate would still reject the compose -- leaving the user holding a
    202 receipt for a Task id that never materialised (review #243 P1).
    """

    # pylint: disable=protected-access
    import api.file_execution_routes as routes
    from domain.errors import ConflictError
    from services.render_review import scene_review

    class _Projects:
        def read(self, _project_id):
            return SimpleNamespace(
                project=SimpleNamespace(
                    timelines=SimpleNamespace(items={"main": object()}),
                ),
            )

    services = SimpleNamespace(projects=_Projects())
    monkeypatch.setattr(
        scene_review,
        "collect_scene_review_targets",
        lambda _timeline: (["scene:hall"], []),
    )

    async def swallows_one(*_args, **_kwargs):
        # The real auto_review gathers with return_exceptions=True and
        # puts the still-broken scene id into its result, exactly like this.
        return ["scene:hall"]

    monkeypatch.setattr(scene_review, "auto_review_stale_scenes", swallows_one)

    with pytest.raises(ConflictError) as captured:
        asyncio.run(
            routes._preflight_scene_review(services, "project-1", "main"),
        )

    assert captured.value.details == {
        "code": "SCENE_REVIEW_INCOMPLETE",
        "scenes": ["scene:hall"],
    }
    assert "scene:hall" in str(captured.value)
