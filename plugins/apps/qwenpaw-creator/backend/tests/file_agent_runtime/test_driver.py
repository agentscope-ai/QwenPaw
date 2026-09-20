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
    FileAgentRuntimeError,
)
from services.file_agent_runtime.driver import (
    _ToolArgumentProgressReporter,
    _live_operation_editing_context,
    _remove_live_operation_scratch,
    _require_actionable_takes,
    _specialist_tool_recovery,
    _tool_call_transport_metadata,
)
from services.file_agent_runtime import driver as driver_module
from services.file_agent_runtime.prompts import render_creator_system_prompt
from services.file_agent_runtime.work_graph import (
    WorkGraph,
    WorkNode,
    WorkNodeStatus,
)
from services.media_files.live_operation import (
    LiveOperationError,
    LiveOperationRun,
)
from services.media_files.live_operation import RecordedTake, TakeManifest
from services.observability import read_trace_records
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    Project,
    SourceAssetVersion,
    VisualEntity,
)
from services.project_files.review import ReviewDecisionItem
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.models import (
    CreatorMessageRecord,
    MessageChannel,
    MessageClassification,
    RuntimeProjectState,
    ReviewBoundary,
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
            initial_message_id=(
                "message-initial" if initial_goal is not None else None
            ),
            initial_client_message_id=(
                "client-initial" if initial_goal is not None else None
            ),
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


def test_live_operation_context_gives_edit_director_verified_action_facts(
    tmp_path,
    monkeypatch,
) -> None:
    project = Project.new(project_id=PROJECT_ID, name="Tutorial")
    version = SourceAssetVersion(
        version_id="asset-version-live-1",
        logical_asset_id="asset-live-1",
        name="搜索仓库",
        file_id="file-live-1",
        checksum="0" * 64,
        media_kind="video",
        media_type="video/mp4",
        duration_seconds=4.2,
        created_at=project.created_at,
        metadata={
            "sourceKind": "live_operation_take",
            "manifestFileId": "file-manifest-1",
        },
    )
    project.assets.source_versions_by_id[version.version_id] = version
    monkeypatch.setattr(
        driver_module,
        "read_take_manifest",
        lambda *_args, **_kwargs: {
            "video": {"duration_ms": 4200},
            "facts": [
                {
                    "op": "click",
                    "t_start_ms": 1000,
                    "t_end_ms": 1200,
                    "target": 'get_by_role("button", name="Search")',
                    "location": {
                        "x": 0.5,
                        "y": 0.2,
                        "width": 0.3,
                        "height": 0.08,
                    },
                },
            ],
        },
    )

    context = _live_operation_editing_context(project, tmp_path)

    assert context is not None
    assert context["schema"] == "creator.live_operation.editing_context"
    assert context["sourceTakeCount"] == 1
    take = context["takes"][0]
    assert take["sourceAssetVersionId"] == version.version_id
    assert take["durationMs"] == 4200
    assert take["facts"] == [
        {
            "op": "click",
            "tStartMs": 1000,
            "tEndMs": 1200,
            "target": 'get_by_role("button", name="Search")',
            "sourceLocation": {
                "x": 0.5,
                "y": 0.2,
                "width": 0.3,
                "height": 0.08,
            },
        },
    ]

    second = version.model_copy(
        update={
            "version_id": "asset-version-live-2",
            "logical_asset_id": "asset-live-2",
            "file_id": "file-live-2",
        },
    )
    project.assets.source_versions_by_id[second.version_id] = second
    monkeypatch.setattr(driver_module, "_LIVE_EDIT_CONTEXT_MAX_FACTS", 1)
    monkeypatch.setattr(driver_module, "_LIVE_EDIT_CONTEXT_MAX_RAW_FACTS", 10)
    monkeypatch.setattr(
        driver_module,
        "read_take_manifest",
        lambda *_args, **_kwargs: {
            "video": {"duration_ms": 1000},
            "facts": [
                {"op": "click", "t_start_ms": 0, "t_end_ms": 1},
            ],
        },
    )
    outer_bounded = _live_operation_editing_context(project, tmp_path)
    assert outer_bounded is not None
    assert outer_bounded["includedTakeCount"] == 1
    assert outer_bounded["truncated"] is True


def test_repeated_live_operations_in_one_request_use_unique_transactions(
    tmp_path,
) -> None:
    """A model may call browser_use more than once in one message.

    Request identity remains the durable provenance, but each distinct tool
    invocation needs its own transaction id or the second asset commit is
    rejected as a replay of the first.
    """
    services, _snapshot = _create_project(tmp_path, initial_goal=None)
    runtime = FileCreatorAgentRuntime(
        services,
        poll_interval_seconds=0.01,
    )

    def screenshot(name: str, color: str) -> LiveOperationRun:
        path = tmp_path / name
        Image.new("RGB", (16, 12), color=color).save(path, format="PNG")
        outcome = LiveOperationRun()
        outcome.screenshots = [str(path)]
        return outcome

    first = runtime._publish_live_operation_sync(
        PROJECT_ID,
        "same-message",
        "operation-one",
        screenshot("one.png", "red"),
    )
    second = runtime._publish_live_operation_sync(
        PROJECT_ID,
        "same-message",
        "operation-two",
        screenshot("two.png", "blue"),
    )

    assert len(first["screenshots"]) == 1
    assert len(second["screenshots"]) == 1
    project = services.projects.read(PROJECT_ID).project
    assert len(project.assets.source_versions_by_id) == 2


def _browser_runtime(tmp_path, monkeypatch, runner):
    services, _snapshot = _create_project(tmp_path, initial_goal=None)
    runtime = FileCreatorAgentRuntime(services, poll_interval_seconds=0.01)
    monkeypatch.setattr(
        driver_module,
        "get_live_operation_enabled",
        lambda: True,
    )
    monkeypatch.setattr(driver_module, "run_browser_code", runner)
    return services, runtime


def test_tool_manifest_gates_live_operation_on_config(monkeypatch):
    """Disabling live operation must unregister its tools entirely."""

    def _names():
        return {
            entry["function"]["name"]
            for entry in driver_module._creator_agent_tool_manifest()
        }

    monkeypatch.setattr(
        driver_module,
        "get_live_operation_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        driver_module,
        "get_computer_use_enabled",
        lambda: False,
    )
    assert not {"browser_use", "computer_use"} & _names()

    monkeypatch.setattr(
        driver_module,
        "get_live_operation_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        driver_module,
        "get_computer_use_enabled",
        lambda: True,
    )
    assert {"browser_use", "computer_use"} <= _names()


def _run_browser_tool(runtime):
    return asyncio.run(
        runtime._run_browser_use(
            request=_record(1),
            run_id="agent-run-1",
            arguments={"code": "await Browser.connect()"},
        ),
    )


def _live_operation_scratch(services):
    return (
        services.projects.project_root(PROJECT_ID) / "runtime/live_operation"
    )


def test_browser_operation_scratch_is_removed_after_publication(
    tmp_path,
    monkeypatch,
) -> None:
    async def fake_run(code, *, run_root, run_id, **kwargs):
        del code, kwargs
        workspace = run_root / "live_operation" / run_id
        workspace.mkdir(parents=True)
        screenshot = workspace / "shot.png"
        Image.new("RGB", (16, 12), color="navy").save(screenshot, format="PNG")
        outcome = LiveOperationRun()
        outcome.screenshots = [str(screenshot)]
        return outcome

    services, runtime = _browser_runtime(tmp_path, monkeypatch, fake_run)
    response = _run_browser_tool(runtime)

    assert len(response["screenshots"]) == 1
    assert list(_live_operation_scratch(services).iterdir()) == []


def test_browser_observation_without_media_is_not_completion_eligible(
    tmp_path,
    monkeypatch,
) -> None:
    async def fake_run(code, *, run_root, run_id, **kwargs):
        del code, run_root, run_id, kwargs
        outcome = LiveOperationRun()
        outcome.output = "two tabs observed"
        return outcome

    _services, runtime = _browser_runtime(tmp_path, monkeypatch, fake_run)
    response = _run_browser_tool(runtime)

    assert response["ok"] is True
    assert response["observationOnly"] is True
    assert response["completionEligible"] is False
    assert response["takes"] == []
    assert response["screenshots"] == []
    assert "cannot satisfy" in response["issues"][0]


def test_browser_operation_scratch_is_removed_after_execution_failure(
    tmp_path,
    monkeypatch,
) -> None:
    async def failing_run(code, *, run_root, run_id, **kwargs):
        del code, kwargs
        workspace = run_root / "live_operation" / run_id
        workspace.mkdir(parents=True)
        (workspace / "partial.mp4").write_bytes(b"partial")
        raise LiveOperationError("strict locator failure")

    services, runtime = _browser_runtime(tmp_path, monkeypatch, failing_run)
    with pytest.raises(FileAgentRuntimeError, match="strict locator failure"):
        _run_browser_tool(runtime)

    assert list(_live_operation_scratch(services).iterdir()) == []


def test_live_operation_scratch_cleanup_rejects_escape_and_symlink(
    tmp_path,
) -> None:
    run_root = tmp_path / "runtime"
    scratch_root = run_root / "live_operation"
    scratch_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    _remove_live_operation_scratch(run_root, "../outside")
    assert marker.read_text(encoding="utf-8") == "keep"

    redirect = scratch_root / "agent-run-link"
    redirect.symlink_to(outside, target_is_directory=True)
    _remove_live_operation_scratch(run_root, redirect.name)
    assert redirect.is_symlink()
    assert marker.read_text(encoding="utf-8") == "keep"

    ordinary = scratch_root / "agent-run-safe"
    ordinary.mkdir()
    (ordinary / "partial.mp4").write_bytes(b"partial")
    _remove_live_operation_scratch(run_root, ordinary.name)
    assert not ordinary.exists()


def test_factless_operation_take_is_rejected_before_publication(
    tmp_path,
) -> None:
    video = tmp_path / "factless.mp4"
    video.write_bytes(b"mp4")
    manifest = TakeManifest(take_id="take-001", duration_ms=1000)
    outcome = LiveOperationRun()
    outcome.takes = [
        RecordedTake(
            take_id=manifest.take_id,
            label="静止等待",
            video_path=video,
            manifest=manifest,
        ),
    ]

    with pytest.raises(FileAgentRuntimeError, match="0 real actions"):
        _require_actionable_takes(outcome, tool_name="browser_use")


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
            "browser_use",
            "elements_at",
            "delegate_to_agent",
            "request_workgraph_execution",
        }
        # The role prompt and static Pydantic schema form one stable system
        # prompt.
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
        if "delegate_to_agent" not in names:
            specialist_started.set()
            await asyncio.Event().wait()
        parent_turn += 1
        if parent_turn == 1:
            return _tool_turn(
                call_id="delegate-hanging-editing",
                name="delegate_to_agent",
                arguments={
                    "role": "ai_editing_director",
                    "target_refs": ["timeline:timeline:main"],
                    "task": "编排 Timeline 选段",
                },
            )
        return AgentModelTurn(content="剪辑模型超时，当前运行已结束。")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="生成角色图",
        )
        driver = _driver(
            services,
            callback,
            model_turn_timeout_seconds=turn_timeout,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(specialist_started.wait(), timeout=2.0)
        await _wait_consumed(services)
        # The specialist is detached: its wall-clock guard trips well after
        # the mainline run has already gone idle.
        await _wait_for(
            lambda: (
                (runs := driver.executions.list_specialist_runs(PROJECT_ID))
                and runs[0].status.value == "FAILED"
            ),
        )
        specialist = driver.executions.list_specialist_runs(PROJECT_ID)[0]
        await driver.stop()
        return specialist

    specialist = asyncio.run(scenario())
    assert specialist.status.value == "FAILED"
    assert f"model turn exceeded {turn_timeout:g} seconds" in (
        specialist.final_summary_text or ""
    )


def test_run_review_feedback_allows_one_successful_repair_delegation(
    tmp_path,
) -> None:
    """One review goal cannot turn into an unbounded paid-media loop."""

    parent_turn = 0
    specialist_turns = 0

    async def callback(messages, tools):
        nonlocal parent_turn, specialist_turns
        names = {item["function"]["name"] for item in tools}
        if "delegate_to_agent" not in names:
            specialist_turns += 1
            return AgentModelTurn(
                content="[SUCCESS] 修复产物已写入 selected output。",
            )
        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-review-1",
                role="ai_editing_director",
                target_refs=["timeline:timeline:main"],
                task="修复本轮异步审阅发现并生成一次新产物",
            )
        if parent_turn == 2:
            assert '"status":"ACCEPTED"' in messages[-1]["content"]
            return AgentModelTurn(
                content="已委派修复，等待 Specialist 终态通知。",
            )
        if parent_turn == 3:
            # The terminal-notification run: a misbehaving model retries the
            # same feedback target — the repair identity must follow the
            # notification hop and refuse a second paid delegation.
            return _delegate_call(
                "delegate-review-2",
                role="ai_editing_director",
                target_refs=["timeline:timeline:main"],
                task="修复本轮异步审阅发现并生成一次新产物",
            )
        assert (
            "already has a successful repair delegation"
            in messages[-1]["content"]
        )
        return AgentModelTurn(content="一次修复已完成，等待调度器处理下游。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal=None)
        message = services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[
                {
                    "type": "text",
                    "text": "【运行审阅反馈 · 第 1/2 轮】只修复 asset:hero",
                },
            ],
            source="run_review_feedback",
            channel=MessageChannel.RUNTIME,
            classification=MessageClassification.MUTATION_INSTRUCTION,
            metadata={"runReview": {"round": 1}},
        ).message
        services.sessions.create_goal(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            root_message_seq=message.message_seq,
            intent="修复异步审阅发现",
            goal_id=GOAL_ID,
        )
        driver = _driver(services, callback)
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(lambda: parent_turn >= 4)
        await driver.wait_until_idle(PROJECT_ID)
        runs = driver.executions.list_specialist_runs(PROJECT_ID)
        await driver.stop()
        repair_state = json.loads(
            (
                services.projects.project_root(PROJECT_ID)
                / "runtime"
                / "run-review"
                / "repair-budget"
                / "state.json"
            ).read_text(encoding="utf-8"),
        )
        return runs, repair_state

    runs, repair_state = asyncio.run(scenario())
    assert parent_turn == 4
    assert specialist_turns == 1
    assert len(runs) == 1
    assert runs[0].status.value == "SUCCEEDED"
    assert (
        repair_state["targets"]["timeline:timeline:main"]["attempts_started"]
        == 1
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
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="请完善项目说明",
        )
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


@pytest.mark.parametrize("transient_lock", [False, True])
@pytest.mark.parametrize("boundary", ["stream", "assistant", "tool"])
def test_session_persistence_retries_without_replaying_model_or_tool(
    tmp_path,
    monkeypatch,
    transient_lock,
    boundary,
) -> None:
    from services.runtime_files.errors import LockTimeoutError

    model_calls = []
    tool_calls = []
    invoke = driver_module.AgentProjectTools.invoke

    def invoke_once(self, name, arguments):
        tool_calls.append(name)
        return invoke(self, name, arguments)

    monkeypatch.setattr(driver_module.AgentProjectTools, "invoke", invoke_once)

    async def callback(_messages, _tools) -> AgentModelTurn:
        model_calls.append(1)
        if len(model_calls) == 1:
            return _read_call("read-once")
        return AgentModelTurn(content="完整结果")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="请生成结果",
        )
        driver = _driver(services, callback)
        original_append_event = driver.sessions.append_event
        original_append_message = driver.sessions.append_message
        append_calls = []

        def contend():
            append_calls.append(1)
            if not transient_lock:
                raise OSError("disk write failed")
            if len(append_calls) <= 4:
                raise LockTimeoutError(tmp_path / "project.lock", 10.0)

        def append_event(*args, **kwargs):
            if (
                boundary == "stream"
                and kwargs.get("event_type") == "agent.message_delta"
            ):
                contend()
            return original_append_event(*args, **kwargs)

        def append_message(*args, **kwargs):
            if kwargs.get("role") == boundary and not kwargs.get(
                "metadata",
                {},
            ).get("toolCall"):
                contend()
            return original_append_message(*args, **kwargs)

        monkeypatch.setattr(driver.sessions, "append_event", append_event)
        monkeypatch.setattr(driver.sessions, "append_message", append_message)
        await _run_to_idle(driver, services, error=not transient_lock)
        session = services.sessions.get_project_session(PROJECT_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return session, events, messages

    session, events, messages = asyncio.run(scenario())

    assert len(model_calls) == (
        1 if boundary == "tool" and not transient_lock else 2
    )
    assert tool_calls == ["read_project"]
    failed = [
        event for event in events if event.event_type == "agent.run.failed"
    ]
    if transient_lock:
        assert session.error is None
        assert not failed
        deltas = [e for e in events if e.event_type == "agent.message_delta"]
        assert [e.payload["delta"] for e in deltas] == ["完整结果"]
        assert len([m for m in messages if m.role == "tool"]) == 1
        assert len([m for m in messages if m.role == "assistant"]) == 2
        assert messages[-1].content_parts[0].text == "完整结果"
    else:
        expected_code = (
            "STREAM_PERSISTENCE_FAILED"
            if boundary == "stream"
            else "AGENT_RUN_FAILED"
        )
        assert session.error["code"] == expected_code
        assert failed[-1].payload["error"]["code"] == expected_code
        if boundary == "stream":
            assert session.error["retryable"] is True


@pytest.mark.parametrize(
    ("queued_notification", "decide_during_run"),
    [(False, False), (True, False), (True, True)],
)
def test_intervention_completion_queues_mainline_resume(
    tmp_path,
    queued_notification,
    decide_during_run,
) -> None:
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
        edit = _edit_client(description="支线修改已完成")

        async def model(messages, tools):
            turn = await edit.complete(messages=messages, tools=tools)
            if decide_during_run and not turn.tool_calls:
                review = services.reviews.active(PROJECT_ID)
                if review is not None:
                    _accept_review(services, review)
            return turn

        driver = _driver(services, model)
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
        notification = None
        if queued_notification:
            notification = services.sessions.append_message(
                PROJECT_ID,
                SESSION_ID,
                CONVERSATION_ID,
                role="user",
                source="runtime_notification",
                channel=MessageChannel.RUNTIME,
                content_parts=[{"type": "text", "text": "素材理解已完成"}],
                metadata={"notificationKind": "subagent_terminal"},
            ).message
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
        if notification is not None:
            assert not any(
                run.caused_by_message_seq == notification.message_seq
                for run in driver.runs.list(PROJECT_ID)
            ), "an older completion notification ran ahead of the intervention"
        resume = _resume_messages()[0]
        await asyncio.sleep(0.05)
        if decide_during_run:
            run = next(
                run
                for run in driver.runs.list(PROJECT_ID)
                if run.caused_by_message_seq == admitted.message.message_seq
            )
            assert run.final_summary == "项目说明已更新。"
            assert not run.review_ids
        else:
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


def _create_persisted_run(
    driver,
    snapshot,
    *,
    run_id: str,
    running: bool = True,
) -> None:
    """Durable run record as the dispatcher persists it for the initial
    request, without any process-local task attached to it."""

    driver.runs.create(
        {
            "run_id": run_id,
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "goal_id": GOAL_ID,
            "conversation_id": CONVERSATION_ID,
            "round_id": f"agent-round-{run_id}",
            "caused_by_message_id": "message-initial",
            "caused_by_message_seq": 1,
            "caused_by_request_id": "client-initial",
            "origin": "initial_creation",
            "review_policy": "auto_fix",
            "input_generation": snapshot.generation,
            "input_etag": snapshot.etag,
        },
    )
    if running:
        driver.runs.transition(
            PROJECT_ID,
            run_id,
            expected_status=AgentRunStatus.QUEUED,
            status=AgentRunStatus.RUNNING,
        )


def test_startup_sweep_reclaims_hard_killed_running_run(
    tmp_path,
    monkeypatch,
) -> None:
    """A crash/SIGKILL skips graceful shutdown: the run stays durably
    RUNNING with error null and the Session keeps its lease. The startup
    sweep must settle it exactly like a SHUTDOWN cancellation and feed it
    into the auto-resume path instead of leaving a permanent zombie."""

    monkeypatch.setattr(
        driver_module,
        "get_media_review_mode",
        lambda: "auto_approve",
    )

    async def scenario():
        services, snapshot = _create_project(
            tmp_path,
            initial_goal="生成完整短片",
        )
        _write_runtime_state(services, snapshot)

        async def callback(_messages, _tools) -> AgentModelTurn:
            return AgentModelTurn(content="继续完成")

        driver = _driver(services, callback)
        _create_persisted_run(driver, snapshot, run_id="crashed-run")
        services.sessions.activate_run(
            PROJECT_ID,
            SESSION_ID,
            goal_id=GOAL_ID,
            run_id="crashed-run",
        )
        # The previous process "dies" here: no graceful shutdown, run
        # durably RUNNING, request message unconsumed, lease held.

        await driver.start()

        await _wait_for(
            lambda: driver.runs.get(PROJECT_ID, "crashed-run").status
            is AgentRunStatus.CANCELLED,
        )

        def _yolo_messages():
            return [
                item
                for item in services.sessions.list_messages(
                    PROJECT_ID,
                    SESSION_ID,
                    after_seq=0,
                    limit=None,
                )
                if item.source == driver.YOLO_RESUME_SOURCE
            ]

        await _wait_for(lambda: len(_yolo_messages()) == 1)
        resume = _yolo_messages()[0]
        await _wait_for(
            lambda: any(
                run.caused_by_message_seq == resume.message_seq
                and run.status is AgentRunStatus.SUCCEEDED
                for run in driver.runs.list(PROJECT_ID)
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        crashed = driver.runs.get(PROJECT_ID, "crashed-run")
        session = services.sessions.get_project_session(PROJECT_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return crashed, resume, session, events

    crashed, resume, session, events = asyncio.run(scenario())
    assert crashed.status is AgentRunStatus.CANCELLED
    assert crashed.error is not None
    # Same terminal shape a graceful shutdown writes, so every existing
    # consumer (including this sweep on the next restart) treats it alike.
    assert crashed.error["code"] == "SHUTDOWN"
    assert resume.metadata["resumeAfterRunId"] == "crashed-run"
    assert session.active_run_id != "crashed-run"
    assert any(
        event.event_type == "agent.run.cancelled"
        and event.payload.get("runId") == "crashed-run"
        and event.payload.get("reclaimedAfterCrash") is True
        for event in events
    )


def test_startup_sweep_never_resumes_interrupted_run(
    tmp_path,
    monkeypatch,
) -> None:
    """INTERRUPTED carries human intent (an explicit stop) and must stay
    excluded from auto-resume even with crash reclamation in the sweep."""

    monkeypatch.setattr(
        driver_module,
        "get_media_review_mode",
        lambda: "auto_approve",
    )

    async def scenario():
        services, snapshot = _create_project(
            tmp_path,
            initial_goal="生成完整短片",
        )
        _write_runtime_state(services, snapshot)
        services.sessions.mark_messages_consumed(
            PROJECT_ID,
            SESSION_ID,
            through_seq=1,
            goal_id=GOAL_ID,
        )

        async def callback(_messages, _tools) -> AgentModelTurn:
            return AgentModelTurn(content="不应被调用")

        driver = _driver(services, callback)
        _create_persisted_run(driver, snapshot, run_id="stopped-run")
        driver.runs.transition(
            PROJECT_ID,
            "stopped-run",
            expected_status=AgentRunStatus.RUNNING,
            status=AgentRunStatus.CANCELLED,
            updates={
                "error": {
                    "code": "INTERRUPTED",
                    "message": "Run interrupted by the user",
                },
            },
        )

        await driver.start()
        await asyncio.sleep(0.1)
        messages = services.sessions.list_messages(
            PROJECT_ID,
            SESSION_ID,
            after_seq=0,
            limit=None,
        )
        runs = driver.runs.list(PROJECT_ID)
        await driver.stop()
        return messages, runs

    messages, runs = asyncio.run(scenario())
    assert not any(
        item.source == FileCreatorAgentRuntime.YOLO_RESUME_SOURCE
        for item in messages
    )
    assert [run.run_id for run in runs] == ["stopped-run"]
    assert runs[0].error["code"] == "INTERRUPTED"


def test_interrupt_revokes_stale_run_before_late_tool_commit(tmp_path) -> None:
    async def scenario():
        services, snapshot = _create_project(
            tmp_path,
            initial_goal="请修改项目",
        )
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


@pytest.mark.parametrize("superseded", [False, True])
@pytest.mark.parametrize("reason", ["user_interrupt", "agentdock_message"])
def test_feedback_keeps_admitted_media_alive_but_hard_stop_cancels_it(
    tmp_path,
    monkeypatch,
    superseded,
    reason,
) -> None:
    """A new user message must not abandon an unrelated paid image call."""

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="制作短剧")
        model_started = asyncio.Event()
        media_started = asyncio.Event()
        release_media = asyncio.Event()
        published: list[str] = []

        async def model(_messages, _tools):
            model_started.set()
            await asyncio.Event().wait()

        async def media_provider(_project_id, _node, _fingerprint):
            media_started.set()
            await release_media.wait()
            published.append("existing-image-result")

        driver = _driver(services, model)
        scheduler = driver.work_scheduler
        monkeypatch.setattr(scheduler, "dispatch_node", media_provider)
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(model_started.wait(), timeout=2)
        node = WorkNode(
            node_id="visual:unrelated",
            kind="visual",
            label="已授权的人物图",
            status=WorkNodeStatus.READY,
            command="GENERATE_ASSET",
            target_ref="asset:hero",
        )
        media = asyncio.create_task(
            scheduler._dispatch(PROJECT_ID, node, "fp"),
        )
        scheduler._dispatch_tasks.setdefault(PROJECT_ID, set()).add(media)
        scheduler._inflight.setdefault(PROJECT_ID, set()).add(node.node_id)
        await asyncio.wait_for(media_started.wait(), timeout=2)
        active = driver._active[PROJECT_ID]
        try:
            assert await driver.interrupt(
                PROJECT_ID,
                superseded=superseded,
                reason=reason,
                expected_run_id=active.run_id,
            )
            await asyncio.wait_for(
                asyncio.gather(active.task, return_exceptions=True),
                timeout=2,
            )
            release_media.set()
            await asyncio.gather(media, return_exceptions=True)
            assert media.cancelled() is not superseded
            assert published == (
                ["existing-image-result"] if superseded else []
            )
        finally:
            release_media.set()
            await driver.stop()

    asyncio.run(scenario())


def test_interrupt_returns_before_slow_task_cleanup_finishes(tmp_path) -> None:
    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="请修改项目",
        )
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
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="生成角色图",
        )
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
                    "delegate-editing",
                    role="ai_editing_director",
                    target_refs=["timeline:timeline:main"],
                    task="角色声音设计",
                )
            if cancel_phase == "waiting_runtime":
                # Specialist turn: park the run in a long-running tool.
                return _media_call(
                    "gen-1",
                    name="tts_generation",
                    target_ref="asset:hero",
                    arguments={"text": "测试取消中的长任务。"},
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


def test_durable_interrupt_stops_owner_without_restarting_message(
    tmp_path,
) -> None:
    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="请修改项目",
        )
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

        # Persist the stop as an independent request handler would. The owning
        # runtime must observe it without a direct call to owner.interrupt().
        # Starting a second runtime here would race its orphan-recovery sweep
        # against this live owner, outside the supported single-backend model.
        services.sessions.set_session_status(
            PROJECT_ID,
            SESSION_ID,
            "INTERRUPT_REQUESTED",
        )
        await asyncio.wait_for(cancelled.wait(), timeout=2.0)
        await owner.wait_until_idle(PROJECT_ID)
        await _wait_session_status(services, "CANCELLED")
        session = services.sessions.get_project_session(PROJECT_ID)
        runs = owner.runs.list(PROJECT_ID)
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
    guard) nor an unrelated runtime state-change ``notify`` may relaunch
    the Agent on the same failed message. Legacy
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
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="请修改项目",
        )
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
    monkeypatch.setenv("TTS_API_KEY", "sk-test")
    parent_turn = 0
    specialist_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn, specialist_turn
        names = {item["function"]["name"] for item in tools}
        if "tts_generation" in names:
            specialist_turn += 1
            if specialist_turn == 1:
                return _media_call(
                    "generate-voice-1",
                    name="tts_generation",
                    target_ref="asset:hero",
                    arguments={"text": "这是一段角色试音。"},
                )
            return AgentModelTurn(content="[SUCCESS]\n角色试音已生成。")
        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-editing-voice-1",
                role="ai_editing_director",
                target_refs=["timeline:timeline:main"],
                task="为 hero 生成角色试音",
            )
        return AgentModelTurn(content="AI 剪辑 Specialist 已完成。")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="生成角色图",
        )
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
        await _wait_for(
            lambda: driver.executions.get_specialist_run(
                PROJECT_ID,
                authorization.run_id,
            ).status.value
            == "SUCCEEDED",
        )
        completed_run = driver.executions.get_specialist_run(
            PROJECT_ID,
            authorization.run_id,
        )
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return authorization, completed_run, events

    authorization, completed_run, events = asyncio.run(scenario())
    assert completed_run.status.value == "SUCCEEDED"
    assert authorization.operation == "tts_generation"
    event_types = {item.event_type for item in events}
    assert "execution.authorization_required" in event_types
    assert "execution.authorization_decided" in event_types


def test_retired_r2v_specialist_cannot_request_paid_authorization(
    tmp_path,
    monkeypatch,
) -> None:
    """The removed R2V delegation surface cannot reach a paid tool."""
    _authorization_gate_modes(monkeypatch, authorization="required")
    parent_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn
        names = {item["function"]["name"] for item in tools}
        assert "r2v_generation" not in names
        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-ep1-video",
                role="r2v_generation_director",
                target_refs=["element:ep1"],
                task="生成 ep1 视频",
            )
        return AgentModelTurn(content="R2V prompt 改由主 Agent 直接负责。")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="生成视频",
        )
        driver = _driver(services, callback)

        await _run_to_idle(driver, services)
        authorizations = driver.executions.list_execution_authorizations(
            PROJECT_ID,
        )
        specialists = driver.executions.list_specialist_runs(PROJECT_ID)
        await driver.stop()
        return authorizations, specialists

    authorizations, specialists = asyncio.run(scenario())
    assert authorizations == []
    assert specialists == []


def test_retired_visual_specialist_cannot_be_delegated(
    tmp_path,
    monkeypatch,
) -> None:
    """The removed visual development surface rejects new delegations."""
    _authorization_gate_modes(monkeypatch, authorization="required")
    parent_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn
        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-hero-design",
                role="visual_development_agent",
                target_refs=["asset:char:hero"],
                task="为角色生成设计图",
            )
        return AgentModelTurn(
            content="视觉资产 prompt 改由主 Agent 直接编写。",
        )

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="生成角色图",
        )
        driver = _driver(services, callback)

        await _run_to_idle(driver, services)
        specialists = driver.executions.list_specialist_runs(PROJECT_ID)
        await driver.stop()
        return specialists

    specialists = asyncio.run(scenario())
    assert specialists == []


def test_mainline_character_voice_waits_for_authorization(
    tmp_path,
    monkeypatch,
) -> None:
    """Voice enrollment moved to the mainline: the paid call still parks on
    an execution authorization, and no SpecialistRun is ever created."""

    _authorization_gate_modes(monkeypatch, authorization="required")
    monkeypatch.setenv("TTS_API_KEY", "sk-test")

    async def fake_voice_tool(_services, **_kwargs):
        return {
            "ok": True,
            "status": "SUCCEEDED",
            "entityId": "char:hero",
            "voiceBound": True,
        }

    monkeypatch.setattr(
        driver_module,
        "invoke_character_voice_tool",
        fake_voice_tool,
    )
    parent_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn
        names = {item["function"]["name"] for item in tools}
        assert "create_character_voice" in names
        parent_turn += 1
        if parent_turn == 1:
            return _tool_turn(
                call_id="voice-1",
                name="create_character_voice",
                arguments={
                    "projectId": PROJECT_ID,
                    "targetRef": "asset:char:hero",
                    "arguments": {"voicePrompt": "低沉沙哑的中年男声"},
                },
            )
        return AgentModelTurn(content="音色已创建并绑定。")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="创建角色音色",
        )
        driver = _driver(services, callback)
        await driver.start()
        driver.notify(PROJECT_ID)
        authorization = await _wait_first_authorization(driver)
        _approve(driver, authorization)
        await _wait_consumed(services)
        await driver.wait_until_idle(PROJECT_ID)
        specialists = driver.executions.list_specialist_runs(PROJECT_ID)
        await driver.stop()
        return authorization, specialists

    authorization, specialists = asyncio.run(scenario())
    assert authorization.operation == "create_character_voice"
    assert specialists == []


@pytest.mark.parametrize(
    "review_state,after_failure,gap,reason,previous_yolo",
    [
        pytest.param(
            "none",
            False,
            True,
            "video_prompt 缺失",
            False,
            id="normal",
        ),
        pytest.param(
            "pending",
            False,
            True,
            "video_prompt 缺失",
            False,
            id="pending-review",
        ),
        pytest.param(
            "accepted",
            False,
            True,
            "video_prompt 缺失",
            False,
            id="accepted-review",
        ),
        pytest.param(
            "none",
            True,
            True,
            "video_prompt 缺失",
            False,
            id="transient-failure",
        ),
        pytest.param(
            "none",
            True,
            False,
            "上游分镜未完成",
            False,
            id="paid-repair-forbidden",
        ),
        pytest.param(
            "none",
            False,
            True,
            "video_prompt 缺失",
            True,
            id="separate-yolo-fuse",
        ),
        pytest.param(
            "none",
            False,
            True,
            "台本文案尚未落到 Element 上",
            False,
            id="structured-gap-not-wording",
        ),
    ],
)
def test_manual_prompt_repair_respects_review_and_never_dispatches_media(
    tmp_path,
    monkeypatch,
    review_state,
    after_failure,
    gap,
    reason,
    previous_yolo,
) -> None:
    services, snapshot = _create_project(tmp_path, initial_goal="完成短剧")
    if review_state != "none":
        candidate = snapshot.project.model_dump(mode="json")
        candidate["description"] = "等待确认的创作改动"
        review = services.commits.commit(
            base=snapshot,
            candidate=candidate,
            round_id="round-pending-review",
            origin="agentdock_interrupt",
            review_policy="require_review",
            review_boundary=ReviewBoundary(
                request_message_seq=1,
                request_id="request-review",
                interrupted_run_id="agent-run-review",
                accepted_generation=snapshot.generation,
                accepted_etag=snapshot.etag,
            ),
            caused_by_request_id="request-review",
            caused_by_message_seq=1,
        ).review
        assert review is not None
        if review_state == "accepted":
            _accept_review(services, review)
    driver = _driver(services, lambda _messages, _tools: AgentModelTurn())
    if previous_yolo:
        for index in range(driver.YOLO_RESUME_MAX_CONSECUTIVE):
            services.sessions.append_message(
                PROJECT_ID,
                SESSION_ID,
                CONVERSATION_ID,
                role="user",
                content_parts=[
                    {"type": "text", "text": f"YOLO resume {index}"},
                ],
                source=driver.YOLO_RESUME_SOURCE,
                channel=MessageChannel.RUNTIME,
                metadata={"projectGeneration": snapshot.generation},
            )
    node = WorkNode(
        node_id="video:ep1",
        kind="video",
        label="第一场 · 视频",
        status=WorkNodeStatus.GATED,
        missing=(reason,),
        authored_text_gap=gap,
    )
    monkeypatch.setattr(
        driver_module,
        "get_media_review_mode",
        lambda: "manual",
    )
    monkeypatch.setattr(
        driver_module,
        "derive_work_graph",
        lambda _project, tasks, *, media_models=None: WorkGraph(
            nodes=(node,),
            generation=1,
        ),
    )
    wakes = []
    monkeypatch.setattr(driver.work_scheduler, "wake", wakes.append)
    before = len(services.sessions.list_messages(PROJECT_ID, SESSION_ID))
    asyncio.run(
        driver._queue_yolo_completion_resume(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            conversation_id=CONVERSATION_ID,
            run_id="agent-run-false-complete",
            after_failure=after_failure,
        ),
    )
    messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)[before:]
    assert wakes == [], "manual prompt repair must never wake paid scheduling"
    if review_state == "pending" or not gap:
        assert messages == []
    else:
        assert len(messages) == 1
        feedback = messages[0]
        assert feedback.source == driver.PROMPT_CONTRACT_RESUME_SOURCE
        assert reason in feedback.content_parts[0].text
        assert "没有提交任何对应的付费媒体任务" in feedback.content_parts[0].text
        assert feedback.metadata["modelRequiredNodes"] == ["video:ep1"]
        if after_failure:
            assert "瞬态故障" in feedback.content_parts[0].text


def test_model_blocked_with_its_pending_review_is_a_neutral_pause(
    tmp_path,
    monkeypatch,
) -> None:
    """
    A specialist may stop after creating a review without calling downstream.
    """

    monkeypatch.setenv("TTS_API_KEY", "sk-test")

    parent_turn = 0
    specialist_turn = 0

    async def callback(messages, tools):
        nonlocal parent_turn, specialist_turn
        names = {item["function"]["name"] for item in tools}
        if "tts_generation" in names:
            specialist_turn += 1
            if specialist_turn == 1:
                return _read_call("read-after-storyboard")
            return AgentModelTurn(
                content="[BLOCKED] hero 角色试音已生成，等待用户审阅。",
            )

        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-hero-voice",
                role="ai_editing_director",
                target_refs=["timeline:timeline:main"],
                task="生成 hero 角色试音并等待审阅",
            )
        if parent_turn == 2:
            delegated = json.loads(messages[-1]["content"])
            assert delegated["status"] == "ACCEPTED"
            return AgentModelTurn(content="已委派，等待 Specialist 终态通知。")
        # The terminal-notification run reports the review pause.
        assert "[WAITING_REVIEW]" in messages[1]["content"]
        return AgentModelTurn(
            content="ep22 分镜图等待审阅，审阅通过后自动继续。",
        )

    async def scenario():
        services, snapshot = _create_project(
            tmp_path,
            initial_goal="生成 ep22 分镜图和视频",
        )

        class PendingReview:
            review_id = "review-ep22-storyboard"

        pending_reviews: list = []
        monkeypatch.setattr(
            services.reviews,
            "all_pending",
            lambda _project_id, **_kwargs: list(pending_reviews),
        )
        driver = _driver(services, callback)

        async def reviewed_read(**_kwargs):
            # The specialist tool creates the review mid-run.
            pending_reviews.append(PendingReview())
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "reviewId": "review-ep22-storyboard",
                    "generation": snapshot.generation,
                    "etag": snapshot.etag,
                },
            )

        driver.specialist_tools.invoke = reviewed_read  # type: ignore[method-assign]
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                (runs := driver.executions.list_specialist_runs(PROJECT_ID))
                and runs[0].status.value == "BLOCKED"
            ),
        )
        # The terminal notification is durably queued, but the active
        # review gates consumption: no new run may start until the user
        # decides.
        await _wait_for(
            lambda: any(
                item.role == "user" and item.source == "runtime_notification"
                for item in services.sessions.list_messages(
                    PROJECT_ID,
                    SESSION_ID,
                )
            ),
        )
        await asyncio.sleep(0.05)
        assert (
            parent_turn == 2
        ), "the notification run must wait for the review decision"
        pending_reviews.clear()
        await _wait_for(lambda: parent_turn >= 3)
        await driver.wait_until_idle(PROJECT_ID)
        specialist = driver.executions.list_specialist_runs(PROJECT_ID)[0]
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return specialist, events, messages

    specialist, events, messages = asyncio.run(scenario())
    assert specialist.status.value == "BLOCKED"
    assert specialist.metadata["waitingReview"] is True
    assert specialist.metadata["waitingReviewId"] == "review-ep22-storyboard"
    waiting_summary = (
        "timeline:timeline:main 的产物已生成，后续步骤尚未开始。请先完成审阅；"
        + "审阅通过后，主线需重新委派同一目标以继续后续步骤。"
    )
    assert specialist.final_summary_text == waiting_summary
    blocked = [
        item for item in events if item.event_type == "subagent.blocked"
    ]
    assert len(blocked) == 1
    assert blocked[0].payload["waitingReview"] is True
    assert blocked[0].payload["reviewId"] == "review-ep22-storyboard"
    notifications = [
        item
        for item in messages
        if item.role == "user" and item.source == "runtime_notification"
    ]
    assert len(notifications) == 1
    assert notifications[0].metadata["specialistStatus"] == "WAITING_REVIEW"
    assert notifications[0].metadata["reviewId"] == "review-ep22-storyboard"
    assert "[WAITING_REVIEW]" in notifications[0].content_parts[0].text


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


# -- runtime notification bus integration ----------------------------------


def test_yolo_resume_carries_quiet_digest_and_respects_fuse(
    tmp_path,
    monkeypatch,
) -> None:
    """Pending quiet progress rides along with the end-of-run resume, and
    interleaved notifications neither spend nor reset the resume fuse."""

    from services.file_agent_runtime.notifications import (
        NOTIFICATION_SOURCE,
        RuntimeEventKind,
    )

    services, _snapshot = _create_project(tmp_path, initial_goal="完成短剧")
    driver = _driver(services, lambda _messages, _tools: AgentModelTurn())
    node = WorkNode(
        node_id="video:ep1",
        kind="video",
        label="第一场 · 视频",
        status=WorkNodeStatus.GATED,
        missing=("video_prompt 缺失",),
        authored_text_gap=True,
    )
    monkeypatch.setattr(
        driver_module,
        "get_media_review_mode",
        lambda: "manual",
    )
    monkeypatch.setattr(
        driver_module,
        "derive_work_graph",
        lambda _project, tasks, *, media_models=None: WorkGraph(
            nodes=(node,),
            generation=1,
        ),
    )

    async def scenario():
        await driver.notifications.inject(
            PROJECT_ID,
            kind=RuntimeEventKind.NODE_SUCCEEDED,
            request_id="node_succeeded-visual:hero-fp1",
            text="生成完成：角色设计 Hero",
        )
        await driver._queue_yolo_completion_resume(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            conversation_id=CONVERSATION_ID,
            run_id="agent-run-digest",
        )

    asyncio.run(scenario())

    feedback = services.sessions.list_messages(PROJECT_ID, SESSION_ID)[-1]
    assert feedback.source == driver.PROMPT_CONTRACT_RESUME_SOURCE
    text = feedback.content_parts[0].text
    assert "生成完成：角色设计 Hero" in text
    assert "video_prompt 缺失" in text
    assert (
        driver.notifications.store.pending_records(PROJECT_ID) == []
    ), "drained quiet records must settle after the resume append"

    # Seed the streak to the cap with a notification after every resume:
    # the fuse must count the resumes and skip the notifications.
    for index in range(driver.PROMPT_CONTRACT_RESUME_MAX_CONSECUTIVE - 1):
        services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": f"repair {index}"}],
            source=driver.PROMPT_CONTRACT_RESUME_SOURCE,
            channel=MessageChannel.RUNTIME,
        )
        services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": f"进度速报 {index}"}],
            source=NOTIFICATION_SOURCE,
            channel=MessageChannel.RUNTIME,
        )

    asyncio.run(
        driver._queue_yolo_completion_resume(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            conversation_id=CONVERSATION_ID,
            run_id="agent-run-fuse",
        ),
    )

    repairs = [
        item
        for item in services.sessions.list_messages(
            PROJECT_ID,
            SESSION_ID,
            after_seq=0,
            limit=None,
        )
        if item.source == driver.PROMPT_CONTRACT_RESUME_SOURCE
    ]
    assert (
        len(repairs) == driver.PROMPT_CONTRACT_RESUME_MAX_CONSECUTIVE
    ), "notification messages must not reset the resume fuse streak"


def test_idle_session_flushes_parked_notification_and_consumes_it(
    tmp_path,
    monkeypatch,
) -> None:
    """A hard-cap parked NEXT_STEP event must not wait forever on an idle
    session: the dispatcher's escape valve delivers it and a run consumes
    it like any other notification message."""

    from services.file_agent_runtime import (
        notifications as notifications_module,
    )
    from services.file_agent_runtime.notifications import RuntimeEventKind

    monkeypatch.setattr(
        notifications_module,
        "NOTIFY_IDLE_FLUSH_COOLDOWN_SECONDS",
        0.0,
    )
    received: list[str] = []

    async def callback(messages, _tools):
        if messages[-1]["role"] == "user":
            received.append(messages[-1]["content"])
        return AgentModelTurn(content="收到。")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="完成短剧",
        )
        driver = _driver(services, callback)
        await _run_to_idle(driver, services)
        driver._specialist_tasks[PROJECT_ID] = {"spec-1": object()}
        await driver.notifications.inject(
            PROJECT_ID,
            kind=RuntimeEventKind.SUBAGENT_TERMINAL,
            request_id="specialist-run-parked-1",
            text="Specialist 终态 [BLOCKED]：TTS 服务不可用。",
        )
        # In-flight specialists own the wake-up: their terminal steer (or
        # the run it starts) drains the outbox, so the valve stays closed.
        await driver._maybe_flush_idle_notifications(PROJECT_ID)
        assert (
            len(driver.notifications.store.pending_records(PROJECT_ID)) == 1
        ), "the valve must stay closed mid-delegation"
        driver._specialist_tasks.pop(PROJECT_ID)
        driver.notify(PROJECT_ID)

        def flush_consumed() -> bool:
            session = services.sessions.get_project_session_snapshot(
                PROJECT_ID,
            )
            flushes = [
                item
                for item in services.sessions.list_messages(
                    PROJECT_ID,
                    SESSION_ID,
                    after_seq=0,
                    limit=None,
                )
                if item.role == "user" and item.metadata.get("idleFlush")
            ]
            return bool(flushes) and (
                session.last_consumed_message_seq >= flushes[-1].message_seq
            )

        await _wait_for(flush_consumed)
        await driver.wait_until_idle(PROJECT_ID)
        undelivered = driver.notifications.store.undelivered_records(
            PROJECT_ID,
        )
        await driver.stop()
        return undelivered

    undelivered = asyncio.run(scenario())

    assert undelivered == []
    flush_inputs = [
        text
        for text in received
        if "Runtime 通知" in text and "TTS 服务不可用" in text
    ]
    assert flush_inputs, "the model must see the flushed notification"


def test_mainline_resume_message_carries_quiet_digest_prefix(
    tmp_path,
    monkeypatch,
) -> None:
    from services.file_agent_runtime.notifications import RuntimeEventKind

    services, snapshot = _create_project(tmp_path, initial_goal="主线目标")
    driver = _driver(services, lambda _messages, _tools: AgentModelTurn())
    driver.runs.create(
        {
            "run_id": "old-run",
            "project_id": PROJECT_ID,
            "session_id": SESSION_ID,
            "goal_id": GOAL_ID,
            "conversation_id": CONVERSATION_ID,
            "round_id": "agent-round-old-run",
            "caused_by_message_id": "message-initial",
            "caused_by_message_seq": 1,
            "caused_by_request_id": "client-initial",
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

    async def scenario():
        await driver.notifications.inject(
            PROJECT_ID,
            kind=RuntimeEventKind.NODE_DISPATCH_STARTED,
            request_id="node_dispatch_started-video:e1-fp1",
            text="已开始生成：视频 e1",
        )
        await driver._queue_mainline_resume(
            project_id=PROJECT_ID,
            session_id=SESSION_ID,
            conversation_id=CONVERSATION_ID,
            intervention_run_id="branch-run",
            interrupted_run_id="old-run",
        )

    asyncio.run(scenario())

    resume = services.sessions.list_messages(PROJECT_ID, SESSION_ID)[-1]
    assert resume.source == driver.MAINLINE_RESUME_SOURCE
    text = resume.content_parts[0].text
    assert "已开始生成：视频 e1" in text
    assert "主线恢复提醒" in text
    assert driver.notifications.store.pending_records(PROJECT_ID) == []


@pytest.mark.parametrize(
    "blocking_source",
    ["user", "run_review_feedback"],
)
def test_batch_merges_notifications_but_stops_at_non_batchable(
    tmp_path,
    blocking_source,
) -> None:
    """Consecutive notifications merge into one run (input-queue drain);
    automated repairs keep their own run, while later progress joins a human.
    """

    from services.file_agent_runtime.notifications import NOTIFICATION_SOURCE

    received: list[str] = []

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="初始目标",
        )
        services.sessions.mark_messages_consumed(
            PROJECT_ID,
            SESSION_ID,
            through_seq=1,
        )
        texts = [
            ("【系统自动消息 · Runtime 通知】进度 0", NOTIFICATION_SOURCE),
            ("【系统自动消息 · Runtime 通知】进度 1", NOTIFICATION_SOURCE),
            ("请修一下这个问题", blocking_source),
            ("【系统自动消息 · Runtime 通知】进度 B", NOTIFICATION_SOURCE),
        ]
        for text, source in texts:
            services.sessions.append_message(
                PROJECT_ID,
                SESSION_ID,
                CONVERSATION_ID,
                role="user",
                content_parts=[{"type": "text", "text": text}],
                source=source,
                channel=MessageChannel.RUNTIME,
            )

        async def callback(messages, _tools):
            received.append(
                "\n".join(
                    str(item["content"])
                    for item in messages
                    if item["role"] == "user"
                ),
            )
            return AgentModelTurn(content="处理完毕。")

        driver = _driver(services, callback)
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_consumed(services, 5)
        await driver.wait_until_idle(PROJECT_ID)
        await driver.stop()
        return services, driver

    services, driver = asyncio.run(scenario())

    expected_runs = 2 if blocking_source == "user" else 3
    assert len(received) == expected_runs
    assert "RUNTIME_NOTIFICATIONS_BATCH" in received[0]
    assert "进度 0" in received[0]
    assert "进度 1" in received[0]
    assert "请修一下这个问题" in received[1]
    assert "RUNTIME_NOTIFICATIONS_BATCH" not in received[1]
    assert "进度 B" in received[-1]
    assert len(driver.runs.list(PROJECT_ID)) == expected_runs
    assert (
        services.sessions.get_project_session(
            PROJECT_ID,
        ).last_consumed_message_seq
        == 5
    )


@pytest.mark.parametrize("source", ["user", "review_rejection_feedback"])
@pytest.mark.parametrize("review_pause", [None, "PENDING_REVIEW", "RESUMING"])
def test_human_revisions_take_priority_over_queued_automated_reviews(
    tmp_path,
    source,
    review_pause,
):
    """A real revision must not wait behind stale automated repair requests."""
    received = []

    async def scenario():
        services, snapshot = _create_project(tmp_path, initial_goal="六集短剧")
        _write_runtime_state(services, snapshot)
        if review_pause:
            candidate = snapshot.project.model_dump(mode="json")
            candidate["description"] = "第二集剧本仍待审阅"
            review = services.commits.commit(
                base=snapshot,
                candidate=candidate,
                round_id="round-draft",
                origin="agentdock_interrupt",
                review_policy="require_review",
                review_boundary=ReviewBoundary(
                    request_message_seq=1,
                    request_id="draft-request",
                    interrupted_run_id="previous-run",
                    accepted_generation=snapshot.generation,
                    accepted_etag=snapshot.etag,
                ),
                caused_by_request_id="draft-request",
                caused_by_message_seq=1,
            ).review
            assert review is not None
        services.sessions.mark_messages_consumed(
            PROJECT_ID,
            SESSION_ID,
            through_seq=1,
        )
        for automated_source in (
            "review_approval_resume",
            "run_review_feedback",
            "render_review_feedback",
            "runtime_notification",
        ):
            services.sessions.append_message(
                PROJECT_ID,
                SESSION_ID,
                CONVERSATION_ID,
                role="user",
                content_parts=[{"type": "text", "text": automated_source}],
                source=automated_source,
                channel=MessageChannel.RUNTIME,
                metadata={
                    "notificationKind": "subagent_terminal",
                    "originSource": "run_review_feedback",
                },
            )

        async def callback(messages, _tools):
            received.append(messages[1]["content"])
            return AgentModelTurn(content="已收到反馈。")

        driver = _driver(services, callback)
        if review_pause:
            services.sessions.set_session_status(
                PROJECT_ID,
                SESSION_ID,
                review_pause,
            )
            await driver._reconcile_project(PROJECT_ID)
            assert PROJECT_ID not in driver._active
            assert (
                received == []
            ), "automatic reviews still wait for human decisions"
        requests = []
        for request_id, text in (
            ("fix-room", "请修正茶社反向机位的窗户方向"),
            ("fix-bottle", "还要让酒瓶与张东身份图保持一致"),
        ):
            admitted = services.sessions.admit_user_request(
                PROJECT_ID,
                SESSION_ID,
                CONVERSATION_ID,
                request_id=request_id,
                client_message_id=request_id,
                content_parts=[{"type": "text", "text": text}],
                source=source,
                channel=MessageChannel.AGENTDOCK,
                classification=MessageClassification.REVIEW_REVISE,
            )
            assert admitted.review_boundary is not None
            requests.append(admitted.message)
            if request_id == "fix-room":
                services.sessions.append_message(
                    PROJECT_ID,
                    SESSION_ID,
                    CONVERSATION_ID,
                    role="user",
                    content_parts=[{"type": "text", "text": "旧分镜自动审阅结果"}],
                    source="run_review_feedback",
                    channel=MessageChannel.RUNTIME,
                )

        await driver.start()
        try:
            driver.notify(PROJECT_ID)
            await _wait_consumed(services, requests[-1].message_seq)
            await driver.wait_until_idle(PROJECT_ID)
            if review_pause:
                active = services.reviews.active(PROJECT_ID)
                assert (
                    active is not None and active.review_id == review.review_id
                )
                assert all(
                    item.decision.value == "PENDING"
                    for item in active.operations
                )
            return driver.runs.list(PROJECT_ID), requests
        finally:
            await driver.stop()

    runs, requests = asyncio.run(scenario())
    assert [run.caused_by_message_seq for run in runs] == [
        requests[-1].message_seq,
    ]
    assert len(received) == 1
    assert "还要让酒瓶与张东身份图" in received[0].split("CURRENT_USER_REQUEST=")[-1]
    # Automated findings remain available as context, without an obsolete
    # paid repair being dispatched ahead of either human request.
    assert "run_review_feedback" in received[0]
    assert "请修正茶社反向机位" in received[0]


# -- asynchronous delegation ------------------------------------------------


def test_delegate_accepted_then_terminal_notification_resumes(
    tmp_path,
) -> None:
    """ACCEPTED tool result now; terminal outcome as a steer notification."""

    parent_turn = 0

    async def callback(messages, tools):
        nonlocal parent_turn
        names = {item["function"]["name"] for item in tools}
        if "delegate_to_agent" not in names:
            return AgentModelTurn(content="[SUCCESS] 素材理解已提交。")
        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-async-1",
                role="ai_editing_director",
                target_refs=["timeline:timeline:main"],
                task="编排 Timeline 选段",
            )
        if parent_turn == 2:
            delegated = json.loads(messages[-1]["content"])
            assert delegated["status"] == "ACCEPTED"
            assert delegated["runId"].startswith("specialist-run-")
            assert delegated["ok"] is True
            return AgentModelTurn(content="已委派，等待 Specialist 终态通知。")
        assert "[SUCCESS]" in messages[1]["content"]
        return AgentModelTurn(content="Specialist 结果已核对。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="剪辑")
        driver = _driver(services, callback)
        driver.specialist_tools.invoke = _succeeded_invoke  # type: ignore[method-assign]
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(lambda: parent_turn >= 3)
        await driver.wait_until_idle(PROJECT_ID)
        runs = driver.executions.list_specialist_runs(PROJECT_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return runs, messages

    runs, messages = asyncio.run(scenario())

    assert len(runs) == 1
    assert runs[0].status.value == "SUCCEEDED"
    notifications = [
        item
        for item in messages
        if item.role == "user" and item.source == "runtime_notification"
    ]
    assert len(notifications) == 1
    assert notifications[0].metadata["specialistStatus"] == "SUCCEEDED"
    assert notifications[0].metadata["specialistRunId"] == runs[0].run_id


def test_stop_after_terminal_persisted_keeps_outcome_and_stays_silent(
    tmp_path,
) -> None:
    """A hard stop landing after SUCCEEDED persisted must neither
    overwrite the terminal outcome nor chase the stop with a spurious
    [FAILED] notification."""

    reached_terminal_event = asyncio.Event()
    parent_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn
        names = {item["function"]["name"] for item in tools}
        if "delegate_to_agent" not in names:
            return AgentModelTurn(content="[SUCCESS] 剪辑完成。")
        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-stop-race",
                role="ai_editing_director",
                target_refs=["timeline:timeline:main"],
                task="编排 Timeline 选段",
            )
        return AgentModelTurn(content="已委派。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="剪辑")
        driver = _driver(services, callback)
        driver.specialist_tools.invoke = _succeeded_invoke  # type: ignore[method-assign]
        original_event = driver._event

        async def gated_event(project_id, session_id, event_type, *args):
            if event_type == "subagent.completed":
                # SUCCEEDED is already durable; park here so the stop
                # lands inside the terminal-event window.
                reached_terminal_event.set()
                await asyncio.Event().wait()
            return await original_event(
                project_id,
                session_id,
                event_type,
                *args,
            )

        driver._event = gated_event  # type: ignore[method-assign]
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(reached_terminal_event.wait(), timeout=10)
        driver._cancel_project_specialists(
            PROJECT_ID,
            reason="user_interrupt",
        )
        await _wait_for(
            lambda: not driver._specialist_tasks.get(PROJECT_ID),
        )
        await driver.wait_until_idle(PROJECT_ID)
        runs = driver.executions.list_specialist_runs(PROJECT_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return runs, messages

    runs, messages = asyncio.run(scenario())

    assert len(runs) == 1
    assert (
        runs[0].status.value == "SUCCEEDED"
    ), "the durable terminal outcome must survive the stop"
    notifications = [
        item
        for item in messages
        if item.role == "user" and item.source == "runtime_notification"
    ]
    assert notifications == [], (
        "a hard stop must not be chased by a fabricated terminal "
        "notification"
    )


def test_new_mainline_run_does_not_cancel_running_specialist(
    tmp_path,
) -> None:
    """_begin_epoch of a later run must not kill a detached specialist."""

    release = asyncio.Event()
    specialist_started = asyncio.Event()
    parent_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn
        names = {item["function"]["name"] for item in tools}
        if "delegate_to_agent" not in names:
            specialist_started.set()
            await release.wait()
            return AgentModelTurn(content="[SUCCESS] 剪辑完成。")
        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-longrun",
                role="ai_editing_director",
                target_refs=["timeline:timeline:main"],
                task="编排 Timeline 选段",
            )
        return AgentModelTurn(content="收到。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="剪辑")
        driver = _driver(services, callback)

        def consumed() -> int:
            # Snapshot read: the full get_project_session recovery holds
            # the exclusive session lock and, polled tightly, starves the
            # dispatcher's shared snapshot read (writer-priority lock).
            return services.sessions.get_project_session_snapshot(
                PROJECT_ID,
            ).last_consumed_message_seq

        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(specialist_started.wait(), timeout=5.0)
        await _wait_for(lambda: consumed() >= 1)
        # A human message starts a NEW mainline run while the specialist
        # is still working: its _begin_epoch increments the project epoch.
        services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": "顺便改一下标题"}],
            source="user",
        )
        driver.notify(PROJECT_ID)
        await _wait_for(lambda: consumed() >= 2)
        release.set()
        await _wait_for(
            lambda: (
                (runs := driver.executions.list_specialist_runs(PROJECT_ID))
                and runs[0].status.value == "SUCCEEDED"
            ),
        )
        runs = driver.executions.list_specialist_runs(PROJECT_ID)
        await driver.stop()
        return runs

    runs = asyncio.run(scenario())
    assert runs[0].status.value == "SUCCEEDED"


def test_stop_cancels_detached_specialists_without_notification(
    tmp_path,
) -> None:
    release = asyncio.Event()
    specialist_started = asyncio.Event()
    parent_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn
        names = {item["function"]["name"] for item in tools}
        if "delegate_to_agent" not in names:
            specialist_started.set()
            await release.wait()
            return AgentModelTurn(content="[SUCCESS] 不应到达。")
        parent_turn += 1
        if parent_turn == 1:
            return _delegate_call(
                "delegate-stop",
                role="ai_editing_director",
                target_refs=["timeline:timeline:main"],
                task="编排 Timeline 选段",
            )
        return AgentModelTurn(content="收到。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="剪辑")
        driver = _driver(services, callback)
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(specialist_started.wait(), timeout=5.0)
        await _wait_consumed(services, 1)
        await driver.stop()
        runs = driver.executions.list_specialist_runs(PROJECT_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        return runs, messages

    runs, messages = asyncio.run(scenario())
    assert runs[0].status.value == "CANCELLED"
    assert not [
        item
        for item in messages
        if item.role == "user" and item.source == "runtime_notification"
    ], "a human-initiated stop must not chase the cancelled work"


def test_inflight_target_refuses_duplicate_delegation(tmp_path) -> None:
    release = asyncio.Event()
    parent_turn = 0
    duplicate_error: list[str] = []

    async def callback(messages, tools):
        nonlocal parent_turn
        names = {item["function"]["name"] for item in tools}
        if "delegate_to_agent" not in names:
            await release.wait()
            return AgentModelTurn(content="[SUCCESS] 剪辑完成。")
        parent_turn += 1
        if parent_turn <= 2:
            return _delegate_call(
                f"delegate-dup-{parent_turn}",
                role="ai_editing_director",
                target_refs=["timeline:timeline:main"],
                task="编排 Timeline 选段",
            )
        duplicate_error.append(messages[-1]["content"])
        release.set()
        return AgentModelTurn(content="等待首个委派完成。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="剪辑")
        driver = _driver(services, callback)
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(lambda: parent_turn >= 3)
        await _wait_consumed(services, 1)
        await _wait_for(
            lambda: any(
                run.status.value == "SUCCEEDED"
                for run in driver.executions.list_specialist_runs(PROJECT_ID)
            ),
        )
        runs = driver.executions.list_specialist_runs(PROJECT_ID)
        await driver.stop()
        return runs

    runs = asyncio.run(scenario())
    assert len(runs) == 1, "the duplicate delegation must not spawn a run"
    assert duplicate_error
    assert "already in flight" in duplicate_error[0]


def test_startup_reclaims_orphaned_specialist_runs(tmp_path) -> None:
    from domain.enums import SpecialistRole as SpecialistRoleEnum
    from domain.enums import SpecialistRunStatus as RunStatus
    from services.runtime_files.execution_models import SpecialistRunRecord

    async def scenario():
        services, snapshot = _create_project(tmp_path, initial_goal="剪辑")
        executions = _driver(
            services,
            lambda _messages, _tools: AgentModelTurn(),
        ).executions
        record = SpecialistRunRecord(
            run_id="specialist-run-orphan",
            project_id=PROJECT_ID,
            round_id="agent-round-old",
            role=SpecialistRoleEnum.AI_EDITING_DIRECTOR,
            target_refs=["timeline:timeline:main"],
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            related_run_id="agent-run-old",
            prompt_spec_id="file_project_json.ai_editing_director.v1",
            caused_by_message_id="message-initial",
            caused_by_message_seq=1,
            metadata={"parentActionId": "delegate-call-1"},
        )
        executions.create_specialist_run(record)
        executions.transition_specialist_run(
            PROJECT_ID,
            record.run_id,
            expected_status=RunStatus.QUEUED,
            status=RunStatus.RUNNING_MODEL,
        )
        # A media-execution run (no parentActionId) shares the same store
        # but owns provider-resume machinery: restart must not touch it.
        media_record = SpecialistRunRecord(
            run_id="specialist-run-media",
            project_id=PROJECT_ID,
            round_id="agent-round-old",
            role=SpecialistRoleEnum.AI_EDITING_DIRECTOR,
            target_refs=["element:e1"],
            input_generation=snapshot.generation,
            input_etag=snapshot.etag,
            related_run_id="agent-run-old",
            prompt_spec_id="file_project_json.ai_editing_director.v1",
            caused_by_message_id="message-initial",
            caused_by_message_seq=1,
            metadata={"commandType": "generate_storyboard_image"},
        )
        executions.create_specialist_run(media_record)
        executions.transition_specialist_run(
            PROJECT_ID,
            media_record.run_id,
            expected_status=RunStatus.QUEUED,
            status=RunStatus.RUNNING_MODEL,
        )
        # Fresh process: the run has no owning task anymore.
        driver = _driver(
            services,
            lambda _messages, _tools: AgentModelTurn(),
        )
        await driver.start()
        await _wait_for(
            lambda: driver.executions.get_specialist_run(
                PROJECT_ID,
                record.run_id,
            ).status.value
            == "FAILED",
        )
        reclaimed = driver.executions.get_specialist_run(
            PROJECT_ID,
            record.run_id,
        )
        media_untouched = driver.executions.get_specialist_run(
            PROJECT_ID,
            media_record.run_id,
        )
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return reclaimed, media_untouched, messages

    reclaimed, media_untouched, messages = asyncio.run(scenario())
    assert reclaimed.status.value == "FAILED"
    assert (
        media_untouched.status.value == "RUNNING_MODEL"
    ), "media execution runs must survive the restart sweep"
    assert "orphaned by restart" in (reclaimed.final_summary_text or "")
    notifications = [
        item
        for item in messages
        if item.role == "user" and item.source == "runtime_notification"
    ]
    assert len(notifications) == 1
    assert notifications[0].metadata["specialistStatus"] == "FAILED"
    assert "进程重启" in notifications[0].content_parts[0].text


def test_subagent_terminal_notification_is_never_batched(tmp_path) -> None:
    """Terminal notifications carry delegation-origin identity resolved
    from the run's head message; merging one into another head's batch
    would strip repair dedup and the paid repair budget."""

    from services.file_agent_runtime.notifications import NOTIFICATION_SOURCE

    received: list[str] = []

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="初始目标",
        )
        services.sessions.mark_messages_consumed(
            PROJECT_ID,
            SESSION_ID,
            through_seq=1,
        )
        services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[
                {
                    "type": "text",
                    "text": "【系统自动消息 · Runtime 通知】普通进度",
                },
            ],
            source=NOTIFICATION_SOURCE,
            channel=MessageChannel.RUNTIME,
            metadata={"notificationKind": "node_succeeded"},
        )
        services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[
                {
                    "type": "text",
                    "text": "【系统自动消息 · Runtime 通知】Specialist 终态 [SUCCEEDED]",
                },
            ],
            source=NOTIFICATION_SOURCE,
            channel=MessageChannel.RUNTIME,
            metadata={
                "notificationKind": "subagent_terminal",
                "originSource": "run_review_feedback",
                "originMessageId": "message-review-1",
            },
        )

        async def callback(messages, _tools):
            received.append(messages[1]["content"])
            return AgentModelTurn(content="已核对。")

        driver = _driver(services, callback)
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_consumed(services, 3)
        await driver.wait_until_idle(PROJECT_ID)
        runs = driver.runs.list(PROJECT_ID)
        await driver.stop()
        return runs

    runs = asyncio.run(scenario())

    assert len(received) == 2, (
        "the terminal notification must start its own run so its origin "
        "identity governs repair dedup and budget"
    )
    assert "普通进度" in received[0]
    assert "Specialist 终态" in received[1]
    assert "Specialist 终态" not in received[0]
    assert len(runs) == 2


@pytest.mark.parametrize(
    ("source", "notification_kind"),
    [
        (source, kind)
        for source in (
            "user",
            "review_rejection_feedback",
            "review_approval_resume",
        )
        for kind in (None, "node_succeeded", "subagent_terminal")
    ]
    + [
        (source, kind)
        for source in ("user", "review_rejection_feedback")
        for kind in (
            "foreign_subagent_terminal",
            "run_review_feedback",
            "render_review_feedback",
        )
    ],
)
def test_running_user_message_joins_current_run_once(
    tmp_path,
    notification_kind,
    source,
) -> None:
    """Human input and undo-and-redo feedback reach the live run exactly once."""
    from services.runtime_files.execution_models import (
        SpecialistRole,
        SpecialistRunRecord,
        SpecialistRunStatus,
    )

    correction = "我不希望水豚噜噜头顶着橘子了，我希望他头顶一个西瓜"
    notification = "【系统自动消息 · Runtime 通知】素材理解完成"
    received = []
    correction_seq = 0

    async def scenario():
        services, _ = _create_project(tmp_path, initial_goal="制作噜噜视频")

        async def callback(messages, _tools):
            nonlocal correction_seq
            received.append([dict(item) for item in messages])
            if len(received) == 1:
                if notification_kind:
                    metadata = {"notificationKind": notification_kind}
                    if notification_kind in {
                        "subagent_terminal",
                        "foreign_subagent_terminal",
                    }:
                        head = services.sessions.list_messages(
                            PROJECT_ID,
                            SESSION_ID,
                        )[0]
                        record = SpecialistRunRecord(
                            run_id="specialist-run-source-intelligence",
                            project_id=PROJECT_ID,
                            round_id="source-round",
                            role=SpecialistRole.SOURCE_INTELLIGENCE,
                            input_generation=1,
                            input_etag="initial-etag",
                            prompt_spec_id="source-intelligence-test",
                            caused_by_message_id=head.message_id,
                            caused_by_message_seq=head.message_seq,
                            metadata={
                                "originSource": head.source,
                                "originMessageId": (
                                    "older-review-message"
                                    if notification_kind
                                    == "foreign_subagent_terminal"
                                    else head.message_id
                                ),
                            },
                        )
                        metadata["notificationKind"] = "subagent_terminal"
                        driver.executions.create_specialist_run(record)
                        for previous, status in (
                            (
                                SpecialistRunStatus.QUEUED,
                                SpecialistRunStatus.RUNNING_MODEL,
                            ),
                            (
                                SpecialistRunStatus.RUNNING_MODEL,
                                SpecialistRunStatus.SUCCEEDED,
                            ),
                        ):
                            driver.executions.transition_specialist_run(
                                PROJECT_ID,
                                record.run_id,
                                expected_status=previous,
                                status=status,
                            )
                        metadata["specialistRunId"] = record.run_id
                    services.sessions.append_message(
                        PROJECT_ID,
                        SESSION_ID,
                        CONVERSATION_ID,
                        role="user",
                        content_parts=[{"type": "text", "text": notification}],
                        source=(
                            notification_kind
                            if notification_kind
                            in {
                                "run_review_feedback",
                                "render_review_feedback",
                            }
                            else "runtime_notification"
                        ),
                        channel=MessageChannel.RUNTIME,
                        metadata=metadata,
                    )
                appended = services.sessions.append_message(
                    PROJECT_ID,
                    SESSION_ID,
                    CONVERSATION_ID,
                    role="user",
                    content_parts=[{"type": "text", "text": correction}],
                    client_message_id="running-correction",
                    source=source,
                    channel=MessageChannel.AGENTDOCK,
                    classification=(
                        MessageClassification.REVIEW_REVISE
                        if source != "user"
                        else MessageClassification.MUTATION_INSTRUCTION
                    ),
                    metadata={
                        "context": {
                            "panel": "assets",
                            "selected": {
                                "ref": "visual-variant:char:lulu@variant:lulu-id",
                            },
                        },
                    },
                )
                correction_seq = appended.message.message_seq
                return _read_call("read-before-correction")
            if len(received) == 2:
                return _read_call("read-after-correction")
            return AgentModelTurn(content="已收到，把橘子换成西瓜。")

        driver = _driver(services, callback)
        await driver.start()
        try:
            driver.notify(PROJECT_ID)
            await _wait_for(lambda: correction_seq > 0)
            await _wait_consumed(services, correction_seq)
            await driver.wait_until_idle(PROJECT_ID)
            return driver.runs.list(PROJECT_ID)
        finally:
            await driver.stop()

    runs = asyncio.run(scenario())
    assert len(received) == 3
    assert len(runs) == 1
    assert (
        sum(
            item["role"] == "user" and correction in str(item["content"])
            for item in received[-1]
        )
        == 1
    )
    correction_message = next(
        item["content"]
        for item in received[1]
        if item["role"] == "user" and correction in str(item["content"])
    )
    assert ("请先用简短的公开回复确认" in correction_message) == (
        source != "review_approval_resume"
    )
    assert (
        '"selected":{"ref":"visual-variant:char:lulu@variant:lulu-id"}'
        in correction_message
    )
    assert runs[0].status is AgentRunStatus.SUCCEEDED
    if notification_kind:
        runtime_messages = [
            item["content"]
            for item in received[-1]
            if item["role"] == "user" and notification in str(item["content"])
        ]
        assert runtime_messages == [notification]


def test_feedback_queued_during_run_start_reaches_first_model_turn(tmp_path):
    received = []
    correction = "第八镜要改成两个人物的近景对话"

    async def scenario():
        services, _ = _create_project(tmp_path, initial_goal="六集短剧")

        async def callback(messages, _tools):
            received.append(messages)
            return AgentModelTurn(content="已收到第八镜修改。")

        driver = _driver(services, callback)

        queued = False

        async def starting(**_kwargs):
            nonlocal queued
            if queued:
                return []
            queued = True
            message = services.sessions.append_message(
                PROJECT_ID,
                SESSION_ID,
                CONVERSATION_ID,
                role="user",
                source="review_rejection_feedback",
                channel=MessageChannel.AGENTDOCK,
                content_parts=[{"type": "text", "text": correction}],
            )
            assert message.message.message_seq == 2
            return []

        driver._start_attached_source_understanding = starting
        await driver.start()
        try:
            driver.notify(PROJECT_ID)
            await _wait_consumed(services, 2)
            await driver.wait_until_idle(PROJECT_ID)
            return driver.runs.list(PROJECT_ID)
        finally:
            await driver.stop()

    runs = asyncio.run(scenario())
    assert len(runs) == len(received) == 1
    assert (
        sum(
            correction in str(message["content"])
            for message in received[0]
            if message["role"] == "user"
        )
        == 1
    )


def test_turn_boundary_digest_injected_once_across_turns(tmp_path) -> None:
    """The same staged progress must not be re-appended on every model turn."""

    from services.file_agent_runtime.notifications import RuntimeEventKind

    final_turn_messages: list[list[str]] = []

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="剪辑")

        turn = {"count": 0}

        async def callback(messages, _tools):
            turn["count"] += 1
            if turn["count"] == 1:
                return _read_call("read-1")
            final_turn_messages.append(
                [
                    str(item["content"])
                    for item in messages
                    if item["role"] == "user"
                ],
            )
            return AgentModelTurn(content="收到进度。")

        driver = _driver(services, callback)
        await driver.notifications.inject(
            PROJECT_ID,
            kind=RuntimeEventKind.NODE_DISPATCH_STARTED,
            request_id="node_dispatch_started-video:e9-fp1",
            text="已开始生成：视频 e9",
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_consumed(services, 1)
        await driver.wait_until_idle(PROJECT_ID)
        states = {
            record.state
            for record in driver.notifications.store._current_versions(
                PROJECT_ID,
            ).values()
        }
        await driver.stop()
        return states

    states = asyncio.run(scenario())

    assert final_turn_messages, "the run must reach a second model turn"
    digest_count = sum(
        "已开始生成：视频 e9" in content for content in final_turn_messages[-1]
    )
    assert (
        digest_count == 1
    ), "the injected digest must appear exactly once across model turns"
    assert states == {"DRAINED"}


def test_idle_hard_stop_cancels_pending_notifications(tmp_path) -> None:
    """A hard stop with no active mainline must drop undelivered progress."""

    from services.file_agent_runtime.notifications import RuntimeEventKind

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="剪辑")
        driver = _driver(services, lambda _messages, _tools: AgentModelTurn())
        await driver.notifications.inject(
            PROJECT_ID,
            kind=RuntimeEventKind.NODE_DISPATCH_STARTED,
            request_id="node_dispatch_started-video:e1-fp1",
            text="已开始生成：视频 e1",
        )
        await driver.interrupt(PROJECT_ID, reason="user_interrupt")
        return {
            record.state
            for record in driver.notifications.store._current_versions(
                PROJECT_ID,
            ).values()
        }

    states = asyncio.run(scenario())

    assert states == {"CANCELLED"}


def test_review_gate_read_failure_holds_queued_message(tmp_path) -> None:
    """An unreadable Review state must fail closed instead of launching."""

    turns = {"count": 0}

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="剪辑")

        def broken_active(_project_id):
            raise TimeoutError("review store lock timed out")

        original_active = services.reviews.active
        services.reviews.active = broken_active

        async def callback(_messages, _tools):
            turns["count"] += 1
            return AgentModelTurn(content="不应运行。")

        driver = _driver(services, callback)
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.sleep(0.3)
        held = services.sessions.get_project_session_snapshot(
            PROJECT_ID,
        ).last_consumed_message_seq
        turns_while_broken = turns["count"]
        # Restoring the store lets the next poll tick proceed normally.
        services.reviews.active = original_active
        await _wait_consumed(services, 1)
        await driver.wait_until_idle(PROJECT_ID)
        await driver.stop()
        return held, turns_while_broken

    held, turns_while_broken = asyncio.run(scenario())

    assert held == 0, "the queued message must stay unconsumed while unknown"
    assert turns_while_broken == 0, "no model turn may run while unknown"
    assert turns["count"] >= 1, "recovery must consume the message normally"


def test_uploaded_image_understanding_starts_before_first_planning_turn(
    tmp_path,
    monkeypatch,
):
    async def scenario():
        services, _ = _create_project(tmp_path, initial_goal=None)
        ingested, _ = _ingest_many_sync(
            services,
            project_id=PROJECT_ID,
            key="source-bootstrap-image",
            inputs=[
                _AssetInput(
                    name="lulu.png",
                    content=_png_bytes_for_grounding(),
                    media_type="image/png",
                ),
            ],
            attach_source=False,
            scope="source-bootstrap-test",
        )
        version_id = ingested["items"][0]["assetVersionId"]
        _append_initial_request(
            services,
            content_parts=[{"type": "text", "text": "按上传形象创作"}],
            intent="制作",
            metadata={"assetVersionRefs": [f"asset-version:{version_id}"]},
        )
        calls = []

        async def delegate(**kwargs):
            calls.append(kwargs["arguments"])
            return {
                "status": "ACCEPTED",
                "targetRefs": kwargs["arguments"]["target_refs"],
            }

        async def model(messages, _tools):
            assert len(calls) == 1
            source = next(
                iter(
                    services.projects.read(
                        PROJECT_ID,
                    ).project.sources.sources.items.values(),
                ),
            )
            assert source.selected_asset_version_id == version_id
            assert "理解已启动" in str(messages)
            return AgentModelTurn(content="先规划内容，等待素材理解结果。")

        driver = _driver(services, model)
        monkeypatch.setattr(driver, "_run_subagent", delegate)
        await driver.start()
        try:
            driver.notify(PROJECT_ID)
            await _wait_consumed(services, 1)
            await driver.wait_until_idle(PROJECT_ID)
            assert (
                driver.runs.list(PROJECT_ID)[0].status
                is AgentRunStatus.SUCCEEDED
            )
        finally:
            await driver.stop()

    asyncio.run(scenario())


def test_batched_upload_refs_delegate_one_run_per_target(
    tmp_path,
    monkeypatch,
):
    """Refs across a batched run fan out into single-target delegations.

    Chat uploads land as one runtime notification per request; consecutive
    notifications batch into one run whose head is only the first message.
    Every batched ref must still start understanding, and each target gets
    its own specialist run so uploads are understood in parallel.
    """

    async def scenario():
        services, _ = _create_project(tmp_path, initial_goal=None)
        ingested, _ = _ingest_many_sync(
            services,
            project_id=PROJECT_ID,
            key="source-batch-images",
            inputs=[
                _AssetInput(
                    name=f"img-{index}.png",
                    content=_png_bytes_for_grounding(),
                    media_type="image/png",
                )
                for index in range(3)
            ],
            attach_source=False,
            scope="source-batch-test",
        )
        refs = [
            f"asset-version:{item['assetVersionId']}"
            for item in ingested["items"]
        ]
        expected_targets = {
            f"asset:{item['assetId']}" for item in ingested["items"]
        }
        _append_initial_request(
            services,
            content_parts=[{"type": "text", "text": "按上传素材创作"}],
            intent="制作",
            metadata={"assetVersionRefs": refs[:2]},
        )
        services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": "又补了一张图"}],
            channel=MessageChannel.AGENTDOCK,
            metadata={"assetVersionRefs": refs[2:]},
        )
        calls = []

        async def delegate(**kwargs):
            calls.append(kwargs["arguments"])
            return {
                "status": "ACCEPTED",
                "targetRefs": kwargs["arguments"]["target_refs"],
            }

        async def model(_messages, _tools):
            return AgentModelTurn(content="先规划内容，等待素材理解结果。")

        driver = _driver(services, model)
        monkeypatch.setattr(driver, "_run_subagent", delegate)
        await driver.start()
        try:
            driver.notify(PROJECT_ID)
            await _wait_consumed(services, 2)
            await driver.wait_until_idle(PROJECT_ID)
        finally:
            await driver.stop()
        return calls, expected_targets

    calls, expected_targets = asyncio.run(scenario())

    assert [len(call["target_refs"]) for call in calls] == [1, 1, 1]
    assert {call["target_refs"][0] for call in calls} == expected_targets


@pytest.mark.parametrize("upload_count", [1, 2])
def test_upload_joining_a_live_run_starts_understanding(
    tmp_path,
    monkeypatch,
    upload_count,
):
    """Refs on a message that joins a running turn loop must still fan out.

    Field run 2026-09-11 (project-3c08b43d): a video uploaded from the
    composer while the agent was planning joined the live run, yet no
    source_intelligence run was ever created and the started-notice lied.
    """

    calls = []
    received = []

    async def scenario():
        services, _ = _create_project(tmp_path, initial_goal="制作噜噜视频")
        ingested, _ = _ingest_many_sync(
            services,
            project_id=PROJECT_ID,
            key="mid-run-upload",
            inputs=[
                _AssetInput(
                    name=f"voice-ref-{index}.png",
                    content=_png_bytes_for_grounding(),
                    media_type="image/png",
                )
                for index in range(upload_count)
            ],
            attach_source=False,
            scope="mid-run-upload-test",
        )
        items = ingested["items"]

        async def delegate(**kwargs):
            calls.append(kwargs["arguments"])
            return {
                "status": "ACCEPTED",
                "targetRefs": kwargs["arguments"]["target_refs"],
            }

        async def model(messages, _tools):
            received.append([dict(entry) for entry in messages])
            if len(received) == 1:
                for item in items:
                    services.sessions.append_message(
                        PROJECT_ID,
                        SESSION_ID,
                        CONVERSATION_ID,
                        role="user",
                        content_parts=[
                            {"type": "text", "text": "我刚上传了噜噜的参考素材"},
                        ],
                        source="user",
                        channel=MessageChannel.AGENTDOCK,
                        metadata={
                            "assetVersionRefs": [
                                f"asset-version:{item['assetVersionId']}",
                            ],
                        },
                    )
                return _read_call("read-before-upload")
            return AgentModelTurn(content="收到素材，理解进行中。")

        driver = _driver(services, model)
        monkeypatch.setattr(driver, "_run_subagent", delegate)
        await driver.start()
        try:
            driver.notify(PROJECT_ID)
            await _wait_consumed(services, 1 + upload_count)
            await driver.wait_until_idle(PROJECT_ID)
        finally:
            await driver.stop()
        return items

    items = asyncio.run(scenario())

    assert [call["target_refs"] for call in calls] == [
        [f"asset:{item['assetId']}"] for item in items
    ]
    # The joined turn must carry the started-notice so the agent neither
    # re-delegates nor believes understanding is running when it is not.
    joined_turn = received[-1]
    assert any(
        "本轮上传素材的理解已启动" in str(entry.get("content") or "")
        for entry in joined_turn
    )
