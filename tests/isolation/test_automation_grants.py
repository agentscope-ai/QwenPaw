"""自动化创建者自授权和对象权限隔离。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import AgentAccessRecord, AgentResourceRole
from qwenpaw.app.crons.models import CronJobSpec
from qwenpaw.automation.grants import (
    AutomationAuthorizationError,
    AutomationAuthorizationService,
)
from qwenpaw.identity.models import PlatformRole


class FakeRepository:
    def __init__(self):
        self.jobs = {}
        self.authorization = {}
        self.statuses = {}

    async def get_job(self, job_id):
        return self.jobs.get(job_id)

    async def upsert_job(self, job):
        self.jobs[job.id] = job

    async def authorize(self, job_id, **kwargs):
        self.authorization[job_id] = kwargs

    async def get_authorization(self, job_id):
        data = self.authorization.get(job_id)
        if not data:
            return None
        from qwenpaw.app.crons.models import AutomationAuthorization, AutomationGrant

        return AutomationAuthorization(
            schedule_id=job_id,
            authorized_by_user_id=data["authorized_by_user_id"],
            config_version=data["config_version"],
            authorization_digest=data["authorization_digest"],
            grants=[
                AutomationGrant(capability=c, resource_scope=r, target_scope=t)
                for c, r, t in data["grants"]
            ],
        )

    async def set_status(self, job_id, status):
        self.statuses[job_id] = status
        self.jobs[job_id] = self.jobs[job_id].model_copy(
            update={"status": status, "enabled": status == "active"}
        )

    async def revoke_authorization(self, job_id):
        self.authorization.pop(job_id, None)
        await self.set_status(job_id, "authorization_revoked")


def actor(user_id, role=PlatformRole.MEMBER):
    return ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="automation-test",
    )


def spec(*, target_user="spoofed"):
    return CronJobSpec.model_validate(
        {
            "name": "daily report",
            "schedule": {"type": "cron", "cron": "0 9 * * *"},
            "task_type": "agent",
            "request": {"input": "prepare report", "user_id": "spoofed"},
            "dispatch": {
                "channel": "console",
                "target": {"user_id": target_user, "session_id": "daily"},
            },
            "runtime": {"tool_safety": False},
        }
    )


@pytest.mark.asyncio
async def test_creator_becomes_owner_and_self_authorizes_existing_scope():
    repository = FakeRepository()
    creator_id = uuid4()

    async def access_resolver(subject, agent_key):
        assert subject.user_id == creator_id
        return AgentAccessRecord(
            agent_key=agent_key,
            owner_user_id=uuid4(),
            role=AgentResourceRole.USER,
            status="active",
        )

    service = AutomationAuthorizationService(
        repository=repository,
        agent_key="shared-agent",
        access_resolver=access_resolver,
        tool_names_provider=lambda: ["Write", "Read", "Write"],
    )
    created = await service.create(actor(creator_id), spec())

    assert created.created_by_user_id == creator_id
    assert created.automation_owner_user_id == creator_id
    assert created.dispatch.target.user_id == str(creator_id)
    assert created.request.user_id == str(creator_id)
    assert created.runtime.tool_safety is True
    assert created.status == "pending_authorization"

    preview = await service.preview(actor(creator_id), created.id)
    assert preview.tool_names == ("Read", "Write")
    assert preview.target_user_id == creator_id
    authorized = await service.authorize(
        actor(creator_id),
        created.id,
        config_version=preview.config_version,
        authorization_digest=preview.authorization_digest,
    )
    assert authorized.status == "active"


@pytest.mark.asyncio
async def test_other_user_cannot_authorize_or_modify_creator_job():
    repository = FakeRepository()
    creator_id, other_id = uuid4(), uuid4()

    async def access_resolver(subject, agent_key):
        return AgentAccessRecord(
            agent_key=agent_key,
            owner_user_id=other_id,
            role=(
                AgentResourceRole.USER
                if subject.user_id == creator_id
                else AgentResourceRole.OWNER
            ),
            status="active",
        )

    service = AutomationAuthorizationService(
        repository=repository,
        agent_key="shared-agent",
        access_resolver=access_resolver,
        tool_names_provider=lambda: ["Read"],
    )
    created = await service.create(actor(creator_id), spec())
    preview = await service.preview(actor(creator_id), created.id)

    with pytest.raises(AutomationAuthorizationError, match="automation_owner_required"):
        await service.authorize(
            actor(other_id),
            created.id,
            config_version=preview.config_version,
            authorization_digest=preview.authorization_digest,
        )
    with pytest.raises(AutomationAuthorizationError, match="automation_owner_required"):
        await service.require_modify(actor(other_id), created.id)

    await service.pause(actor(other_id), created.id)
    assert repository.statuses[created.id] == "paused"


@pytest.mark.asyncio
async def test_permission_loss_pauses_previously_authorized_job():
    repository = FakeRepository()
    creator_id = uuid4()
    allowed = True

    async def access_resolver(subject, agent_key):
        if not allowed:
            return None
        return AgentAccessRecord(
            agent_key=agent_key,
            owner_user_id=uuid4(),
            role=AgentResourceRole.COLLABORATOR,
            status="active",
        )

    service = AutomationAuthorizationService(
        repository=repository,
        agent_key="shared-agent",
        access_resolver=access_resolver,
        tool_names_provider=lambda: ["Read"],
    )
    created = await service.create(actor(creator_id), spec())
    preview = await service.preview(actor(creator_id), created.id)
    await service.authorize(
        actor(creator_id), created.id,
        config_version=1,
        authorization_digest=preview.authorization_digest,
    )
    allowed = False

    with pytest.raises(AutomationAuthorizationError, match="automation_agent_access_revoked"):
        await service.validate_execution(created.id)
    assert repository.statuses[created.id] == "authorization_revoked"


@pytest.mark.asyncio
async def test_creator_can_revoke_own_authorization():
    repository = FakeRepository()
    creator_id = uuid4()

    async def access_resolver(subject, agent_key):
        return AgentAccessRecord(
            agent_key=agent_key,
            owner_user_id=creator_id,
            role=AgentResourceRole.USER,
            status="active",
        )

    service = AutomationAuthorizationService(
        repository=repository,
        agent_key="shared-agent",
        access_resolver=access_resolver,
        tool_names_provider=lambda: ["Read"],
    )
    created = await service.create(actor(creator_id), spec())
    preview = await service.preview(actor(creator_id), created.id)
    await service.authorize(
        actor(creator_id),
        created.id,
        config_version=preview.config_version,
        authorization_digest=preview.authorization_digest,
    )

    revoked = await service.revoke(actor(creator_id), created.id)

    assert revoked.status == "authorization_revoked"
    assert revoked.enabled is False
    assert await repository.get_authorization(created.id) is None


@pytest.mark.asyncio
async def test_paused_job_cannot_run_and_revoked_job_cannot_resume():
    repository = FakeRepository()
    creator_id = uuid4()

    async def access_resolver(subject, agent_key):
        return AgentAccessRecord(
            agent_key=agent_key,
            owner_user_id=creator_id,
            role=AgentResourceRole.USER,
            status="active",
        )

    service = AutomationAuthorizationService(
        repository=repository,
        agent_key="shared-agent",
        access_resolver=access_resolver,
        tool_names_provider=lambda: [],
    )
    created = await service.create(actor(creator_id), spec())
    preview = await service.preview(actor(creator_id), created.id)
    await service.authorize(
        actor(creator_id),
        created.id,
        config_version=preview.config_version,
        authorization_digest=preview.authorization_digest,
    )
    await service.pause(actor(creator_id), created.id)

    with pytest.raises(AutomationAuthorizationError, match="automation_not_active"):
        await service.validate_execution(created.id)

    await service.revoke(actor(creator_id), created.id)
    with pytest.raises(
        AutomationAuthorizationError, match="automation_authorization_required"
    ):
        await service.resume(actor(creator_id), created.id)
