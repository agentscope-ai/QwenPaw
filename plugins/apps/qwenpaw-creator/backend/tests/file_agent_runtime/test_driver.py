# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,protected-access,too-many-statements
# pylint: disable=unused-argument,use-implicit-booleaness-not-comparison
from __future__ import annotations

import asyncio
import hashlib
import io
import json

import pytest
from PIL import Image

from api.file_asset_routes import _AssetInput, _ingest_many_sync
from services.file_agent_runtime import (
    AgentModelConfigurationError,
    AgentModelTurn,
    AgentRunStatus,
    AgentToolCall,
    CallbackAgentChatClient,
    FileCreatorAgentRuntime,
)
from services.file_agent_runtime.driver import (
    _ToolArgumentProgressReporter,
    _specialist_tool_recovery,
    _tool_call_transport_metadata,
)
from services.file_agent_runtime.prompts import render_creator_system_prompt
from services.observability import read_trace_records
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project, VisualEntity
from services.project_files.review import ReviewDecisionItem
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.models import (
    CreatorMessageRecord,
    MessageChannel,
    MessageClassification,
    RuntimeProjectState,
)
from services.runtime_files.execution_models import (
    ExecutionAuthorizationStatus,
)
from services.specialist_tools import SpecialistToolResult

pytestmark = pytest.mark.unit


PROJECT_ID = "project-1"
SESSION_ID = "session-1"
CONVERSATION_ID = "conversation-1"
GOAL_ID = "goal-1"


def _png_bytes_for_grounding() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 12), color="white").save(output, format="PNG")
    return output.getvalue()


def _record(
    seq: int,
    *,
    role: str = "tool",
    source: str = "runtime_action_result",
    text: str = "",
    metadata: dict | None = None,
) -> CreatorMessageRecord:
    return CreatorMessageRecord(
        message_id=f"message-{seq}",
        project_id=PROJECT_ID,
        creator_session_id=SESSION_ID,
        conversation_id=CONVERSATION_ID,
        message_seq=seq,
        role=role,
        content_parts=[{"type": "text", "text": text}],
        source=source,
        channel=MessageChannel.RUNTIME,
        metadata=metadata or {},
    )


def _snapshot_text(
    generation: int,
    *,
    padding: str = "",
    extra: dict | None = None,
) -> str:
    payload = {
        "project": {"project_id": PROJECT_ID, "generation": generation},
        "generation": generation,
        "etag": f"etag-{generation}",
        **(extra or {}),
    }
    if padding:
        payload["project"]["padding"] = padding * 8000
    return json.dumps(payload)


def test_tool_argument_fragments_are_aggregated_and_persisted_once() -> None:
    emitted: list[tuple[str, int, int, bool]] = []
    fragment = "abcdefghijkl"
    raw = fragment * 2_140
    call = AgentToolCall(
        call_id="call-large",
        name="jq_project",
        arguments={"projectId": PROJECT_ID},
        raw_arguments=raw,
        raw_arguments_bytes=len(raw.encode("utf-8")),
        provider_chunk_count=2_140,
    )

    async def scenario() -> None:
        async def emit(tool_call_id, state, complete) -> None:
            emitted.append(
                (
                    tool_call_id,
                    state.received_bytes,
                    state.provider_chunk_count,
                    complete,
                ),
            )

        reporter = _ToolArgumentProgressReporter(emit)
        for _ in range(2_140):
            await reporter.feed("call-large", "jq_project", fragment)
        await reporter.finish((call,))

    asyncio.run(scenario())

    assert len(emitted) < 30
    assert emitted[0][3] is False
    assert emitted[-1] == ("call-large", len(raw), 2_140, True)
    transport = _tool_call_transport_metadata(call)
    assert transport["rawArguments"] == raw
    assert transport["providerChunkCount"] == 2_140


def test_stale_project_snapshots_are_elided_from_the_continuation() -> None:
    """Only the newest runtime project echo survives prompt assembly.

    A 50-element production run accumulated 18 full project.json echoes
    (2.09MB) in one Conversation and every model call failed with an
    input-length 400. Older echoes carry no information the model cannot
    get from the latest snapshot, so they collapse to change receipts;
    durable history keeps every byte.
    """

    from services.file_agent_runtime.driver import _continuation_message_text

    old_snapshot = _snapshot_text(
        11,
        padding="x",
        extra={
            "transactionId": "transaction-11",
            "changedPointers": ["/name"],
        },
    )
    prior = [
        _record(1, role="user", source="user", text="把故事写完"),
        _record(
            2,
            text=old_snapshot,
            metadata={
                "toolName": "jq_project",
                "resultKind": "project_snapshot",
                "transactionId": "transaction-11",
                "changedPointers": ["/name"],
            },
        ),
        _record(3, role="assistant", source="creator_agent", text="写好了"),
        _record(
            4,
            text=_snapshot_text(113, padding="y"),
            metadata={
                "toolName": "read_project",
                "resultKind": "project_snapshot",
            },
        ),
    ]
    request = _record(5, role="user", source="user", text="继续")

    rendered = _continuation_message_text(request, prior)

    assert "x" * 100 not in rendered
    assert "project_change_receipt" in rendered
    assert "transaction-11" in rendered
    assert "changedPointers" in rendered
    assert "/name" in rendered
    assert "y" * 100 in rendered
    assert "把故事写完" in rendered
    assert "写好了" in rendered


def test_ai_edit_idempotency_can_be_scoped_to_one_model_tool_call() -> None:
    from services.file_agent_runtime.driver import (
        _specialist_tool_invocation_id,
    )

    arguments = {
        "projectId": PROJECT_ID,
        "targetRef": "timeline:timeline:main",
        "arguments": {"operation": "execute"},
    }

    def invocation_id(tool: str, call_id: str) -> str:
        return _specialist_tool_invocation_id(
            "specialist-run-1",
            tool,
            arguments,
            call_id=call_id,
        )

    # ai_edit is scoped per tool call: replays reuse, retries get fresh ids.
    assert invocation_id("ai_edit", "tool-call-1") == invocation_id(
        "ai_edit",
        "tool-call-1",
    )
    assert invocation_id("ai_edit", "tool-call-2") != invocation_id(
        "ai_edit",
        "tool-call-1",
    )
    # Other media tools stay idempotent across retried tool calls.
    assert invocation_id("image_generation", "tool-call-2") == invocation_id(
        "image_generation",
        "tool-call-1",
    )
    assert "file_id=null" in _specialist_tool_recovery("ai_edit")


def _create_project(tmp_path, *, initial_goal: str | None):
    services = CreatorFileServices.create(tmp_path.resolve())

    def initialize(staged_root) -> None:
        services.sessions.initialize_staged_project(
            staged_root,
            PROJECT_ID,
            session_id=SESSION_ID,
            conversation_id=CONVERSATION_ID,
            initial_goal=initial_goal,
            goal_id=GOAL_ID if initial_goal is not None else None,
            initial_message_id="message-initial"
            if initial_goal is not None
            else None,
            initial_client_message_id="client-initial"
            if initial_goal is not None
            else None,
        )

    project = Project.new(project_id=PROJECT_ID, name="Initial")
    project.visual.entities.items["hero"] = VisualEntity(
        entity_id="hero",
        kind="character",
        name="Hero",
        required_variant_ids=[],
    )
    project.visual.entities.order.append("hero")
    snapshot = services.projects.create(
        project,
        initialize_staged_project=initialize,
    )
    services.poller.note_commit(snapshot)
    return services, snapshot


def _edit_client(*, description: str):
    turn = 0

    async def callback(messages, tools):
        nonlocal turn
        assert {item["function"]["name"] for item in tools} == {
            "read_project",
            "read_project_file",
            "jq_project",
            "patch_project",
            "ground_prompt_context",
            "ground_image_objects",
            "elements_at",
            "delegate_to_agent",
        }
        # The role prompt and static Pydantic schema form one stable system prompt.
        assert messages[0]["content"] == render_creator_system_prompt(
            project_id=PROJECT_ID,
        )
        assert "# Workspace 基础 Schema" in messages[0]["content"]
        assert "PROJECT_JSON_SCHEMA=" in messages[0]["content"]
        assert "ground_image_objects" in messages[0]["content"]
        turn += 1
        if turn == 1:
            return _read_call("read-1")
        if turn == 2:
            observed = json.loads(messages[-1]["content"])
            return _tool_turn(
                call_id="write-1",
                name="jq_project",
                arguments={
                    "projectId": PROJECT_ID,
                    "baseEtag": observed["etag"],
                    "program": ".description = $description",
                    "stringArgs": {"description": description},
                },
            )
        return AgentModelTurn(content="项目说明已更新。")

    return CallbackAgentChatClient(callback)


def _tool_turn(**tool_call_kwargs) -> AgentModelTurn:
    return AgentModelTurn(tool_calls=(AgentToolCall(**tool_call_kwargs),))


def _read_call(call_id: str) -> AgentModelTurn:
    return _tool_turn(
        call_id=call_id,
        name="read_project",
        arguments={"projectId": PROJECT_ID},
    )


def _delegate_call(
    call_id: str,
    *,
    role: str,
    target_refs: list[str],
    task: str,
) -> AgentModelTurn:
    return _tool_turn(
        call_id=call_id,
        name="delegate_to_agent",
        arguments={"role": role, "target_refs": target_refs, "task": task},
    )


def _media_call(
    call_id: str,
    *,
    name: str,
    target_ref: str,
    arguments: dict,
) -> AgentModelTurn:
    return _tool_turn(
        call_id=call_id,
        name=name,
        arguments={
            "projectId": PROJECT_ID,
            "targetRef": target_ref,
            "arguments": arguments,
        },
    )


def _driver(services, model, **kwargs) -> FileCreatorAgentRuntime:
    kwargs.setdefault("poll_interval_seconds", 0.01)
    client = (
        model
        if isinstance(model, CallbackAgentChatClient)
        else CallbackAgentChatClient(model)
    )
    return FileCreatorAgentRuntime(services, model_client=client, **kwargs)


async def _wait_consumed(services, seq: int = 1) -> None:
    await _wait_for(
        lambda: services.sessions.get_project_session(
            PROJECT_ID,
        ).last_consumed_message_seq
        == seq,
    )


async def _wait_session_status(services, status: str) -> None:
    await _wait_for(
        lambda: services.sessions.get_project_session(PROJECT_ID).status.value
        == status,
    )


async def _run_to_idle(driver, services, seq: int = 1, *, error: bool = False):
    """Start the driver, feed it one notify, and wait for the run to settle."""

    await driver.start()
    driver.notify(PROJECT_ID)
    if error:
        await _wait_session_status(services, "ERROR")
    else:
        await _wait_consumed(services, seq)
    await driver.wait_until_idle(PROJECT_ID)


def _authorization_gate_modes(monkeypatch, *, authorization: str) -> None:
    """Pin the authorization gate; creation pit stops are covered by
    test_creation_checkpoints.py."""

    import services.file_agent_runtime.driver as driver_module

    monkeypatch.setattr(
        driver_module,
        "get_execution_authorization_mode",
        lambda: authorization,
    )
    monkeypatch.setattr(
        driver_module,
        "get_creation_checkpoint_mode",
        lambda: "skip",
    )


async def _succeeded_invoke(**_kwargs):
    return SpecialistToolResult(
        payload={
            "ok": True,
            "status": "SUCCEEDED",
            "artifactVersionId": "artifact-version-1",
        },
    )


async def _wait_first_authorization(driver):
    await _wait_for(
        lambda: bool(
            driver.executions.list_execution_authorizations(PROJECT_ID),
        ),
    )
    return driver.executions.list_execution_authorizations(PROJECT_ID)[0]


def _approve(driver, authorization) -> None:
    driver.executions.decide_execution_authorization(
        PROJECT_ID,
        authorization.authorization_id,
        authorization_token=authorization.authorization_token,
        status=ExecutionAuthorizationStatus.APPROVED,
        decision={
            "provider": authorization.requested_provider,
            "model": authorization.requested_model,
            "maxCost": 0,
            "maxCandidates": 1,
        },
    )


def _accept_review(services, review):
    return services.reviews.decide(
        project_id=PROJECT_ID,
        review_id=review.review_id,
        decision_token=review.decision_token,
        decisions=[
            ReviewDecisionItem(
                operation_id=operation.operation_id,
                decision="ACCEPT",
            )
            for operation in review.operations
        ],
    )


def _write_runtime_state(services, snapshot) -> None:
    AtomicJsonRecordStore(
        services.root / PROJECT_ID / "runtime" / "state.json",
        RuntimeProjectState,
    ).write(
        RuntimeProjectState(
            project_id=PROJECT_ID,
            active_session_id=SESSION_ID,
            active_goal_id=GOAL_ID,
            last_project_generation=snapshot.generation,
            last_project_etag=snapshot.etag,
            accepted_generation=snapshot.generation,
            accepted_etag=snapshot.etag,
        ),
    )


def _consume_and_activate(services, *, through_seq) -> None:
    """Durable state of an old mainline run: head consumed, run active."""

    services.sessions.mark_messages_consumed(
        PROJECT_ID,
        SESSION_ID,
        through_seq=through_seq,
        goal_id=GOAL_ID,
    )
    services.sessions.activate_run(
        PROJECT_ID,
        SESSION_ID,
        goal_id=GOAL_ID,
        run_id="old-run",
    )


def _admit_agentdock_request(services, *, request_id, client_message_id, text):
    return services.sessions.admit_user_request(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        request_id=request_id,
        client_message_id=client_message_id,
        content_parts=[{"type": "text", "text": text}],
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.MUTATION_INSTRUCTION,
    )


def _append_initial_request(
    services,
    *,
    content_parts,
    intent,
    metadata=None,
    client_message_id=None,
):
    message = services.sessions.append_message(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        role="user",
        content_parts=content_parts,
        client_message_id=client_message_id,
        source="initial_creation",
        channel=MessageChannel.COMPOSER,
        classification=MessageClassification.MUTATION_INSTRUCTION,
        metadata=metadata,
    ).message
    services.sessions.create_goal(
        PROJECT_ID,
        SESSION_ID,
        CONVERSATION_ID,
        root_message_seq=message.message_seq,
        intent=intent,
        goal_id=GOAL_ID,
    )
    return message


async def _wait_for(predicate, *, timeout: float = 30.0) -> None:
    # Generous ceiling: the loop returns as soon as the predicate holds,
    # while parallel full-suite runs need headroom under load.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise TimeoutError("condition was not reached")
        await asyncio.sleep(0.01)


def test_specialist_model_turn_has_a_wall_clock_timeout(tmp_path) -> None:
    parent_turn = 0
    specialist_started = asyncio.Event()
    # The hanging specialist never returns, so any finite budget trips
    # its wall-clock guard; keep the budget generous enough that normal
    # parent turns survive even on heavily loaded CI runners (a 0.02s
    # budget was flaky there — parent turns got killed as collateral).
    turn_timeout = 5.0

    async def callback(_messages, tools):
        nonlocal parent_turn
        names = {item["function"]["name"] for item in tools}
        if "image_generation" in names:
            specialist_started.set()
            await asyncio.Event().wait()
        parent_turn += 1
        if parent_turn == 1:
            return _tool_turn(
                call_id="delegate-hanging-visual",
                name="delegate_to_agent",
                arguments={
                    "role": "visual_development_agent",
                    "target_refs": ["asset:hero"],
                    "task": "生成角色图",
                },
            )
        return AgentModelTurn(content="视觉模型超时，当前运行已结束。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="生成角色图")
        driver = _driver(
            services,
            callback,
            model_turn_timeout_seconds=turn_timeout,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(specialist_started.wait(), timeout=2.0)
        await _wait_consumed(services)
        await driver.wait_until_idle(PROJECT_ID)
        specialist = driver.executions.list_specialist_runs(PROJECT_ID)[0]
        await driver.stop()
        return specialist

    specialist = asyncio.run(scenario())
    assert specialist.status.value == "FAILED"
    assert f"model turn exceeded {turn_timeout:g} seconds" in (
        specialist.final_summary_text or ""
    )


def _corrupted_jq_call(*, call_id: str, etag: str) -> AgentToolCall:
    """Mirror a syntax-repaired call whose program drifted into jsonArgs."""

    return AgentToolCall(
        call_id=call_id,
        name="jq_project",
        arguments={
            "projectId": PROJECT_ID,
            "baseEtag": etag,
            "jsonArgs": {
                "timeline_elements": {
                    "elem-01": {"program": ".description = $description"},
                },
            },
        },
        raw_arguments_bytes=18_522,
        arguments_repaired=True,
        strict_json_error="Unterminated string at EOF",
    )


def test_malformed_jq_project_arguments_recover_with_a_fresh_small_call(
    tmp_path,
) -> None:
    """A repaired-but-truncated jq_project payload never executes.

    json_repair can close a truncated stream so the object still carries
    projectId/program; jq must not execute such a payload because argument
    values may have silently lost their tails, and the truncation-specific
    hint names the cause and forces one entry per call.
    """

    turn = 0

    async def callback(messages, _tools):
        nonlocal turn
        turn += 1
        if turn == 1:
            return _read_call("read-before-corruption")
        if turn == 2:
            observed = json.loads(messages[-1]["content"])
            return _tool_turn(
                call_id="malformed-write",
                name="jq_project",
                arguments={
                    "projectId": PROJECT_ID,
                    "baseEtag": observed["etag"],
                    "program": ".description = $description",
                    "stringArgs": {
                        "description": "truncated mid-sentence descri",
                    },
                },
                raw_arguments_bytes=18_522,
                arguments_repaired=True,
                strict_json_error="Unterminated string at EOF",
            )
        if turn == 3:
            rejected = json.loads(messages[-1]["content"])
            assert rejected["error"]["type"] == "MalformedJqProjectArguments"
            recovery = rejected["error"]["recovery"]
            assert "json_repair" in rejected["error"]["message"]
            assert rejected["error"]["details"]["schemaValid"] is True
            assert rejected["error"]["details"]["safeToExecute"] is False
            assert rejected["error"]["details"]["jsonRepairApplied"] is True
            assert rejected["error"]["retry"]["attempt"] == 1
            assert "cut off" in recovery
            assert "Unterminated string at EOF" in recovery
            assert "18522 bytes" in recovery
            assert "under 4096 bytes" in recovery
            assert (
                "one timeline element or settings change per jq_project call"
                in recovery
            )
            return _read_call("reread-after-corruption")
        if turn == 4:
            observed = json.loads(messages[-1]["content"])
            return _tool_turn(
                call_id="small-replacement-write",
                name="jq_project",
                arguments={
                    "projectId": PROJECT_ID,
                    "baseEtag": observed["etag"],
                    "program": ".description = $description",
                    "stringArgs": {
                        "description": "recovered in a small commit",
                    },
                },
            )
        return AgentModelTurn(content="Recovered and completed.")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="Create the project plan",
        )
        driver = _driver(services, callback)
        await _run_to_idle(driver, services)
        project = services.projects.read(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return project, session, events, messages

    project, session, events, messages = asyncio.run(scenario())

    # The malformed payload never reached jq: only the clean resend landed.
    assert project.project.description == "recovered in a small commit"
    assert project.generation == 1
    assert session.error is None
    assert turn == 5
    checks = [
        event
        for event in events
        if event.event_type == "agent.tool_arguments_checked"
    ]
    assert len(checks) == 2
    assert checks[0].payload["rawArgumentsBytes"] == 18_522
    assert checks[0].payload["jsonRepairApplied"] is True
    assert checks[0].payload["schemaValid"] is True
    assert checks[0].payload["safeToExecute"] is False
    assert checks[1].payload["safeToExecute"] is True
    assert checks[1].payload["schemaValid"] is True
    malformed_results = [
        json.loads(message.content_parts[0].text or "{}")
        for message in messages
        if message.role == "tool"
        and message.metadata.get("toolCallId") == "malformed-write"
    ]
    assert (
        malformed_results[0]["error"]["type"] == "MalformedJqProjectArguments"
    )


@pytest.mark.parametrize(
    ("tool", "failure", "expected", "expected_casefold", "targeted_marker"),
    [
        pytest.param(
            "r2v_generation",
            "Task task-1 ended as QUARANTINED: {'code': 'PROJECT_INPUT_SNAPSHOT_STALE', 'message': 'PROJECT_INPUT_SNAPSHOT_STALE'}",
            ["quarantined", "read_project", "fresh r2v_generation call"],
            [],
            "quarantined",
            id="stale-snapshot-quarantine",
        ),
        pytest.param(
            "image_generation",
            "Task task-1 ended as FAILED: {'code': 'IMAGE_GENERATION_FAILED', 'message': 'Image generation failed with status 400: Your request was rejected by the safety system.'}",
            ["safety system", "scene or prop"],
            ["do not resubmit the same arguments", "remove"],
            "safety system",
            id="image-safety-rejection",
        ),
    ],
)
def test_terminated_media_tasks_get_targeted_recovery(
    tool,
    failure,
    expected,
    expected_casefold,
    targeted_marker,
) -> None:
    """Deterministic media-task terminations name their exact repair steps.

    Quarantined/stale Tasks must tell the model to re-admit a fresh call
    (replaying the identical call can only hit the same terminated Task;
    without this guidance the model burned its remaining turns retrying).
    Non-retryable provider moderation rejections (real faces, safety
    system) can never succeed with identical references/arguments, so the
    recovery must name the reference fix instead of the generic retry
    text.
    """

    targeted = _specialist_tool_recovery(tool, failure)
    for snippet in expected:
        assert snippet in targeted
    for snippet in expected_casefold:
        assert snippet in targeted.casefold()

    # Unrelated failures keep their existing generic guidance.
    generic = _specialist_tool_recovery(
        tool,
        "Task task-2 ended as FAILED: provider timeout",
    )
    assert targeted_marker not in generic


def test_video_reference_failures_get_targeted_recovery() -> None:
    budget = _specialist_tool_recovery(
        "r2v_generation",
        "VIDEO_REFERENCE_BUDGET_EXCEEDED",
        code="VIDEO_REFERENCE_BUDGET_EXCEEDED",
    )
    assert "No task was created" in budget
    assert "maxReferenceVideos" in budget
    assert "video_reference_version_ids" in budget
    assert "Preserve the selected storyboard" in budget

    unknown = _specialist_tool_recovery(
        "r2v_generation",
        "VIDEO_MODEL_CAPABILITY_UNKNOWN",
        code="VIDEO_MODEL_CAPABILITY_UNKNOWN",
    )
    assert "unregistered gateway alias" in unknown
    assert "Do not guess a generic limit" in unknown


def test_repeated_malformed_jq_project_arguments_stop_after_two_retries(
    tmp_path,
) -> None:
    turn = 0
    etag = ""

    async def callback(messages, _tools):
        nonlocal turn, etag
        turn += 1
        if turn == 1:
            return _read_call("read-before-repeats")
        if turn == 2:
            etag = json.loads(messages[-1]["content"])["etag"]
        return AgentModelTurn(
            tool_calls=(
                _corrupted_jq_call(
                    call_id=f"malformed-repeat-{turn}",
                    etag=etag,
                ),
            ),
        )

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="Create the project plan",
        )
        driver = _driver(services, callback)
        await _run_to_idle(driver, services, error=True)
        project = services.projects.read(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return project, session, messages

    project, session, messages = asyncio.run(scenario())

    assert project.generation == 0
    assert turn == 4
    assert session.error is not None
    assert session.error["code"] == "TOOL_NON_PROGRESS"
    assert session.error["retryable"] is False
    assert "after 2 bounded retries" in session.error["message"]
    errors = [
        json.loads(message.content_parts[0].text or "{}")["error"]
        for message in messages
        if message.role == "tool"
        and str(message.metadata.get("toolCallId") or "").startswith(
            "malformed-repeat-",
        )
    ]
    assert [item["retry"]["attempt"] for item in errors] == [1, 2, 3]
    assert [item["retry"]["retriesRemaining"] for item in errors] == [2, 1, 0]
    assert [item["retry"]["samePayload"] for item in errors] == [
        False,
        True,
        True,
    ]
    assert "Do not resend it" in errors[-1]["recovery"]


def test_initial_creation_runs_auto_fix_tool_loop_without_review(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="请完善项目说明")
        driver = _driver(services, _edit_client(description="由初始任务生成"))
        await _run_to_idle(driver, services)
        project = services.projects.read(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        goal = services.sessions.get_goal(PROJECT_ID, GOAL_ID)
        runs = driver.runs.list(PROJECT_ID)
        review = services.reviews.active(PROJECT_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return project, session, goal, runs, review, messages, events

    project, session, goal, runs, review, messages, events = asyncio.run(
        scenario(),
    )
    assert project.project.description == "由初始任务生成"
    assert project.generation == 1
    assert review is None
    assert session.status.value == "IDLE"
    assert session.error is None
    assert goal.status.value == "COMPLETED"
    assert len(runs) == 1
    assert runs[0].status is AgentRunStatus.SUCCEEDED
    assert runs[0].origin.value == "initial_creation"
    assert runs[0].review_policy.value == "auto_fix"
    assert runs[0].tool_call_count == 2
    assert {item.role for item in messages} >= {"user", "assistant", "tool"}
    event_types = {item.event_type for item in events}
    assert {
        "agent.message_delta",
        "agent.tool_progress",
        "message.completed",
        "agent.tool_started",
        "agent.tool_completed",
    } <= event_types
    trace_records = read_trace_records(filters={"projectId": PROJECT_ID})
    trace_names = {item["name"] for item in trace_records}
    assert {
        "creator.agent.execution.started",
        "creator.agent.run.started",
        "creator.agent.tool_started",
        "creator.agent.tool_completed",
        "creator.agent.run.completed",
        "creator.agent.execution.finished",
    } <= trace_names
    assert not any(name.endswith("_delta") for name in trace_names)
    assert len({item["traceId"] for item in trace_records}) == 1
    assistant_turns = [item for item in messages if item.role == "assistant"]
    assert assistant_turns[0].source == "creator_agent"
    assert assistant_turns[0].metadata["actionId"] == "read-1"
    persisted_tool_call = assistant_turns[0].metadata["toolCall"]
    assert {
        key: persisted_tool_call[key] for key in ("id", "name", "arguments")
    } == {
        "id": "read-1",
        "name": "read_project",
        "arguments": {"projectId": PROJECT_ID},
    }
    assert persisted_tool_call["transport"]["rawArgumentsCaptured"] is False


def test_creator_agent_can_call_ground_prompt_context_tool(
    tmp_path,
    monkeypatch,
) -> None:
    from services.file_agent_runtime import driver as driver_module

    image_buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color="blue").save(image_buffer, format="WEBP")
    image_bytes = image_buffer.getvalue()
    external_root = tmp_path.parent / f"{tmp_path.name}-grounding"
    external_root.mkdir()
    grounding_image = external_root / "haaland.webp"
    grounding_image.write_bytes(image_bytes)
    grounding_sha = hashlib.sha256(image_bytes).hexdigest()

    async def fake_ground_prompt_context(prompt: str, **kwargs):
        assert prompt == "哈兰德参加偶像练习生"
        assert kwargs["queries"] == ["Erling Haaland visual reference"]
        assert kwargs["include_visuals"] is True
        return {
            "ok": True,
            "status": "success",
            "provider": "dashscope_web_search_image",
            "grounded_context": (
                f"Visual References:\n[V1] accepted/identity local={grounding_image.as_uri()}"
            ),
            "visual_sources": [
                {
                    "verification": {
                        "status": "accepted",
                        "usage": "identity",
                    },
                    "local_url": grounding_image.as_uri(),
                    "local_path": str(grounding_image),
                    "media_type": "image/webp",
                    "storage_sha256": grounding_sha,
                    "title": "Erling Haaland official portrait",
                },
            ],
        }

    monkeypatch.setattr(
        driver_module,
        "ground_prompt_context",
        fake_ground_prompt_context,
    )

    turn = 0

    async def callback(messages, tools):
        nonlocal turn
        assert "ground_prompt_context" in {
            item["function"]["name"] for item in tools
        }
        turn += 1
        if turn == 1:
            return _tool_turn(
                call_id="ground-1",
                name="ground_prompt_context",
                arguments={
                    "projectId": PROJECT_ID,
                    "prompt": "哈兰德参加偶像练习生",
                    "queries": ["Erling Haaland visual reference"],
                    "includeVisuals": True,
                },
            )
        result = json.loads(messages[-1]["content"])
        assert result["provider"] == "dashscope_web_search_image"
        assert grounding_image.as_uri() in result["grounded_context"]
        assert result["visual_sources"][0]["source_asset_version_id"]
        assert result["visual_sources"][0]["workspace_ref"].startswith(
            "asset://",
        )
        return AgentModelTurn(content="grounding 已完成")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="哈兰德参加偶像练习生",
        )
        runtime = _driver(services, callback)
        await _run_to_idle(runtime, services)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await runtime.stop()
        return services, messages, events

    services, messages, events = asyncio.run(scenario())
    tool_results = [
        item
        for item in messages
        if item.source == "runtime_action_result"
        and item.metadata.get("tool") == "ground_prompt_context"
    ]
    assert len(tool_results) == 1
    assert tool_results[0].metadata["resultKind"] == "web_grounding"
    payload = json.loads(tool_results[0].content_parts[0].text or "")
    assert payload["ok"] is True
    source_version_id = payload["visual_sources"][0]["source_asset_version_id"]
    project = services.projects.read(PROJECT_ID).project
    assert source_version_id in project.assets.source_versions_by_id
    assert (
        project.assets.source_versions_by_id[source_version_id].checksum
        == grounding_sha
    )
    assert any(
        event.event_type == "agent.tool_completed"
        and event.payload.get("tool") == "ground_prompt_context"
        for event in events
    )


def test_object_grounding_generated_url_is_scoped_to_current_project(
    tmp_path,
    monkeypatch,
) -> None:
    from services.file_agent_runtime import driver as driver_module

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    services, _snapshot = _create_project(tmp_path, initial_goal=None)
    runtime = FileCreatorAgentRuntime(services, poll_interval_seconds=0.01)
    image_bytes = _png_bytes_for_grounding()
    ingested, _ = _ingest_many_sync(
        services,
        project_id=PROJECT_ID,
        key="object-grounding-image",
        inputs=[
            _AssetInput(
                name="input.png",
                content=image_bytes,
                media_type="image/png",
            ),
        ],
        attach_source=False,
        scope="object-grounding-ref-test",
    )
    asset_id = ingested["items"][0]["assetId"]
    version_id = ingested["items"][0]["assetVersionId"]
    current_image = (
        services.projects.project_root(PROJECT_ID)
        / "runtime"
        / "task-work"
        / "request-1"
        / "input.png"
    )
    current_image.parent.mkdir(parents=True)
    current_image.write_bytes(image_bytes)
    current_url = (
        f"/generated/projects/{PROJECT_ID}/task-work/request-1/input.png"
    )

    def resolve(image_ref):
        return asyncio.run(
            runtime._resolve_object_grounding_image(PROJECT_ID, image_ref),
        )

    assert resolve(current_url) == current_image.read_bytes()
    assert resolve(f"asset-version:{version_id}") == image_bytes
    assert resolve(f"asset://{asset_id}@{version_id}") == image_bytes
    with pytest.raises(
        driver_module.FileAgentRuntimeError,
        match="outside the current Project",
    ):
        resolve(
            "/generated/projects/other-project/task-work/request-1/input.png",
        )


def test_stream_persistence_failure_is_not_reported_as_a_model_failure(
    tmp_path,
    monkeypatch,
) -> None:
    async def callback(_messages, _tools) -> AgentModelTurn:
        return AgentModelTurn(content="完整结果")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="请生成结果")
        driver = _driver(services, callback)
        original_append_event = driver.sessions.append_event

        def append_event(*args, **kwargs):
            if kwargs.get("event_type") == "agent.message_delta":
                raise OSError("runtime lock timeout")
            return original_append_event(*args, **kwargs)

        monkeypatch.setattr(driver.sessions, "append_event", append_event)
        await _run_to_idle(driver, services, error=True)
        session = services.sessions.get_project_session(PROJECT_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return session, events

    session, events = asyncio.run(scenario())

    assert session.error is not None
    assert session.error["code"] == "STREAM_PERSISTENCE_FAILED"
    assert session.error["retryable"] is True
    failed = [
        event for event in events if event.event_type == "agent.run.failed"
    ]
    assert failed[-1].payload["error"]["code"] == "STREAM_PERSISTENCE_FAILED"


def test_intervention_completion_queues_mainline_resume(tmp_path) -> None:
    async def scenario():
        services, snapshot = _create_project(tmp_path, initial_goal=None)
        first = _append_initial_request(
            services,
            content_parts=[{"type": "text", "text": "主线目标：生成完整短片"}],
            intent="主线目标",
            client_message_id="mainline-client",
        )
        _consume_and_activate(services, through_seq=first.message_seq)
        _write_runtime_state(services, snapshot)
        driver = _driver(services, _edit_client(description="支线修改已完成"))
        # Durable record of the interrupted mainline run (as _cancel_run
        # leaves it after a real supersede).
        driver.runs.create(
            {
                "run_id": "old-run",
                "project_id": PROJECT_ID,
                "session_id": SESSION_ID,
                "goal_id": GOAL_ID,
                "conversation_id": CONVERSATION_ID,
                "round_id": "agent-round-old-run",
                "caused_by_message_id": first.message_id,
                "caused_by_message_seq": first.message_seq,
                "caused_by_request_id": "mainline-client",
                "origin": "runtime_task",
                "review_policy": "auto_fix",
                "input_generation": snapshot.generation,
                "input_etag": snapshot.etag,
            },
        )
        driver.runs.transition(
            PROJECT_ID,
            "old-run",
            expected_status=AgentRunStatus.QUEUED,
            status=AgentRunStatus.RUNNING,
        )
        driver.runs.transition(
            PROJECT_ID,
            "old-run",
            expected_status=AgentRunStatus.RUNNING,
            status=AgentRunStatus.CANCELLED,
        )
        admitted = _admit_agentdock_request(
            services,
            request_id="interrupt-request",
            client_message_id="interrupt-message",
            text="把说明改成支线版本",
        )
        assert admitted.review_boundary is not None
        assert admitted.review_boundary.interrupted_run_id == "old-run"

        await driver.start()
        driver.notify(PROJECT_ID)

        def _resume_messages():
            return [
                item
                for item in services.sessions.list_messages(
                    PROJECT_ID,
                    SESSION_ID,
                    after_seq=0,
                    limit=None,
                )
                if item.source == "mainline_resume"
            ]

        await _wait_for(lambda: len(_resume_messages()) == 1)
        resume = _resume_messages()[0]
        await asyncio.sleep(0.05)
        assert not any(
            run.caused_by_message_seq == resume.message_seq
            for run in driver.runs.list(PROJECT_ID)
        ), "mainline resumed before the intervention Review was accepted"
        review = services.reviews.active(PROJECT_ID)
        assert review is not None
        _accept_review(services, review)
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: any(
                run.caused_by_message_seq == resume.message_seq
                and run.status is AgentRunStatus.SUCCEEDED
                for run in driver.runs.list(PROJECT_ID)
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        driver.notify(PROJECT_ID)
        await asyncio.sleep(0.05)
        resume_count = len(_resume_messages())
        runs = driver.runs.list(PROJECT_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return resume, resume_count, runs, events

    resume, resume_count, runs, events = asyncio.run(scenario())
    assert resume.channel is MessageChannel.RUNTIME
    assert resume.review_boundary is None
    assert resume.metadata["interruptedRunId"] == "old-run"
    assert resume_count == 1
    resume_run = next(
        run for run in runs if run.caused_by_message_seq == resume.message_seq
    )
    assert resume_run.origin.value == "runtime_task"
    assert resume_run.review_policy.value == "auto_fix"
    assert resume_run.review_boundary is None
    assert "agent.mainline.resumed" in {item.event_type for item in events}


def test_interrupt_revokes_stale_run_before_late_tool_commit(tmp_path) -> None:
    async def scenario():
        services, snapshot = _create_project(tmp_path, initial_goal="请修改项目")
        started = asyncio.Event()

        async def stubborn_model(_messages, _tools):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # Simulate a provider adapter that swallows cancellation and
                # returns a late mutation. The run epoch must still reject it.
                return _tool_turn(
                    call_id="late-write",
                    name="jq_project",
                    arguments={
                        "projectId": PROJECT_ID,
                        "baseEtag": snapshot.etag,
                        "program": '.description = "must-not-commit"',
                    },
                )

        driver = _driver(services, stubborn_model)
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(started.wait(), timeout=2.0)
        interrupted = await driver.interrupt(PROJECT_ID, reason="test-stop")
        await driver.wait_until_idle(PROJECT_ID)
        project = services.projects.read(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        run = driver.runs.list(PROJECT_ID)[0]
        await driver.stop()
        return interrupted, project, session, run

    interrupted, project, session, run = asyncio.run(scenario())
    assert interrupted is True
    assert project.generation == 0
    assert project.project.description == ""
    assert run.status is AgentRunStatus.CANCELLED
    assert session.status.value == "CANCELLED"
    assert session.last_consumed_message_seq == 1


def test_interrupt_returns_before_slow_task_cleanup_finishes(tmp_path) -> None:
    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="请修改项目")
        started = asyncio.Event()
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()

        async def slow_cancel_model(_messages, _tools):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleanup_started.set()
                await release_cleanup.wait()
                raise

        driver = _driver(services, slow_cancel_model)
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(started.wait(), timeout=2.0)

        interrupted = await asyncio.wait_for(
            driver.interrupt(PROJECT_ID, reason="test-stop"),
            timeout=0.2,
        )
        await asyncio.wait_for(cleanup_started.wait(), timeout=2.0)
        still_active = PROJECT_ID in driver._active
        release_cleanup.set()
        await driver.wait_until_idle(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        await driver.stop()
        return interrupted, still_active, session

    interrupted, still_active, session = asyncio.run(scenario())
    assert interrupted is True
    assert still_active is True
    assert session.status.value == "CANCELLED"


@pytest.mark.parametrize("cancel_phase", ["running_model", "waiting_runtime"])
def test_specialist_cancel_emits_terminal_event(
    tmp_path,
    monkeypatch,
    cancel_phase,
) -> None:
    """A specialist run cancelled mid-flight must emit a terminal
    ``subagent.failed`` event, both from RUNNING_MODEL and from
    WAITING_RUNTIME (a long-running tool mid-invoke).

    Regression note for the WAITING_RUNTIME case: the run reaches the
    cancel-except only after the invoke-finally bridges WAITING_RUNTIME back
    to RUNNING_MODEL, so the on-disk transition succeeds — but the terminal
    event was still missing.  Locks in that the event fires on this path too.
    """
    if cancel_phase == "waiting_runtime":
        _authorization_gate_modes(monkeypatch, authorization="allow_all")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="生成角色图")
        blocked = asyncio.Event()
        cancel_entered = asyncio.Event()

        async def _block_until_cancelled() -> None:
            blocked.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancel_entered.set()
                raise

        async def callback(messages, tools):
            names = {item["function"]["name"] for item in tools}
            if "delegate_to_agent" in names:
                return _delegate_call(
                    "delegate-visual",
                    role="visual_development_agent",
                    target_refs=["project:assets"],
                    task="整体视觉",
                )
            if cancel_phase == "waiting_runtime":
                # Specialist turn: park the run in a long-running tool.
                return _media_call(
                    "gen-1",
                    name="image_generation",
                    target_ref="asset:hero",
                    arguments={"prompt": "hero"},
                )
            # Specialist turn: block forever until the parent is interrupted.
            await _block_until_cancelled()

        async def blocking_invoke(**_kwargs):
            await _block_until_cancelled()

        driver = _driver(services, callback)
        if cancel_phase == "waiting_runtime":
            driver.specialist_tools.invoke = blocking_invoke  # type: ignore[method-assign]
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(blocked.wait(), timeout=2.0)
        interrupted = await driver.interrupt(PROJECT_ID, reason="test-stop")
        await driver.wait_until_idle(PROJECT_ID)
        specialist_runs = driver.executions.list_specialist_runs(PROJECT_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return interrupted, specialist_runs, events, cancel_entered

    interrupted, specialist_runs, events, cancel_entered = asyncio.run(
        scenario(),
    )

    assert interrupted is True
    assert (
        cancel_entered.is_set()
    ), "CancelledError never reached the specialist"
    assert len(specialist_runs) == 1
    assert specialist_runs[0].status.value == "CANCELLED"
    terminal = [
        item
        for item in events
        if item.event_type.startswith("subagent.")
        and item.event_type
        in {"subagent.failed", "subagent.cancelled", "subagent.completed"}
    ]
    assert terminal, (
        f"no terminal subagent event emitted on cancel ({cancel_phase}); "
        "events="
        f"{[e.event_type for e in events if e.event_type.startswith('subagent.')]}"
    )
    cancelled_event = terminal[-1]
    assert cancelled_event.event_type == "subagent.failed"
    assert cancelled_event.payload.get("cancelled") is True


def test_durable_interrupt_stops_remote_owner_without_restarting_message(
    tmp_path,
) -> None:
    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="请修改项目")
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def blocking_model(_messages, _tools):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        owner = _driver(services, blocking_model)
        await owner.start()
        owner.notify(PROJECT_ID)
        await asyncio.wait_for(started.wait(), timeout=2.0)

        # Simulate the stop request landing in another QwenPaw process.  The
        # durable Session status is the cross-process signal; this coordinator
        # deliberately has no local handle for the active run.
        services.sessions.set_session_status(
            PROJECT_ID,
            SESSION_ID,
            "INTERRUPT_REQUESTED",
        )
        non_owner = _driver(services, blocking_model)
        await non_owner.start()
        interrupted_locally = await non_owner.interrupt(
            PROJECT_ID,
            reason="remote-stop",
        )
        assert interrupted_locally is False

        await asyncio.wait_for(cancelled.wait(), timeout=2.0)
        await owner.wait_until_idle(PROJECT_ID)
        await _wait_session_status(services, "CANCELLED")
        session = services.sessions.get_project_session(PROJECT_ID)
        runs = owner.runs.list(PROJECT_ID)
        await non_owner.stop()
        await owner.stop()
        return session, runs

    session, runs = asyncio.run(scenario())
    assert session.status.value == "CANCELLED"
    assert session.active_run_id is None
    assert session.last_consumed_message_seq == session.last_message_seq == 1
    assert len(runs) == 1
    assert runs[0].status is AgentRunStatus.CANCELLED


@pytest.mark.parametrize(
    "legacy_unconsumed_head",
    [False, True],
    ids=["failed-head-consumed", "legacy-unconsumed-head"],
)
def test_failed_run_is_not_relaunched_after_restart_or_notify(
    tmp_path,
    monkeypatch,
    legacy_unconsumed_head,
) -> None:
    """A failed request is a durable input boundary.

    Neither a process restart (which discards the in-memory blocked-head
    guard) nor an unrelated ``notify`` (model config saves wake every
    Project) may relaunch the Agent on the same failed message. Legacy
    sessions written before failures consumed their request must not
    auto-start the Agent either; reconciliation consumes the failed head
    based on the durable run record instead.

    Also locks in the failure surface itself: a missing model
    configuration persists a ``MODEL_CONFIG_MISSING`` session error and
    fails the goal.
    """

    relaunch_calls = 0

    async def failing(_messages, _tools):
        raise AgentModelConfigurationError(
            "Creator text model configuration is incomplete: api_key",
        )

    async def counting(_messages, _tools) -> AgentModelTurn:
        nonlocal relaunch_calls
        relaunch_calls += 1
        return AgentModelTurn(content="不应被调用")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="请修改项目")
        first = _driver(services, failing)
        if legacy_unconsumed_head:
            # Model the legacy failure path that never consumed the request.
            monkeypatch.setattr(
                first.sessions,
                "mark_messages_consumed",
                lambda *args, **kwargs: services.sessions.get_project_session(
                    PROJECT_ID,
                ),
            )
        await first.start()
        first.notify(PROJECT_ID)
        await _wait_session_status(services, "ERROR")
        await first.wait_until_idle(PROJECT_ID)
        failed_session = services.sessions.get_project_session(PROJECT_ID)
        goal = services.sessions.get_goal(PROJECT_ID, GOAL_ID)
        await first.stop()

        # A fresh runtime instance models a QwenPaw restart: the in-memory
        # ``_blocked_heads`` guard is gone and only durable state remains.
        second = _driver(services, counting)
        await second.start()
        second.notify(PROJECT_ID)
        if legacy_unconsumed_head:
            await _wait_consumed(services)
        else:
            await asyncio.sleep(0.2)
        await second.wait_until_idle(PROJECT_ID)
        runs = second.runs.list(PROJECT_ID)
        await second.stop()
        return failed_session, goal, runs

    failed_session, goal, runs = asyncio.run(scenario())
    assert failed_session.error is not None
    assert failed_session.error["code"] == "MODEL_CONFIG_MISSING"
    assert "api_key" in failed_session.error["message"]
    assert goal.status.value == "FAILED"
    expected_consumed = 0 if legacy_unconsumed_head else 1
    assert failed_session.last_consumed_message_seq == expected_consumed
    assert relaunch_calls == 0
    assert len(runs) == 1
    assert runs[0].status is AgentRunStatus.FAILED


def test_costly_specialist_tool_waits_for_file_authorization(
    tmp_path,
    monkeypatch,
) -> None:
    _authorization_gate_modes(monkeypatch, authorization="required")
    parent_turn = 0
    specialist_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn, specialist_turn
        names = {item["function"]["name"] for item in tools}
        if "image_generation" in names:
            specialist_turn += 1
            if specialist_turn == 1:
                return _media_call(
                    "generate-image-1",
                    name="image_generation",
                    target_ref="asset:hero",
                    arguments={"prompt": "hero portrait"},
                )
            return AgentModelTurn(content="[SUCCESS]\n角色图已生成。")
        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-visual-1",
                role="visual_development_agent",
                target_refs=["asset:hero"],
                task="生成角色图",
            )
        return AgentModelTurn(content="视觉 Specialist 已完成。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="生成角色图")
        driver = _driver(services, callback)

        driver.specialist_tools.invoke = _succeeded_invoke  # type: ignore[method-assign]
        await driver.start()
        driver.notify(PROJECT_ID)
        authorization = await _wait_first_authorization(driver)
        await _wait_for(
            lambda: (
                driver.executions.get_specialist_run(
                    PROJECT_ID,
                    authorization.run_id,
                ).status.value
                == "WAITING_AUTHORIZATION"
            ),
        )
        _approve(driver, authorization)
        await _wait_consumed(services)
        await driver.wait_until_idle(PROJECT_ID)
        completed_run = driver.executions.get_specialist_run(
            PROJECT_ID,
            authorization.run_id,
        )
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return authorization, completed_run, events

    authorization, completed_run, events = asyncio.run(scenario())
    assert completed_run.status.value == "SUCCEEDED"
    assert authorization.operation == "image_generation"
    event_types = {item.event_type for item in events}
    assert "execution.authorization_required" in event_types
    assert "execution.authorization_decided" in event_types


def test_approved_billing_arguments_do_not_trip_the_drift_guard(
    tmp_path,
    monkeypatch,
) -> None:
    """An unchanged authorized r2v call must run (review M1 regression).

    The drift guard compares billing-sensitive arguments (durationSeconds /
    resolution / mode) against ``authorization.scope["parameters"]``; the
    scope stores the full billing arguments, so a request whose terms did
    not change between approval and invocation must never be rejected.
    """

    _authorization_gate_modes(monkeypatch, authorization="required")
    parent_turn = 0
    specialist_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn, specialist_turn
        names = {item["function"]["name"] for item in tools}
        if "r2v_generation" in names:
            specialist_turn += 1
            if specialist_turn == 1:
                return _media_call(
                    "generate-ep1-video",
                    name="r2v_generation",
                    target_ref="element:ep1",
                    arguments={
                        "prompt": "ep1 video",
                        "durationSeconds": 5,
                        "resolution": "720P",
                        "mode": "r2v",
                    },
                )
            return AgentModelTurn(content="[SUCCESS]\n视频已生成。")
        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-ep1-video",
                role="r2v_generation_director",
                target_refs=["element:ep1"],
                task="生成 ep1 视频",
            )
        return AgentModelTurn(content="R2V Specialist 已完成。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="生成视频")
        driver = _driver(services, callback)

        driver.specialist_tools.invoke = _succeeded_invoke  # type: ignore[method-assign]
        await driver.start()
        driver.notify(PROJECT_ID)
        authorization = await _wait_first_authorization(driver)
        _approve(driver, authorization)
        await driver.wait_until_idle(PROJECT_ID)
        completed_run = driver.executions.get_specialist_run(
            PROJECT_ID,
            authorization.run_id,
        )
        await driver.stop()
        return authorization, completed_run

    authorization, completed_run = asyncio.run(scenario())
    # The billed terms were recorded in full on the approval scope…
    approved = authorization.scope["parameters"]
    assert approved["durationSeconds"] == 5
    assert approved["resolution"] == "720P"
    assert approved["mode"] == "r2v"
    # …so the unchanged invocation passes the drift guard and completes.
    assert completed_run.status.value == "SUCCEEDED"


def test_model_blocked_with_its_pending_review_is_a_neutral_pause(
    tmp_path,
    monkeypatch,
) -> None:
    """A specialist may stop after creating a review without calling downstream."""

    parent_turn = 0
    specialist_turn = 0

    async def callback(messages, tools):
        nonlocal parent_turn, specialist_turn
        names = {item["function"]["name"] for item in tools}
        if "image_generation" in names:
            specialist_turn += 1
            if specialist_turn == 1:
                return _read_call("read-after-storyboard")
            return AgentModelTurn(
                content="[BLOCKED] element:ep22 分镜图已生成，等待用户审阅后生成视频。",
            )

        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-ep22-storyboard",
                role="r2v_generation_director",
                target_refs=["element:ep22"],
                task="生成 ep22 分镜图，等待审阅后再生成视频",
            )
        delegated = json.loads(messages[-1]["content"])
        assert delegated["status"] == "WAITING_REVIEW"
        assert delegated["waitingReview"] is True
        return AgentModelTurn(
            content="ep22 分镜图等待审阅。审阅通过后告诉我“继续”，我会接着生成视频。",
        )

    async def scenario():
        services, snapshot = _create_project(
            tmp_path,
            initial_goal="生成 ep22 分镜图和视频",
        )

        class PendingReview:
            review_id = "review-ep22-storyboard"

        monkeypatch.setattr(
            services.reviews,
            "all_pending",
            lambda _project_id: [PendingReview()],
        )
        driver = _driver(services, callback)

        async def reviewed_read(**_kwargs):
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "reviewId": "review-ep22-storyboard",
                    "generation": snapshot.generation,
                    "etag": snapshot.etag,
                },
            )

        driver.specialist_tools.invoke = reviewed_read  # type: ignore[method-assign]
        await _run_to_idle(driver, services)
        specialist = driver.executions.list_specialist_runs(PROJECT_ID)[0]
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        run = driver.runs.list(PROJECT_ID)[0]
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return specialist, events, session, run, messages

    specialist, events, session, run, messages = asyncio.run(scenario())
    assert specialist.status.value == "BLOCKED"
    assert specialist.metadata["waitingReview"] is True
    assert specialist.metadata["waitingReviewId"] == "review-ep22-storyboard"
    waiting_summary = (
        "element:ep22 的分镜图已生成，视频尚未开始。请先审阅分镜图；"
        "审阅通过后，主线需对该 Element 重新委派 R2V 生成 Director 以继续生成视频；"
        "这不算重新生成已通过产物。"
    )
    assert specialist.final_summary_text == waiting_summary
    blocked = [
        item for item in events if item.event_type == "subagent.blocked"
    ]
    assert len(blocked) == 1
    assert blocked[0].payload["waitingReview"] is True
    assert blocked[0].payload["reviewId"] == "review-ep22-storyboard"
    assert session.status.value == "PENDING_REVIEW"
    expected_final_summary = f"{waiting_summary}\n\n无需另行发送消息。"
    assert run.final_summary == expected_final_summary
    assert messages[-1].content_parts[0].text == expected_final_summary
    assert "告诉我" not in (run.final_summary or "")


def test_workspace_commits_wake_the_media_scheduler(tmp_path) -> None:
    """Every committed structure write wakes the per-project scheduler.

    Prompt-first planning writes complete variant prompts many turns
    before the run ends; without a commit-time wake the READY anchors
    idle until run completion (measured at ~9 minutes on a five-act
    project). Empty commits must stay silent.
    """

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal=None)
        driver = _driver(
            services,
            lambda *args, **kwargs: AgentModelTurn(content="idle"),
        )
        woken: list[str] = []
        driver.work_scheduler.wake = woken.append  # type: ignore[method-assign]

        async def _noop_event(*args, **kwargs) -> None:
            return None

        driver._event = _noop_event  # type: ignore[method-assign]
        await driver._workspace_changed(
            PROJECT_ID,
            SESSION_ID,
            "run-1",
            None,
            {"changedPointers": ["/strategy/creative_brief"]},
            action_id="call-1",
        )
        await driver._workspace_changed(
            PROJECT_ID,
            SESSION_ID,
            "run-1",
            None,
            {"changedPointers": []},
            action_id="call-2",
        )
        return woken

    assert asyncio.run(scenario()) == [PROJECT_ID]
