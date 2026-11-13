# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""
Explicit WorkGraph admission uses real durable approvals; providers are mocked.
"""

import asyncio
import dataclasses
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from api.dependencies import creator_error_handler, project_file_services
from api.file_execution_routes import router as execution_router
from api.project_file_routes import router as project_router
from domain.enums import TaskKind, TaskStatus
from domain.errors import CreatorError
from services.project_files import frontend_edit_hold
from services.project_files.json_pointer import hash_json_value
from services.file_agent_runtime import (
    AgentModelTurn,
    AgentToolCall,
    CallbackAgentChatClient,
    FileCreatorAgentRuntime,
)
from services.file_agent_runtime import driver as dm
from services.file_agent_runtime import work_scheduler as sm
from services.file_agent_runtime.work_graph import (
    WorkGraph,
    WorkNode,
    WorkNodeStatus,
)
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


def test_failed_receipt_reaches_agent_and_cannot_be_narrated_as_submitted(
    tmp_path,
    monkeypatch,
):
    pin(monkeypatch)
    failure = "已本地拦截，未调用图片模型：请修改项目中的 prompt，再请求生成。"
    graph = WorkGraph(
        generation=1,
        nodes=(
            WorkNode(
                node_id="visual:hero:v:base",
                kind="visual",
                label="角色基础图",
                status=WorkNodeStatus.DONE,
                target_ref="asset:hero",
            ),
            WorkNode(
                node_id="visual:hero:v:battle",
                kind="visual",
                label="角色状态图",
                status=WorkNodeStatus.FAILED,
                target_ref="asset:hero",
                error=failure,
            ),
            WorkNode(
                node_id="script:main",
                kind="script",
                label="序章剧本",
                status=WorkNodeStatus.STALE,
            ),
            WorkNode(
                node_id="bundle:project",
                kind="bundle",
                label="互动包",
                status=WorkNodeStatus.GATED,
                missing=("script:main",),
            ),
        ),
    )
    monkeypatch.setattr(dm, "derive_work_graph", lambda *_a, **_kw: graph)

    async def context(*_args, **_kwargs):
        return (
            services.projects.read("probe-project"),
            [],
            graph,
            {
                "visual:hero:v:battle": "FAILED",
            },
        )

    monkeypatch.setattr(dm, "ready_request_context", context)
    turns = 0

    async def model(messages, _tools):
        nonlocal turns
        turns += 1
        if turns == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="blocked-request",
                        name="request_workgraph_execution",
                        arguments={
                            "projectId": "probe-project",
                            "targetRefs": ["asset:hero"],
                            "kinds": ["visual"],
                        },
                    ),
                ),
            )
        result = json.loads(messages[-1]["content"])
        assert result["status"] == "PARTIAL"
        assert result["items"][1]["error"] == failure
        assert result["productionStatus"]["bundle"]["status"] == "gated"
        # Reproduce the observed model mistake, including streaming deltas.
        return AgentModelTurn(content="状态图正在提交制作，序章已合成，互动包可以下载。")

    services = create(tmp_path)
    runtime = FileCreatorAgentRuntime(
        services,
        model_client=CallbackAgentChatClient(model),
        poll_interval_seconds=0.01,
    )

    async def scenario():
        try:
            await runtime.start()
            runtime.notify("probe-project")
            await wait_for(lambda: turns == 2)
            await runtime.wait_until_idle("probe-project")
        finally:
            await runtime.stop()

    asyncio.run(scenario())
    records = services.sessions.list_messages("probe-project", "probe-session")
    final = [item for item in records if item.role == "assistant"][-1]
    text = final.content_parts[0].text
    assert "互动包尚未就绪" in text
    assert "角色状态图：生成失败" in text
    assert "正在提交制作" not in text
    assert "互动包可以下载" not in text
    deltas = [
        event.payload.get("delta", "")
        for event in services.sessions.list_events(
            "probe-project",
            "probe-session",
        )
        if event.event_type == "agent.message_delta"
        and event.payload.get("streamKind") == "text"
    ]
    assert "正在提交制作" not in "".join(deltas)
    assert not runtime.executions.list_tasks("probe-project")


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


def test_prompt_sync_gated_request_surfaces_diagnostic_fields(
    tmp_path,
    monkeypatch,
):
    """A prompt-sync GATED node must reach the agent with its precise gate.

    Locks in #7720 finding #1 at the driver boundary: the BLOCKED item
    carries ``missing`` + ``promptSyncRequired`` (not a bare GATED), and the
    public summary names the sync gate without leaking internal refs.
    """
    pin(monkeypatch)

    async def scenario():
        services = create(tmp_path)
        node = WorkNode(
            node_id="storyboard:e1",
            kind="storyboard",
            label="第一场 · 分镜",
            status=WorkNodeStatus.GATED,
            missing=("分镜内容与提示词待同步",),
            authored_text_gap=True,
            prompt_sync_required=True,
            command="GENERATE_STORYBOARD_IMAGE",
            target_ref="element:e1",
        )
        graph = WorkGraph(nodes=(node,), generation=1)

        async def fake_context(svcs, _execs, pid, **_kwargs):
            # Only the request path reads this; hand back the GATED node and
            # its pre-dispatch block reason (extra kwargs like
            # ``check_media_budget`` are irrelevant to this canned graph).
            return (
                svcs.projects.read(pid),
                [],
                graph,
                {"storyboard:e1": "GATED"},
            )

        monkeypatch.setattr(dm, "ready_request_context", fake_context)

        turns = 0

        async def model(_messages, _tools):
            nonlocal turns
            turns += 1
            if turns == 1:
                return AgentModelTurn(
                    tool_calls=(
                        AgentToolCall(
                            call_id="gated-call",
                            name="request_workgraph_execution",
                            arguments={
                                "projectId": "probe-project",
                                "targetRefs": ["element:e1"],
                                "kinds": ["storyboard"],
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
                lambda: any(
                    message.role == "tool"
                    for message in services.sessions.list_messages(
                        "probe-project",
                        "probe-session",
                    )
                ),
            )
            await runtime.wait_until_idle("probe-project")
        finally:
            await runtime.stop()

        results = [
            json.loads(message.content_parts[0].text)
            for message in services.sessions.list_messages(
                "probe-project",
                "probe-session",
            )
            if message.role == "tool"
        ]
        assert results, "blocked request must persist a tool result"
        result = results[0]
        assert result["status"] == "BLOCKED"
        item = result["items"][0]
        assert item["status"] == "BLOCKED"
        assert item["reason"] == "GATED"
        assert item["nodeId"] == "storyboard:e1"
        assert item["targetRef"] == "element:e1"
        assert item["promptSyncRequired"] is True
        assert item["missing"] == ["分镜内容与提示词待同步"]
        # Public summary names the gate; internal refs never leak.
        assert "同步分镜/提示词" in result["summary"]
        assert not calls, "a pre-dispatch block must not call the provider"

    asyncio.run(scenario())


def test_post_approval_prompt_sync_gate_surfaces_diagnostic_fields(
    tmp_path,
    monkeypatch,
):
    """A node gated *after* authorization must still name its precise gate.

    The pre-dispatch item is covered by
    ``test_prompt_sync_gated_request_surfaces_diagnostic_fields``; this locks
    the sibling re-check path in ``execute_one`` (driver.py) that re-reads
    the graph once the paid approval returns. If the selected node flips to a
    prompt-sync GATED state while the approval card is open, the BLOCKED item
    must carry ``missing`` + ``promptSyncRequired`` too (#7720 finding #1).
    """
    pin(monkeypatch)

    async def scenario():
        services = create(tmp_path)
        real_context = dm.ready_request_context
        reads = {"n": 0}

        async def fake_context(svcs, execs, pid, **kwargs):
            snapshot, tasks, graph, blocked = await real_context(
                svcs,
                execs,
                pid,
                **kwargs,
            )
            reads["n"] += 1
            if reads["n"] == 1:
                # First read: the visual node is READY and enters ``plans``.
                return snapshot, tasks, graph, blocked
            # Post-approval re-check: flip the selected node to prompt-sync
            # GATED, as if the prompts were edited while approval was open.
            # ``asset:hero`` is a visual node; prompt_sync_required is forced
            # here only to exercise the diagnostic path -- in production the
            # field is set on storyboard/video nodes, never on a bare visual.
            gated_nodes = tuple(
                dataclasses.replace(
                    node,
                    status=WorkNodeStatus.GATED,
                    prompt_sync_required=True,
                    missing=("分镜内容与提示词待同步",),
                )
                if node.target_ref == "asset:hero"
                else node
                for node in graph.nodes
            )
            gated_graph = WorkGraph(
                nodes=gated_nodes,
                generation=graph.generation,
            )
            gated_blocked = {
                **blocked,
                **{
                    node.node_id: "GATED"
                    for node in gated_nodes
                    if node.target_ref == "asset:hero"
                },
            }
            return snapshot, tasks, gated_graph, gated_blocked

        monkeypatch.setattr(dm, "ready_request_context", fake_context)

        turns = 0

        async def model(_messages, _tools):
            nonlocal turns
            turns += 1
            if turns == 1:
                return AgentModelTurn(
                    tool_calls=(
                        AgentToolCall(
                            call_id="post-approval-gate",
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
            await wait_for(
                lambda: any(
                    message.role == "tool"
                    for message in services.sessions.list_messages(
                        "probe-project",
                        "probe-session",
                    )
                ),
            )
            await runtime.wait_until_idle("probe-project")
        finally:
            await runtime.stop()

        results = [
            json.loads(message.content_parts[0].text)
            for message in services.sessions.list_messages(
                "probe-project",
                "probe-session",
            )
            if message.role == "tool"
        ]
        assert results, "the gated re-check must persist a tool result"
        result = results[0]
        assert result["status"] == "BLOCKED"
        item = result["items"][0]
        assert item["status"] == "BLOCKED"
        assert item["reason"] == "GATED"
        assert item["targetRef"] == "asset:hero"
        assert item["promptSyncRequired"] is True
        assert item["missing"] == ["分镜内容与提示词待同步"]
        assert "同步分镜/提示词" in result["summary"]
        # The re-check blocked before dispatch: no paid provider call.
        assert not calls

    asyncio.run(scenario())


def _project_api_client(services):
    app = FastAPI()
    app.add_exception_handler(CreatorError, creator_error_handler)
    app.include_router(project_router)
    app.include_router(execution_router)
    app.dependency_overrides[project_file_services] = lambda: services
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


@pytest.mark.parametrize("timing", ["before_request", "during_dispatch"])
def test_agent_workgraph_request_cannot_bypass_manual_hold(
    tmp_path,
    monkeypatch,
    timing,
):
    from services.file_agent_runtime.manual_regeneration_hold import (
        ManualRegenerationHoldStore,
        admission_guard,
    )

    pin(monkeypatch)

    async def scenario():
        services = create(tmp_path)
        turns = 0

        async def model(_messages, _tools):
            nonlocal turns
            turns += 1
            if turns == 1:
                return AgentModelTurn(
                    tool_calls=(
                        AgentToolCall(
                            call_id="held-work",
                            name="request_workgraph_execution",
                            arguments={
                                "projectId": "probe-project",
                                "targetRefs": ["asset:hero"],
                                "kinds": ["visual"],
                            },
                        ),
                    ),
                )
            return AgentModelTurn(content="Paused for manual inspection.")

        runtime = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(model),
            poll_interval_seconds=0.01,
        )
        _, _, graph, _ = await dm.ready_request_context(
            services,
            runtime.executions,
            "probe-project",
            check_media_budget=False,
        )
        node = next(item for item in graph.nodes if item.kind == "visual")
        upstream = WorkNode(
            node_id="storyboard:upstream",
            kind="storyboard",
            label="Upstream",
            status=WorkNodeStatus.DONE,
        )
        holds = ManualRegenerationHoldStore(services.root)

        def hold():
            operation = holds.begin(
                "probe-project",
                upstream,
                (
                    upstream,
                    dataclasses.replace(node, deps=(upstream.node_id,)),
                ),
            )
            holds.admitted(operation)

        if timing == "before_request":
            hold()

        async def dispatch(*_args, **_kwargs):
            hold()
            with admission_guard(services.root, "probe-project"):
                pytest.fail("late manual hold was bypassed")

        monkeypatch.setattr(runtime.work_scheduler, "dispatch_node", dispatch)
        try:
            await runtime.start()
            runtime.notify("probe-project")
            if timing == "during_dispatch":
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
            await wait_for(lambda: turns >= 2)
            await runtime.wait_until_idle("probe-project")
            results = [
                json.loads(message.content_parts[0].text)
                for message in services.sessions.list_messages(
                    "probe-project",
                    "probe-session",
                )
                if message.role == "tool"
            ]
            assert results[0]["status"] == "BLOCKED"
            assert not runtime.executions.list_tasks("probe-project")
            if timing == "before_request":
                assert (
                    results[0]["items"][0]["reason"]
                    == "MANUAL_REGENERATION_HOLD"
                )
                assert not runtime.executions.list_execution_authorizations(
                    "probe-project",
                )
        finally:
            await runtime.stop()

    asyncio.run(scenario())


async def _saved_prompt(services, scope, suffix):
    base = services.projects.read("probe-project")
    if scope == "visual":
        pointer = "/visual/entities/items/hero/variants/items/base/prompt"
    else:
        field = (
            "storyboard_prompt" if scope == "storyboard" else "video_prompt"
        )
        pointer = (
            "/timelines/items/timeline:main/elements_by_id/e1/creation/"
            f"{field}"
        )
    previous = base.project.model_dump(mode="json")
    for part in pointer.strip("/").split("/"):
        previous = previous[part]
    async with _project_api_client(services) as client:
        response = await client.patch(
            "/projects/probe-project/project",
            json={
                "clientCommandId": f"save-{base.generation}",
                "editSessionId": "prompt-editor",
                "baseGeneration": base.generation,
                "baseEtag": base.etag,
                "operations": [
                    {
                        "op": "replace",
                        "path": pointer,
                        "value": previous + suffix,
                        "expectedValueHash": hash_json_value(previous),
                    },
                ],
            },
        )
    assert response.status_code == 200, response.text
    saved = services.projects.read("probe-project")
    assert response.json()["etag"] == saved.etag
    if scope != "visual":
        assert frontend_edit_hold.hold_remaining("probe-project", "e1") > 0
    return saved


@pytest.mark.parametrize("scope", ["visual", "storyboard", "r2v", "t2v"])
@pytest.mark.parametrize(
    "case",
    [
        "unchanged",
        "unchanged-etag",
        "saved-edit",
        "no-etag",
        "edit-again",
        "old-task",
        "full-input-drift",
        "provider-drift",
        "model-drift",
    ],
)
def test_saved_prompt_authorization_rebinding(
    tmp_path,
    monkeypatch,
    scope,
    case,
):
    # Keep the media/authorization matrix and its assertions together.
    # pylint: disable=too-many-statements
    from services.project_files.models import TimelineElement
    from test_work_graph import _add_element, _element, _select_slot

    pin(monkeypatch)
    monkeypatch.setattr(frontend_edit_hold, "_holds", {})

    async def scenario():
        # Branches cover distinct edit, replay, and provider/model drift cases.
        # pylint: disable=too-many-branches,too-many-statements
        services = create(tmp_path)
        if scope != "visual":
            base = services.projects.read("probe-project")
            project = base.project.model_copy(deep=True)
            element = (
                TimelineElement.model_validate(
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
                if scope == "t2v"
                else _element("e1")
            )
            _add_element(project, element)
            if scope == "r2v":
                _select_slot(
                    project,
                    slot_id="element:e1:storyboard",
                    kind="r2v_storyboard_image",
                    owner_ref="element:e1",
                    version_id="art:sb",
                )
            await services.commit_candidate(
                base=base,
                candidate=project.model_dump(mode="json"),
                origin="frontend_edit",
                review_policy="auto_fix",
                caused_by_request_id="setup-element",
            )
        target = "asset:hero" if scope == "visual" else "element:e1"
        kind = scope if scope in {"visual", "storyboard"} else "video"
        turns = 0

        async def model(_messages, _tools):
            nonlocal turns
            turns += 1
            if turns == 1:
                return AgentModelTurn(
                    tool_calls=(
                        AgentToolCall(
                            call_id="saved-prompt",
                            name="request_workgraph_execution",
                            arguments={
                                "projectId": "probe-project",
                                "targetRefs": [target],
                                "kinds": [kind],
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
        approved = asyncio.Event()
        resume = asyncio.Event()
        original_wait = runtime._await_execution_authorization

        async def pause_after_approval(**kwargs):
            authorization_id = await original_wait(
                project_id=kwargs.pop("project_id"),
                session_id=kwargs.pop("session_id"),
                parent_run_id=kwargs.pop("parent_run_id"),
                specialist_run_id=kwargs.pop("specialist_run_id"),
                round_id=kwargs.pop("round_id"),
                fence=kwargs.pop("fence"),
                request=kwargs.pop("request"),
                common=kwargs.pop("common"),
                call_id=kwargs.pop("call_id"),
                spec=kwargs.pop("spec"),
                arguments=kwargs.pop("arguments"),
                tools=kwargs.pop("tools"),
                **kwargs,
            )
            approved.set()
            await resume.wait()
            return authorization_id

        monkeypatch.setattr(
            runtime,
            "_await_execution_authorization",
            pause_after_approval,
        )
        try:
            initial, _, graph, _ = await dm.ready_request_context(
                services,
                runtime.executions,
                "probe-project",
                check_media_budget=False,
            )
            node = next(
                n
                for n in graph.nodes
                if n.target_ref == target and n.kind == kind
            )
            original_plan = dm.requested_work_node(initial, node)
            old_ledger = runtime.work_scheduler._ledger_fingerprint(node)
            await runtime.start()
            runtime.notify("probe-project")
            await wait_for(
                lambda: runtime.executions.list_execution_authorizations(
                    "probe-project",
                ),
            )
            record = runtime.executions.list_execution_authorizations(
                "probe-project",
            )[0]
            assert record.status is ExecutionAuthorizationStatus.PENDING
            assert record.scope["workGraph"] == {
                "nodeId": node.node_id,
                "fingerprint": original_plan.fingerprint,
                "provider": record.requested_provider,
                "model": record.requested_model,
            }
            assert not calls
            saved = initial
            if not case.startswith("unchanged"):
                saved = await _saved_prompt(
                    services,
                    scope,
                    " Warm golden lighting.",
                )
            snapshot, _, saved_graph, blocked = await dm.ready_request_context(
                services,
                runtime.executions,
                "probe-project",
                check_media_budget=False,
            )
            saved_node = saved_graph.by_id[node.node_id]
            held = scope != "visual" and not case.startswith("unchanged")
            if held:
                assert blocked[node.node_id] == "EDIT_IN_PROGRESS"
            else:
                assert node.node_id not in blocked
            saved_plan = dm.requested_work_node(snapshot, saved_node)
            saved_ledger = runtime.work_scheduler._ledger_fingerprint(
                saved_node,
            )
            with_etag = case not in {"unchanged", "no-etag"}
            payload = {
                "authorizationToken": record.authorization_token,
                "provider": record.requested_provider,
                "model": record.requested_model,
                "maxCost": 0,
                "maxCandidates": 1,
                **({"projectEtag": saved.etag} if with_etag else {}),
            }
            async with _project_api_client(services) as client:
                for _ in range(2):
                    result = await client.post(
                        f"/projects/probe-project/execution-authorizations/"
                        f"{record.authorization_id}/approve",
                        headers={"Idempotency-Key": "saved-approval"},
                        json=payload,
                    )
                    assert result.status_code == 200, result.text
                    assert result.json()["status"] == "APPROVED"
            await asyncio.wait_for(approved.wait(), timeout=3)
            decision = runtime.executions.get_execution_authorization(
                "probe-project",
                record.authorization_id,
            ).decision
            if with_etag:
                assert decision["workGraph"] == {
                    "nodeId": node.node_id,
                    "etag": saved.etag,
                    "fingerprint": saved_plan.fingerprint,
                    "ledgerFingerprint": saved_ledger,
                }
            else:
                assert "workGraph" not in decision
            if held:
                assert (
                    frontend_edit_hold.hold_remaining("probe-project", "e1")
                    > 0
                )
                _, _, _, still_blocked = await dm.ready_request_context(
                    services,
                    runtime.executions,
                    "probe-project",
                    check_media_budget=False,
                )
                assert still_blocked[node.node_id] == "EDIT_IN_PROGRESS"
                _, _, _, confirmed_blocked = await dm.ready_request_context(
                    services,
                    runtime.executions,
                    "probe-project",
                    check_media_budget=False,
                    confirmed_project_etag=saved.etag,
                    confirmed_node_id=node.node_id,
                )
                assert node.node_id not in confirmed_blocked
                # Confirming a video does not confirm the same element's
                # storyboard (or vice versa).
                for sibling in saved_graph.nodes:
                    if (
                        sibling.target_ref == target
                        and sibling.node_id != node.node_id
                    ):
                        assert (
                            confirmed_blocked[sibling.node_id]
                            == "EDIT_IN_PROGRESS"
                        )
            if case == "edit-again":
                await _saved_prompt(
                    services,
                    scope,
                    " A different camera angle.",
                )
            elif case == "full-input-drift":
                base = services.projects.read("probe-project")
                candidate = base.project.model_dump(mode="json")
                candidate["settings"]["language"] = "en-US"
                await services.commit_candidate(
                    base=base,
                    candidate=candidate,
                    origin="frontend_edit",
                    review_policy="auto_fix",
                    caused_by_request_id="later-setting",
                )
                latest, _, latest_graph, _ = await dm.ready_request_context(
                    services,
                    runtime.executions,
                    "probe-project",
                    check_media_budget=False,
                )
                latest_node = latest_graph.by_id[node.node_id]
                assert (
                    runtime.work_scheduler._ledger_fingerprint(latest_node)
                    == saved_ledger
                )
                assert (
                    dm.requested_work_node(latest, latest_node).fingerprint
                    != saved_plan.fingerprint
                )
                # Even after grace naturally expires, the full approved
                # fingerprint (not only the ledger slot) must still match.
                expired = (
                    frontend_edit_hold.time.monotonic()
                    + frontend_edit_hold.FRONTEND_EDIT_GRACE_SECONDS
                    + 1
                )
                monkeypatch.setattr(
                    frontend_edit_hold,
                    "time",
                    SimpleNamespace(monotonic=lambda: expired),
                )
            elif case in {"provider-drift", "model-drift"}:
                monkeypatch.setattr(
                    dm,
                    "_execution_provider_model",
                    lambda *_: (
                        ("other-provider", "probe-model")
                        if case == "provider-drift"
                        else ("probe-provider", "other-model")
                    ),
                )
            if case == "old-task":
                old_key = (
                    f"dag-{node.node_id}-"
                    f"{runtime.work_scheduler._dispatch_slot(old_ledger)}"
                )
                runtime.executions.create_task(
                    TaskRecord(
                        task_id="old-paid-task",
                        project_id="probe-project",
                        kind=TaskKind.IMAGE_GENERATION,
                        status=TaskStatus.QUEUED,
                        request_fingerprint="old-inputs",
                        idempotency_key=old_key,
                        caused_by_request_id=old_key,
                        metadata={"targetRef": target},
                    ),
                )
                for before, after in (
                    (TaskStatus.QUEUED, TaskStatus.RUNNING),
                    (TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
                ):
                    runtime.executions.transition_task(
                        "probe-project",
                        "old-paid-task",
                        expected_status=before,
                        status=after,
                    )
                assert old_ledger != saved_ledger
            resume.set()
            await wait_for(lambda: turns >= 2)
            await runtime.wait_until_idle("probe-project")
            results = [
                json.loads(m.content_parts[0].text)
                for m in services.sessions.list_messages(
                    "probe-project",
                    "probe-session",
                )
                if m.role == "tool"
            ]
            assert len(results) == 1
            item = results[0]["items"][0]
            if case in {
                "no-etag",
                "edit-again",
                "full-input-drift",
                "provider-drift",
                "model-drift",
            }:
                assert item["reason"] == (
                    "EDIT_IN_PROGRESS"
                    if held and case in {"no-etag", "edit-again"}
                    else "APPROVED_INPUTS_CHANGED"
                )
                assert not calls
                assert not runtime.executions.list_tasks("probe-project")
            else:
                assert item["status"] == "SUCCEEDED", item
                assert not item.get("replayed")
                assert calls == [node.node_id]
                task = runtime.executions.get_task(
                    "probe-project",
                    item["taskId"],
                )
                assert task.idempotency_key == (
                    f"dag-{node.node_id}-"
                    f"{runtime.work_scheduler._dispatch_slot(saved_ledger)}"
                )
            assert (
                len(
                    runtime.executions.list_execution_authorizations(
                        "probe-project",
                    ),
                )
                == 1
            )
        finally:
            resume.set()
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
