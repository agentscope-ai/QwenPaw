# -*- coding: utf-8 -*-
"""集中式 capability 判定。"""

from __future__ import annotations

from ..identity.models import PlatformRole
from .actor import ActorContext, ActorType
from .capabilities import Capability


class AuthorizationDeniedError(RuntimeError):
    """对外统一为不泄露资源细节的 forbidden。"""

    def __init__(self) -> None:
        super().__init__("forbidden")


class AuthorizationService:
    """管理员拥有普通用户能力，并增加平台治理能力。"""

    def is_allowed(self, actor: ActorContext, capability: Capability) -> bool:
        if actor.actor_type is ActorType.SERVICE:
            return capability in (
                Capability.PLATFORM_USE,
                Capability.AGENT_USE,
            )
        if actor.actor_type is not ActorType.USER:
            return False
        if capability in (Capability.PLATFORM_USE, Capability.AGENT_USE):
            return actor.platform_role in (PlatformRole.ADMIN, PlatformRole.MEMBER)
        if capability in (
            Capability.USERS_MANAGE,
            Capability.PLATFORM_SETTINGS_MANAGE,
            Capability.MODELS_MANAGE,
            Capability.SKILLS_MANAGE,
            Capability.PLUGINS_MANAGE,
            Capability.PUBLICATIONS_REVIEW,
        ):
            return actor.platform_role is PlatformRole.ADMIN
        return False

    def require(self, actor: ActorContext, capability: Capability) -> None:
        if not self.is_allowed(actor, capability):
            raise AuthorizationDeniedError()
