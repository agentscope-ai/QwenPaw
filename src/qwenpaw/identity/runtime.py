# -*- coding: utf-8 -*-
"""多用户身份服务的运行时装配边界。"""

from __future__ import annotations

from dataclasses import dataclass

from ..constant import EnvVarLoader
from .governance import UserGovernanceService
from .preferences import PostgresPreferenceRepository
from .repository import PostgresUserRepository
from .service import UserService
from .session_repository import PostgresSessionRepository
from .sessions import SessionService


@dataclass(frozen=True, slots=True)
class IdentityRuntime:
    users: UserService
    sessions: SessionService
    preferences: PostgresPreferenceRepository


def is_multi_user_enabled() -> bool:
    return EnvVarLoader.get_bool("QWENPAW_MULTI_USER_ENABLED", False)


def get_identity_schema() -> str:
    return EnvVarLoader.get_str("QWENPAW_DATABASE_SCHEMA", "qwenpaw").strip()


def get_identity_runtime() -> IdentityRuntime:
    schema = get_identity_schema()
    return IdentityRuntime(
        users=UserService(PostgresUserRepository(schema=schema)),
        sessions=SessionService(PostgresSessionRepository(schema=schema)),
        preferences=PostgresPreferenceRepository(schema=schema),
    )


def get_user_governance_service() -> UserGovernanceService:
    """装配管理员用户治理服务，复用同一身份 Schema。"""
    schema = get_identity_schema()
    repository = PostgresUserRepository(schema=schema)
    runtime = get_identity_runtime()
    return UserGovernanceService(
        repository=repository,
        user_service=runtime.users,
        session_service=runtime.sessions,
    )
