# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""
Explicit WorkGraph admission uses real durable approvals; providers are mocked.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from services.file_agent_runtime import (
    AgentModelTurn,
    AgentToolCall,
    CallbackAgentChatClient,
    FileCreatorAgentRuntime,
)
from services.file_agent_runtime import driver as dm
from services.file_agent_runtime import work_scheduler as sm
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project, VisualEntity, VisualVariant
from services.runtime_files.execution_models import (
    TaskRecord,
    ExecutionAuthorizationStatus,
)
from services.runtime_files.models import (
    MessageChannel,
    MessageClassification,
    ReviewBoundary,
)
from domain.enums import TaskKind, TaskStatus


async def wait_for(predicate, seconds=12):
    limit = asyncio.get_running_loop().time() + seconds
    while not predicate():
        if asyncio.get_running_loop().time() > limit:
            raise AssertionError("probe wait timed out")
        await asyncio.sleep(0.01)


def create(temporary):
    services = CreatorFileServices.create(temporary.resolve())
    project = Project.new(project_id="probe-project", name="Independent probe")
    project.visual.entities.items["hero"] = VisualEntity(
        entity_id="hero",
        kind="character",
        name="Hero",
        required_variant_ids=["base"],
        variants={
            "items": {
                "base": VisualVariant(
                    variant_id="base",
                    prompt="Adult in a grey coat.",
                ),
            },
            "order": ["base"],
        },
    )
    project.visual.entities.order.append("hero")

    def initialize(staged):
        services.sessions.initialize_staged_project(
            staged,
            "probe-project",
            session_id="probe-session",
            conversation_id="probe-conversation",
            initial_goal="Generate only this character.",
            goal_id="probe-goal",
            initial_message_id="probe-message",
            initial_client_message_id="probe-client",
        )

    snapshot = services.projects.create(
        project,
        initialize_staged_project=initialize,
    )
    services.poller.note_commit(snapshot)
    return services


def pin(monkeypatch):
    monkeypatch.setattr(
        dm,
        "get_execution_authorization_mode",
        lambda: "required",
    )
    monkeypatch.setattr(
        sm,
        "get_execution_authorization_mode",
        lambda: "required",
    )
    monkeypatch.setattr(dm, "get_creation_checkpoint_mode", lambda: "skip")
    monkeypatch.setattr(dm, "get_media_review_mode", lambda: "required")
    monkeypatch.setattr(
        dm,
        "_execution_provider_model",
        lambda *_args, **_kw: ("probe-provider", "probe-model"),
    )


@pytest.mark.parametrize("cancel_first", [False, True])
def test_required_approval_and_repeated_tool_only_one_real_admission(
    tmp_path,
    monkeypatch,
    cancel_first,
):
    pin(monkeypatch)

    async def scenario():
        services = create(tmp_path)
        turns = 0

        async def model(_messages, _tools):
            nonlocal turns
            turns += 1
            if turns <= 2 or (cancel_first and turns == 4):
                return AgentModelTurn(
                    tool_calls=(
                        AgentToolCall(
                            call_id=f"probe-call-{turns}",
                            name="request_workgraph_execution",
                            arguments={
                                "projectId": "probe-project",
                                "targetRefs": ["asset:hero"],
                                "kinds": ["visual"],
                            },
                        ),
                    ),
                )
            return AgentModelTurn(content="Complete.")

        runtime = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(model),
            poll_interval_seconds=0.01,
        )
        calls = []

        fake_dispatch(runtime, calls)
        try:
            await runtime.start()
            runtime.notify("probe-project")
            await wait_for(
                lambda: len(
                    runtime.executions.list_execution_authorizations(
                        "probe-project",
                    ),
                )
                == 1,
            )
            assert not calls, "admission happened before approval"
            authorization = runtime.executions.list_execution_authorizations(
                "probe-project",
            )[0]
            if cancel_first:
                runtime.executions.decide_execution_authorization(
                    "probe-project",
                    authorization.authorization_id,
                    authorization_token=authorization.authorization_token,
                    status=ExecutionAuthorizationStatus.REJECTED,
                )
            else:
                approve(runtime, authorization)
            await wait_for(lambda: turns >= 3)
            await runtime.wait_until_idle("probe-project")
            assert len(calls) == (0 if cancel_first else 1)
            assert (
                len(
                    runtime.executions.list_execution_authorizations(
                        "probe-project",
                    ),
                )
                == 1
            )
            assert len(runtime.executions.list_tasks("probe-project")) == len(
                calls,
            )
            if cancel_first:
                results = [
                    json.loads(message.content_parts[0].text)
                    for message in services.sessions.list_messages(
                        "probe-project",
                        "probe-session",
                    )
                    if message.role == "tool"
                ]
                assert len(results) == 2
                assert all(
                    result["items"][0]["reason"] == "AUTHORIZATION_REJECTED"
                    for result in results
                )
                services.sessions.admit_user_request(
                    "probe-project",
                    "probe-session",
                    "probe-conversation",
                    request_id="renewed-request",
                    client_message_id="renewed-client",
                    content_parts=[
                        {
                            "type": "text",
                            "text": "Please generate that image now.",
                        },
                    ],
                    channel=MessageChannel.AGENTDOCK,
                    classification=MessageClassification.MUTATION_INSTRUCTION,
                )
                runtime.notify("probe-project")
                await wait_for(
                    lambda: len(
                        runtime.executions.list_execution_authorizations(
                            "probe-project",
                        ),
                    )
                    == 2,
                )
                assert not calls
                records = runtime.executions.list_execution_authorizations(
                    "probe-project",
                )
                renewed = next(
                    record
                    for record in records
                    if record.status is ExecutionAuthorizationStatus.PENDING
                )
                approve(runtime, renewed)
                await wait_for(lambda: turns >= 5)
                await runtime.wait_until_idle("probe-project")
                assert len(calls) == 1
        finally:
            await runtime.stop()

    asyncio.run(scenario())


def test_review_opened_during_authorization_keeps_its_wait_reason(
    tmp_path,
    monkeypatch,
):
    pin(monkeypatch)

    async def scenario():
        services = create(tmp_path)

        async def model(_messages, _tools):
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="pending-approval",
                        name="request_workgraph_execution",
                        arguments={
                            "projectId": "probe-project",
                            "targetRefs": ["asset:hero"],
                            "kinds": ["visual"],
                        },
                    ),
                ),
            )

        runtime = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(model),
            poll_interval_seconds=0.01,
        )
        calls = []
        fake_dispatch(runtime, calls)
        try:
            await runtime.start()
            runtime.notify("probe-project")
            await wait_for(
                lambda: runtime.executions.list_execution_authorizations(
                    "probe-project",
                ),
            )
            authorization = runtime.executions.list_execution_authorizations(
                "probe-project",
            )[0]
            base = services.projects.read("probe-project")
            candidate = base.project.model_dump(mode="json")
            candidate["description"] = "Another edit awaits human review."
            await services.commit_candidate(
                base=base,
                candidate=candidate,
                origin="agentdock_idle_goal",
                review_policy="require_review",
                review_boundary=ReviewBoundary(
                    request_message_seq=2,
                    request_id="other-edit",
                    accepted_generation=base.generation,
                    accepted_etag=base.etag,
                ),
                caused_by_request_id="other-edit",
                caused_by_message_seq=2,
            )
            approve(runtime, authorization)
            await runtime.wait_until_idle("probe-project")
            results = [
                json.loads(message.content_parts[0].text)
                for message in services.sessions.list_messages(
                    "probe-project",
                    "probe-session",
                )
                if message.role == "tool"
            ]
            assert results[0]["items"][0]["reason"] == "WAITING_REVIEW"
            assert results[0]["items"][0]["executionAuthorizationId"] == (
                authorization.authorization_id
            )
            assert not calls
            assert services.reviews.active("probe-project") is not None
        finally:
            await runtime.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("superseded", [False, True])
def test_authorized_provider_outlives_feedback_but_not_hard_stop(
    tmp_path,
    monkeypatch,
    superseded,
):
    pin(monkeypatch)

    async def scenario():
        services = create(tmp_path)
        release = asyncio.Event()
        started = asyncio.Event()

        async def model(_messages, _tools):
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="media-before-feedback",
                        name="request_workgraph_execution",
                        arguments={
                            "projectId": "probe-project",
                            "targetRefs": ["asset:hero"],
                            "kinds": ["visual"],
                        },
                    ),
                ),
            )

        runtime = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(model),
            poll_interval_seconds=0.01,
        )
        calls = []
        fake_dispatch(runtime, calls, release=release, started=started)
        try:
            await runtime.start()
            runtime.notify("probe-project")
            await wait_for(
                lambda: runtime.executions.list_execution_authorizations(
                    "probe-project",
                ),
            )
            approve(
                runtime,
                runtime.executions.list_execution_authorizations(
                    "probe-project",
                )[0],
            )
            await asyncio.wait_for(started.wait(), timeout=3)
            handle = runtime._active["probe-project"]
            await runtime.interrupt(
                "probe-project",
                superseded=superseded,
                reason="agentdock_message" if superseded else "user_interrupt",
                expected_run_id=handle.run_id,
            )
            await asyncio.gather(handle.task, return_exceptions=True)
            release.set()
            if superseded:
                await wait_for(
                    lambda: runtime.executions.list_tasks("probe-project")[
                        0
                    ].status
                    is TaskStatus.SUCCEEDED,
                )
            else:
                # The HTTP hard-stop performs this durable cleanup after
                # signalling process-local jobs. Exercise the same boundary.
                from api.file_session_routes import (
                    _cancel_active_project_tasks_sync,
                )

                _cancel_active_project_tasks_sync(services, "probe-project")
                assert (
                    runtime.executions.list_tasks("probe-project")[0].status
                    is TaskStatus.CANCELLED
                )
            assert len(calls) == 1
        finally:
            release.set()
            await runtime.stop()

    asyncio.run(scenario())


def approve(runtime, record):
    runtime.executions.decide_execution_authorization(
        "probe-project",
        record.authorization_id,
        authorization_token=record.authorization_token,
        status=ExecutionAuthorizationStatus.APPROVED,
        decision={
            "provider": record.requested_provider,
            "model": record.requested_model,
            "maxCost": 0,
            "maxCandidates": 1,
        },
    )


def fake_dispatch(runtime, calls, *, release=None, started=None):
    async def dispatch(project_id, node, fingerprint, **kwargs):
        snapshot = runtime.services.projects.read(project_id)
        assert kwargs["expected_object_versions"] == (
            f"project:{snapshot.etag}:work-graph",
        )
        calls.append(node.node_id)
        slot = runtime.work_scheduler._dispatch_slot(fingerprint)
        key = f"dag-{node.node_id}-{slot}"
        task = runtime.executions.create_task(
            TaskRecord(
                task_id=f"paid-task-{len(calls)}",
                project_id=project_id,
                kind=TaskKind.IMAGE_GENERATION,
                status=TaskStatus.QUEUED,
                request_fingerprint="probe-input",
                idempotency_key=key,
                caused_by_request_id=key,
                metadata={"targetRef": node.target_ref},
            ),
        )
        runtime.executions.transition_task(
            project_id,
            task.task_id,
            expected_status=TaskStatus.QUEUED,
            status=TaskStatus.RUNNING,
        )
        if started is not None:
            started.set()
        if release is not None:
            await release.wait()
        runtime.executions.transition_task(
            project_id,
            task.task_id,
            expected_status=TaskStatus.RUNNING,
            status=TaskStatus.SUCCEEDED,
        )
        return SimpleNamespace(task_id=task.task_id)

    runtime.work_scheduler.dispatch_node = dispatch
