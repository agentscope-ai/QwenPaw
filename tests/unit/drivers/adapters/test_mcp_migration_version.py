# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Versioned, one-shot MCP migration watermark (#6130).

Before this change the startup migration used "does the DriverCard file
exist?" as its "already migrated?" judgement.  Deleting a migrated client
(Console) removed the card but left the legacy ``agent.json -> mcp.clients``
entry, so the next start re-derived the card — the deleted client reappeared.

The fix moves the judgement onto an explicit, persisted schema watermark
(``MCPConfig.migration_version``) that is decoupled from card existence:

* once a workspace has reached ``CURRENT_MCP_MIGRATION_VERSION`` the migration
  is skipped entirely, so a deleted card is never resurrected;
* the ``env:`` self-heal upgrade (#6029) is folded in as a one-shot v1->v2
  step instead of being re-scanned on every start.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

import qwenpaw.config.config as cfg_config
from qwenpaw.config.config import MCPConfig
from qwenpaw.drivers.adapters.mcp_legacy_config import (
    CURRENT_MCP_MIGRATION_VERSION,
    migrate_legacy_mcp_if_needed,
)
from qwenpaw.drivers.contracts import CredentialRef, DriverCard, PolicyRule
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.types import CredentialRecord
from qwenpaw.drivers.manager import DriverManager
from qwenpaw.drivers.storage import (
    card_path,
    delete_card,
    dump_card,
    load_card,
)


def _client() -> SimpleNamespace:
    """A minimal legacy MCP client config (read via getattr by migration)."""
    return SimpleNamespace(
        transport="streamable_http",
        url="https://mcp.example.com/api/",
        headers={},
    )


def _mcp(clients: dict, version: int) -> SimpleNamespace:
    """Fake MCPConfig exposing .clients and a writable .migration_version."""
    return SimpleNamespace(clients=dict(clients), migration_version=version)


def _ws(mcp: SimpleNamespace, agent_id: str = "default") -> SimpleNamespace:
    """Fake Workspace exposing ._config.mcp and .agent_id for migration."""
    return SimpleNamespace(_config=SimpleNamespace(mcp=mcp), agent_id=agent_id)


@pytest.fixture
def captured_saves(monkeypatch: pytest.MonkeyPatch) -> list:
    """Capture save_agent_config calls without touching global config."""
    saves: list = []
    monkeypatch.setattr(
        cfg_config,
        "save_agent_config",
        lambda agent_id, config: saves.append((agent_id, config)),
    )
    return saves


def test_mcp_config_defaults_migration_version_zero() -> None:
    assert MCPConfig().migration_version == 0
    # Round-trips through model_dump so it persists in agent.json.
    dumped = MCPConfig(migration_version=2).model_dump()
    assert dumped["migration_version"] == 2


@pytest.mark.asyncio
async def test_migration_skipped_when_already_at_current_version(
    tmp_path: Path,
    captured_saves: list,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    manager = DriverManager(tmp_path / "drivers", store)
    mcp = _mcp({"wind": _client()}, version=CURRENT_MCP_MIGRATION_VERSION)

    report = await migrate_legacy_mcp_if_needed(_ws(mcp), manager)

    # A legacy client whose card does not exist is NOT re-created (#6130).
    assert not card_path(
        tmp_path / "drivers",
        "wind",
        protocol="mcp",
    ).exists()
    assert report.migrated == []
    assert captured_saves == []  # nothing persisted on the skip path


@pytest.mark.asyncio
async def test_migration_runs_and_persists_watermark_when_unmigrated(
    tmp_path: Path,
    captured_saves: list,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    manager = DriverManager(tmp_path / "drivers", store)
    mcp = _mcp({"wind": _client()}, version=0)

    await migrate_legacy_mcp_if_needed(_ws(mcp), manager)

    assert card_path(tmp_path / "drivers", "wind", protocol="mcp").exists()
    assert mcp.migration_version == CURRENT_MCP_MIGRATION_VERSION
    assert captured_saves and captured_saves[0][0] == "default"


@pytest.mark.asyncio
async def test_deleted_card_not_resurrected_after_watermark(
    tmp_path: Path,
    captured_saves: list,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    manager = DriverManager(tmp_path / "drivers", store)
    mcp = _mcp({"wind": _client()}, version=0)
    ws = _ws(mcp)

    # First boot: migrate -> card created, watermark bumped once.
    await migrate_legacy_mcp_if_needed(ws, manager)
    target = card_path(tmp_path / "drivers", "wind", protocol="mcp")
    assert target.exists()

    # Console delete: card removed, legacy mcp.clients entry left intact.
    delete_card(target)
    assert not target.exists()
    assert "wind" in mcp.clients

    # Restart: migration sees the watermark and does NOT recreate the card,
    # and performs no further persistence (steady state is write-free).
    report = await migrate_legacy_mcp_if_needed(ws, manager)
    assert not target.exists()
    assert report.migrated == []
    assert len(captured_saves) == 1


@pytest.mark.asyncio
async def test_migration_folds_env_ref_upgrade_step(
    tmp_path: Path,
    captured_saves: list,
) -> None:
    # A card already migrated (v1) but still holding a ${VAR} literal.
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    await store.put(
        CredentialRecord(
            ref="mcp/wind",
            kind="static",
            secrets={"authorization": "Bearer ${API_KEY}"},
        ),
    )
    cards_dir = tmp_path / "drivers"
    dump_card(
        DriverCard(
            name="wind",
            protocol="mcp",
            endpoint={
                "transport": "streamable_http",
                "url": "https://mcp.example.com/api/",
                "headers": {
                    "Authorization": {
                        "source": "credential",
                        "credential": "static",
                        "field": "authorization",
                    },
                },
            },
            credentials={"static": CredentialRef("static", "mcp/wind")},
            policy=[PolicyRule(subject="*", effect="allow")],
        ),
        card_path(cards_dir, "wind", protocol="mcp"),
    )
    manager = DriverManager(cards_dir, store)
    # version=1 -> only the v1->v2 env: ref upgrade step should run.
    mcp = _mcp({}, version=1)

    await migrate_legacy_mcp_if_needed(_ws(mcp), manager)

    card = load_card(card_path(cards_dir, "wind", protocol="mcp"))
    assert card.endpoint["headers"]["Authorization"] == {
        "source": "credential",
        "credential": "env_api_key",
        "field": "value",
        "format": "Bearer {value}",
    }
    assert mcp.migration_version == CURRENT_MCP_MIGRATION_VERSION
    assert len(captured_saves) == 1
