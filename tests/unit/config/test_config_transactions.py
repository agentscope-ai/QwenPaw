# -*- coding: utf-8 -*-
"""Tests for atomic root and per-agent configuration transactions."""

# Pytest fixtures intentionally provide setup-only arguments to tests.
# pylint: disable=redefined-outer-name,unused-argument

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from qwenpaw.config import utils as config_utils
from qwenpaw.config.config import (
    AGENT_MAIL_CREDENTIAL_REF,
    AgentMailConfig,
    AgentMailCredential,
    AgentProfileConfig,
    AgentProfileRef,
    AgentsConfig,
    Config,
    load_agent_config,
    mutate_agent_config,
    save_agent_config,
)
from qwenpaw.drivers.credentials.store import AsyncCredentialStore


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch):
    """Point config persistence and both caches at one temporary tree."""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_utils, "get_config_path", lambda: config_path)
    monkeypatch.setattr(config_utils, "_config_cache", None)
    monkeypatch.setattr(config_utils, "_config_mtime", None)
    monkeypatch.setattr(config_utils, "_agent_config_cache", {})
    return config_path


def test_load_config_returns_detached_cache_copy(isolated_config):
    """Mutating a loaded object without saving cannot poison the cache."""
    config_utils.save_config(Config(user_timezone="UTC"))

    loaded = config_utils.load_config()
    loaded.user_timezone = "Asia/Shanghai"

    assert config_utils.load_config().user_timezone == "UTC"


def test_powercontext_installation_id_is_generated_once_and_persisted(
    isolated_config,
):
    first = config_utils.get_or_create_powercontext_installation_id()
    second = config_utils.get_or_create_powercontext_installation_id()

    assert first == second
    assert len(first) == 32
    assert config_utils.load_config().powercontext_installation_id == first


def test_powercontext_existing_installation_id_does_not_require_write(
    isolated_config,
    monkeypatch,
):
    """A persisted ID must remain usable when root config is read-only."""
    installation_id = "a" * 32
    config_utils.save_config(
        Config(powercontext_installation_id=installation_id),
    )
    save_config = Mock(side_effect=OSError("read-only config"))
    monkeypatch.setattr(config_utils, "save_config", save_config)

    assert (
        config_utils.get_or_create_powercontext_installation_id()
        == installation_id
    )
    save_config.assert_not_called()


def test_powercontext_installation_id_rejects_invalid_persisted_value():
    with pytest.raises(ValidationError, match="installation_id"):
        Config(powercontext_installation_id="not-an-installation-id")


def test_concurrent_root_mutations_retain_both_changes(isolated_config):
    """Root transactions serialize load, mutate, persist, and publish."""
    config_utils.save_config(Config())

    def set_timezone(config: Config) -> None:
        config.user_timezone = "Asia/Shanghai"

    def set_audio_mode(config: Config) -> None:
        config.agents.audio_mode = "native"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(config_utils.mutate_config, set_timezone),
            executor.submit(config_utils.mutate_config, set_audio_mode),
        ]
        for future in futures:
            future.result()

    reloaded = config_utils.load_config()
    assert reloaded.user_timezone == "Asia/Shanghai"
    assert reloaded.agents.audio_mode == "native"


def test_failed_root_write_preserves_disk_and_cache(isolated_config):
    """A failed atomic replacement must not publish its candidate."""
    config_utils.save_config(Config(user_timezone="UTC"))
    before = isolated_config.read_text(encoding="utf-8")

    def set_timezone(config: Config) -> None:
        config.user_timezone = "Asia/Shanghai"

    with patch.object(
        config_utils,
        "write_json_atomic",
        side_effect=OSError("write failed"),
    ):
        with pytest.raises(OSError, match="write failed"):
            config_utils.mutate_config(set_timezone)

    assert isolated_config.read_text(encoding="utf-8") == before
    assert config_utils.load_config().user_timezone == "UTC"


@pytest.fixture
def isolated_agent(isolated_config, tmp_path: Path):
    """Create one root profile and persisted agent configuration."""
    workspace = tmp_path / "workspaces" / "agent"
    workspace.mkdir(parents=True)
    root = Config(
        agents=AgentsConfig(
            profiles={
                "agent": AgentProfileRef(
                    id="agent",
                    workspace_dir=str(workspace),
                ),
            },
        ),
    )
    config_utils.save_config(root)
    save_agent_config(
        "agent",
        AgentProfileConfig(
            id="agent",
            name="Agent",
            description="original",
        ),
    )
    return workspace / "agent.json"


def test_load_agent_config_returns_detached_cache_copy(isolated_agent):
    """Agent cache state is not exposed as a mutable canonical object."""
    loaded = load_agent_config("agent")
    loaded.description = "unsaved"

    assert load_agent_config("agent").description == "original"


def test_concurrent_agent_mutations_retain_both_changes(isolated_agent):
    """Agent transactions preserve independent concurrent field updates."""

    def set_description(config: AgentProfileConfig) -> None:
        config.description = "updated"

    def set_language(config: AgentProfileConfig) -> None:
        config.language = "zh"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                mutate_agent_config,
                "agent",
                set_description,
            ),
            executor.submit(
                mutate_agent_config,
                "agent",
                set_language,
            ),
        ]
        for future in futures:
            future.result()

    reloaded = load_agent_config("agent")
    assert reloaded.description == "updated"
    assert reloaded.language == "zh"


def test_failed_agent_write_preserves_disk_and_cache(isolated_agent):
    """Agent write failure leaves its prior disk and cache snapshots intact."""
    before = json.loads(isolated_agent.read_text(encoding="utf-8"))

    def set_description(config: AgentProfileConfig) -> None:
        config.description = "updated"

    with patch(
        "qwenpaw.config.config.write_json_atomic",
        side_effect=OSError("write failed"),
    ):
        with pytest.raises(OSError, match="write failed"):
            mutate_agent_config("agent", set_description)

    after = json.loads(isolated_agent.read_text(encoding="utf-8"))
    assert after == before
    assert load_agent_config("agent").description == "original"


def _mail_config(auth_code: str = "a" * 16) -> AgentMailConfig:
    return AgentMailConfig(
        credential=AgentMailCredential(
            name="tester",
            domain="163.com",
            auth_code=auth_code,
            password="mail-password",
            phone_number="13800000000",
        ),
    )


def test_agent_mail_secrets_round_trip_outside_agent_json(isolated_agent):
    workspace = isolated_agent.parent
    config = load_agent_config("agent")
    config.mail = _mail_config()

    save_agent_config("agent", config)

    persisted = isolated_agent.read_text(encoding="utf-8")
    assert "a" * 16 not in persisted
    assert "mail-password" not in persisted
    assert "13800000000" not in persisted
    credential_text = (workspace / "credentials.yaml").read_text("utf-8")
    assert "a" * 16 not in credential_text
    assert "mail-password" not in credential_text
    assert "13800000000" not in credential_text
    assert "ENC:" in credential_text
    # pylint: disable=protected-access
    config_utils._agent_config_cache.clear()
    reloaded = load_agent_config("agent")
    assert reloaded.mail is not None
    assert reloaded.mail.credential.auth_code == "a" * 16
    assert reloaded.mail.credential.password == "mail-password"
    assert reloaded.mail.credential.phone_number == "13800000000"


def test_load_migrates_legacy_plaintext_mail_credentials(isolated_agent):
    workspace = isolated_agent.parent
    legacy = json.loads(isolated_agent.read_text(encoding="utf-8"))
    legacy["mail"] = _mail_config().model_dump()
    # Secret fields are write-only now, so emulate a file written by the old
    # schema explicitly.
    legacy["mail"]["credential"].update(
        {
            "auth_code": "b" * 16,
            "password": "legacy-password",
            "phone_number": "13900000000",
        },
    )
    isolated_agent.write_text(json.dumps(legacy), encoding="utf-8")
    # pylint: disable=protected-access
    config_utils._agent_config_cache.clear()

    loaded = load_agent_config("agent")

    sanitized = isolated_agent.read_text(encoding="utf-8")
    assert "b" * 16 not in sanitized
    assert "legacy-password" not in sanitized
    assert "13900000000" not in sanitized
    assert loaded.mail is not None
    assert loaded.mail.credential.auth_code == "b" * 16
    record = AsyncCredentialStore(
        workspace / "credentials.yaml",
    ).get_sync(AGENT_MAIL_CREDENTIAL_REF)
    assert record.secrets["password"] == "legacy-password"


def test_failed_agent_write_restores_previous_mail_credential(isolated_agent):
    workspace = isolated_agent.parent
    config = load_agent_config("agent")
    config.mail = _mail_config("a" * 16)
    save_agent_config("agent", config)

    updated = load_agent_config("agent")
    assert updated.mail is not None
    updated.mail.credential.auth_code = "b" * 16
    with patch(
        "qwenpaw.config.config.write_json_atomic",
        side_effect=OSError("write failed"),
    ):
        with pytest.raises(OSError, match="write failed"):
            save_agent_config("agent", updated)

    record = AsyncCredentialStore(
        workspace / "credentials.yaml",
    ).get_sync(AGENT_MAIL_CREDENTIAL_REF)
    assert record.secrets["auth_code"] == "a" * 16
    cached = load_agent_config("agent")
    assert cached.mail is not None
    assert cached.mail.credential.auth_code == "a" * 16
