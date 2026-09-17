# -*- coding: utf-8 -*-
"""用户账户审计必须脱敏。"""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.identity.audit import UserAuditRepository
from qwenpaw.identity.models import PlatformRole


class FakeResult:
    pass


class FakeSession:
    def __init__(self) -> None:
        self.parameters = None

    async def execute(self, _statement, parameters):
        self.parameters = parameters
        return FakeResult()


@pytest.mark.asyncio
async def test_password_audit_records_only_changed_field_name() -> None:
    session = FakeSession()

    @asynccontextmanager
    async def factory():
        yield session

    repository = UserAuditRepository(session_factory=factory)
    actor = ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=PlatformRole.ADMIN,
        admin_mode=False,
        request_id="req-1",
    )

    await repository.record(
        actor=actor,
        target_user_id=uuid4(),
        action="admin.user.password.reset",
        changed_fields=["password"],
    )

    assert session.parameters["detail"] == '{"changed_fields": ["password"]}'
    assert "new_password" not in session.parameters
