# -*- coding: utf-8 -*-
"""领域仓库选择器必须失败关闭且只返回一条读写路径。"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager

import pytest


def _module():
    return importlib.import_module("qwenpaw.persistence.repository_provider")


def _settings(storage_mode: str):
    class Settings:
        pass

    settings = Settings()
    settings.storage_mode = storage_mode
    return settings


def _policy(*, validated=(), frozen=(), writes=(), reversed_domains=()):
    module = _module()
    convert = lambda values: frozenset(module.CutoverDomain(value) for value in values)
    return module.CutoverPolicy(
        validated_domains=convert(validated),
        legacy_writes_frozen_domains=convert(frozen),
        postgres_writes_open_domains=convert(writes),
        reverse_migrated_domains=convert(reversed_domains),
    )


async def _ready():
    module = _module()
    return module.MigrationState(
        current_revision=module.EXPECTED_SCHEMA_REVISION,
        expected_revision=module.EXPECTED_SCHEMA_REVISION,
        ready=True,
        error_code=None,
    )


def test_expected_revision_tracks_current_alembic_head() -> None:
    assert _module().EXPECTED_SCHEMA_REVISION == "0020_agent_personal_library"


@pytest.mark.asyncio
async def test_legacy_mode_returns_only_legacy_repository() -> None:
    module = _module()
    legacy = object()
    provider = module.RepositoryProvider(
        domain="agents",
        access="read",
        legacy_repository=legacy,
        postgres_repository=object(),
        settings_loader=lambda: _settings("legacy"),
        migration_state_reader=pytest.fail,
        policy_loader=lambda: _policy(),
    )
    assert await provider.get_repository() is legacy


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "access", "error_code"),
    [
        (_policy(), "read", "domain_migration_not_validated"),
        (_policy(validated=("agents",)), "read", "legacy_writes_not_frozen"),
        (
            _policy(validated=("agents",), frozen=("agents",)),
            "write",
            "postgres_writes_not_open",
        ),
    ],
)
async def test_incomplete_domain_gate_blocks_postgres(
    policy, access, error_code
) -> None:
    module = _module()
    provider = module.RepositoryProvider(
        domain="agents",
        access=access,
        legacy_repository=object(),
        postgres_repository=object(),
        settings_loader=lambda: _settings("postgres"),
        migration_state_reader=_ready,
        policy_loader=lambda: policy,
    )
    with pytest.raises(module.RepositorySelectionError) as caught:
        await provider.get_repository()
    assert caught.value.error_code == error_code


@pytest.mark.asyncio
@pytest.mark.parametrize("access", ["read", "write"])
async def test_complete_domain_gate_returns_exact_postgres_repository(access) -> None:
    module = _module()
    postgres = object()
    provider = module.RepositoryProvider(
        domain="messages",
        access=access,
        legacy_repository=object(),
        postgres_repository=postgres,
        settings_loader=lambda: _settings("postgres"),
        migration_state_reader=_ready,
        policy_loader=lambda: _policy(
            validated=("messages",),
            frozen=("messages",),
            writes=("messages",),
        ),
    )
    assert await provider.get_repository() is postgres


@pytest.mark.asyncio
async def test_rollback_after_postgres_write_requires_reverse_migration() -> None:
    module = _module()
    base = dict(validated=("inbox",), frozen=("inbox",), writes=("inbox",))
    blocked = module.RepositoryProvider(
        domain="inbox",
        access="read",
        legacy_repository=object(),
        settings_loader=lambda: _settings("legacy"),
        policy_loader=lambda: _policy(**base),
    )
    with pytest.raises(module.RepositorySelectionError) as caught:
        await blocked.get_repository()
    assert caught.value.error_code == "rollback_requires_reverse_migration"

    legacy = object()
    allowed = module.RepositoryProvider(
        domain="inbox",
        access="read",
        legacy_repository=legacy,
        settings_loader=lambda: _settings("legacy"),
        policy_loader=lambda: _policy(**base, reversed_domains=("inbox",)),
    )
    assert await allowed.get_repository() is legacy


def test_policy_loader_rejects_unknown_and_out_of_order_domains(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv(module.CUTOVER_VALIDATED_ENV, "agents")
    monkeypatch.setenv(module.CUTOVER_LEGACY_FROZEN_ENV, "agents,unknown")
    with pytest.raises(module.RepositorySelectionError) as caught:
        module.load_cutover_policy()
    assert caught.value.error_code == "unknown_cutover_domain"

    monkeypatch.setenv(module.CUTOVER_LEGACY_FROZEN_ENV, "agents")
    monkeypatch.setenv(module.CUTOVER_POSTGRES_WRITES_ENV, "agents,inbox")
    with pytest.raises(module.RepositorySelectionError) as caught:
        module.load_cutover_policy()
    assert caught.value.error_code == "postgres_write_before_legacy_freeze"


def test_provider_rejects_unknown_access_type() -> None:
    module = _module()
    with pytest.raises(module.RepositorySelectionError) as caught:
        module.RepositoryProvider(
            domain="agents",
            access="delete",
            legacy_repository=object(),
        )
    assert caught.value.error_code == "invalid_repository_access"


@pytest.mark.asyncio
async def test_multi_user_startup_requires_every_domain(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "load_database_settings",
        lambda: type("Settings", (), {"multi_user_enabled": True})(),
    )
    monkeypatch.setattr(module, "read_migration_state", _ready)
    monkeypatch.setattr(
        module,
        "load_cutover_policy",
        lambda: _policy(
            validated=("agents",),
            frozen=("agents",),
            writes=("agents",),
        ),
    )
    with pytest.raises(module.RepositorySelectionError) as caught:
        await module.validate_runtime_cutover()
    assert caught.value.error_code == "domain_migration_not_validated"


@pytest.mark.asyncio
async def test_multi_user_startup_accepts_complete_cutover(monkeypatch) -> None:
    module = _module()
    all_domains = tuple(domain.value for domain in module.ALL_CUTOVER_DOMAINS)
    monkeypatch.setattr(
        module,
        "load_database_settings",
        lambda: type("Settings", (), {"multi_user_enabled": True})(),
    )
    monkeypatch.setattr(module, "read_migration_state", _ready)
    monkeypatch.setattr(
        module,
        "load_cutover_policy",
        lambda: _policy(
            validated=all_domains,
            frozen=all_domains,
            writes=all_domains,
        ),
    )
    await module.validate_runtime_cutover()


@pytest.mark.asyncio
async def test_migration_state_reader_is_read_only_and_schema_scoped(
    monkeypatch,
) -> None:
    module = _module()
    statements = []

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class Session:
        async def execute(self, statement, parameters=None):
            statements.append((str(statement), parameters))
            return Result(
                "alembic_version"
                if len(statements) == 1
                else module.EXPECTED_SCHEMA_REVISION
            )

    @asynccontextmanager
    async def session_factory():
        yield Session()

    monkeypatch.setattr(module, "database_session", session_factory)
    monkeypatch.setenv("QWENPAW_DATABASE_SCHEMA", "qwenpaw")
    state = await module.read_migration_state()

    assert state.ready is True
    assert len(statements) == 2
    assert statements[0][1] == {"qualified_table": "qwenpaw.alembic_version"}
    assert all("INSERT" not in sql and "UPDATE" not in sql for sql, _ in statements)
