# -*- coding: utf-8 -*-
"""Creation pit-stop checkpoints gate costly generation deterministically."""
from __future__ import annotations

import asyncio

import pytest

from domain.enums import SpecialistRole
from services.file_agent_runtime import (
    AgentModelTurn,
    AgentToolCall,
    CallbackAgentChatClient,
    FileCreatorAgentRuntime,
)
from services.file_agent_runtime.checkpoints import (
    CHECKPOINT_DESIGN,
    CHECKPOINT_PLAN,
    checkpoint_authorization_id,
    required_checkpoint_phases,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.execution_models import (
    ExecutionAuthorizationStatus,
)
from services.specialist_tools import SpecialistToolResult

pytestmark = pytest.mark.unit

PROJECT_ID = "project-1"
SESSION_ID = "session-1"
CONVERSATION_ID = "conversation-1"
GOAL_ID = "goal-1"


def _create_project(tmp_path, *, initial_goal: str):
    services = CreatorFileServices.create(tmp_path.resolve())

    def initialize(staged_root) -> None:
        services.sessions.initialize_staged_project(
            staged_root,
            PROJECT_ID,
            session_id=SESSION_ID,
            conversation_id=CONVERSATION_ID,
            initial_goal=initial_goal,
            goal_id=GOAL_ID,
            initial_message_id="message-initial",
            initial_client_message_id="client-initial",
        )

    snapshot = services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Initial"),
        initialize_staged_project=initialize,
    )
    services.poller.note_commit(snapshot)
    return services


async def _wait_for(predicate, *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise TimeoutError("condition was not reached")
        await asyncio.sleep(0.01)


def test_design_images_only_need_the_plan_checkpoint() -> None:
    """Design images are what the design checkpoint reviews later.

    Requiring the design checkpoint for them would deadlock the flow, so
    only storyboards and videos wait for it.
    """

    assert required_checkpoint_phases(
        "image_generation",
        SpecialistRole.VISUAL_DEVELOPMENT,
    ) == (CHECKPOINT_PLAN,)
    assert required_checkpoint_phases(
        "image_generation",
        SpecialistRole.R2V_GENERATION_DIRECTOR,
    ) == (CHECKPOINT_PLAN, CHECKPOINT_DESIGN)
    assert required_checkpoint_phases(
        "r2v_generation",
        SpecialistRole.R2V_GENERATION_DIRECTOR,
    ) == (CHECKPOINT_PLAN, CHECKPOINT_DESIGN)
    # Non-media tools are never gated.
    assert not required_checkpoint_phases(
        "commit_source_intelligence",
        SpecialistRole.SOURCE_INTELLIGENCE,
    )


def _visual_delegation_client():
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

    return CallbackAgentChatClient(callback)


def _driver_with_recorded_media(services, invocations: list[str]):
    driver = FileCreatorAgentRuntime(
        services,
        model_client=_visual_delegation_client(),
        poll_interval_seconds=0.01,
    )

    async def fake_invoke(**kwargs):
        invocations.append(str(kwargs.get("name")))
        return SpecialistToolResult(
            payload={
                "ok": True,
                "status": "SUCCEEDED",
                "artifactVersionId": "artifact-version-1",
            },
        )

    driver.specialist_tools.invoke = fake_invoke  # type: ignore[method-assign]
    return driver


def test_plan_checkpoint_blocks_generation_until_the_user_approves(
    tmp_path,
    monkeypatch,
) -> None:
    """No pixels are produced before the plan checkpoint is cleared."""

    import services.file_agent_runtime.driver as driver_module

    monkeypatch.setattr(
        driver_module,
        "get_execution_authorization_mode",
        lambda: "allow_all",
    )
    monkeypatch.setattr(
        driver_module,
        "get_creation_checkpoint_mode",
        lambda: "required",
    )
    invocations: list[str] = []

    async def scenario():
        services = _create_project(tmp_path, initial_goal="生成角色图")
        driver = _driver_with_recorded_media(services, invocations)
        await driver.start()
        driver.notify(PROJECT_ID)
        authorization_id = checkpoint_authorization_id(
            PROJECT_ID,
            CHECKPOINT_PLAN,
        )
        await _wait_for(
            lambda: bool(
                driver.executions.list_execution_authorizations(PROJECT_ID),
            ),
        )
        pending = driver.executions.get_execution_authorization(
            PROJECT_ID,
            authorization_id,
        )
        # The gate held: the media tool never ran.
        blocked_invocations = list(invocations)

        driver.executions.decide_execution_authorization(
            PROJECT_ID,
            authorization_id,
            authorization_token=pending.authorization_token,
            status=ExecutionAuthorizationStatus.APPROVED,
            decision={
                "provider": pending.requested_provider,
                "model": pending.requested_model,
                "maxCost": 0,
                "maxCandidates": 1,
            },
        )
        await _wait_for(lambda: bool(invocations))
        await _wait_for(
            lambda: services.sessions.get_project_session(
                PROJECT_ID,
            ).last_consumed_message_seq
            == 1,
        )
        await driver.wait_until_idle(PROJECT_ID)
        session = services.sessions.get_project_session(PROJECT_ID)
        await driver.stop()
        return pending, blocked_invocations, session

    pending, blocked_invocations, session = asyncio.run(scenario())

    assert pending.operation == "creation_checkpoint_plan"
    assert pending.status is ExecutionAuthorizationStatus.PENDING
    assert "计划检查点" in pending.summary
    assert blocked_invocations == []
    # After approval the same call went through.
    assert invocations == ["image_generation"]
    assert session.error is None


def test_declined_plan_checkpoint_refuses_without_generating(
    tmp_path,
    monkeypatch,
) -> None:
    """A declined pit stop yields guidance, not a retry loop."""

    import services.file_agent_runtime.driver as driver_module

    monkeypatch.setattr(
        driver_module,
        "get_execution_authorization_mode",
        lambda: "allow_all",
    )
    monkeypatch.setattr(
        driver_module,
        "get_creation_checkpoint_mode",
        lambda: "required",
    )
    invocations: list[str] = []

    async def scenario():
        services = _create_project(tmp_path, initial_goal="生成角色图")
        driver = _driver_with_recorded_media(services, invocations)
        await driver.start()
        driver.notify(PROJECT_ID)
        authorization_id = checkpoint_authorization_id(
            PROJECT_ID,
            CHECKPOINT_PLAN,
        )
        await _wait_for(
            lambda: bool(
                driver.executions.list_execution_authorizations(PROJECT_ID),
            ),
        )
        pending = driver.executions.get_execution_authorization(
            PROJECT_ID,
            authorization_id,
        )
        driver.executions.decide_execution_authorization(
            PROJECT_ID,
            authorization_id,
            authorization_token=pending.authorization_token,
            status=ExecutionAuthorizationStatus.REJECTED,
        )
        await _wait_for(
            lambda: services.sessions.get_project_session(
                PROJECT_ID,
            ).last_consumed_message_seq
            == 1,
        )
        await driver.wait_until_idle(PROJECT_ID)
        messages = driver.executions.list_specialist_messages(
            PROJECT_ID,
            pending.run_id,
        )
        await driver.stop()
        return messages

    messages = asyncio.run(scenario())

    assert not invocations
    refusals = [
        item
        for item in messages
        if "CreationCheckpointBlocked" in str(item.content_parts)
    ]
    assert refusals, "the specialist must see the checkpoint refusal"
    text = str(refusals[0].content_parts)
    assert "创作检查点" in text
    assert "不要重试生成" in text


def _repeating_visual_client():
    """Delegates and generates once per run, across any number of runs."""

    counter = 0

    async def callback(messages, tools):
        nonlocal counter
        names = {item["function"]["name"] for item in tools}
        last_role = messages[-1]["role"] if messages else "user"
        if "image_generation" in names:
            if last_role == "tool":
                return AgentModelTurn(content="[SUCCESS]\n角色图已生成。")
            counter += 1
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id=f"generate-image-{counter}",
                        name="image_generation",
                        arguments={
                            "projectId": PROJECT_ID,
                            "targetRef": "asset:hero",
                            "arguments": {"prompt": "hero portrait"},
                        },
                    ),
                ),
            )
        if last_role == "tool":
            return AgentModelTurn(content="视觉 Specialist 已完成。")
        counter += 1
        return AgentModelTurn(
            tool_calls=(
                AgentToolCall(
                    call_id=f"delegate-visual-{counter}",
                    name="delegate_to_agent",
                    arguments={
                        "role": "visual_development_agent",
                        "target_refs": ["asset:hero"],
                        "task": "生成角色图",
                    },
                ),
            ),
        )

    return CallbackAgentChatClient(callback)


def test_rejected_checkpoint_reopens_for_a_revised_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    """reject → revise → a fresh approval card → approve → generation runs."""

    import services.file_agent_runtime.driver as driver_module

    monkeypatch.setattr(
        driver_module,
        "get_execution_authorization_mode",
        lambda: "allow_all",
    )
    monkeypatch.setattr(
        driver_module,
        "get_creation_checkpoint_mode",
        lambda: "required",
    )
    invocations: list[str] = []

    async def scenario():
        services = _create_project(tmp_path, initial_goal="生成角色图")
        driver = FileCreatorAgentRuntime(
            services,
            model_client=_repeating_visual_client(),
            poll_interval_seconds=0.01,
        )

        async def fake_invoke(**kwargs):
            invocations.append(str(kwargs.get("name")))
            return SpecialistToolResult(
                payload={
                    "ok": True,
                    "status": "SUCCEEDED",
                    "artifactVersionId": "artifact-version-1",
                },
            )

        driver.specialist_tools.invoke = (  # type: ignore[method-assign]
            fake_invoke
        )
        await driver.start()
        driver.notify(PROJECT_ID)

        first_id = checkpoint_authorization_id(PROJECT_ID, CHECKPOINT_PLAN)
        await _wait_for(
            lambda: bool(
                driver.executions.list_execution_authorizations(PROJECT_ID),
            ),
        )
        pending = driver.executions.get_execution_authorization(
            PROJECT_ID,
            first_id,
        )
        driver.executions.decide_execution_authorization(
            PROJECT_ID,
            first_id,
            authorization_token=pending.authorization_token,
            status=ExecutionAuthorizationStatus.REJECTED,
        )
        await _wait_for(
            lambda: services.sessions.get_project_session(
                PROJECT_ID,
            ).last_consumed_message_seq
            == 1,
        )
        await driver.wait_until_idle(PROJECT_ID)
        assert not invocations
        first_goal = services.sessions.get_goal(PROJECT_ID, GOAL_ID)
        if first_goal.status.value not in ("COMPLETED", "CANCELLED"):
            services.sessions.set_goal_status(
                PROJECT_ID,
                GOAL_ID,
                "COMPLETED",
            )

        # The user revises the plan and asks for the images again.
        second = services.sessions.append_message(
            PROJECT_ID,
            SESSION_ID,
            CONVERSATION_ID,
            role="user",
            content_parts=[
                {"type": "text", "text": "计划已按意见修改，请重新生成角色图"},
            ],
        ).message
        driver.notify(PROJECT_ID)

        retry_id = checkpoint_authorization_id(
            PROJECT_ID,
            CHECKPOINT_PLAN,
            1,
        )

        def retry_pending() -> bool:
            try:
                driver.executions.get_execution_authorization(
                    PROJECT_ID,
                    retry_id,
                )
            except RecordNotFoundError:
                return False
            return True

        await _wait_for(retry_pending)
        retry = driver.executions.get_execution_authorization(
            PROJECT_ID,
            retry_id,
        )
        assert retry.status is ExecutionAuthorizationStatus.PENDING
        driver.executions.decide_execution_authorization(
            PROJECT_ID,
            retry_id,
            authorization_token=retry.authorization_token,
            status=ExecutionAuthorizationStatus.APPROVED,
            decision={
                "provider": retry.requested_provider,
                "model": retry.requested_model,
                "maxCost": 0,
                "maxCandidates": 1,
            },
        )
        await _wait_for(lambda: bool(invocations))
        await _wait_for(
            lambda: services.sessions.get_project_session(
                PROJECT_ID,
            ).last_consumed_message_seq
            >= second.message_seq,
        )
        await driver.wait_until_idle(PROJECT_ID)
        rejected = driver.executions.get_execution_authorization(
            PROJECT_ID,
            first_id,
        )
        await driver.stop()
        return rejected

    rejected = asyncio.run(scenario())

    # The revised attempt generated; the audit trail keeps the rejection.
    assert invocations == ["image_generation"]
    assert rejected.status is ExecutionAuthorizationStatus.REJECTED


def test_skip_mode_runs_unattended(tmp_path, monkeypatch) -> None:
    """The toggle keeps unattended runs possible for power users."""

    import services.file_agent_runtime.driver as driver_module

    monkeypatch.setattr(
        driver_module,
        "get_execution_authorization_mode",
        lambda: "allow_all",
    )
    monkeypatch.setattr(
        driver_module,
        "get_creation_checkpoint_mode",
        lambda: "skip",
    )
    invocations: list[str] = []

    async def scenario():
        services = _create_project(tmp_path, initial_goal="生成角色图")
        driver = _driver_with_recorded_media(services, invocations)
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: services.sessions.get_project_session(
                PROJECT_ID,
            ).last_consumed_message_seq
            == 1,
        )
        await driver.wait_until_idle(PROJECT_ID)
        authorizations = driver.executions.list_execution_authorizations(
            PROJECT_ID,
        )
        await driver.stop()
        return authorizations

    authorizations = asyncio.run(scenario())

    assert invocations == ["image_generation"]
    assert authorizations == []
