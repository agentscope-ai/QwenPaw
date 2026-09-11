# -*- coding: utf-8 -*-
"""Unit tests for _validate_mail_config push-rule validation."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from fastapi import HTTPException

from qwenpaw.app.routers.agents import (
    CopyAgentRequest,
    CreateAgentRequest,
    _build_copied_agent_config,
    _build_qwenpawmail_env,
    _ensure_mail_triage_file,
    _generate_qwenpawmail_driver_card,
    _resolve_qwenpawmail_command,
    _sync_qwenpawmail_driver_card,
    _validate_mail_config,
    copy_agent,
    create_agent,
    update_agent,
)
from qwenpaw.config.config import (
    AGENT_MAIL_CREDENTIAL_REF,
    AgentMailConfig,
    AgentMailCredential,
    AgentMailPushConfig,
    AgentMailPushRule,
    AgentProfileConfig,
)
from qwenpaw.drivers.credentials.store import AsyncCredentialStore
from qwenpaw.drivers.credentials.bindings import (
    resolve_binding,
    resolve_credentials,
)
from qwenpaw.drivers.credentials.providers import build_provider
from qwenpaw.drivers.contracts import DriverPolicy, PolicyRule, PolicyTarget
from qwenpaw.drivers.storage import dump_card, load_card


def _valid_mail(push: AgentMailPushConfig | None = None) -> AgentMailConfig:
    return AgentMailConfig(
        is_new_account=False,
        credential=AgentMailCredential(
            name="tester",
            domain="163.com",
            auth_code="a" * 16,
            password="",
            phone_number="",
        ),
        push=push,
    )


def test_valid_config_without_push_passes():
    _validate_mail_config(_valid_mail())


def test_valid_push_config_passes():
    push = AgentMailPushConfig(
        mode="rules_then_agent",
        rules=[
            AgentMailPushRule(
                field="subject",
                contains="invoice",
                action="move",
                param="Archive",
            ),
            AgentMailPushRule(
                field="from",
                contains="mom",
                action="wake_agent",
            ),
        ],
    )
    _validate_mail_config(_valid_mail(push))


def test_move_rule_without_param_rejected():
    push = AgentMailPushConfig(
        mode="rules_only",
        rules=[
            AgentMailPushRule(
                field="subject",
                contains="x",
                action="move",
                param="  ",
            ),
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_mail_config(_valid_mail(push))
    assert exc_info.value.status_code == 400
    assert "move" in exc_info.value.detail


def test_too_many_rules_rejected():
    push = AgentMailPushConfig(
        mode="rules_only",
        rules=[
            AgentMailPushRule(field="from", contains=f"user{i}")
            for i in range(51)
        ],
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_mail_config(_valid_mail(push))
    assert exc_info.value.status_code == 400
    assert "50" in exc_info.value.detail


def test_unsupported_domain_still_rejected():
    mail = _valid_mail()
    mail.credential.domain = "unknown.example"
    with pytest.raises(HTTPException) as exc_info:
        _validate_mail_config(mail)
    assert exc_info.value.status_code == 400


def test_new_whitelisted_domains_pass():
    for domain in (
        "sina.com",
        "sina.cn",
        "aliyun.com",
        "gmail.com",
        "exmail.qq.com",
        "qiye.aliyun.com",
        "qiye.163.com",
    ):
        mail = _valid_mail()
        mail.credential.domain = domain
        _validate_mail_config(mail)


def test_enterprise_provider_allows_custom_domain():
    mail = _valid_mail()
    mail.credential.provider = "tencent_exmail"
    mail.credential.domain = "mycompany.com"
    _validate_mail_config(mail)


def test_enterprise_provider_rejects_malformed_domain():
    for bad_domain in (
        "",
        "nodot",
        "bad domain.com",
        "foo..com",
        "-bad.com",
        "evil.com;rm",
    ):
        mail = _valid_mail()
        mail.credential.provider = "aliyun_qiye"
        mail.credential.domain = bad_domain
        with pytest.raises(HTTPException) as exc_info:
            _validate_mail_config(mail)
        assert exc_info.value.status_code == 400


def test_enterprise_provider_rejects_whitelisted_domain():
    """Well-known domains must not carry an enterprise provider."""
    for domain in ("163.com", "gmail.com", "exmail.qq.com"):
        mail = _valid_mail()
        mail.credential.provider = "tencent_exmail"
        mail.credential.domain = domain
        with pytest.raises(HTTPException) as exc_info:
            _validate_mail_config(mail)
        assert exc_info.value.status_code == 400
        assert "well-known domain" in exc_info.value.detail


def test_invalid_provider_rejected():
    mail = _valid_mail()
    mail.credential.provider = "unknown_provider"
    with pytest.raises(HTTPException) as exc_info:
        _validate_mail_config(mail)
    assert exc_info.value.status_code == 400
    assert "provider" in exc_info.value.detail


def test_microsoft_domains_rejected_with_oauth2_reason():
    for domain in (
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "office365.com",
    ):
        mail = _valid_mail()
        mail.credential.domain = domain
        with pytest.raises(HTTPException) as exc_info:
            _validate_mail_config(mail)
        assert exc_info.value.status_code == 400
        assert "OAuth2" in exc_info.value.detail


def test_env_injects_hosts_for_enterprise_provider(tmp_path):
    mail = _valid_mail()
    mail.credential.provider = "netease_qiye"
    mail.credential.domain = "mycompany.com"
    env = _build_qwenpawmail_env(mail, tmp_path)
    assert env["QWENPAWMAIL_EMAIL"] == "tester@mycompany.com"
    assert env["QWENPAWMAIL_AUTH_CODE"] == {
        "source": "credential",
        "credential": "mail",
        "field": "auth_code",
    }
    assert env["QWENPAWMAIL_IMAP_HOST"] == "imap.qiye.163.com"
    assert env["QWENPAWMAIL_IMAP_PORT"] == "993"
    assert env["QWENPAWMAIL_SMTP_HOST"] == "smtp.qiye.163.com"
    # NetEase enterprise SMTP SSL port is 994, not 465.
    assert env["QWENPAWMAIL_SMTP_PORT"] == "994"


def test_env_injects_tencent_exmail_hosts(tmp_path):
    mail = _valid_mail()
    mail.credential.provider = "tencent_exmail"
    mail.credential.domain = "mycompany.com"
    env = _build_qwenpawmail_env(mail, tmp_path)
    assert env["QWENPAWMAIL_IMAP_HOST"] == "imap.exmail.qq.com"
    assert env["QWENPAWMAIL_IMAP_PORT"] == "993"
    assert env["QWENPAWMAIL_SMTP_HOST"] == "smtp.exmail.qq.com"
    assert env["QWENPAWMAIL_SMTP_PORT"] == "465"


def test_env_without_provider_has_no_host_overrides(tmp_path):
    env = _build_qwenpawmail_env(_valid_mail(), tmp_path)
    assert env["QWENPAWMAIL_EMAIL"] == "tester@163.com"
    assert "QWENPAWMAIL_IMAP_HOST" not in env
    assert "QWENPAWMAIL_IMAP_PORT" not in env
    assert "QWENPAWMAIL_SMTP_HOST" not in env
    assert "QWENPAWMAIL_SMTP_PORT" not in env


def test_env_injects_workspace_and_state_dirs(tmp_path):
    env = _build_qwenpawmail_env(_valid_mail(), tmp_path)
    assert env["QWENPAWMAIL_STATE_DIR"] == str(tmp_path / "mail_state")
    assert env["QWENPAWMAIL_WORKSPACE_DIR"] == str(tmp_path)


def test_env_without_workspace_dir_has_no_dir_vars():
    env = _build_qwenpawmail_env(_valid_mail())
    assert "QWENPAWMAIL_STATE_DIR" not in env
    assert "QWENPAWMAIL_WORKSPACE_DIR" not in env


def test_create_agent_rejects_mail_for_third_party_backend():
    request = CreateAgentRequest(
        name="mailbot",
        backend="claude_code",
        mail=_valid_mail(),
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_agent(request=request, http_request=None))
    assert exc_info.value.status_code == 400
    assert "qwenpaw backend" in exc_info.value.detail


def test_create_mail_agent_driver_failure_is_not_committed(tmp_path):
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={},
            agent_order=[],
            language="en",
        ),
    )
    request = CreateAgentRequest(
        id="mail-create-failure",
        name="mailbot",
        workspace_dir=str(tmp_path),
        mail=_valid_mail(),
    )
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=config,
        ),
        patch(
            "qwenpaw.app.routers.agents._initialize_agent_workspace",
        ),
        patch(
            "qwenpaw.app.routers.agents._sync_qwenpawmail_driver_card",
            return_value=False,
        ),
        patch(
            "qwenpaw.app.routers.agents._persist_created_agent",
        ) as persist_agent,
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(create_agent(request=request, http_request=None))

    assert exc_info.value.status_code == 500
    assert config.agents.profiles == {}
    persist_agent.assert_not_called()


def test_copy_mail_agent_driver_failure_is_not_committed(
    tmp_path,
    monkeypatch,
):
    source_workspace = tmp_path / "source"
    source_workspace.mkdir()
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "source": SimpleNamespace(
                    workspace_dir=str(source_workspace),
                    enabled=True,
                ),
            },
            agent_order=["source"],
            language="en",
        ),
    )
    source_config = AgentProfileConfig(
        id="source",
        name="source",
        workspace_dir=str(source_workspace),
        backend="qwenpaw",
        mail=_valid_mail(),
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.agents.WORKING_DIR",
        tmp_path,
    )
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=source_config,
        ),
        patch(
            "qwenpaw.app.routers.agents._generate_unique_id",
            return_value="copy-failure",
        ),
        patch("qwenpaw.app.routers.agents._prepare_copied_workspace"),
        patch(
            "qwenpaw.app.routers.agents._sync_qwenpawmail_driver_card",
            return_value=False,
        ),
        patch(
            "qwenpaw.app.routers.agents._persist_created_agent",
        ) as persist_agent,
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                copy_agent(
                    agentId="source",
                    request=CopyAgentRequest(name="copy"),
                    http_request=None,
                ),
            )

    assert exc_info.value.status_code == 500
    assert set(config.agents.profiles) == {"source"}
    persist_agent.assert_not_called()


def _fake_global_config(agent_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        agents=SimpleNamespace(
            profiles={agent_id: SimpleNamespace(workspace_dir="/tmp/ws")},
        ),
    )


def test_update_agent_rejects_mail_when_existing_backend_third_party():
    # Request does not set backend explicitly: the effective backend
    # must fall back to the existing third-party config.
    body = AgentProfileConfig(id="a1", name="bot", mail=_valid_mail())
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=_fake_global_config("a1"),
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=SimpleNamespace(backend="claude_code"),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                update_agent(agentId="a1", agent_config=body, request=None),
            )
    assert exc_info.value.status_code == 400
    assert "qwenpaw backend" in exc_info.value.detail


def test_update_agent_rejects_mail_with_explicit_third_party_backend():
    body = AgentProfileConfig(
        id="a1",
        name="bot",
        backend="claude_code",
        mail=_valid_mail(),
    )
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=_fake_global_config("a1"),
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=SimpleNamespace(backend="qwenpaw"),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                update_agent(agentId="a1", agent_config=body, request=None),
            )
    assert exc_info.value.status_code == 400
    assert "qwenpaw backend" in exc_info.value.detail


def test_update_agent_lock_recheck_rejects_stale_backend_snapshot():
    """The in-lock re-check must catch a concurrent backend switch.

    The unlocked snapshot still reports the qwenpaw backend, but by the
    time the file lock is taken a concurrent request has persisted a
    third-party backend: the merged config must be rejected inside the
    lock instead of persisting the illegal backend+mail combination.
    """
    body = AgentProfileConfig(id="a1", name="bot", mail=_valid_mail())

    async def _fake_update_locked(agent_id, apply_update):
        stale = AgentProfileConfig(
            id=agent_id,
            name="bot",
            backend="claude_code",
        )
        apply_update(stale)

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=_fake_global_config("a1"),
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            return_value=SimpleNamespace(backend="qwenpaw"),
        ),
        patch(
            "qwenpaw.app.routers.agents.update_agent_config_async",
            new=_fake_update_locked,
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                update_agent(agentId="a1", agent_config=body, request=None),
            )
    assert exc_info.value.status_code == 400
    assert "qwenpaw backend" in exc_info.value.detail


# ── qwenpawmail MCP command resolution ──────────────────────────────


def test_resolve_qwenpawmail_command_env_override(monkeypatch):
    monkeypatch.setenv("QWENPAWMAIL_PYTHON", "/custom/bin/python")
    assert _resolve_qwenpawmail_command() == "/custom/bin/python"


def test_resolve_qwenpawmail_command_uses_current_env(monkeypatch):
    monkeypatch.delenv("QWENPAWMAIL_PYTHON", raising=False)
    with patch(
        "importlib.util.find_spec",
        return_value=object(),
    ):
        assert _resolve_qwenpawmail_command() == sys.executable


def test_resolve_qwenpawmail_command_falls_back_to_path(monkeypatch):
    monkeypatch.delenv("QWENPAWMAIL_PYTHON", raising=False)
    with patch(
        "importlib.util.find_spec",
        return_value=None,
    ):
        assert _resolve_qwenpawmail_command() == "python"


def test_driver_card_uses_resolved_command(tmp_path, monkeypatch):
    monkeypatch.setenv("QWENPAWMAIL_PYTHON", "/custom/bin/python")
    _generate_qwenpawmail_driver_card(tmp_path, _valid_mail())
    card_path = tmp_path / "drivers" / "mcp" / "qwenpawmail.yaml"
    card = yaml.safe_load(card_path.read_text(encoding="utf-8"))
    assert card["endpoint"]["command"] == "/custom/bin/python"
    assert card["endpoint"]["args"] == ["-m", "qwenpawmail_mcp"]
    # The old personal-machine interpreter path must never leak in.
    card_text = card_path.read_text(encoding="utf-8")
    assert "/Users/luohh/Documents/mcp" not in card_text
    assert "a" * 16 not in card_text
    assert card["credentials"]["mail"] == {
        "kind": "static",
        "ref": AGENT_MAIL_CREDENTIAL_REF,
    }
    assert card["policy"] == {"default_effect": "ask", "rules": []}
    credential_text = (tmp_path / "credentials.yaml").read_text("utf-8")
    assert "a" * 16 not in credential_text
    assert "ENC:" in credential_text


def test_driver_runtime_resolves_mail_secret_from_credential_store(tmp_path):
    assert _generate_qwenpawmail_driver_card(tmp_path, _valid_mail())
    card = load_card(tmp_path / "drivers" / "mcp" / "qwenpawmail.yaml")
    store = AsyncCredentialStore(tmp_path / "credentials.yaml")
    providers = {
        alias: build_provider(reference, store)
        for alias, reference in card.credentials.items()
    }

    resolved = asyncio.run(resolve_credentials(providers))
    env = resolve_binding(card.endpoint["env"], resolved)

    assert env["QWENPAWMAIL_EMAIL"] == "tester@163.com"
    assert env["QWENPAWMAIL_AUTH_CODE"] == "a" * 16


def test_sync_upgrades_legacy_plaintext_driver_card(tmp_path):
    card_path = tmp_path / "drivers" / "mcp" / "qwenpawmail.yaml"
    card_path.parent.mkdir(parents=True)
    card_path.write_text(
        """name: qwenpawmail
protocol: mcp
endpoint:
  transport: stdio
  command: python
  args: [-m, qwenpawmail_mcp]
  env:
    QWENPAWMAIL_EMAIL: tester@163.com
    QWENPAWMAIL_AUTH_CODE: aaaaaaaaaaaaaaaa
credentials: {}
""",
        encoding="utf-8",
    )

    assert _sync_qwenpawmail_driver_card(
        tmp_path,
        _valid_mail(),
        "qwenpaw",
    )

    rewritten = card_path.read_text("utf-8")
    assert "a" * 16 not in rewritten
    assert AGENT_MAIL_CREDENTIAL_REF in rewritten


def test_sync_preserves_policy_enabled_and_tool_whitelist(tmp_path):
    original_mail = _valid_mail()
    assert _generate_qwenpawmail_driver_card(tmp_path, original_mail)
    card_path = tmp_path / "drivers" / "mcp" / "qwenpawmail.yaml"
    card = load_card(card_path)
    expected_policy = DriverPolicy(
        default_effect="allow",
        rules=[
            PolicyRule(
                effect="deny",
                target=PolicyTarget(kind="tool", name="delete_message"),
            ),
        ],
    )
    card.policy = expected_policy
    card.enabled = False
    card.config["tools"] = ["list_messages", "get_message"]
    dump_card(card, card_path)

    # Backend restart synchronization must retain user-controlled card state.
    assert _sync_qwenpawmail_driver_card(
        tmp_path,
        original_mail,
        "qwenpaw",
    )
    restarted = load_card(card_path)
    assert restarted.policy == expected_policy
    assert restarted.enabled is False
    assert restarted.config["tools"] == ["list_messages", "get_message"]

    # Editing the mailbox must update credentials without resetting that state.
    updated_mail = _valid_mail()
    updated_mail.credential.name = "updated"
    updated_mail.credential.auth_code = "b" * 16
    assert _sync_qwenpawmail_driver_card(
        tmp_path,
        updated_mail,
        "qwenpaw",
        force_rewrite=True,
    )
    updated = load_card(card_path)
    assert updated.endpoint["env"]["QWENPAWMAIL_EMAIL"] == "updated@163.com"
    assert updated.policy == expected_policy
    assert updated.enabled is False
    assert updated.config["tools"] == ["list_messages", "get_message"]
    credential = AsyncCredentialStore(
        tmp_path / "credentials.yaml",
    ).get_sync(AGENT_MAIL_CREDENTIAL_REF)
    assert credential.secrets["auth_code"] == "b" * 16


def _run_mail_revocation_update(tmp_path, body: AgentProfileConfig):
    persisted = [
        AgentProfileConfig(
            id="a1",
            name="bot",
            workspace_dir=str(tmp_path),
            backend="qwenpaw",
            mail=_valid_mail(),
        ),
    ]
    _generate_qwenpawmail_driver_card(tmp_path, persisted[0].mail)

    async def _fake_update(_agent_id, apply_update):
        updated = persisted[0].model_copy(deep=True)
        apply_update(updated)
        persisted[0] = updated
        return updated

    def _fake_load(_agent_id):
        return persisted[0]

    global_config = _fake_global_config("a1")
    global_config.agents.profiles["a1"].workspace_dir = str(tmp_path)
    global_config.agents.language = "en"
    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=global_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            side_effect=_fake_load,
        ),
        patch(
            "qwenpaw.app.routers.agents.update_agent_config_async",
            new=_fake_update,
        ),
        patch("qwenpaw.app.routers.agents.schedule_agent_reload"),
    ):
        asyncio.run(
            update_agent(agentId="a1", agent_config=body, request=None),
        )
    return persisted[0]


def test_update_personal_mail_to_none_revokes_driver_card(tmp_path):
    updated = _run_mail_revocation_update(
        tmp_path,
        AgentProfileConfig(id="a1", name="bot", mail=None),
    )
    card_path = tmp_path / "drivers" / "mcp" / "qwenpawmail.yaml"
    assert updated.mail is None
    assert not card_path.exists()
    # Driver discovery has no card to reload.
    from qwenpaw.drivers.storage import list_card_paths

    assert list_card_paths(tmp_path / "drivers") == []
    # Repeated close is idempotent.
    _sync_qwenpawmail_driver_card(tmp_path, None, "qwenpaw")
    assert not card_path.exists()


def test_update_qwenpaw_to_third_party_revokes_driver_card(tmp_path):
    updated = _run_mail_revocation_update(
        tmp_path,
        AgentProfileConfig(
            id="a1",
            name="bot",
            backend="claude_code",
            mail=None,
        ),
    )
    assert updated.backend == "claude_code"
    assert updated.mail is None
    assert not (tmp_path / "drivers" / "mcp" / "qwenpawmail.yaml").exists()


def test_update_cannot_relocate_mail_driver_writes(tmp_path):
    registered_workspace = tmp_path / "registered"
    requested_workspace = tmp_path / "request-controlled"

    updated = _run_mail_revocation_update(
        registered_workspace,
        AgentProfileConfig(
            id="a1",
            name="bot",
            workspace_dir=str(requested_workspace),
            mail=None,
        ),
    )

    assert updated.workspace_dir == str(registered_workspace)
    assert not (
        registered_workspace / "drivers" / "mcp" / "qwenpawmail.yaml"
    ).exists()
    assert not requested_workspace.exists()


def test_update_omitted_secret_keeps_existing_mail_credential(tmp_path):
    incoming = _valid_mail()
    incoming.credential.auth_code = ""

    updated = _run_mail_revocation_update(
        tmp_path,
        AgentProfileConfig(id="a1", name="bot", mail=incoming),
    )

    assert updated.mail is not None
    assert updated.mail.credential.auth_code == "a" * 16
    stored = AsyncCredentialStore(tmp_path / "credentials.yaml").get_sync(
        AGENT_MAIL_CREDENTIAL_REF,
    )
    assert stored.secrets["auth_code"] == "a" * 16


def test_update_changed_mailbox_requires_fresh_secret(tmp_path):
    incoming = _valid_mail()
    incoming.credential.name = "different"
    incoming.credential.auth_code = ""

    with pytest.raises(HTTPException) as exc_info:
        _run_mail_revocation_update(
            tmp_path,
            AgentProfileConfig(id="a1", name="bot", mail=incoming),
        )

    assert exc_info.value.status_code == 400
    assert "auth_code" in exc_info.value.detail


def test_failed_driver_rewrite_revokes_stale_credentials(tmp_path):
    card_path = tmp_path / "drivers" / "mcp" / "qwenpawmail.yaml"
    card_path.parent.mkdir(parents=True)
    card_path.write_text("old plaintext credentials", encoding="utf-8")
    with patch(
        "qwenpaw.app.mail.driver_config.generate_qwenpawmail_driver_card",
        return_value=False,
    ):
        assert not _sync_qwenpawmail_driver_card(
            tmp_path,
            _valid_mail(),
            "qwenpaw",
            force_rewrite=True,
        )
    assert not card_path.exists()


def test_update_driver_failure_restores_previous_config(tmp_path):
    previous_mail = _valid_mail()
    updated_mail = _valid_mail()
    updated_mail.credential.auth_code = "b" * 16
    stale_workspace = tmp_path / "legacy-request-path"
    persisted = [
        AgentProfileConfig(
            id="a1",
            name="bot",
            workspace_dir=str(stale_workspace),
            backend="qwenpaw",
            mail=previous_mail,
        ),
    ]

    async def _fake_update(_agent_id, apply_update):
        candidate = persisted[0].model_copy(deep=True)
        apply_update(candidate)
        persisted[0] = candidate
        return candidate

    def _fake_load(_agent_id):
        return persisted[0]

    def _fake_save(_agent_id, config):
        persisted[0] = config.model_copy(deep=True)

    global_config = _fake_global_config("a1")
    global_config.agents.profiles["a1"].workspace_dir = str(tmp_path)
    global_config.agents.language = "en"
    body = AgentProfileConfig(id="a1", name="bot", mail=updated_mail)

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=global_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            side_effect=_fake_load,
        ),
        patch(
            "qwenpaw.app.routers.agents.update_agent_config_async",
            new=_fake_update,
        ),
        patch(
            "qwenpaw.app.routers.agents.save_agent_config",
            side_effect=_fake_save,
        ),
        patch(
            "qwenpaw.app.routers.agents._sync_qwenpawmail_driver_card",
            side_effect=[False, True],
        ) as sync_driver,
        patch(
            "qwenpaw.app.routers.agents.schedule_agent_reload",
        ) as reload_agent,
    ):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                update_agent(
                    agentId="a1",
                    agent_config=body,
                    request=None,
                ),
            )

    assert exc_info.value.status_code == 500
    assert "previous mail configuration was restored" in exc_info.value.detail
    assert persisted[0].mail is not None
    assert persisted[0].mail.credential.auth_code == "a" * 16
    assert persisted[0].workspace_dir == str(tmp_path)
    assert sync_driver.call_count == 2
    assert all(call.args[0] == tmp_path for call in sync_driver.call_args_list)
    reload_agent.assert_not_called()


def test_update_failed_new_card_rebuilds_old_credentials(tmp_path):
    previous_mail = _valid_mail()
    updated_mail = _valid_mail()
    updated_mail.credential.auth_code = "b" * 16
    persisted = [
        AgentProfileConfig(
            id="a1",
            name="bot",
            workspace_dir=str(tmp_path),
            backend="qwenpaw",
            mail=previous_mail,
        ),
    ]
    assert _generate_qwenpawmail_driver_card(tmp_path, previous_mail)

    async def _fake_update(_agent_id, apply_update):
        candidate = persisted[0].model_copy(deep=True)
        apply_update(candidate)
        persisted[0] = candidate
        return candidate

    def _fake_load(_agent_id):
        return persisted[0]

    def _fake_save(_agent_id, config):
        persisted[0] = config.model_copy(deep=True)

    def _fail_only_new_credentials(workspace_dir, mail):
        if mail.credential.auth_code == "b" * 16:
            return False
        return _generate_qwenpawmail_driver_card(workspace_dir, mail)

    global_config = _fake_global_config("a1")
    global_config.agents.profiles["a1"].workspace_dir = str(tmp_path)
    global_config.agents.language = "en"
    body = AgentProfileConfig(id="a1", name="bot", mail=updated_mail)

    with (
        patch(
            "qwenpaw.app.routers.agents.load_config",
            return_value=global_config,
        ),
        patch(
            "qwenpaw.app.routers.agents.load_agent_config",
            side_effect=_fake_load,
        ),
        patch(
            "qwenpaw.app.routers.agents.update_agent_config_async",
            new=_fake_update,
        ),
        patch(
            "qwenpaw.app.routers.agents.save_agent_config",
            side_effect=_fake_save,
        ),
        patch(
            "qwenpaw.app.mail.driver_config.generate_qwenpawmail_driver_card",
            side_effect=_fail_only_new_credentials,
        ),
        patch(
            "qwenpaw.app.routers.agents.schedule_agent_reload",
        ) as reload_agent,
    ):
        with pytest.raises(HTTPException):
            asyncio.run(
                update_agent(
                    agentId="a1",
                    agent_config=body,
                    request=None,
                ),
            )

    card_path = tmp_path / "drivers" / "mcp" / "qwenpawmail.yaml"
    card = yaml.safe_load(card_path.read_text("utf-8"))
    assert persisted[0].mail is not None
    assert persisted[0].mail.credential.auth_code == "a" * 16
    assert card["endpoint"]["env"]["QWENPAWMAIL_AUTH_CODE"] == {
        "source": "credential",
        "credential": "mail",
        "field": "auth_code",
    }
    stored = AsyncCredentialStore(tmp_path / "credentials.yaml").get_sync(
        AGENT_MAIL_CREDENTIAL_REF,
    )
    assert stored.secrets["auth_code"] == "a" * 16
    reload_agent.assert_not_called()


def test_copied_agent_drops_mail_for_third_party_backend(tmp_path):
    source = AgentProfileConfig(
        id="src",
        name="src",
        backend="claude_code",
        mail=_valid_mail(),
    )
    copied = _build_copied_agent_config(
        source_config=source,
        new_id="new",
        new_name="src Copy",
        workspace_dir=tmp_path,
    )
    assert copied.mail is None


def test_copied_agent_keeps_mail_for_qwenpaw_backend(tmp_path):
    source = AgentProfileConfig(
        id="src",
        name="src",
        backend="qwenpaw",
        mail=_valid_mail(),
    )
    copied = _build_copied_agent_config(
        source_config=source,
        new_id="new",
        new_name="src Copy",
        workspace_dir=tmp_path,
    )
    assert copied.mail is not None


def test_aliyun_domain_accepts_non_16_char_auth_code():
    """aliyun.com uses login password which is not 16 chars."""
    mail = AgentMailConfig(
        is_new_account=False,
        credential=AgentMailCredential(
            name="tester",
            domain="aliyun.com",
            auth_code="my_login_password_123",
            password="",
            phone_number="",
        ),
    )
    _validate_mail_config(mail)


def test_enterprise_provider_accepts_non_16_char_auth_code():
    """Enterprise mail providers use login/client passwords (non-16 chars)."""
    for provider in ("tencent_exmail", "aliyun_qiye", "netease_qiye"):
        mail = AgentMailConfig(
            is_new_account=False,
            credential=AgentMailCredential(
                name="tester",
                domain="mycompany.com",
                auth_code="enterprise_pwd_8",
                password="",
                phone_number="",
                provider=provider,
            ),
        )
        _validate_mail_config(mail)


def test_aliyun_domain_rejects_empty_auth_code():
    """aliyun.com still requires a non-empty auth_code."""
    mail = AgentMailConfig(
        is_new_account=False,
        credential=AgentMailCredential(
            name="tester",
            domain="aliyun.com",
            auth_code="",
            password="",
            phone_number="",
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_mail_config(mail)
    assert exc_info.value.status_code == 400
    assert "auth_code" in exc_info.value.detail


def test_personal_mail_without_password_phone_passes():
    """Personal mailbox only needs name + auth_code, not password/phone."""
    mail = AgentMailConfig(
        is_new_account=False,
        credential=AgentMailCredential(
            name="tester",
            domain="163.com",
            auth_code="a" * 16,
            password="",
            phone_number="",
        ),
    )
    # Should not raise
    _validate_mail_config(mail)


def test_personal_mail_without_name_rejected():
    """Personal mailbox still requires credential name."""
    mail = AgentMailConfig(
        is_new_account=False,
        credential=AgentMailCredential(
            name="",
            domain="163.com",
            auth_code="a" * 16,
            password="",
            phone_number="",
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_mail_config(mail)
    assert exc_info.value.status_code == 400
    assert "credential name" in exc_info.value.detail


def test_dedicated_mailbox_allows_registration_without_secrets():
    """Registration starts without persisting password or phone details."""
    mail = AgentMailConfig(
        is_new_account=True,
        credential=AgentMailCredential(
            name="",
            domain="163.com",
            auth_code="",
        ),
    )

    _validate_mail_config(mail)

    assert mail.is_new_account is True
    assert mail.credential.auth_code == ""


def test_dedicated_mailbox_credential_completes_provisioning(tmp_path):
    """The optional credential turns a registered mailbox into a live one."""
    mail = AgentMailConfig(
        is_new_account=True,
        credential=AgentMailCredential(
            name="registered",
            domain="163.com",
            auth_code="a" * 16,
            password="legacy-password",
            phone_number="13800000000",
        ),
    )

    _validate_mail_config(mail)

    assert mail.is_new_account is False
    assert mail.credential.password == ""
    assert mail.credential.phone_number == ""
    env = _build_qwenpawmail_env(mail, tmp_path)
    assert env["QWENPAWMAIL_EMAIL"] == "registered@163.com"
    assert env["QWENPAWMAIL_AUTH_CODE"]["field"] == "auth_code"
    assert _generate_qwenpawmail_driver_card(tmp_path, mail)
    card = load_card(tmp_path / "drivers" / "mcp" / "qwenpawmail.yaml")
    assert card.endpoint["env"]["QWENPAWMAIL_EMAIL"] == "registered@163.com"
    stored = AsyncCredentialStore(
        tmp_path / "credentials.yaml",
    ).get_sync(AGENT_MAIL_CREDENTIAL_REF)
    assert stored.public["is_new_account"] is False
    assert stored.secrets == {"auth_code": "a" * 16}


def test_dedicated_mailbox_rejects_invalid_optional_auth_code():
    mail = AgentMailConfig(
        is_new_account=True,
        credential=AgentMailCredential(
            name="registered",
            domain="gmail.com",
            auth_code="too-short",
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        _validate_mail_config(mail)

    assert exc_info.value.status_code == 400
    assert "exactly 16 characters" in exc_info.value.detail


# ── MAIL_TRIAGE.md seed distribution ──────────────────────────────


def test_ensure_mail_triage_file_copies_seed(tmp_path):
    _ensure_mail_triage_file(tmp_path, "zh")
    target = tmp_path / "MAIL_TRIAGE.md"
    assert target.is_file()
    text = target.read_text("utf-8")
    assert "邮件分诊树" in text
    assert "F1 探索处理" in text


def test_ensure_mail_triage_file_skips_existing(tmp_path):
    target = tmp_path / "MAIL_TRIAGE.md"
    target.write_text("user grown tree", "utf-8")
    _ensure_mail_triage_file(tmp_path, "zh")
    assert target.read_text("utf-8") == "user grown tree"


def test_ensure_mail_triage_file_falls_back_to_en(tmp_path):
    # Unsupported language normalizes to en; en also carries the seed.
    _ensure_mail_triage_file(tmp_path, "fr")
    assert (tmp_path / "MAIL_TRIAGE.md").is_file()
