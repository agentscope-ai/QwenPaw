"""自动化 API 必须把可信主体传给对象级授权服务。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.crons.api import (
    AutomationAuthorizeRequest,
    authorize_job,
    create_job,
    list_jobs,
    revoke_job_authorization,
)
from qwenpaw.app.crons.models import CronJobSpec
from qwenpaw.automation.grants import AutomationAuthorizationError
from qwenpaw.identity.models import PlatformRole


def _actor() -> ActorContext:
    return ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="automation-api-test",
    )


def _job() -> CronJobSpec:
    return CronJobSpec.model_validate(
        {
            "name": "owner job",
            "schedule": {"type": "cron", "cron": "0 9 * * *"},
            "task_type": "text",
            "text": "hello",
            "dispatch": {
                "channel": "console",
                "target": {"user_id": "spoofed", "session_id": "daily"},
            },
        }
    )


@pytest.mark.asyncio
async def test_create_and_list_use_authenticated_actor():
    actor = _actor()
    calls = []

    class Service:
        async def create(self, subject, spec):
            calls.append(("create", subject))
            return spec.model_copy(
                update={
                    "created_by_user_id": subject.user_id,
                    "automation_owner_user_id": subject.user_id,
                    "status": "pending_authorization",
                }
            )

        async def list_visible(self, subject, *, scope):
            calls.append((scope, subject))
            return []

    manager = SimpleNamespace(
        authorization_service=Service(),
        refresh_job=lambda job_id: _async_none(),
    )

    created = await create_job(_job(), mgr=manager, actor=actor)
    assert created.automation_owner_user_id == actor.user_id
    assert await list_jobs(scope="mine", mgr=manager, actor=actor) == []
    assert calls == [("create", actor), ("mine", actor)]


@pytest.mark.asyncio
async def test_authorize_and_revoke_delegate_only_to_service():
    actor = _actor()
    job = _job().model_copy(update={"id": str(uuid4())})
    calls = []

    class Service:
        async def authorize(self, subject, job_id, **payload):
            calls.append(("authorize", subject, job_id, payload))
            return job.model_copy(update={"status": "active"})

        async def revoke(self, subject, job_id):
            calls.append(("revoke", subject, job_id))
            return job.model_copy(update={"status": "authorization_revoked"})

    manager = SimpleNamespace(
        authorization_service=Service(),
        refresh_job=lambda job_id: _async_none(),
    )
    payload = AutomationAuthorizeRequest(
        config_version=2,
        authorization_digest="a" * 64,
    )

    authorized = await authorize_job(job.id, payload, mgr=manager, actor=actor)
    revoked = await revoke_job_authorization(job.id, mgr=manager, actor=actor)

    assert authorized.status == "active"
    assert revoked.status == "authorization_revoked"
    assert calls[0][3] == {
        "config_version": 2,
        "authorization_digest": "a" * 64,
    }


@pytest.mark.asyncio
async def test_agent_access_required_maps_to_forbidden_without_leaking_data():
    actor = _actor()

    class Service:
        async def list_visible(self, subject, *, scope):
            raise AutomationAuthorizationError("automation_agent_access_required")

    manager = SimpleNamespace(authorization_service=Service())
    with pytest.raises(Exception) as raised:
        await list_jobs(scope="agent", mgr=manager, actor=actor)
    assert raised.value.status_code == 403
    assert raised.value.detail == "automation_agent_access_required"


async def _async_none():
    return None
