# -*- coding: utf-8 -*-
"""Unit tests for AgentMailPushConfig serialization semantics."""

from __future__ import annotations

from qwenpaw.config.config import (
    AgentMailConfig,
    AgentMailCredential,
    AgentMailPushConfig,
    AgentMailPushRule,
)


def test_push_defaults():
    push = AgentMailPushConfig()
    assert push.mode == "off"
    assert push.rules == []
    assert push.poll_interval_seconds == 120
    # Access control is opt-in: new agents start with it disabled.
    assert push.access_control_enabled is False


def test_push_rule_defaults():
    rule = AgentMailPushRule()
    assert rule.field == "from"
    assert rule.contains == ""
    assert rule.action == "notify"
    assert rule.param == ""


def test_push_none_is_not_serialized():
    """push=None must not land in agent.json (exclude_none dump)."""
    mail = AgentMailConfig(
        credential=AgentMailCredential(name="tester"),
    )
    dumped = mail.model_dump(exclude_none=True)
    assert "push" not in dumped


def test_mail_secrets_are_write_only():
    mail = AgentMailConfig(
        credential=AgentMailCredential(
            name="tester",
            auth_code="a" * 16,
            password="secret-password",
            phone_number="13800000000",
        ),
    )

    credential = mail.model_dump()["credential"]
    assert "auth_code" not in credential
    assert "password" not in credential
    assert "phone_number" not in credential
    representation = repr(mail)
    assert "a" * 16 not in representation
    assert "secret-password" not in representation
    assert "13800000000" not in representation


def test_legacy_mail_config_without_push_loads():
    """Old agent.json payloads without a push key stay valid."""
    mail = AgentMailConfig.model_validate(
        {
            "is_new_account": False,
            "credential": {"name": "tester", "domain": "163.com"},
        },
    )
    assert mail.push is None


def test_push_round_trip():
    mail = AgentMailConfig(
        credential=AgentMailCredential(name="tester"),
        push=AgentMailPushConfig(
            mode="rules_then_agent",
            rules=[
                AgentMailPushRule(
                    field="subject",
                    contains="invoice",
                    action="move",
                    param="Archive",
                ),
            ],
            poll_interval_seconds=60,
        ),
    )
    dumped = mail.model_dump(exclude_none=True)
    assert dumped["push"]["mode"] == "rules_then_agent"
    assert dumped["push"]["rules"][0]["action"] == "move"
    restored = AgentMailConfig.model_validate(dumped)
    assert restored.push is not None
    assert restored.push.poll_interval_seconds == 60
    assert restored.push.rules[0].param == "Archive"
