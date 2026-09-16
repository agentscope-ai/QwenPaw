# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""
Explicit WorkGraph admission uses real durable approvals; providers are mocked.
"""

import asyncio
from types import SimpleNamespace


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


def test_required_approval_and_repeated_tool_only_one_real_admission(
    tmp_path,
    monkeypatch,
):
    pin(monkeypatch)

    async def scenario():
        services = create(tmp_path)
        turns = 0

        async def model(_messages, _tools):
            nonlocal turns
            turns += 1
            if turns <= 2:
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
            approve(runtime, authorization)
            await wait_for(lambda: turns >= 3)
            await runtime.wait_until_idle("probe-project")
            assert len(calls) == 1
            assert (
                len(
                    runtime.executions.list_execution_authorizations(
                        "probe-project",
                    ),
                )
                == 1
            )
            assert len(runtime.executions.list_tasks("probe-project")) == 1
        finally:
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


def fake_dispatch(runtime, calls):
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
        runtime.executions.transition_task(
            project_id,
            task.task_id,
            expected_status=TaskStatus.RUNNING,
            status=TaskStatus.SUCCEEDED,
        )
        return SimpleNamespace(task_id=task.task_id)

    runtime.work_scheduler.dispatch_node = dispatch
