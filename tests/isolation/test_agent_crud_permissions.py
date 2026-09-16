# -*- coding: utf-8 -*-
"""多用户 Agent CRUD 必须按 owner/成员关系授权并采用软删除。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_membership import AccessibleAgent, AgentAccessDeniedError
from qwenpaw.access.agent_repository import (
    AgentReferenceCounts,
    AgentResourceRole,
    LegacyAgentRecord,
)
from qwenpaw.app.routers import agents as agents_router
from qwenpaw.config.config import AgentProfileConfig, AgentProfileRef, Config
from qwenpaw.identity.models import PlatformRole


def _actor(role: PlatformRole = PlatformRole.MEMBER) -> ActorContext:
    return ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="req-agent-crud",
    )


def _request(actor: ActorContext, manager=None):
    return SimpleNamespace(
        state=SimpleNamespace(actor=actor),
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=manager),
        ),
    )


def _config() -> Config:
    config = Config()
    config.agents.profiles = {
        "default": AgentProfileRef(
            id="default",
            workspace_dir="/tmp/default",
            enabled=True,
        ),
        "mine": AgentProfileRef(
            id="mine",
            workspace_dir="/tmp/mine",
            enabled=True,
        ),
        "hidden": AgentProfileRef(
            id="hidden",
            workspace_dir="/tmp/hidden",
            enabled=True,
        ),
    }
    config.agents.agent_order = ["default", "mine", "hidden"]
    return config


def _profile(agent_id: str) -> AgentProfileConfig:
    return AgentProfileConfig(
        id=agent_id,
        name=agent_id.title(),
        description=f"{agent_id} description",
        workspace_dir=f"/tmp/{agent_id}",
    )


class ListMembershipService:
    def __init__(self, actor: ActorContext) -> None:
        self.actor = actor

    async def list_accessible(self, *, actor, legacy_agents):
        assert actor is self.actor
        mine = next(agent for agent in legacy_agents if agent.key == "mine")
        return [
            AccessibleAgent(
                agent=mine,
                owner_user_id=actor.user_id,
                role=AgentResourceRole.OWNER,
                registration_state="registered",
            )
        ]


class CollaboratorListMembershipService:
    def __init__(self, actor: ActorContext) -> None:
        self.actor = actor

    async def list_accessible(self, *, actor, legacy_agents):
        assert actor is self.actor
        shared = next(agent for agent in legacy_agents if agent.key == "mine")
        return [
            AccessibleAgent(
                agent=shared,
                owner_user_id=uuid4(),
                role=AgentResourceRole.COLLABORATOR,
                registration_state="registered",
            )
        ]


@pytest.mark.asyncio
async def test_list_returns_only_accessible_agents_with_role_metadata(
    monkeypatch,
) -> None:
    actor = _actor()
    config = _config()
    monkeypatch.setattr(agents_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "load_agent_config", _profile)
    monkeypatch.setattr(
        agents_router,
        "_get_agent_membership_service",
        lambda: ListMembershipService(actor),
    )

    response = await agents_router.list_agents(_request(actor))

    assert [agent.id for agent in response.agents] == ["mine"]
    assert response.agents[0].access_role == "owner"
    assert response.agents[0].registration_state == "registered"
    assert response.agents[0].can_edit is True
    assert response.agents[0].can_delete is True


@pytest.mark.asyncio
async def test_collaborator_can_edit_but_cannot_reorder_or_manage_members(
    monkeypatch,
) -> None:
    actor = _actor()
    config = _config()
    monkeypatch.setattr(agents_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "load_agent_config", _profile)
    monkeypatch.setattr(
        agents_router,
        "_get_agent_membership_service",
        lambda: CollaboratorListMembershipService(actor),
    )

    response = await agents_router.list_agents(_request(actor))

    agent = response.agents[0]
    assert agent.access_role == "collaborator"
    assert agent.can_edit is True
    assert agent.can_copy is True
    assert agent.can_toggle is True
    assert agent.can_delete is False
    assert agent.can_reorder is False
    assert agent.can_manage_members is False


class DenyingMembershipService:
    async def require_role(self, **_kwargs):
        raise AgentAccessDeniedError()


@pytest.mark.asyncio
async def test_get_agent_hides_inaccessible_resource(monkeypatch) -> None:
    actor = _actor(PlatformRole.ADMIN)
    config = _config()
    monkeypatch.setattr(agents_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "load_agent_config", _profile)
    monkeypatch.setattr(
        agents_router,
        "_get_agent_membership_service",
        lambda: DenyingMembershipService(),
    )

    with pytest.raises(agents_router.HTTPException) as exc_info:
        await agents_router.get_agent("hidden", request=_request(actor))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "forbidden"


class OwnerMembershipService:
    async def require_role(self, *, actor, agent, allowed_roles):
        assert AgentResourceRole.OWNER in allowed_roles
        return AccessibleAgent(
            agent=agent,
            owner_user_id=actor.user_id,
            role=AgentResourceRole.OWNER,
            registration_state="registered",
        )


class RecordingMetadataRepository:
    def __init__(self) -> None:
        self.status_changes: list[tuple[str, str]] = []

    async def reference_counts(self, agent_key: str) -> AgentReferenceCounts:
        assert agent_key == "mine"
        return AgentReferenceCounts(conversations=2, skills=1)

    async def set_status(self, agent_key: str, status: str) -> None:
        self.status_changes.append((agent_key, status))


@pytest.mark.asyncio
async def test_delete_soft_deletes_metadata_and_keeps_workspace_registration(
    monkeypatch,
) -> None:
    actor = _actor()
    config = _config()
    repository = RecordingMetadataRepository()
    workspace_repository = SimpleNamespace(
        mark_agent_cleanup_pending=AsyncMock(return_value=2),
    )

    class Manager:
        def is_agent_startup_in_progress(self, _agent_id: str) -> bool:
            return False

        async def stop_agent(self, agent_id: str) -> None:
            assert agent_id == "mine"

    monkeypatch.setattr(agents_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "load_agent_config", _profile)
    monkeypatch.setattr(
        agents_router,
        "_get_agent_membership_service",
        lambda: OwnerMembershipService(),
    )
    monkeypatch.setattr(
        agents_router,
        "_get_agent_metadata_repository",
        lambda: repository,
    )
    monkeypatch.setattr(
        agents_router,
        "_get_agent_user_workspace_repository",
        lambda: workspace_repository,
    )

    response = await agents_router.delete_agent(
        "mine",
        request=_request(actor, Manager()),
    )

    assert repository.status_changes == [("mine", "deleted")]
    workspace_repository.mark_agent_cleanup_pending.assert_awaited_once_with(
        agent_key="mine",
    )
    assert "mine" in config.agents.profiles
    assert "mine" in config.agents.agent_order
    assert response["references"] == {"conversations": 2, "skills": 1}


class RecordingCreateRepository:
    def __init__(self) -> None:
        self.registrations: list[tuple[str, object, str]] = []
        self.updated: list[LegacyAgentRecord] = []

    async def register_owner(self, *, agent, owner_user_id, status=None):
        self.registrations.append((agent.key, owner_user_id, status))

    async def update_metadata(self, *, agent):
        self.updated.append(agent)


@pytest.mark.asyncio
async def test_create_registers_current_user_as_owner_and_activates_metadata(
    monkeypatch,
    tmp_path,
) -> None:
    actor = _actor()
    config = _config()
    repository = RecordingCreateRepository()
    saved_profiles: list[AgentProfileConfig] = []
    manager = SimpleNamespace(schedule_agent_startup=lambda _agent_id: None)

    monkeypatch.setattr(agents_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "save_config", lambda _config: None)
    monkeypatch.setattr(
        agents_router,
        "save_agent_config",
        lambda _agent_id, profile: saved_profiles.append(profile),
    )
    monkeypatch.setattr(
        agents_router,
        "_initialize_agent_workspace",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        agents_router,
        "_get_agent_metadata_repository",
        lambda: repository,
    )

    result = await agents_router.create_agent(
        agents_router.CreateAgentRequest(
            id="created",
            name="Created Agent",
            workspace_dir=str(tmp_path / "created"),
            backend="codex",
        ),
        http_request=_request(actor, manager),
    )

    assert result.id == "created"
    assert repository.registrations == [
        ("created", actor.user_id, "draft"),
    ]
    assert [(item.key, item.status) for item in repository.updated] == [
        ("created", "active"),
    ]
    assert saved_profiles[0].name == "Created Agent"


class UserOnlyMembershipService:
    async def require_role(self, **_kwargs):
        raise AgentAccessDeniedError()


@pytest.mark.asyncio
async def test_run_only_user_cannot_toggle_agent(monkeypatch) -> None:
    actor = _actor()
    config = _config()
    monkeypatch.setattr(agents_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "load_agent_config", _profile)
    monkeypatch.setattr(
        agents_router,
        "_get_agent_membership_service",
        lambda: UserOnlyMembershipService(),
    )

    with pytest.raises(agents_router.HTTPException) as exc_info:
        await agents_router.toggle_agent_enabled(
            "mine",
            True,
            request=_request(actor),
        )

    assert exc_info.value.status_code == 403
