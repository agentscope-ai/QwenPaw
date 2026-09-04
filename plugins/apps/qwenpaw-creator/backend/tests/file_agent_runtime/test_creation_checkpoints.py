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
    CHECKPOINT_SCRIPT,
    CHECKPOINT_STRUCTURE,
    checkpoint_authorization_id,
    required_checkpoint_phases,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project, VisualEntity
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
    return services


async def _wait_for(predicate, *, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise TimeoutError("condition was not reached")
        await asyncio.sleep(0.01)


def test_design_images_only_need_the_plan_checkpoint() -> None:
    """Requiring the design checkpoint for design images would deadlock:
    only storyboards and videos wait for it."""
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


def test_multi_timeline_projects_prepend_structure_and_script() -> None:
    """Blueprint ladder（方案 3.1）：多集/分支项目在生成前先确认
    结构与剧本；设计图只等结构（可与剧本审阅并行）。"""

    assert required_checkpoint_phases(
        "image_generation",
        SpecialistRole.VISUAL_DEVELOPMENT,
        timeline_count=3,
    ) == (CHECKPOINT_STRUCTURE, CHECKPOINT_PLAN)
    assert required_checkpoint_phases(
        "image_generation",
        SpecialistRole.R2V_GENERATION_DIRECTOR,
        timeline_count=3,
    ) == (
        CHECKPOINT_STRUCTURE,
        CHECKPOINT_SCRIPT,
        CHECKPOINT_PLAN,
        CHECKPOINT_DESIGN,
    )
    assert required_checkpoint_phases(
        "r2v_generation",
        SpecialistRole.R2V_GENERATION_DIRECTOR,
        timeline_count=2,
    ) == (
        CHECKPOINT_STRUCTURE,
        CHECKPOINT_SCRIPT,
        CHECKPOINT_PLAN,
        CHECKPOINT_DESIGN,
    )


def test_single_timeline_structure_is_always_silent() -> None:
    """单 timeline 项目感知不到 structure/script；调用点拿不到
    project（timeline_count=None）时同样按单 timeline 处理。"""

    for timeline_count in (1, None):
        assert required_checkpoint_phases(
            "image_generation",
            SpecialistRole.VISUAL_DEVELOPMENT,
            timeline_count=timeline_count,
        ) == (CHECKPOINT_PLAN,)
        assert required_checkpoint_phases(
            "r2v_generation",
            SpecialistRole.R2V_GENERATION_DIRECTOR,
            timeline_count=timeline_count,
        ) == (CHECKPOINT_PLAN, CHECKPOINT_DESIGN)


def test_skip_mode_silences_structure_and_script_too(monkeypatch) -> None:
    """yolo（creation_checkpoints.mode=skip）强制 delegated：
    多集项目的全部检查点同样静默，沿用既有 skip 语义路径。"""

    from models import config as model_config

    monkeypatch.setattr(
        model_config,
        "_get_user_config",
        lambda: {"creation_checkpoints": {"mode": "skip"}},
    )
    assert not required_checkpoint_phases(
        "r2v_generation",
        SpecialistRole.R2V_GENERATION_DIRECTOR,
        timeline_count=5,
    )
    assert not required_checkpoint_phases(
        "image_generation",
        SpecialistRole.VISUAL_DEVELOPMENT,
        timeline_count=5,
    )


def _legacy_r2v_checkpoint_client():
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
                                "targetRef": "element:ep1",
                                "arguments": {"prompt": "ep1 storyboard"},
                            },
                        ),
                    ),
                )
            return AgentModelTurn(content="[SUCCESS]\n分镜图已生成。")
        parent_turn += 1
        if parent_turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="delegate-r2v-1",
                        name="delegate_to_agent",
                        arguments={
                            "role": "r2v_generation_director",
                            "target_refs": ["element:ep1"],
                            "task": "生成 ep1 分镜图",
                        },
                    ),
                ),
            )
        return AgentModelTurn(content="R2V Specialist 已完成。")

    return CallbackAgentChatClient(callback)


def _driver_with_recorded_media(services, invocations: list[str]):
    driver = FileCreatorAgentRuntime(
        services,
        model_client=_legacy_r2v_checkpoint_client(),
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


def _admit_legacy_r2v_checkpoint_harness(monkeypatch) -> None:
    """Exercise the durable checkpoint ladder without re-enabling R2V.

    New main-Agent manifests reject R2V delegation.  The enum and media tool
    remain readable for historical runs, and this narrow test harness admits
    one such record so the pre-existing checkpoint state machine still has
    end-to-end coverage.
    """

    import services.file_agent_runtime.driver as driver_module

    monkeypatch.setattr(
        driver_module.DelegateToAgentInput,
        "validate_contract",
        lambda self, *, project_id: None,
    )
    monkeypatch.setattr(
        driver_module,
        "specialist_system_prompt",
        lambda *args, **kwargs: "Legacy R2V checkpoint test prompt.",
    )


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
    _admit_legacy_r2v_checkpoint_harness(monkeypatch)
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
        design_authorization_id = checkpoint_authorization_id(
            PROJECT_ID,
            CHECKPOINT_DESIGN,
        )
        await _wait_for(
            lambda: any(
                item.authorization_id == design_authorization_id
                for item in driver.executions.list_execution_authorizations(
                    PROJECT_ID,
                )
            ),
        )
        design_pending = driver.executions.get_execution_authorization(
            PROJECT_ID,
            design_authorization_id,
        )
        assert not invocations
        driver.executions.decide_execution_authorization(
            PROJECT_ID,
            design_authorization_id,
            authorization_token=design_pending.authorization_token,
            status=ExecutionAuthorizationStatus.APPROVED,
            decision={
                "provider": design_pending.requested_provider,
                "model": design_pending.requested_model,
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
    _admit_legacy_r2v_checkpoint_harness(monkeypatch)
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
            >= 1,
        )
        # The specialist runs detached from the mainline turn: wait for it
        # to observe the rejection instead of racing driver.stop().
        await _wait_for(
            lambda: any(
                "CreationCheckpointBlocked" in str(item.content_parts)
                for item in driver.executions.list_specialist_messages(
                    PROJECT_ID,
                    pending.run_id,
                )
            ),
        )
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
    _admit_legacy_r2v_checkpoint_harness(monkeypatch)
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


def test_execution_mode_scales_the_checkpoint_ladder(monkeypatch) -> None:
    """Upstream three governance modes (WT-B3).

    ``delegated`` drops the pit stops entirely; ``fine_tuning`` keeps a
    single plan-phase scope confirmation; ``co_creation`` is the default
    full ladder (covered by the test above).
    """
    from models import config as model_config

    monkeypatch.setattr(
        model_config,
        "get_execution_mode",
        lambda: "delegated",
    )
    assert not required_checkpoint_phases(
        "image_generation",
        SpecialistRole.R2V_GENERATION_DIRECTOR,
    )
    assert not required_checkpoint_phases(
        "r2v_generation",
        SpecialistRole.R2V_GENERATION_DIRECTOR,
    )

    monkeypatch.setattr(
        model_config,
        "get_execution_mode",
        lambda: "fine_tuning",
    )
    assert required_checkpoint_phases(
        "image_generation",
        SpecialistRole.R2V_GENERATION_DIRECTOR,
    ) == (CHECKPOINT_PLAN,)
    assert required_checkpoint_phases(
        "r2v_generation",
        SpecialistRole.R2V_GENERATION_DIRECTOR,
    ) == (CHECKPOINT_PLAN,)


def test_yolo_skip_forces_delegated_execution_mode(monkeypatch) -> None:
    """Ladder consistency: creation_checkpoints.mode=skip means no
    mid-flight gates, so the stored execution_mode is overridden."""
    from models import config as model_config

    monkeypatch.setattr(
        model_config,
        "_get_user_config",
        lambda: {
            "creation_checkpoints": {
                "mode": "skip",
                "execution_mode": "co_creation",
            },
        },
    )
    assert model_config.get_execution_mode() == "delegated"

    monkeypatch.setattr(
        model_config,
        "_get_user_config",
        lambda: {
            "creation_checkpoints": {
                "mode": "required",
                "execution_mode": "fine_tuning",
            },
        },
    )
    assert model_config.get_execution_mode() == "fine_tuning"

    # Unknown/absent values fall back to the co-creation default.
    monkeypatch.setattr(
        model_config,
        "_get_user_config",
        lambda: {"creation_checkpoints": {"mode": "required"}},
    )
    assert model_config.get_execution_mode() == "co_creation"
