# -*- coding: utf-8 -*-
"""Integration tests for mail access-control internals.

Covers src/qwenpaw/app/mail/mail_access_control.py (387 uncovered
lines): ACL address validation, user-info / pending-entry / ACL
serialization, sender decision chain, store registry.
"""
# pylint: disable=protected-access

from __future__ import annotations

from pathlib import Path

import pytest


# ------------------------------------------------------------------ #
# address validation
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_validate_acl_address_plain_email() -> None:
    """A normal user@domain address passes."""
    from qwenpaw.app.mail.mail_access_control import validate_acl_address

    validate_acl_address("user@example.com")  # must not raise


@pytest.mark.integration
@pytest.mark.p1
def test_validate_acl_address_wildcard_domain() -> None:
    """A *@domain wildcard passes."""
    from qwenpaw.app.mail.mail_access_control import validate_acl_address

    validate_acl_address("*@example.com")  # must not raise


@pytest.mark.integration
@pytest.mark.p1
def test_validate_acl_address_case_normalized() -> None:
    """Addresses are lower-cased and trimmed before validation."""
    from qwenpaw.app.mail.mail_access_control import validate_acl_address

    validate_acl_address("  USER@Example.COM  ")  # must not raise


@pytest.mark.integration
@pytest.mark.p1
def test_validate_acl_address_rejects_garbage() -> None:
    """Malformed addresses raise ValueError."""
    from qwenpaw.app.mail.mail_access_control import validate_acl_address

    for bad in ["", "no-at-sign", "a@", "@example.com", "*@", "a b@c.com"]:
        with pytest.raises(ValueError):
            validate_acl_address(bad)


# ------------------------------------------------------------------ #
# dataclass serialization
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_mail_user_info_roundtrip() -> None:
    """MailUserInfo serializes and restores remark/display name."""
    from qwenpaw.app.mail.mail_access_control import MailUserInfo

    info = MailUserInfo(remark="vip", display_name="Alice")
    restored = MailUserInfo.from_dict(info.to_dict())
    assert restored.remark == "vip"
    assert restored.display_name == "Alice"


@pytest.mark.integration
@pytest.mark.p1
def test_mail_user_info_from_string_legacy() -> None:
    """Legacy string data becomes a remark-only record."""
    from qwenpaw.app.mail.mail_access_control import MailUserInfo

    restored = MailUserInfo.from_dict("legacy note")
    assert restored.remark == "legacy note"


@pytest.mark.integration
@pytest.mark.p1
def test_mail_user_info_from_none() -> None:
    """None data becomes an empty record."""
    from qwenpaw.app.mail.mail_access_control import MailUserInfo

    restored = MailUserInfo.from_dict(None)
    assert restored.remark == ""
    assert restored.display_name == ""


@pytest.mark.integration
@pytest.mark.p1
def test_mail_pending_entry_roundtrip() -> None:
    """MailPendingEntry serializes subject/sender/uid fields."""
    from qwenpaw.app.mail.mail_access_control import MailPendingEntry

    entry = MailPendingEntry.from_dict(
        {
            "uid": 42,
            "sender_address": "a@example.com",
            "subject": "hi",
            "folder": "INBOX",
        },
    )
    data = entry.to_dict()
    assert data.get("uid") == 42
    restored = MailPendingEntry.from_dict(data)
    assert restored.to_dict().get("sender_address") == "a@example.com"


@pytest.mark.integration
@pytest.mark.p1
def test_agent_mail_acl_roundtrip() -> None:
    """AgentMailACL round-trips whitelist/blacklist/pending lists."""
    from qwenpaw.app.mail.mail_access_control import (
        AgentMailACL,
        MailPendingEntry,
        MailUserInfo,
    )

    acl = AgentMailACL(
        whitelist={"a@x.com": MailUserInfo(remark="ok")},
        blacklist={"b@x.com": MailUserInfo(remark="bad")},
        pending=[MailPendingEntry.from_dict({"uid": 1})],
    )
    data = acl.to_dict()
    restored = AgentMailACL.from_dict(data)
    assert set(restored.whitelist) == {"a@x.com"}
    assert set(restored.blacklist) == {"b@x.com"}
    assert len(restored.pending) == 1


@pytest.mark.integration
@pytest.mark.p1
def test_agent_mail_acl_empty_defaults() -> None:
    """Empty ACL exposes empty containers."""
    from qwenpaw.app.mail.mail_access_control import AgentMailACL

    acl = AgentMailACL()
    data = acl.to_dict()
    assert data["whitelist"] == {}
    assert data["blacklist"] == {}
    assert data["pending"] == []
    assert data["approved_replay"] == []


# ------------------------------------------------------------------ #
# sender decision chain
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_check_sender_unknown_agent(tmp_path: Path) -> None:
    """No ACL configured for the agent yields 'unknown'."""
    from qwenpaw.app.mail.mail_access_control import (
        get_mail_access_control_store,
    )

    ws = tmp_path / "ws-sender"
    ws.mkdir()
    store = get_mail_access_control_store(ws)
    assert store.check_sender("no-such-agent", "a@x.com") == "unknown"


@pytest.mark.integration
@pytest.mark.p1
def test_extract_domain_pure() -> None:
    """Domain extraction lowercases and splits at @."""
    from qwenpaw.app.mail.mail_access_control import (
        MailAccessControlStore,
    )

    assert MailAccessControlStore._extract_domain("a@x.com") == "x.com"
    assert MailAccessControlStore._extract_domain("no-at") == ""


# ------------------------------------------------------------------ #
# store registry
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_store_registry_singleton_per_workspace(tmp_path: Path) -> None:
    """Registry returns the same store instance per workspace dir."""
    from qwenpaw.app.mail.mail_access_control import (
        get_mail_access_control_store,
    )

    ws = tmp_path / "ws-reg"
    ws.mkdir()
    store_a = get_mail_access_control_store(ws)
    store_b = get_mail_access_control_store(ws)
    assert store_a is store_b
