# -*- coding: utf-8 -*-
"""Task 12.3：切换门与唯一读写路径契约。"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from qwenpaw.persistence.repository_provider import (
    CutoverDomain,
    CutoverPolicy,
    MigrationState,
    RepositoryProvider,
    RepositorySelectionError,
)


@dataclass
class RecordingRepository:
    rows: list[dict]
    reads: int = 0
    writes: list[dict] = field(default_factory=list)

    async def list_rows(self) -> list[dict]:
        self.reads += 1
        return self.rows

    async def append(self, row: dict) -> None:
        self.writes.append(row)


def _settings(mode: str):
    return type("Settings", (), {"storage_mode": mode})()


def _policy(domain: CutoverDomain, *, writes_open: bool) -> CutoverPolicy:
    selected = frozenset({domain})
    return CutoverPolicy(
        validated_domains=selected,
        legacy_writes_frozen_domains=selected,
        postgres_writes_open_domains=selected if writes_open else frozenset(),
        reverse_migrated_domains=frozenset(),
    )


async def _ready() -> MigrationState:
    return MigrationState(
        current_revision="0018_automation_authorization",
        expected_revision="0018_automation_authorization",
        ready=True,
        error_code=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", list(CutoverDomain))
async def test_validated_domain_reads_equivalent_rows_from_only_postgres(
    domain,
) -> None:
    fixture = [{"id": "a", "order": 1}, {"id": "b", "order": 2}]
    legacy = RecordingRepository(rows=list(fixture))
    postgres = RecordingRepository(rows=list(fixture))
    provider = RepositoryProvider(
        domain=domain,
        access="read",
        legacy_repository=legacy,
        postgres_repository=postgres,
        settings_loader=lambda: _settings("postgres"),
        migration_state_reader=_ready,
        policy_loader=lambda: _policy(domain, writes_open=False),
    )

    selected = await provider.get_repository()
    assert await selected.list_rows() == fixture
    assert postgres.reads == 1
    assert legacy.reads == 0


@pytest.mark.asyncio
async def test_write_cutover_never_dual_writes() -> None:
    legacy = RecordingRepository(rows=[])
    postgres = RecordingRepository(rows=[])
    provider = RepositoryProvider(
        domain="messages",
        access="write",
        legacy_repository=legacy,
        postgres_repository=postgres,
        settings_loader=lambda: _settings("postgres"),
        migration_state_reader=_ready,
        policy_loader=lambda: _policy(CutoverDomain.MESSAGES, writes_open=True),
    )
    selected = await provider.get_repository()
    await selected.append({"event": "final"})
    assert postgres.writes == [{"event": "final"}]
    assert legacy.writes == []


@pytest.mark.asyncio
async def test_write_cannot_open_before_legacy_freeze() -> None:
    invalid = CutoverPolicy(
        validated_domains=frozenset({CutoverDomain.MESSAGES}),
        legacy_writes_frozen_domains=frozenset(),
        postgres_writes_open_domains=frozenset({CutoverDomain.MESSAGES}),
        reverse_migrated_domains=frozenset(),
    )
    provider = RepositoryProvider(
        domain="messages",
        access="write",
        legacy_repository=RecordingRepository(rows=[]),
        postgres_repository=RecordingRepository(rows=[]),
        settings_loader=lambda: _settings("postgres"),
        migration_state_reader=_ready,
        policy_loader=lambda: invalid,
    )
    with pytest.raises(RepositorySelectionError) as caught:
        await provider.get_repository()
    assert caught.value.error_code == "postgres_write_before_legacy_freeze"
