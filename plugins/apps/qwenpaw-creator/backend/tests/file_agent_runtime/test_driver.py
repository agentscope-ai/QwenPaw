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
from domain.errors import ReviewPendingError
from schemas.assets import SourceMediaMetadata, SourceModelRunRef
from services.file_agent_runtime import (
    AgentModelConfigurationError,
    AgentModelTurn,
    AgentRunStatus,
    AgentToolCall,
    CallbackAgentChatClient,
    FileCreatorAgentRuntime,
)
from services.file_agent_runtime.driver import (
    MalformedJqProjectArguments,
    _apply_review_feedback_to_tool_arguments,
    _jq_project_argument_diagnosis,
    _review_feedback_target_refs,
    _specialist_tool_recovery,
)
from services.file_agent_runtime.prompts import render_creator_system_prompt
from services.observability import read_trace_records
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
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
from services.source_analysis import (
    SourceAnalyzerOutput,
    SourceMediaAnalysisService,
)
from services.specialist_tools import SpecialistToolResult

pytestmark = pytest.mark.unit


PROJECT_ID = "project-1"
SESSION_ID = "session-1"
CONVERSATION_ID = "conversation-1"
GOAL_ID = "goal-1"


def test_rejection_feedback_is_fenced_and_injected_into_media_prompt() -> None:
    request = CreatorMessageRecord(
        message_id="message-review-feedback",
        project_id=PROJECT_ID,
        creator_session_id=SESSION_ID,
        conversation_id=CONVERSATION_ID,
        message_seq=3,
        role="user",
        content_parts=[{"type": "text", "text": "请按反馈重做"}],
        source="review_rejection_feedback",
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.REVIEW_REVISE,
        metadata={
            "decisionId": "decision-dramatic",
            "rejectionFeedback": {
                "action": "UNDO_AND_REGENERATE",
                "problemNote": "画面张力不足",
                "regenerationInstruction": "更加 dramatic",
            },
            "targets": [{"target_ref": "element:ep22"}],
        },
    )
    arguments = {
        "projectId": PROJECT_ID,
        "targetRef": "element:ep22",
        "arguments": {"prompt": "原始分镜 prompt"},
    }

    enriched, applied = _apply_review_feedback_to_tool_arguments(
        request,
        name="image_generation",
        arguments=arguments,
    )

    assert _review_feedback_target_refs(request) == {"element:ep22"}
    assert applied is True
    assert arguments["arguments"]["prompt"] == "原始分镜 prompt"
    prompt = enriched["arguments"]["prompt"]
    assert "[review-decision:decision-dramatic]" in prompt
    assert "画面张力不足" in prompt
    assert "更加 dramatic" in prompt


def test_unified_rejection_feedback_is_injected_into_media_prompt() -> None:
    request = CreatorMessageRecord(
        message_id="message-review-feedback-unified",
        project_id=PROJECT_ID,
        creator_session_id=SESSION_ID,
        conversation_id=CONVERSATION_ID,
        message_seq=4,
        role="user",
        content_parts=[{"type": "text", "text": "请按反馈重做"}],
        source="review_rejection_feedback",
        channel=MessageChannel.AGENTDOCK,
        classification=MessageClassification.REVIEW_REVISE,
        metadata={
            "decisionId": "decision-unified",
            "rejectionFeedback": {
                "action": "UNDO_AND_REGENERATE",
                "feedbackNote": ("人物仍像巅峰时期；保持身份一致，改成落魄时期"),
            },
            "targets": [{"target_ref": "element:ep22"}],
        },
    )
    arguments = {
        "projectId": PROJECT_ID,
        "targetRef": "element:ep22",
        "arguments": {"prompt": "原始分镜 prompt"},
    }

    enriched, applied = _apply_review_feedback_to_tool_arguments(
        request,
        name="image_generation",
        arguments=arguments,
    )

    assert applied is True
    prompt = enriched["arguments"]["prompt"]
    assert "必须吸收的用户反馈" in prompt
    assert "保持身份一致，改成落魄时期" in prompt


def test_stale_project_snapshots_are_elided_from_the_continuation() -> None:
    """Only the newest runtime project echo survives prompt assembly.

    A 50-element production run accumulated 18 full project.json echoes
    (2.09MB) in one Conversation and every model call failed with an
    input-length 400. Older echoes carry no information the model cannot
    get from read_project, so they collapse to a one-line stub; durable
    history keeps every byte.
    """

    from services.file_agent_runtime.driver import (
        _continuation_message_text,
    )

    def message(seq: int, *, role: str, source: str, text: str):
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
        )

    old_snapshot = json.dumps(
        {"project": {"generation": 11, "padding": "x" * 8000}},
    )
    new_snapshot = json.dumps(
        {"project": {"generation": 113, "padding": "y" * 8000}},
    )
    prior = [
        message(1, role="user", source="user", text="把故事写完"),
        message(
            2,
            role="tool",
            source="runtime_action_result",
            text=old_snapshot,
        ),
        message(3, role="assistant", source="creator_agent", text="写好了"),
        message(
            4,
            role="tool",
            source="runtime_action_result",
            text=new_snapshot,
        ),
    ]
    request = message(5, role="user", source="user", text="继续")

    rendered = _continuation_message_text(request, prior)

    # The stale echo is gone, replaced by a stub that names its vintage.
    assert "x" * 100 not in rendered
    assert "generation 11 时点" in rendered
    assert "read_project" in rendered
    # The newest echo and ordinary messages survive verbatim.
    assert "y" * 100 in rendered
    assert "把故事写完" in rendered
    assert "写好了" in rendered


def test_small_runtime_results_are_never_elided() -> None:
    from services.file_agent_runtime.driver import (
        _continuation_message_text,
    )

    def message(seq: int, *, role: str, source: str, text: str):
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
        )

    prior = [
        message(
            1,
            role="tool",
            source="runtime_action_result",
            text='{"ok": true, "taskId": "task-1"}',
        ),
        message(
            2,
            role="tool",
            source="runtime_action_result",
            text='{"ok": true, "taskId": "task-2"}',
        ),
    ]
    request = message(3, role="user", source="user", text="继续")

    rendered = _continuation_message_text(request, prior)

    assert "task-1" in rendered
    assert "task-2" in rendered
    assert "已省略" not in rendered


def test_grounding_tool_is_absent_when_grounding_is_disabled(
    monkeypatch,
) -> None:
    from services.file_agent_runtime import driver as driver_module

    monkeypatch.setattr(
        driver_module,
        "get_web_grounding_enabled",
        lambda: False,
    )

    names = {
        item["function"]["name"]
        for item in driver_module._creator_agent_tool_manifest()
    }

    assert "ground_prompt_context" not in names


def test_message_text_includes_exact_project_json_selection_locator() -> None:
    from services.file_agent_runtime.driver import _message_text

    message = CreatorMessageRecord(
        message_id="message-selection",
        project_id=PROJECT_ID,
        creator_session_id=SESSION_ID,
        conversation_id=CONVERSATION_ID,
        message_seq=1,
        role="user",
        content_parts=[{"type": "text", "text": "修改这段描述"}],
        metadata={
            "context": {
                "panel": "plan",
                "selection": {
                    "ref": "element:edit-1",
                    "field": "element:edit-1/creation/reason",
                    "path": "/timelines/items/timeline:main/elements_by_id/edit-1/creation/reason",
                    "label": "素材选择依据",
                    "text": "猫跳上桌面",
                    "start": 0,
                    "end": 5,
                },
            },
        },
    )

    rendered = _message_text(message)

    assert rendered.startswith("修改这段描述\n[Creator UI 结构化上下文")
    assert '"ref":"element:edit-1"' in rendered
    assert '"field":"element:edit-1/creation/reason"' in rendered
    assert (
        '"path":"/timelines/items/timeline:main/elements_by_id/edit-1/creation/reason"'
        in rendered
    )


def test_ai_edit_idempotency_can_be_scoped_to_one_model_tool_call() -> None:
    from services.file_agent_runtime.driver import (
        _specialist_tool_invocation_id,
    )

    arguments = {
        "projectId": PROJECT_ID,
        "targetRef": "timeline:timeline:main",
        "arguments": {"operation": "execute"},
    }
    first = _specialist_tool_invocation_id(
        "specialist-run-1",
        "ai_edit",
        arguments,
        call_id="tool-call-1",
    )
    replay = _specialist_tool_invocation_id(
        "specialist-run-1",
        "ai_edit",
        arguments,
        call_id="tool-call-1",
    )
    retry = _specialist_tool_invocation_id(
        "specialist-run-1",
        "ai_edit",
        arguments,
        call_id="tool-call-2",
    )
    image_first = _specialist_tool_invocation_id(
        "specialist-run-1",
        "image_generation",
        arguments,
        call_id="tool-call-1",
    )
    image_retry = _specialist_tool_invocation_id(
        "specialist-run-1",
        "image_generation",
        arguments,
        call_id="tool-call-2",
    )

    assert first == replay
    assert retry != first
    assert image_retry == image_first
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
            initial_client_message_id=(
                "client-initial" if initial_goal is not None else None
            ),
        )

    snapshot = services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Initial"),
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
            "ground_prompt_context",
            "elements_at",
            "delegate_to_agent",
        }
        # The role prompt and static Pydantic schema form one stable system prompt.
        assert messages[0]["content"] == render_creator_system_prompt(
            project_id=PROJECT_ID,
        )
        assert "# Workspace 基础 Schema" in messages[0]["content"]
        assert "PROJECT_JSON_SCHEMA=" in messages[0]["content"]
        turn += 1
        if turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="read-1",
                        name="read_project",
                        arguments={"projectId": PROJECT_ID},
                    ),
                ),
            )
        if turn == 2:
            observed = json.loads(messages[-1]["content"])
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="write-1",
                        name="jq_project",
                        arguments={
                            "projectId": PROJECT_ID,
                            "baseEtag": observed["etag"],
                            "program": ".description = $description",
                            "stringArgs": {"description": description},
                        },
                    ),
                ),
            )
        return AgentModelTurn(content="项目说明已更新。")

    return CallbackAgentChatClient(callback)


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
                    "elem-01": {
                        "program": ".description = $description",
                    },
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
    turn = 0

    async def callback(messages, _tools):
        nonlocal turn
        turn += 1
        if turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="read-before-corruption",
                        name="read_project",
                        arguments={"projectId": PROJECT_ID},
                    ),
                ),
            )
        if turn == 2:
            observed = json.loads(messages[-1]["content"])
            return AgentModelTurn(
                tool_calls=(
                    _corrupted_jq_call(
                        call_id="malformed-write",
                        etag=observed["etag"],
                    ),
                ),
            )
        if turn == 3:
            rejected = json.loads(messages[-1]["content"])
            assert rejected["error"]["type"] == ("MalformedJqProjectArguments")
            assert rejected["error"]["retry"] == {
                "attempt": 1,
                "retriesRemaining": 2,
                "samePayload": False,
            }
            assert rejected["error"]["details"]["missingTopLevel"] == [
                "program",
            ]
            assert rejected["error"]["details"]["nestedRequiredPaths"] == [
                "$.jsonArgs.timeline_elements.elem-01.program",
            ]
            assert "Split bulk work" in rejected["error"]["recovery"]
            assert "ValidationError" not in messages[-1]["content"]
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="reread-after-corruption",
                        name="read_project",
                        arguments={"projectId": PROJECT_ID},
                    ),
                ),
            )
        if turn == 4:
            observed = json.loads(messages[-1]["content"])
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
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
                    ),
                ),
            )
        return AgentModelTurn(content="Recovered and completed.")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="Create the project plan",
        )
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        project = services.projects.read(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return project, session, events, messages

    project, session, events, messages = asyncio.run(scenario())

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
    assert checks[0].payload["schemaValid"] is False
    assert checks[1].payload["schemaValid"] is True
    malformed_results = [
        json.loads(message.content_parts[0].text or "{}")
        for message in messages
        if message.role == "tool"
        and message.metadata.get("toolCallId") == "malformed-write"
    ]
    assert malformed_results[0]["error"]["type"] == (
        "MalformedJqProjectArguments"
    )


def test_stale_snapshot_and_quarantine_replays_get_targeted_recovery() -> None:
    """Quarantined/stale media tasks tell the model to re-admit fresh.

    Replaying the identical call can only hit the same terminated Task;
    without this guidance the model burned its remaining turns retrying.
    """

    stale = _specialist_tool_recovery(
        "r2v_generation",
        "Task task-1 ended as QUARANTINED: {'code': "
        "'PROJECT_INPUT_SNAPSHOT_STALE', 'message': "
        "'PROJECT_INPUT_SNAPSHOT_STALE'}",
    )
    assert "quarantined" in stale
    assert "read_project" in stale
    assert "fresh r2v_generation call" in stale

    replay = _specialist_tool_recovery(
        "image_generation",
        "图片 Task 已终止: QUARANTINED",
    )
    assert "fresh image_generation call" in replay

    # Unrelated failures keep their existing guidance.
    generic = _specialist_tool_recovery(
        "r2v_generation",
        "Task task-2 ended as FAILED: provider timeout",
    )
    assert "quarantined" not in generic


def test_r2v_real_face_rejection_gets_targeted_recovery() -> None:
    """The provider face-moderation error names the exact repair steps.

    A non-retryable real-face rejection can never succeed with the same
    references; the recovery must say to drop source-photo references and
    keep generated artifact references instead of the generic retry text.
    """

    targeted = _specialist_tool_recovery(
        "r2v_generation",
        "Task task-1 ended as FAILED: {'code': 'R2V_PROVIDER_FAILED', "
        "'message': 'The input content is suspected to include real "
        "human faces.', 'retryable': False}",
    )
    assert "real human faces" in targeted
    assert "video_reference_version_ids" in targeted
    assert "artifact-version" in targeted
    assert "do not resubmit the same references" in targeted.casefold()

    # Other r2v failures keep the generic guidance.
    generic = _specialist_tool_recovery(
        "r2v_generation",
        "Task task-2 ended as FAILED: provider timeout",
    )
    assert "video_reference_version_ids" not in generic


def test_extra_data_recovery_names_the_premature_close() -> None:
    """An "Extra data" strict error gets the premature-close hint.

    The model closed the root object early and kept streaming entries;
    the recovery must name that mistake with the byte offset instead of
    only suggesting smaller batches.
    """

    diagnosis = _jq_project_argument_diagnosis(
        AgentToolCall(
            call_id="extra-data-write",
            name="jq_project",
            arguments={
                "projectId": PROJECT_ID,
                "program": ".description = $description",
                "stringArgs": {"description": "partial"},
            },
            raw_arguments_bytes=9_364,
            arguments_repaired=True,
            strict_json_error=(
                "JSONDecodeError: Extra data: line 1 column 5757 (char 5756)"
            ),
        ),
    )
    assert diagnosis.schema_valid is True
    assert diagnosis.safe_to_execute is False

    recovery = MalformedJqProjectArguments(
        diagnosis,
        attempt=1,
        repeated_payload=False,
    ).tool_result()["error"]["recovery"]

    assert "closed the top-level JSON object too early" in recovery
    assert "char 5756" in recovery
    assert "one jq_project call per timeline" in recovery


def test_repaired_jq_project_arguments_never_execute_even_when_schema_valid(
    tmp_path,
) -> None:
    """A truncated-then-repaired payload with intact top-level keys is not run.

    json_repair can close a truncated stream so the object still carries
    projectId/program; jq must not execute such a payload because argument
    values may have silently lost their tails.
    """

    turn = 0

    async def callback(messages, _tools):
        nonlocal turn
        turn += 1
        if turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="read-before-truncation",
                        name="read_project",
                        arguments={"projectId": PROJECT_ID},
                    ),
                ),
            )
        if turn == 2:
            observed = json.loads(messages[-1]["content"])
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="repaired-write",
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
                    ),
                ),
            )
        if turn == 3:
            rejected = json.loads(messages[-1]["content"])
            assert rejected["error"]["type"] == ("MalformedJqProjectArguments")
            assert "json_repair" in rejected["error"]["message"]
            assert rejected["error"]["details"]["schemaValid"] is True
            assert rejected["error"]["details"]["safeToExecute"] is False
            assert rejected["error"]["details"]["jsonRepairApplied"] is True
            assert rejected["error"]["retry"]["attempt"] == 1
            # The truncation-specific hint names the cause and forces
            # one entry per call instead of generic "smaller batches".
            recovery = rejected["error"]["recovery"]
            assert "cut off" in recovery
            assert "Unterminated string at EOF" in recovery
            assert "one jq_project call per timeline" in recovery
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="reread-after-truncation",
                        name="read_project",
                        arguments={"projectId": PROJECT_ID},
                    ),
                ),
            )
        if turn == 4:
            observed = json.loads(messages[-1]["content"])
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="clean-replacement-write",
                        name="jq_project",
                        arguments={
                            "projectId": PROJECT_ID,
                            "baseEtag": observed["etag"],
                            "program": ".description = $description",
                            "stringArgs": {
                                "description": "full description, resent",
                            },
                        },
                    ),
                ),
            )
        return AgentModelTurn(content="Resent the full commit.")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="Create the project plan",
        )
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        project = services.projects.read(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return project, session, events

    project, session, events = asyncio.run(scenario())

    # The repaired payload never reached jq: only the clean resend committed.
    assert project.project.description == "full description, resent"
    assert project.generation == 1
    assert session.error is None
    assert turn == 5
    checks = [
        event
        for event in events
        if event.event_type == "agent.tool_arguments_checked"
    ]
    assert len(checks) == 2
    assert checks[0].payload["jsonRepairApplied"] is True
    assert checks[0].payload["schemaValid"] is True
    assert checks[0].payload["safeToExecute"] is False
    assert checks[1].payload["safeToExecute"] is True


def test_repeated_malformed_jq_project_arguments_stop_after_two_retries(
    tmp_path,
) -> None:
    turn = 0
    etag = ""

    async def callback(messages, _tools):
        nonlocal turn, etag
        turn += 1
        if turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="read-before-repeats",
                        name="read_project",
                        arguments={"projectId": PROJECT_ID},
                    ),
                ),
            )
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
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).status.value
                == "ERROR"
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        project = services.projects.read(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return project, session, messages

    project, session, messages = asyncio.run(scenario())

    assert project.generation == 0
    assert turn == 4
    assert session.error is not None
    assert session.error["code"] == "MODEL_REQUEST_FAILED"
    assert session.error["retryable"] is True
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
    assert [item["retry"]["retriesRemaining"] for item in errors] == [
        2,
        1,
        0,
    ]
    assert [item["retry"]["samePayload"] for item in errors] == [
        False,
        True,
        True,
    ]
    assert "Do not resend it" in errors[-1]["recovery"]


async def _wait_for(predicate, *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise TimeoutError("condition was not reached")
        await asyncio.sleep(0.01)


def test_initial_creation_runs_auto_fix_tool_loop_without_review(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="请完善项目说明")
        driver = FileCreatorAgentRuntime(
            services,
            model_client=_edit_client(description="由初始任务生成"),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
            timeout=15.0,
        )
        await driver.wait_until_idle(PROJECT_ID)
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
        "agent.tool_delta",
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
    tool_results = [item for item in messages if item.role == "tool"]
    assert all(
        "准备调用工具" not in str(part.text or "")
        for item in assistant_turns
        for part in item.content_parts
    )
    assert assistant_turns[0].source == "creator_agent"
    assert assistant_turns[0].metadata["actionId"] == "read-1"
    assert assistant_turns[0].metadata["toolCall"] == {
        "id": "read-1",
        "name": "read_project",
        "arguments": {"projectId": PROJECT_ID},
    }
    assert all(item.source == "runtime_action_result" for item in tool_results)
    assert all(
        isinstance(json.loads(item.content_parts[0].text or ""), dict)
        for item in tool_results
    )


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
        assert kwargs["timeout"] == 60.0
        assert kwargs["visual_search_timeout"] == 120.0
        assert kwargs["image_download_timeout"] == 30.0
        assert kwargs["verification_timeout"] == 120.0
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
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="ground-1",
                        name="ground_prompt_context",
                        arguments={
                            "projectId": PROJECT_ID,
                            "prompt": "哈兰德参加偶像练习生",
                            "queries": ["Erling Haaland visual reference"],
                            "includeVisuals": True,
                        },
                    ),
                ),
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
        runtime = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        await runtime.start()
        runtime.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
        )
        await runtime.wait_until_idle(PROJECT_ID)
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


def test_grounding_visual_promotion_requires_explicit_acceptance() -> None:
    from services.file_agent_runtime import driver as driver_module

    assert driver_module._grounding_visual_is_usable(
        {"verification": {"status": "accepted"}},
    )
    assert not driver_module._grounding_visual_is_usable({})
    assert not driver_module._grounding_visual_is_usable(
        {"verification": {"status": "error"}},
    )
    assert not driver_module._grounding_visual_is_usable(
        {"verification": {"status": "unranked"}},
    )
    assert not driver_module._grounding_visual_is_usable(
        {"verification": {"status": "rejected"}},
    )


def test_grounding_visual_promotion_is_idempotent(tmp_path) -> None:
    image_buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color="blue").save(image_buffer, format="WEBP")
    image_bytes = image_buffer.getvalue()
    grounding_image = tmp_path / "grounding.webp"
    grounding_image.write_bytes(image_bytes)
    grounding_sha = hashlib.sha256(image_bytes).hexdigest()
    visual_source = {
        "verification": {"status": "accepted", "usage": "identity"},
        "local_url": grounding_image.as_uri(),
        "local_path": str(grounding_image),
        "media_type": "image/webp",
        "storage_sha256": grounding_sha,
        "title": "Grounding identity portrait",
    }
    services, _snapshot = _create_project(tmp_path, initial_goal=None)
    runtime = FileCreatorAgentRuntime(services)

    first = runtime._promote_grounding_visuals_sync(
        PROJECT_ID,
        "grounding-request-1",
        [visual_source],
    )
    first_project = services.projects.read(PROJECT_ID).project
    file_id = first["promoted"][0]["file_id"]
    first_created_at = first_project.assets.files_by_id[file_id].created_at
    first_generation = first_project.generation

    replay = runtime._promote_grounding_visuals_sync(
        PROJECT_ID,
        "grounding-request-1",
        [visual_source],
    )
    replay_project = services.projects.read(PROJECT_ID).project

    assert first["promoted_count"] == 1
    assert replay["promoted_count"] == 1
    assert replay["issues"] == []
    assert replay_project.generation == first_generation
    assert (
        replay_project.assets.files_by_id[file_id].created_at
        == first_created_at
    )


def test_stream_persistence_failure_is_not_reported_as_a_model_failure(
    tmp_path,
    monkeypatch,
) -> None:
    async def callback(_messages, _tools) -> AgentModelTurn:
        return AgentModelTurn(content="完整结果")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="请生成结果")
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        original_append_event = driver.sessions.append_event

        def append_event(*args, **kwargs):
            if kwargs.get("event_type") == "agent.message_delta":
                raise OSError("runtime lock timeout")
            return original_append_event(*args, **kwargs)

        monkeypatch.setattr(driver.sessions, "append_event", append_event)
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).status.value
                == "ERROR"
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
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


def test_parent_authors_timeline_elements_without_planning_specialists(
    tmp_path,
) -> None:
    turn = 0

    async def callback(messages, tools):
        nonlocal turn
        tool_names = {item["function"]["name"] for item in tools}
        assert tool_names == {
            "read_project",
            "read_project_file",
            "jq_project",
            "ground_prompt_context",
            "elements_at",
            "delegate_to_agent",
        }
        delegate = next(
            item
            for item in tools
            if item["function"]["name"] == "delegate_to_agent"
        )
        roles = delegate["function"]["parameters"]["properties"]["role"][
            "enum"
        ]
        assert roles == [
            "source_intelligence_agent",
            "visual_development_agent",
            "r2v_generation_director",
            "ai_editing_director",
        ]

        turn += 1
        if turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="main-read",
                        name="read_project",
                        arguments={"projectId": PROJECT_ID},
                    ),
                ),
            )
        if turn == 2:
            observed = json.loads(messages[-1]["content"])
            elements = {
                "r2v-1": {
                    "element_id": "r2v-1",
                    "label": "主 Agent 创建的画面",
                    "enabled": True,
                    "span": {"start_tick": 0, "duration_tick": 15_000},
                    "location": {
                        "coordinate_space": "normalized_canvas",
                        "x": 0,
                        "y": 0,
                        "width": 1,
                        "height": 1,
                        "anchor_x": 0.5,
                        "anchor_y": 0.5,
                        "rotation_degrees": 0,
                        "opacity": 1,
                    },
                    "z_index": 0,
                    "creation": {
                        "type": "r2v",
                        "intent": "建立可执行生成画面",
                        "narrative": "角色走入雨夜街道",
                        "continuity": "保持角色造型",
                        "character_refs": [],
                        "scene_ref": None,
                        "prop_refs": [],
                        "shots": {
                            "items": {
                                "shot-1": {
                                    "shot_id": "shot-1",
                                    "description": "角色走入雨夜街道",
                                    "camera": "⊙ 静止",
                                    "framing": "全景",
                                    "duration_seconds": 15,
                                },
                            },
                            "order": ["shot-1"],
                        },
                    },
                    "outputs": {},
                    "render_source": None,
                    "provenance_refs": [],
                },
            }
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="main-write-structure",
                        name="jq_project",
                        arguments={
                            "projectId": PROJECT_ID,
                            "baseEtag": observed["etag"],
                            "program": '.timelines.items["timeline:main"].elements_by_id = $elements',
                            "jsonArgs": {"elements": elements},
                        },
                    ),
                ),
            )
        return AgentModelTurn(content="主 Agent 已建立 Timeline Element。")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="请创建一个剪辑项目结构",
        )
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        project = services.projects.read(PROJECT_ID)
        specialist_runs = driver.executions.list_specialist_runs(PROJECT_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return project, specialist_runs, events

    project, specialist_runs, events = asyncio.run(scenario())
    element = project.project.timelines.items["timeline:main"].elements_by_id[
        "r2v-1"
    ]
    assert element.creation.type == "r2v"
    assert element.span.duration_tick == 15_000
    assert specialist_runs == []
    event_types = [item.event_type for item in events]
    assert "workspace.head_changed" in event_types
    assert not any(item.startswith("subagent.") for item in event_types)


def test_source_intelligence_receives_every_user_media_part_directly(
    tmp_path,
) -> None:
    parent_turn = 0
    source_turn = 0
    observed_source_content: list[dict[str, object]] = []
    observed_correction = ""

    async def parent_callback(messages, tools):
        nonlocal parent_turn
        assert "delegate_to_agent" in {
            item["function"]["name"] for item in tools
        }
        parent_turn += 1
        if parent_turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="delegate-source",
                        name="delegate_to_agent",
                        arguments={
                            "role": "source_intelligence_agent",
                            "target_refs": ["asset:input-video"],
                            "task": "理解用户提交的全部素材。",
                        },
                    ),
                ),
            )
        return AgentModelTurn(content="素材理解 Agent 已收到原生素材。")

    async def source_callback(messages, tools):
        nonlocal source_turn, observed_correction
        assert "commit_source_intelligence" in {
            item["function"]["name"] for item in tools
        }
        assert "jq_project" not in {item["function"]["name"] for item in tools}
        source_turn += 1
        if source_turn == 1:
            content = messages[1]["content"]
            assert isinstance(content, list)
            observed_source_content.extend(content)
            return AgentModelTurn(content="[SUCCESS]\n已直接观察全部用户素材。")
        assert messages[-1]["role"] == "user"
        observed_correction = str(messages[-1]["content"])
        return AgentModelTurn(content="[FAILED]\n测试未提供可提交的 ProjectSource。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal=None)
        message = services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[
                {"type": "text", "text": "请理解两个素材"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://cdn.example.com/input.png"},
                },
                {
                    "type": "video_url",
                    "video_url": {"url": "https://cdn.example.com/input.mp4"},
                },
            ],
            source="initial_creation",
            channel=MessageChannel.COMPOSER,
            classification=MessageClassification.MUTATION_INSTRUCTION,
        ).message
        services.sessions.create_goal(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            root_message_seq=message.message_seq,
            intent="请理解两个素材",
            goal_id=GOAL_ID,
        )
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(parent_callback),
            source_model_client=CallbackAgentChatClient(source_callback),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == message.message_seq
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        specialist_runs = driver.executions.list_specialist_runs(PROJECT_ID)
        await driver.stop()
        return specialist_runs

    specialist_runs = asyncio.run(scenario())

    assert [item["type"] for item in observed_source_content] == [
        "text",
        "image_url",
        "video_url",
    ]
    assert observed_source_content[1]["image_url"] == {
        "url": "https://cdn.example.com/input.png",
    }
    assert observed_source_content[2]["video_url"] == {
        "url": "https://cdn.example.com/input.mp4",
    }
    assert len(specialist_runs) == 1
    assert specialist_runs[0].status.value == "FAILED"
    assert "commit_source_intelligence" in observed_correction
    assert "禁止再次返回自然语言分析" in observed_correction
    assert specialist_runs[0].final_summary_text == "测试未提供可提交的 ProjectSource。"


def test_parent_reads_persisted_source_intelligence_and_links_project_structure(
    tmp_path,
    monkeypatch,
) -> None:
    class FakeAnalyzer:
        async def analyze(self, request):
            coverage = {
                "visual": {
                    "mode": "available",
                    "producer": "model_native",
                    "ratio": 1.0,
                },
                "asr": {
                    "mode": "unavailable",
                    "producer": None,
                    "ratio": None,
                },
                "ocr": {
                    "mode": "unavailable",
                    "producer": None,
                    "ratio": None,
                },
                "audio": {
                    "mode": "unavailable",
                    "producer": None,
                    "ratio": None,
                },
            }
            model_run = SourceModelRunRef(
                id="model-run-source-1",
                provider="fake",
                model="fake-vlm",
            )
            return SourceAnalyzerOutput(
                raw={
                    "summary": "海边日落中人物向镜头走来",
                    "coverage": coverage,
                    "shots": [],
                    "transcript": [],
                    "words": [],
                    "ocrSegments": [],
                    "audioEvents": [],
                    "entities": [],
                    "semanticEntries": [],
                },
                media=SourceMediaMetadata(
                    mediaKind="video",
                    mediaType="video/mp4",
                    durationMs=5000,
                    width=1920,
                    height=1080,
                ),
                model_runs=(model_run,),
                coverage_policy=coverage,
                provenance_refs=(request.evidence_ref,),
            )

    async def fake_model_upload(*_args, **_kwargs):
        return "https://model.example.com/source.mp4"

    monkeypatch.setattr(
        "services.file_agent_runtime.native_media.model_config.get_vlm_api_key",
        lambda: "configured",
    )
    monkeypatch.setattr(
        "services.file_agent_runtime.native_media.upload_local_file_to_dashscope_temp",
        fake_model_upload,
    )
    monkeypatch.setattr(
        "services.source_analysis.service._probe_media",
        lambda _path, version: SourceMediaMetadata(
            mediaKind=version.media_kind,
            mediaType=version.media_type,
            durationMs=5000,
            width=1920,
            height=1080,
        ),
    )

    parent_turn = 0
    source_turn = 0
    asset_id = ""
    asset_version_id = ""
    source_id = ""
    read_intelligence = False

    async def parent_callback(messages, tools):
        nonlocal parent_turn, read_intelligence
        parent_turn += 1
        if parent_turn == 1:
            assert (
                f"asset-version:{asset_version_id}" in messages[-1]["content"]
            )
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="main-read-before-source",
                        name="read_project",
                        arguments={"projectId": PROJECT_ID},
                    ),
                ),
            )
        if parent_turn == 2:
            observed = json.loads(messages[-1]["content"])
            source = observed["project"]["sources"]["sources"]["items"][
                source_id
            ]
            assert source["selected_asset_version_id"] == asset_version_id
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="delegate-source-persisted",
                        name="delegate_to_agent",
                        arguments={
                            "role": "source_intelligence_agent",
                            "target_refs": [f"asset:{asset_id}"],
                            "task": "理解本轮上传素材并持久化 Source Intelligence。",
                        },
                    ),
                ),
            )
        if parent_turn == 3:
            delegated = json.loads(messages[-1]["content"])
            assert delegated["ok"] is True
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="main-reread-after-source",
                        name="read_project",
                        arguments={"projectId": PROJECT_ID},
                    ),
                ),
            )
        if parent_turn == 4:
            observed = json.loads(messages[-1]["content"])
            source = observed["project"]["sources"]["sources"]["items"][
                source_id
            ]
            intelligence_id = source["current_intelligence_version_id"]
            assert intelligence_id
            file_id = observed["project"]["assets"][
                "intelligence_versions_by_id"
            ][intelligence_id]["file_id"]
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="main-read-source-intelligence",
                        name="read_project_file",
                        arguments={
                            "projectId": PROJECT_ID,
                            "fileId": file_id,
                        },
                    ),
                ),
            )
        if parent_turn == 5:
            indexed = json.loads(messages[-1]["content"])
            assert "海边日落中人物向镜头走来" in indexed["content"]
            read_intelligence = True
            latest = next(
                json.loads(message["content"])
                for message in reversed(messages)
                if message.get("name") == "read_project"
            )
            intelligence_id = latest["project"]["sources"]["sources"]["items"][
                source_id
            ]["current_intelligence_version_id"]
            assert intelligence_id
            elements = {
                "edit-source": {
                    "element_id": "edit-source",
                    "label": "海边日落素材选择",
                    "enabled": True,
                    "span": {"start_tick": 0, "duration_tick": 5_000},
                    "location": {
                        "coordinate_space": "normalized_canvas",
                        "x": 0,
                        "y": 0,
                        "width": 1,
                        "height": 1,
                        "anchor_x": 0.5,
                        "anchor_y": 0.5,
                        "rotation_degrees": 0,
                        "opacity": 1,
                    },
                    "z_index": 0,
                    "creation": {
                        "type": "edit",
                        "intent": "剪出人物在海边日落中走向镜头的范围",
                        "reason": "素材理解确认该时段包含完整动作",
                        "original_sound": "preserve",
                        "source_intelligence_version_id": intelligence_id,
                    },
                    "outputs": {},
                    "render_source": {
                        "type": "source_asset_version",
                        "version_id": asset_version_id,
                        "source_in_tick": 0,
                        "source_out_tick": 5_000,
                        "playback_rate": 1,
                        "loop": False,
                    },
                    "provenance_refs": [
                        f"source:{source_id}",
                        f"source-intelligence:{intelligence_id}",
                    ],
                },
            }
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="main-link-source-structure",
                        name="jq_project",
                        arguments={
                            "projectId": PROJECT_ID,
                            "baseEtag": latest["etag"],
                            "program": '.timelines.items["timeline:main"].elements_by_id = $elements',
                            "jsonArgs": {"elements": elements},
                        },
                    ),
                ),
            )
        return AgentModelTurn(content="已根据素材理解建立 Edit Element。")

    async def source_callback(messages, tools):
        nonlocal source_turn
        source_turn += 1
        names = {item["function"]["name"] for item in tools}
        assert "commit_source_intelligence" in names
        if source_turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="commit-source-persisted",
                        name="commit_source_intelligence",
                        arguments={
                            "projectId": PROJECT_ID,
                            "targetRef": f"asset:{asset_id}",
                            "arguments": {
                                "summary": "海边日落中人物向镜头走来，完整过程清晰可见。",
                                "shots": [
                                    {
                                        "startMs": 0,
                                        "endMs": 5000,
                                        "description": (
                                            "人物在海边日落环境中由远及近走向镜头；"
                                            "固定机位，中景逐渐变为近景，暖色逆光稳定。"
                                        ),
                                        "events": ["人物行走", "逐渐接近镜头"],
                                        "confidence": 0.95,
                                    },
                                ],
                                "entities": [
                                    {
                                        "kind": "person",
                                        "label": "主要人物",
                                        "description": "从远处持续走向镜头",
                                        "startMs": 0,
                                        "endMs": 5000,
                                        "confidence": 0.95,
                                    },
                                ],
                                "semanticEntries": [
                                    {
                                        "startMs": 0,
                                        "endMs": 5000,
                                        "text": "人物在海边日落中完成走向镜头的动作",
                                        "tags": ["海边", "日落", "行走", "接近镜头"],
                                        "confidence": 0.95,
                                    },
                                ],
                            },
                        },
                    ),
                ),
            )
        if source_turn == 2:
            result = json.loads(messages[-1]["content"])
            assert result["status"] == "SUCCEEDED"
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="source-confirm-project",
                        name="read_project",
                        arguments={"projectId": PROJECT_ID},
                    ),
                ),
            )
        observed = json.loads(messages[-1]["content"])
        source = observed["project"]["sources"]["sources"]["items"][source_id]
        assert source["current_intelligence_version_id"]
        return AgentModelTurn(
            content="[SUCCESS]\n素材理解已持久化并关联 ProjectSource。",
        )

    async def scenario():
        nonlocal asset_id, asset_version_id, source_id
        services, _snapshot = _create_project(tmp_path, initial_goal=None)
        ingested, _ = _ingest_many_sync(
            services,
            project_id=PROJECT_ID,
            key="source-for-main-agent",
            inputs=[
                _AssetInput(
                    name="source.mp4",
                    content=b"verified-source",
                    media_type="video/mp4",
                ),
            ],
            attach_source=True,
            scope="main-agent-source-link-test",
        )
        asset_id = ingested["items"][0]["assetId"]
        asset_version_id = ingested["items"][0]["assetVersionId"]
        source_id = next(
            iter(
                services.projects.read(
                    PROJECT_ID,
                ).project.sources.sources.items,
            ),
        )
        analyzer_service = SourceMediaAnalysisService(
            services,
            analyzer=FakeAnalyzer(),
        )
        monkeypatch.setattr(
            "services.specialist_tools.source_analysis_service",
            lambda _services: analyzer_service,
        )
        message = services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": "把上传素材剪成一个短视频"}],
            source="initial_creation",
            channel=MessageChannel.COMPOSER,
            classification=MessageClassification.MUTATION_INSTRUCTION,
            metadata={
                "assetVersionRefs": [f"asset-version:{asset_version_id}"],
            },
        ).message
        services.sessions.create_goal(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            root_message_seq=message.message_seq,
            intent="把上传素材剪成一个短视频",
            goal_id=GOAL_ID,
        )
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(parent_callback),
            source_model_client=CallbackAgentChatClient(source_callback),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == message.message_seq
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        project = services.projects.read(PROJECT_ID).project
        specialist_runs = driver.executions.list_specialist_runs(PROJECT_ID)
        await driver.stop()
        return project, specialist_runs

    project, specialist_runs = asyncio.run(scenario())
    assert read_intelligence is True
    element = project.timelines.items["timeline:main"].elements_by_id[
        "edit-source"
    ]
    assert element.render_source is not None
    assert element.render_source.version_id == asset_version_id
    assert element.creation.source_intelligence_version_id is not None
    assert (
        project.sources.sources.items[
            source_id
        ].current_intelligence_version_id
        is not None
    )
    assert {item.role.value for item in specialist_runs} == {
        "source_intelligence_agent",
    }


def test_agentdock_boundary_is_carried_into_run_and_creates_review(
    tmp_path,
) -> None:
    async def scenario():
        services, snapshot = _create_project(tmp_path, initial_goal=None)
        root = services.root
        first = services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": "初始目标"}],
            client_message_id="initial-client",
            source="initial_creation",
            channel=MessageChannel.COMPOSER,
            classification=MessageClassification.MUTATION_INSTRUCTION,
        ).message
        services.sessions.create_goal(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            root_message_seq=first.message_seq,
            intent="初始目标",
            goal_id=GOAL_ID,
        )
        services.sessions.mark_messages_consumed(
            PROJECT_ID,
            SESSION_ID,
            through_seq=first.message_seq,
            goal_id=GOAL_ID,
        )
        services.sessions.activate_run(
            PROJECT_ID,
            SESSION_ID,
            goal_id=GOAL_ID,
            run_id="old-run",
        )
        AtomicJsonRecordStore(
            root / PROJECT_ID / "runtime" / "state.json",
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
        admitted = services.sessions.admit_user_request(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            request_id="interrupt-request",
            client_message_id="interrupt-message",
            content_parts=[{"type": "text", "text": "把说明改成审阅版本"}],
            channel=MessageChannel.AGENTDOCK,
            classification=MessageClassification.MUTATION_INSTRUCTION,
        )
        assert admitted.review_boundary is not None

        driver = FileCreatorAgentRuntime(
            services,
            model_client=_edit_client(description="等待用户审阅"),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == admitted.message.message_seq
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        runs = driver.runs.list(PROJECT_ID)
        review = services.reviews.active(PROJECT_ID)
        pending_session = services.sessions.get_project_session(PROJECT_ID)
        assert review is not None
        resolved = services.reviews.decide(
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
        assert resolved.status.value == "RESOLVED"
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).status.value
                == "IDLE"
            ),
        )
        session = services.sessions.get_project_session(PROJECT_ID)
        goal = services.sessions.get_goal(PROJECT_ID, GOAL_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return admitted, runs, review, pending_session, session, goal, events

    (
        admitted,
        runs,
        review,
        pending_session,
        session,
        goal,
        events,
    ) = asyncio.run(
        scenario(),
    )
    run = runs[-1]
    assert run.origin.value == "agentdock_interrupt"
    assert run.review_policy.value == "require_review"
    assert run.review_boundary == admitted.review_boundary
    assert run.caused_by_request_id == admitted.review_boundary.request_id
    assert review is not None
    assert run.review_ids == [review.review_id]
    assert pending_session.status.value == "PENDING_REVIEW"
    assert session.status.value == "IDLE"
    assert goal.status.value == "COMPLETED"
    assert "agent.review.resolved" in {item.event_type for item in events}


def test_intervention_completion_queues_mainline_resume(tmp_path) -> None:
    async def scenario():
        services, snapshot = _create_project(tmp_path, initial_goal=None)
        root = services.root
        first = services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[{"type": "text", "text": "主线目标：生成完整短片"}],
            client_message_id="mainline-client",
            source="initial_creation",
            channel=MessageChannel.COMPOSER,
            classification=MessageClassification.MUTATION_INSTRUCTION,
        ).message
        services.sessions.create_goal(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            root_message_seq=first.message_seq,
            intent="主线目标",
            goal_id=GOAL_ID,
        )
        services.sessions.mark_messages_consumed(
            PROJECT_ID,
            SESSION_ID,
            through_seq=first.message_seq,
            goal_id=GOAL_ID,
        )
        services.sessions.activate_run(
            PROJECT_ID,
            SESSION_ID,
            goal_id=GOAL_ID,
            run_id="old-run",
        )
        AtomicJsonRecordStore(
            root / PROJECT_ID / "runtime" / "state.json",
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
        driver = FileCreatorAgentRuntime(
            services,
            model_client=_edit_client(description="支线修改已完成"),
            poll_interval_seconds=0.01,
        )
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
        admitted = services.sessions.admit_user_request(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            request_id="interrupt-request",
            client_message_id="interrupt-message",
            content_parts=[{"type": "text", "text": "把说明改成支线版本"}],
            channel=MessageChannel.AGENTDOCK,
            classification=MessageClassification.MUTATION_INSTRUCTION,
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
        services.reviews.decide(
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
                return AgentModelTurn(
                    tool_calls=(
                        AgentToolCall(
                            call_id="late-write",
                            name="jq_project",
                            arguments={
                                "projectId": PROJECT_ID,
                                "baseEtag": snapshot.etag,
                                "program": '.description = "must-not-commit"',
                            },
                        ),
                    ),
                )

        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(stubborn_model),
            poll_interval_seconds=0.01,
        )
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

        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(slow_cancel_model),
            poll_interval_seconds=0.01,
        )
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


def test_specialist_cancel_emits_terminal_event(tmp_path) -> None:
    """A specialist run cancelled mid-flight (RUNNING_MODEL) must emit a
    terminal ``subagent.failed`` event.
    """

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="生成角色图")
        specialist_started = asyncio.Event()
        cancel_entered = asyncio.Event()

        async def callback(messages, tools):
            names = {item["function"]["name"] for item in tools}
            if "delegate_to_agent" in names:
                return AgentModelTurn(
                    tool_calls=(
                        AgentToolCall(
                            call_id="delegate-visual",
                            name="delegate_to_agent",
                            arguments={
                                "role": "visual_development_agent",
                                "target_refs": ["project:assets"],
                                "task": "整体视觉",
                            },
                        ),
                    ),
                )
            # Specialist turn: block forever until the parent is interrupted.
            specialist_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancel_entered.set()
                raise

        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(specialist_started.wait(), timeout=2.0)
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
    ), "CancelledError never reached the specialist coroutine"
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
        "no terminal subagent event emitted on cancel; events="
        f"{[e.event_type for e in events if e.event_type.startswith('subagent.')]}"
    )
    cancelled_event = terminal[-1]
    assert cancelled_event.event_type == "subagent.failed"
    assert cancelled_event.payload.get("cancelled") is True


def test_specialist_cancel_while_waiting_runtime_emits_terminal_event(
    tmp_path,
    monkeypatch,
) -> None:
    """A specialist run cancelled while WAITING_RUNTIME (a long-running tool
    mid-invoke) must still emit a terminal ``subagent.failed`` event.

    Regression companion to the RUNNING_MODEL case: the run reaches the
    cancel-except only after the invoke-finally bridges WAITING_RUNTIME back to
    RUNNING_MODEL, so the on-disk transition succeeds — but the terminal event
    was still missing.  Locks in that the event fires on this path too.
    """
    import services.file_agent_runtime.driver as driver_module
    from models.config import (
        CREATION_CHECKPOINT_SKIP,
        EXECUTION_AUTHORIZATION_ALLOW_ALL,
    )

    monkeypatch.setattr(
        driver_module,
        "get_execution_authorization_mode",
        lambda: EXECUTION_AUTHORIZATION_ALLOW_ALL,
    )
    # This test owns cancel-while-waiting, not the creation pit stops.
    monkeypatch.setattr(
        driver_module,
        "get_creation_checkpoint_mode",
        lambda: CREATION_CHECKPOINT_SKIP,
    )

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="生成角色图")
        invoke_started = asyncio.Event()
        cancel_entered = asyncio.Event()

        async def callback(messages, tools):
            names = {item["function"]["name"] for item in tools}
            if "delegate_to_agent" in names:
                return AgentModelTurn(
                    tool_calls=(
                        AgentToolCall(
                            call_id="delegate-visual",
                            name="delegate_to_agent",
                            arguments={
                                "role": "visual_development_agent",
                                "target_refs": ["project:assets"],
                                "task": "整体视觉",
                            },
                        ),
                    ),
                )
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="gen-1",
                        name="image_generation",
                        arguments={
                            "projectId": PROJECT_ID,
                            "targetRef": "asset:hero",
                            "arguments": {"prompt": "hero"},
                        },
                    ),
                ),
            )

        async def blocking_invoke(**_kwargs):
            invoke_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancel_entered.set()
                raise

        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        driver.specialist_tools.invoke = blocking_invoke  # type: ignore[method-assign]
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(invoke_started.wait(), timeout=2.0)
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
    ), "CancelledError never reached the specialist invoke"
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
        "no terminal subagent event emitted on cancel while WAITING_RUNTIME; "
        "events="
        f"{[e.event_type for e in events if e.event_type.startswith('subagent.')]}"
    )
    cancelled_event = terminal[-1]
    assert cancelled_event.event_type == "subagent.failed"
    assert cancelled_event.payload.get("cancelled") is True


def test_redundant_supersede_preserves_pending_replacement_message(
    tmp_path,
) -> None:
    async def scenario():
        services, snapshot = _create_project(
            tmp_path,
            initial_goal="先完成原始任务",
        )
        services.sessions.mark_messages_consumed(
            PROJECT_ID,
            SESSION_ID,
            through_seq=1,
            goal_id=GOAL_ID,
        )
        services.sessions.activate_run(
            PROJECT_ID,
            SESSION_ID,
            goal_id=GOAL_ID,
            run_id="old-run",
        )
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
        admitted = services.sessions.admit_user_request(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            request_id="replacement-request",
            client_message_id="replacement-message",
            content_parts=[{"type": "text", "text": "把片段缩短两秒"}],
            channel=MessageChannel.AGENTDOCK,
            classification=MessageClassification.MUTATION_INSTRUCTION,
        )
        assert admitted.review_boundary is not None
        services.sessions.clear_active_run(
            PROJECT_ID,
            SESSION_ID,
            expected_run_id="old-run",
            status="RESUMING",
        )

        async def replacement_model(_messages, _tools):
            return AgentModelTurn(content="替代请求已完成。")

        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(replacement_model),
            poll_interval_seconds=0.01,
        )
        interrupted = await driver.interrupt(
            PROJECT_ID,
            superseded=True,
            reason="agentdock_interrupt",
        )
        pending = services.sessions.get_project_session(PROJECT_ID)
        events_before_start = services.sessions.list_events(
            PROJECT_ID,
            SESSION_ID,
        )

        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == admitted.message.message_seq
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        runs = driver.runs.list(PROJECT_ID)
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return (
            interrupted,
            admitted,
            pending,
            session,
            runs,
            events_before_start,
            events,
        )

    (
        interrupted,
        admitted,
        pending,
        session,
        runs,
        events_before_start,
        events,
    ) = asyncio.run(scenario())

    assert interrupted is False
    assert pending.status.value == "RESUMING"
    assert pending.last_consumed_message_seq == 1
    assert pending.last_message_seq == admitted.message.message_seq == 2
    assert "agent.interrupt.idle" not in {
        item.event_type for item in events_before_start
    }
    assert session.status.value == "IDLE"
    assert session.last_consumed_message_seq == admitted.message.message_seq
    assert len(runs) == 1
    assert runs[0].status is AgentRunStatus.SUCCEEDED
    assert runs[0].origin.value == "agentdock_interrupt"
    assert runs[0].caused_by_message_seq == admitted.message.message_seq
    assert "agent.interrupt.idle" not in {item.event_type for item in events}


def test_agentdock_message_after_interrupt_reuses_goal_and_conversation_context(
    tmp_path,
) -> None:
    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="先完成猫咪短片的素材整理",
        )
        first_started = asyncio.Event()
        observed_user_contexts: list[str] = []

        async def model(messages, _tools):
            user_context = str(messages[1]["content"])
            observed_user_contexts.append(user_context)
            if len(observed_user_contexts) == 1:
                first_started.set()
                await asyncio.Event().wait()
            return AgentModelTurn(content="已继承原任务并继续完成剪辑。")

        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(model),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await asyncio.wait_for(first_started.wait(), timeout=2.0)
        await driver.interrupt(PROJECT_ID, reason="user-stop")
        await driver.wait_until_idle(PROJECT_ID)

        stopped = services.sessions.get_project_session(PROJECT_ID)
        stopped_goal = services.sessions.get_goal(PROJECT_ID, GOAL_ID)
        admitted = services.sessions.admit_user_request(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            request_id="continue-request",
            client_message_id="continue-message",
            content_parts=[{"type": "text", "text": "继续刚才的任务，开始剪辑。"}],
            channel=MessageChannel.AGENTDOCK,
            classification=MessageClassification.MUTATION_INSTRUCTION,
        )
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == admitted.message.message_seq
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)

        resumed = services.sessions.get_project_session(PROJECT_ID)
        resumed_goal = services.sessions.get_goal(PROJECT_ID, GOAL_ID)
        runs = driver.runs.list(PROJECT_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return (
            stopped,
            stopped_goal,
            admitted,
            resumed,
            resumed_goal,
            runs,
            messages,
            observed_user_contexts,
        )

    (
        stopped,
        stopped_goal,
        admitted,
        resumed,
        resumed_goal,
        runs,
        messages,
        observed_user_contexts,
    ) = asyncio.run(scenario())

    assert stopped.status.value == "CANCELLED"
    assert stopped.active_goal_id == GOAL_ID
    assert stopped_goal.status.value == "CANCELLED"
    assert admitted.message.conversation_id == CONVERSATION_ID
    assert resumed.status.value == "IDLE"
    assert resumed.active_goal_id == GOAL_ID
    assert resumed_goal.status.value == "COMPLETED"
    assert [item.goal_id for item in runs] == [GOAL_ID, GOAL_ID]
    assert [item.status for item in runs] == [
        AgentRunStatus.CANCELLED,
        AgentRunStatus.SUCCEEDED,
    ]
    assert len(observed_user_contexts) == 2
    continuation_context = observed_user_contexts[1]
    assert "CONVERSATION_HISTORY_JSON=" in continuation_context
    assert "先完成猫咪短片的素材整理" in continuation_context
    assert "CURRENT_USER_REQUEST=\n继续刚才的任务，开始剪辑。" in continuation_context
    assert [item.conversation_id for item in messages] == [
        CONVERSATION_ID,
        CONVERSATION_ID,
        CONVERSATION_ID,
    ]


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

        owner = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(blocking_model),
            poll_interval_seconds=0.01,
        )
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
        non_owner = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(blocking_model),
            poll_interval_seconds=0.01,
        )
        await non_owner.start()
        interrupted_locally = await non_owner.interrupt(
            PROJECT_ID,
            reason="remote-stop",
        )
        assert interrupted_locally is False

        await asyncio.wait_for(cancelled.wait(), timeout=2.0)
        await owner.wait_until_idle(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).status.value
                == "CANCELLED"
            ),
        )
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


def test_missing_model_configuration_persists_session_error(tmp_path) -> None:
    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="请修改项目")

        async def missing(_messages, _tools):
            raise AgentModelConfigurationError(
                "Creator text model configuration is incomplete: api_key",
            )

        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(missing),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).status.value
                == "ERROR"
            ),
        )
        session = services.sessions.get_project_session(PROJECT_ID)
        goal = services.sessions.get_goal(PROJECT_ID, GOAL_ID)
        run = driver.runs.list(PROJECT_ID)[0]
        await driver.stop()
        return session, goal, run

    session, goal, run = asyncio.run(scenario())
    assert session.error is not None
    assert session.error["code"] == "MODEL_CONFIG_MISSING"
    assert "api_key" in session.error["message"]
    assert goal.status.value == "FAILED"
    assert run.status is AgentRunStatus.FAILED


def test_failed_run_is_not_relaunched_after_restart_or_notify(
    tmp_path,
) -> None:
    """A failed request is a durable input boundary.

    Neither a process restart (which discards the in-memory blocked-head
    guard) nor an unrelated ``notify`` (model config saves wake every
    Project) may relaunch the Agent on the same failed message.
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
        first = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(failing),
            poll_interval_seconds=0.01,
        )
        await first.start()
        first.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).status.value
                == "ERROR"
            ),
        )
        await first.wait_until_idle(PROJECT_ID)
        failed_session = services.sessions.get_project_session(PROJECT_ID)
        await first.stop()

        # A fresh runtime instance models a QwenPaw restart: the in-memory
        # ``_blocked_heads`` guard is gone and only durable state remains.
        second = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(counting),
            poll_interval_seconds=0.01,
        )
        await second.start()
        second.notify(PROJECT_ID)
        await asyncio.sleep(0.2)
        await second.wait_until_idle(PROJECT_ID)
        runs = second.runs.list(PROJECT_ID)
        await second.stop()
        return failed_session, runs

    failed_session, runs = asyncio.run(scenario())
    assert failed_session.last_consumed_message_seq == 1
    assert relaunch_calls == 0
    assert len(runs) == 1
    assert runs[0].status is AgentRunStatus.FAILED


def test_legacy_unconsumed_failed_head_is_consumed_instead_of_relaunched(
    tmp_path,
    monkeypatch,
) -> None:
    """Sessions written before failures consumed their request must not
    auto-start the Agent after a restart; reconciliation consumes the failed
    head based on the durable run record instead."""

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
        first = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(failing),
            poll_interval_seconds=0.01,
        )
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
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).status.value
                == "ERROR"
            ),
        )
        await first.wait_until_idle(PROJECT_ID)
        await first.stop()
        legacy_session = services.sessions.get_project_session(PROJECT_ID)

        second = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(counting),
            poll_interval_seconds=0.01,
        )
        await second.start()
        second.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
        )
        await second.wait_until_idle(PROJECT_ID)
        runs = second.runs.list(PROJECT_ID)
        await second.stop()
        return legacy_session, runs

    legacy_session, runs = asyncio.run(scenario())
    assert legacy_session.last_consumed_message_seq == 0
    assert relaunch_calls == 0
    assert len(runs) == 1
    assert runs[0].status is AgentRunStatus.FAILED


def test_costly_specialist_tool_waits_for_file_authorization(
    tmp_path,
    monkeypatch,
) -> None:
    import services.file_agent_runtime.driver as driver_module

    monkeypatch.setattr(
        driver_module,
        "get_execution_authorization_mode",
        lambda: "required",
    )
    # This test owns the per-execution authorization gate; the creation
    # pit stops are covered by test_creation_checkpoints.py.
    monkeypatch.setattr(
        driver_module,
        "get_creation_checkpoint_mode",
        lambda: "skip",
    )
    parent_turn = 0
    specialist_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn, specialist_turn
        names = {item["function"]["name"] for item in tools}
        if "image_generation" in names:
            specialist_turn += 1
            if specialist_turn == 1:
                return AgentModelTurn(
                    tool_calls=(
                        AgentToolCall(
                            call_id="generate-image-1",
                            name="image_generation",
                            arguments={
                                "projectId": PROJECT_ID,
                                "targetRef": "asset:hero",
                                "arguments": {"prompt": "hero portrait"},
                            },
                        ),
                    ),
                )
            return AgentModelTurn(content="[SUCCESS]\n角色图已生成。")
        parent_turn += 1
        if parent_turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="delegate-visual-1",
                        name="delegate_to_agent",
                        arguments={
                            "role": "visual_development_agent",
                            "target_refs": ["asset:hero"],
                            "task": "生成角色图",
                        },
                    ),
                ),
            )
        return AgentModelTurn(content="视觉 Specialist 已完成。")

    async def scenario():
        services, _snapshot = _create_project(tmp_path, initial_goal="生成角色图")
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )

        async def fake_invoke(**_kwargs):
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "status": "SUCCEEDED",
                    "artifactVersionId": "artifact-version-1",
                },
            )

        driver.specialist_tools.invoke = fake_invoke  # type: ignore[method-assign]
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: bool(
                driver.executions.list_execution_authorizations(PROJECT_ID),
            ),
        )
        authorization = driver.executions.list_execution_authorizations(
            PROJECT_ID,
        )[0]
        await _wait_for(
            lambda: (
                driver.executions.get_specialist_run(
                    PROJECT_ID,
                    authorization.run_id,
                ).status.value
                == "WAITING_AUTHORIZATION"
            ),
        )
        waiting_run = driver.executions.get_specialist_run(
            PROJECT_ID,
            authorization.run_id,
        )
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
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        completed_run = driver.executions.get_specialist_run(
            PROJECT_ID,
            authorization.run_id,
        )
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return authorization, waiting_run, completed_run, events

    authorization, waiting_run, completed_run, events = asyncio.run(scenario())
    assert waiting_run.status.value == "WAITING_AUTHORIZATION"
    assert completed_run.status.value == "SUCCEEDED"
    assert authorization.operation == "image_generation"
    event_types = {item.event_type for item in events}
    assert "execution.authorization_required" in event_types
    assert "execution.authorization_decided" in event_types


def test_review_pending_is_a_neutral_specialist_pause(
    tmp_path,
    monkeypatch,
) -> None:
    import services.file_agent_runtime.driver as driver_module
    from models.config import (
        CREATION_CHECKPOINT_SKIP,
        EXECUTION_AUTHORIZATION_ALLOW_ALL,
    )

    monkeypatch.setattr(
        driver_module,
        "get_execution_authorization_mode",
        lambda: EXECUTION_AUTHORIZATION_ALLOW_ALL,
    )
    monkeypatch.setattr(
        driver_module,
        "get_creation_checkpoint_mode",
        lambda: CREATION_CHECKPOINT_SKIP,
    )
    parent_turn = 0

    async def callback(_messages, tools):
        nonlocal parent_turn
        names = {item["function"]["name"] for item in tools}
        if "r2v_generation" in names:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="generate-ep22-video",
                        name="r2v_generation",
                        arguments={
                            "projectId": PROJECT_ID,
                            "targetRef": "element:ep22",
                            "arguments": {"prompt": "ep22 video"},
                        },
                    ),
                ),
            )
        parent_turn += 1
        if parent_turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="delegate-ep22-video",
                        name="delegate_to_agent",
                        arguments={
                            "role": "r2v_generation_director",
                            "target_refs": ["element:ep22"],
                            "task": "生成 ep22 视频",
                        },
                    ),
                ),
            )
        assert json.loads(_messages[-1]["content"])["status"] == (
            "WAITING_REVIEW"
        )
        return AgentModelTurn(content="等待审阅通过后自动继续。")

    async def scenario():
        services, _snapshot = _create_project(
            tmp_path,
            initial_goal="生成 ep22 视频",
        )
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )

        async def pending_review(**_kwargs):
            raise ReviewPendingError(
                "storyboard is waiting for review",
                details={
                    "reason": "INPUT_PENDING_REVIEW",
                    "reviewId": "review-ep22",
                    "artifactVersionId": "artifact-version-ep22",
                    "targetRef": "element:ep22",
                    "commandType": "GENERATE_R2V_VIDEO",
                },
            )

        driver.specialist_tools.invoke = pending_review  # type: ignore[method-assign]
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        specialist = driver.executions.list_specialist_runs(PROJECT_ID)[0]
        events = services.sessions.list_events(PROJECT_ID, SESSION_ID)
        await driver.stop()
        return specialist, events

    specialist, events = asyncio.run(scenario())
    assert specialist.status.value == "BLOCKED"
    assert specialist.metadata["waitingReview"] is True
    assert "视频尚未开始" in (specialist.final_summary_text or "")
    blocked = [
        item for item in events if item.event_type == "subagent.blocked"
    ]
    assert len(blocked) == 1
    assert blocked[0].payload["waitingReview"] is True
    assert not [
        item for item in events if item.event_type == "subagent.failed"
    ]


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
                return AgentModelTurn(
                    tool_calls=(
                        AgentToolCall(
                            call_id="read-after-storyboard",
                            name="read_project",
                            arguments={"projectId": PROJECT_ID},
                        ),
                    ),
                )
            return AgentModelTurn(
                content=("[BLOCKED] element:ep22 分镜图已生成，等待用户审阅后生成视频。"),
            )

        parent_turn += 1
        if parent_turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="delegate-ep22-storyboard",
                        name="delegate_to_agent",
                        arguments={
                            "role": "r2v_generation_director",
                            "target_refs": ["element:ep22"],
                            "task": "生成 ep22 分镜图，等待审阅后再生成视频",
                        },
                    ),
                ),
            )
        delegated = json.loads(messages[-1]["content"])
        assert delegated["status"] == "WAITING_REVIEW"
        assert delegated["waitingReview"] is True
        return AgentModelTurn(
            content=("ep22 分镜图等待审阅。审阅通过后告诉我“继续”，我会接着生成视频。"),
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
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )

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
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
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
    waiting_summary = "element:ep22 的分镜图已生成，视频尚未开始。请先审阅分镜图；审阅通过后将自动继续生成视频。"
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
    completed = [
        item for item in events if item.event_type == "agent.run.completed"
    ]
    assert completed[-1].payload["summary"] == expected_final_summary
    streamed_text = "".join(
        str(item.payload.get("delta") or "")
        for item in events
        if item.event_type == "agent.message_delta"
        and item.payload.get("streamKind") == "text"
    )
    assert "告诉我" not in streamed_text
    assert expected_final_summary in streamed_text
