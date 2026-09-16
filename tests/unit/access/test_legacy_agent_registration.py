# -*- coding: utf-8 -*-
"""旧智能体治理登记的回归测试。"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from qwenpaw.access.agent_repository import LegacyAgentRecord
from qwenpaw.access.legacy_agent_registration import (
    synchronize_legacy_agent_governance,
)


class RecordingRepository:
    def __init__(self, first_admin_id: UUID | None, registered: set[str]) -> None:
        self.first_admin_id = first_admin_id
        self.registered = set(registered)
        self.registered_owners: list[tuple[LegacyAgentRecord, UUID]] = []

    async def get_first_admin_id(self) -> UUID | None:
        return self.first_admin_id

    async def list_registered_keys(self, agent_keys: list[str]) -> set[str]:
        return self.registered.intersection(agent_keys)

    async def register_owner(
        self,
        *,
        agent: LegacyAgentRecord,
        owner_user_id: UUID,
    ) -> None:
        self.registered.add(agent.key)
        self.registered_owners.append((agent, owner_user_id))


def _config():
    return SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "default": SimpleNamespace(
                    workspace_dir="workspaces/default",
                    enabled=True,
                ),
                "member-agent": SimpleNamespace(
                    workspace_dir="workspaces/member-agent",
                    enabled=True,
                ),
                "disabled-agent": SimpleNamespace(
                    workspace_dir="workspaces/disabled-agent",
                    enabled=False,
                ),
            }
        )
    )


def _load_profile(agent_id: str):
    return SimpleNamespace(
        name=f"Name {agent_id}",
        description=f"Description {agent_id}",
    )


@pytest.mark.asyncio
async def test_registers_only_unregistered_legacy_agents_to_first_admin() -> None:
    first_admin_id = uuid4()
    repository = RecordingRepository(first_admin_id, {"member-agent"})

    count = await synchronize_legacy_agent_governance(
        config=_config(),
        repository=repository,
        profile_loader=_load_profile,
    )

    assert count == 2
    assert [item[0].key for item in repository.registered_owners] == [
        "default",
        "disabled-agent",
    ]
    assert {item[0].key: item[0].status for item in repository.registered_owners} == {
        "default": "active",
        "disabled-agent": "disabled",
    }
    assert {item[1] for item in repository.registered_owners} == {first_admin_id}


@pytest.mark.asyncio
async def test_synchronization_is_idempotent() -> None:
    repository = RecordingRepository(uuid4(), set())

    first_count = await synchronize_legacy_agent_governance(
        config=_config(),
        repository=repository,
        profile_loader=_load_profile,
    )
    second_count = await synchronize_legacy_agent_governance(
        config=_config(),
        repository=repository,
        profile_loader=_load_profile,
    )

    assert first_count == 3
    assert second_count == 0
    assert len(repository.registered_owners) == 3


@pytest.mark.asyncio
async def test_skips_registration_when_no_active_admin_exists() -> None:
    repository = RecordingRepository(None, set())

    count = await synchronize_legacy_agent_governance(
        config=_config(),
        repository=repository,
        profile_loader=_load_profile,
    )

    assert count == 0
    assert repository.registered_owners == []
