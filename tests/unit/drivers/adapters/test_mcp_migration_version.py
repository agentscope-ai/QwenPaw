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
from unittest.mock import patch

import pytest

import qwenpaw.config.config as cfg_config
from qwenpaw.config import utils as config_utils
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    Config,
    MCPClientConfig,
    MCPConfig,
)
from qwenpaw.config.runtime import RuntimeParameters
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


def _client() -> MCPClientConfig:
    return MCPClientConfig(
        name="wind",
        transport="streamable_http",
        url="https://mcp.example.com/api/",
    )


@pytest.fixture
def save_mcp(tmp_path, monkeypatch):
    """Give the migration a real saved profile in the card store's owner."""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_utils, "get_config_path", lambda: config_path)
    monkeypatch.setattr(config_utils, "_config_cache", None)
    monkeypatch.setattr(config_utils, "_config_mtime", None)
    monkeypatch.setattr(config_utils, "_agent_config_cache", {})
    config_utils.save_config(
        Config(
            agents=AgentsConfig(
                profiles={
                    "default": AgentProfileRef(
                        id="default",
                        workspace_dir=str(tmp_path),
                    ),
                },
            ),
        ),
    )

    def save(clients, version):
        cfg_config.save_agent_config(
            "default",
            AgentProfileConfig(
                id="default",
                name="Default",
                workspace_dir=str(tmp_path),
                mcp=MCPConfig(clients=clients, migration_version=version),
            ),
        )
        return tmp_path / "agent.json"

    return save


def test_mcp_config_defaults_migration_version_zero() -> None:
    assert MCPConfig().migration_version == 0
    # Round-trips through model_dump so it persists in agent.json.
    dumped = MCPConfig(migration_version=2).model_dump()
    assert dumped["migration_version"] == 2


@pytest.mark.asyncio
async def test_migration_skipped_when_already_at_current_version(
    tmp_path: Path,
    save_mcp,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    manager = DriverManager(tmp_path / "drivers", store)
    path = save_mcp({"wind": _client()}, CURRENT_MCP_MIGRATION_VERSION)
    before = path.stat().st_mtime_ns
    report = await migrate_legacy_mcp_if_needed("default", manager)

    # A legacy client whose card does not exist is NOT re-created (#6130).
    assert not card_path(
        tmp_path / "drivers",
        "wind",
        protocol="mcp",
    ).exists()
    assert report.migrated == []
    assert path.stat().st_mtime_ns == before


@pytest.mark.asyncio
async def test_migration_runs_and_persists_watermark_when_unmigrated(
    tmp_path: Path,
    save_mcp,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    manager = DriverManager(tmp_path / "drivers", store)
    save_mcp({"wind": _client()}, 0)
    profile = cfg_config.load_persisted_agent_config("default")
    parameters = RuntimeParameters.from_profile(
        profile,
        defaults={"approval_level": "OFF"},
    )
    alternate = DriverManager(tmp_path / "other" / "drivers", store)
    with parameters.scope():
        await migrate_legacy_mcp_if_needed("default", alternate)
        assert await alternate.card_store.list_paths() == []
        with patch.object(
            cfg_config,
            "save_agent_config",
            side_effect=OSError("save failed"),
        ):
            with pytest.raises(OSError, match="save failed"):
                await migrate_legacy_mcp_if_needed("default", manager)
        assert card_path(tmp_path / "drivers", "wind", protocol="mcp").exists()
        assert cfg_config.load_persisted_agent_config("default") == profile
        report = await migrate_legacy_mcp_if_needed("default", manager)

    assert [client.reason for client in report.skipped] == [
        "driver_card_exists",
    ]
    saved = cfg_config.load_persisted_agent_config("default")
    assert saved.mcp.migration_version == CURRENT_MCP_MIGRATION_VERSION
    assert saved.approval_level == profile.approval_level


@pytest.mark.asyncio
async def test_deleted_card_not_resurrected_after_watermark(
    tmp_path: Path,
    save_mcp,
) -> None:
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    manager = DriverManager(tmp_path / "drivers", store)
    path = save_mcp({"wind": _client()}, 0)

    # First boot: migrate -> card created, watermark bumped once.
    await migrate_legacy_mcp_if_needed("default", manager)
    target = card_path(tmp_path / "drivers", "wind", protocol="mcp")
    assert target.exists()
    migrated = path.stat().st_mtime_ns

    # Console delete: card removed, legacy mcp.clients entry left intact.
    delete_card(target)
    assert not target.exists()
    assert (
        "wind" in cfg_config.load_persisted_agent_config("default").mcp.clients
    )

    # Restart: migration sees the watermark and does NOT recreate the card,
    # and performs no further persistence (steady state is write-free).
    report = await migrate_legacy_mcp_if_needed("default", manager)
    assert not target.exists()
    assert report.migrated == []
    assert path.stat().st_mtime_ns == migrated


@pytest.mark.asyncio
async def test_migration_folds_env_ref_upgrade_step(
    tmp_path: Path,
    save_mcp,
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
    save_mcp({}, 1)
    await migrate_legacy_mcp_if_needed("default", manager)

    card = load_card(card_path(cards_dir, "wind", protocol="mcp"))
    assert card.endpoint["headers"]["Authorization"] == {
        "source": "credential",
        "credential": "env_api_key",
        "field": "value",
        "format": "Bearer {value}",
    }
    saved = cfg_config.load_persisted_agent_config("default")
    assert saved.mcp.migration_version == CURRENT_MCP_MIGRATION_VERSION
