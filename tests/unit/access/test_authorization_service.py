# -*- coding: utf-8 -*-
"""平台 capability 必须体现管理员只是增加治理权限。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.capabilities import Capability
from qwenpaw.access.service import AuthorizationDeniedError, AuthorizationService
from qwenpaw.identity.models import PlatformRole


def _actor(role: PlatformRole, *, legacy: bool = False) -> ActorContext:
    return ActorContext(
        user_id=None if legacy else uuid4(),
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="req-capability",
    )


def test_member_keeps_normal_use_but_cannot_manage_platform_users() -> None:
    service = AuthorizationService()
    member = _actor(PlatformRole.MEMBER)

    assert service.is_allowed(member, Capability.PLATFORM_USE)
    assert not service.is_allowed(member, Capability.USERS_MANAGE)
    with pytest.raises(AuthorizationDeniedError, match="forbidden"):
        service.require(member, Capability.USERS_MANAGE)


def test_admin_has_member_capabilities_plus_user_governance() -> None:
    service = AuthorizationService()
    admin = _actor(PlatformRole.ADMIN)

    assert service.is_allowed(admin, Capability.PLATFORM_USE)
    assert service.is_allowed(admin, Capability.USERS_MANAGE)


def test_legacy_compatibility_actor_preserves_existing_routes() -> None:
    service = AuthorizationService()
    legacy = _actor(PlatformRole.ADMIN, legacy=True)

    assert service.is_allowed(legacy, Capability.PLATFORM_USE)
    assert service.is_allowed(legacy, Capability.USERS_MANAGE)
