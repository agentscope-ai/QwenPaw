# -*- coding: utf-8 -*-
"""按领域选择唯一持久化路径，禁止隐式双读和双写。"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Literal, TypeVar

from sqlalchemy import text

from ..constant import EnvVarLoader
from .database import database_session
from .mode import StorageMode
from .settings import DatabaseSettings, load_database_settings

EXPECTED_SCHEMA_REVISION = "0020_agent_personal_library"
CUTOVER_VALIDATED_ENV = "QWENPAW_CUTOVER_VALIDATED_DOMAINS"
CUTOVER_LEGACY_FROZEN_ENV = "QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS"
CUTOVER_POSTGRES_WRITES_ENV = "QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS"
CUTOVER_REVERSE_MIGRATED_ENV = "QWENPAW_CUTOVER_REVERSE_MIGRATED_DOMAINS"
_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

RepositoryT = TypeVar("RepositoryT")
RepositoryAccess = Literal["read", "write"]


class CutoverDomain(StrEnum):
    """可独立迁移和切换的业务领域。"""

    IDENTITY = "identity"
    AGENTS = "agents"
    CONVERSATIONS = "conversations"
    MESSAGES = "messages"
    SKILLS = "skills"
    MCP = "mcp"
    CRON = "cron"
    INBOX = "inbox"
    TOKENS = "tokens"


ALL_CUTOVER_DOMAINS = frozenset(CutoverDomain)


@dataclass(frozen=True, slots=True)
class MigrationState:
    """不含凭据的 Alembic 版本检查结果。"""

    current_revision: str | None
    expected_revision: str
    ready: bool
    error_code: str | None


@dataclass(frozen=True, slots=True)
class CutoverPolicy:
    """一次进程启动使用的显式领域切换声明。"""

    validated_domains: frozenset[CutoverDomain]
    legacy_writes_frozen_domains: frozenset[CutoverDomain]
    postgres_writes_open_domains: frozenset[CutoverDomain]
    reverse_migrated_domains: frozenset[CutoverDomain]

    def read_uses_postgres(self, domain: CutoverDomain) -> bool:
        return (
            domain in self.validated_domains
            and domain in self.legacy_writes_frozen_domains
        )

    def write_uses_postgres(self, domain: CutoverDomain) -> bool:
        return (
            self.read_uses_postgres(domain)
            and domain in self.postgres_writes_open_domains
        )

    def assert_valid(self) -> None:
        if not self.legacy_writes_frozen_domains <= self.validated_domains:
            raise RepositorySelectionError("legacy_freeze_without_validation")
        if not self.postgres_writes_open_domains <= self.legacy_writes_frozen_domains:
            raise RepositorySelectionError("postgres_write_before_legacy_freeze")
        if not self.reverse_migrated_domains <= self.postgres_writes_open_domains:
            raise RepositorySelectionError("reverse_migration_without_postgres_write")


class RepositorySelectionError(RuntimeError):
    """在访问任何仓库前返回稳定且不含凭据的错误。"""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(f"Repository selection failed ({error_code})")


class LegacyWriteBlockedError(RuntimeError):
    """切换后仍尝试写入 Legacy 业务事实时失败关闭。"""

    def __init__(self, domain: CutoverDomain) -> None:
        self.domain = domain
        self.error_code = "legacy_write_blocked"
        super().__init__(f"Legacy write blocked for domain ({domain.value})")


def assert_legacy_write_allowed(
    domain: CutoverDomain | str,
    *,
    settings_loader: Callable[[], DatabaseSettings] = load_database_settings,
) -> None:
    """只允许 Legacy 存储模式修改旧业务事实。"""
    resolved = CutoverDomain(domain)
    settings = settings_loader()
    if (
        settings.multi_user_enabled
        or StorageMode(settings.storage_mode) is StorageMode.POSTGRES
    ):
        raise LegacyWriteBlockedError(resolved)


def _database_schema() -> str:
    schema = EnvVarLoader.get_str("QWENPAW_DATABASE_SCHEMA", "qwenpaw").strip().lower()
    if not _SAFE_SCHEMA.fullmatch(schema):
        raise RepositorySelectionError("invalid_database_schema")
    return schema


def _load_domain_set(env_name: str) -> frozenset[CutoverDomain]:
    raw = EnvVarLoader.get_str(env_name, "").strip()
    if not raw:
        return frozenset()
    values = {item.strip().lower() for item in raw.split(",") if item.strip()}
    if "all" in values:
        if len(values) != 1:
            raise RepositorySelectionError("invalid_cutover_domain_list")
        return ALL_CUTOVER_DOMAINS
    try:
        return frozenset(CutoverDomain(value) for value in values)
    except ValueError as exc:
        raise RepositorySelectionError("unknown_cutover_domain") from exc


def load_cutover_policy() -> CutoverPolicy:
    """读取并校验领域切换声明；空声明不会自动切换任何领域。"""
    policy = CutoverPolicy(
        validated_domains=_load_domain_set(CUTOVER_VALIDATED_ENV),
        legacy_writes_frozen_domains=_load_domain_set(CUTOVER_LEGACY_FROZEN_ENV),
        postgres_writes_open_domains=_load_domain_set(CUTOVER_POSTGRES_WRITES_ENV),
        reverse_migrated_domains=_load_domain_set(CUTOVER_REVERSE_MIGRATED_ENV),
    )
    policy.assert_valid()
    return policy


async def validate_runtime_cutover() -> None:
    """多用户启动前确认所有实际 PostgreSQL 领域均已完成切换。"""
    settings = load_database_settings()
    policy = load_cutover_policy()
    if not settings.multi_user_enabled:
        return
    migration = await read_migration_state()
    if not migration.ready:
        raise RepositorySelectionError(migration.error_code or "schema_not_ready")
    if not ALL_CUTOVER_DOMAINS <= policy.validated_domains:
        raise RepositorySelectionError("domain_migration_not_validated")
    if not ALL_CUTOVER_DOMAINS <= policy.legacy_writes_frozen_domains:
        raise RepositorySelectionError("legacy_writes_not_frozen")
    if not ALL_CUTOVER_DOMAINS <= policy.postgres_writes_open_domains:
        raise RepositorySelectionError("postgres_writes_not_open")


async def read_migration_state() -> MigrationState:
    """只读所选 Schema 的 Alembic 版本。"""
    schema = _database_schema()
    qualified_table = f"{schema}.alembic_version"
    async with database_session() as session:
        table_result = await session.execute(
            text("SELECT to_regclass(:qualified_table)"),
            {"qualified_table": qualified_table},
        )
        if table_result.scalar_one_or_none() is None:
            return MigrationState(
                current_revision=None,
                expected_revision=EXPECTED_SCHEMA_REVISION,
                ready=False,
                error_code="schema_not_initialized",
            )
        revision_result = await session.execute(
            text(f'SELECT version_num FROM "{schema}".alembic_version')
        )
        revision = revision_result.scalar_one_or_none()
    ready = revision == EXPECTED_SCHEMA_REVISION
    return MigrationState(
        current_revision=revision,
        expected_revision=EXPECTED_SCHEMA_REVISION,
        ready=ready,
        error_code=None if ready else "schema_revision_incomplete",
    )


class RepositoryProvider(Generic[RepositoryT]):
    """按领域和访问类型返回唯一仓库实现。"""

    def __init__(
        self,
        *,
        domain: CutoverDomain | str,
        access: RepositoryAccess,
        legacy_repository: RepositoryT,
        postgres_repository: RepositoryT | None = None,
        settings_loader: Callable[[], DatabaseSettings] = load_database_settings,
        migration_state_reader: Callable[
            [], Awaitable[MigrationState]
        ] = read_migration_state,
        policy_loader: Callable[[], CutoverPolicy] = load_cutover_policy,
    ) -> None:
        try:
            self._domain = CutoverDomain(domain)
        except ValueError as exc:
            raise RepositorySelectionError("unknown_cutover_domain") from exc
        if access not in {"read", "write"}:
            raise RepositorySelectionError("invalid_repository_access")
        self._access = access
        self._legacy_repository = legacy_repository
        self._postgres_repository = postgres_repository
        self._settings_loader = settings_loader
        self._migration_state_reader = migration_state_reader
        self._policy_loader = policy_loader

    async def get_repository(self) -> RepositoryT:
        """返回一个路径，并在任何不完整切换状态下失败关闭。"""
        settings = self._settings_loader()
        mode = StorageMode(settings.storage_mode)
        policy = self._policy_loader()
        policy.assert_valid()

        if mode is StorageMode.LEGACY:
            if (
                self._domain in policy.postgres_writes_open_domains
                and self._domain not in policy.reverse_migrated_domains
            ):
                raise RepositorySelectionError("rollback_requires_reverse_migration")
            return self._legacy_repository

        migration_state = await self._migration_state_reader()
        if not migration_state.ready:
            raise RepositorySelectionError(
                migration_state.error_code or "schema_not_ready"
            )
        if self._domain not in policy.validated_domains:
            raise RepositorySelectionError("domain_migration_not_validated")
        if self._domain not in policy.legacy_writes_frozen_domains:
            raise RepositorySelectionError("legacy_writes_not_frozen")
        if (
            self._access == "write"
            and self._domain not in policy.postgres_writes_open_domains
        ):
            raise RepositorySelectionError("postgres_writes_not_open")
        if self._postgres_repository is None:
            raise RepositorySelectionError("postgres_repository_unavailable")
        return self._postgres_repository
