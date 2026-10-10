# -*- coding: utf-8 -*-
"""Regression tests for shared MailClient/monitor IMAP mutations."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from qwenpawmail_mcp.config import Config, load_config
from qwenpawmail_mcp.errors import CapabilityError, MailError
from qwenpawmail_mcp.mail_client import MailClient
from qwenpawmail_mcp.providers import ProviderCapabilities


class MutationConn:
    """Small stateful IMAP double that can expose destructive call order."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.selected = "INBOX"
        self.select_failures: set[str] = set()
        self.move_typ = "NO"
        self.copy_typ = "OK"
        self.store_typ = "OK"
        self.uid_expunge_typ = "OK"
        self.append_typ = "OK"
        self.create_typ = "OK"
        self.create_detail = b"created"
        self.search_result = b""
        self.deleted_uids = {"99"}
        self.global_expunge_called = False
        self.raw = (
            b"From: alice@example.com\r\n"
            b"Message-ID: <message-42@example.com>\r\n\r\n"
            b"body"
        )

    def select(self, folder, readonly=False):
        self.calls.append(("SELECT", folder, readonly))
        if folder in self.select_failures:
            return ("NO", [b"cannot select target"])
        self.selected = folder
        return ("OK", [b"1"])

    def create(self, folder):
        self.calls.append(("CREATE", folder))
        return (self.create_typ, [self.create_detail])

    def status(self, folder, items):
        self.calls.append(("STATUS", folder, items))
        return ("NO", [b"missing"])

    def uid(self, command, *args):
        # pylint: disable=too-many-return-statements
        self.calls.append((command, *args))
        if command == "MOVE":
            return (self.move_typ, [b"move response"])
        if command == "COPY":
            return (self.copy_typ, [b"copy response"])
        if command == "STORE":
            if self.store_typ == "OK":
                self.deleted_uids.add(str(args[0]))
            return (self.store_typ, [b"store response"])
        if command == "EXPUNGE":
            if self.uid_expunge_typ == "OK":
                self.deleted_uids.discard(str(args[0]))
            return (self.uid_expunge_typ, [b"uid expunge response"])
        if command == "FETCH" and args[1] == "(BODY.PEEK[])":
            return ("OK", [(b"1 (BODY[])", self.raw), b")"])
        if command == "FETCH" and args[1] == "(FLAGS)":
            return ("OK", [b"1 (FLAGS (\\Seen))"])
        if command == "SEARCH":
            # If a caller searches the still-selected source after a failed
            # target SELECT, it would incorrectly find this same message.
            return ("OK", [self.search_result])
        raise AssertionError(f"unexpected UID command: {command} {args}")

    def append(self, folder, flags, date_time, raw):
        self.calls.append(("APPEND", folder, flags, date_time, raw))
        return (self.append_typ, [b"append response"])

    def expunge(self):
        self.global_expunge_called = True
        self.deleted_uids.clear()
        self.calls.append(("GLOBAL EXPUNGE",))
        return ("OK", [b""])


def _config(capabilities: ProviderCapabilities) -> Config:
    return Config(
        email="tester@qq.com",
        auth_code="secret",
        imap_host="imap.qq.com",
        imap_port=993,
        smtp_host="smtp.qq.com",
        smtp_port=465,
        requires_id_command=True,
        capabilities=capabilities,
    )


def _client(monkeypatch, conn: MutationConn, caps: ProviderCapabilities):
    client = MailClient(_config(caps))

    @contextmanager
    def fake_imap():
        yield conn

    monkeypatch.setattr(client, "_imap", fake_imap)
    return client


def test_mail_client_copy_fallback_never_global_expunges(monkeypatch):
    conn = MutationConn()
    client = _client(monkeypatch, conn, ProviderCapabilities())

    result = client.move_message("INBOX", "42", "Archive")

    assert result["moved"] is True
    assert result["via"] == "uid_copy"
    assert ("COPY", "42", '"Archive"') in conn.calls
    assert ("STORE", "42", "+FLAGS", "(\\Deleted)") in conn.calls
    assert ("EXPUNGE", "42") in conn.calls
    assert not conn.global_expunge_called
    assert conn.deleted_uids == {"99"}


def test_mail_client_copy_and_append_failure_preserve_source(monkeypatch):
    conn = MutationConn()
    conn.copy_typ = "NO"
    conn.append_typ = "NO"
    client = _client(monkeypatch, conn, ProviderCapabilities())

    with pytest.raises(CapabilityError):
        client.move_message("INBOX", "42", "Archive")

    assert not any(call[0] == "STORE" for call in conn.calls)
    assert not any(call[0] == "EXPUNGE" for call in conn.calls)
    assert not conn.global_expunge_called
    assert conn.deleted_uids == {"99"}


def test_append_duplicate_check_requires_successful_target_select(monkeypatch):
    conn = MutationConn()
    conn.copy_typ = "NO"
    conn.append_typ = "NO"
    conn.select_failures.add('"Archive"')
    conn.search_result = b"42"
    caps = ProviderCapabilities(move=False, copy=False, uid_expunge=False)
    client = _client(monkeypatch, conn, caps)

    with pytest.raises(CapabilityError):
        client.move_message("INBOX", "42", "Archive")

    # A failed target SELECT must not SEARCH the still-selected source and
    # mistake the source message for an already-appended target copy.
    assert not any(call[0] == "SEARCH" for call in conn.calls)
    assert any(call[0] == "APPEND" for call in conn.calls)
    assert not any(call[0] == "STORE" for call in conn.calls)
    assert conn.deleted_uids == {"99"}


def test_store_failure_after_copy_is_reported_before_expunge(monkeypatch):
    conn = MutationConn()
    conn.store_typ = "NO"
    client = _client(monkeypatch, conn, ProviderCapabilities())

    with pytest.raises(MailError, match=r"STORE \\Deleted"):
        client.move_message("INBOX", "42", "Archive")

    assert any(call[0] == "COPY" for call in conn.calls)
    assert not any(call[0] == "EXPUNGE" for call in conn.calls)
    assert conn.deleted_uids == {"99"}


def test_create_folder_is_idempotent_on_already_exists(monkeypatch):
    conn = MutationConn()
    conn.create_typ = "NO"
    conn.create_detail = b"[ALREADYEXISTS] Mailbox already exists"
    client = _client(monkeypatch, conn, ProviderCapabilities())

    assert client.create_folder("Archive") == {
        "created": "Archive",
        "already_exists": True,
    }


def test_custom_enterprise_host_recovers_restricted_capabilities():
    config = load_config(
        {
            "QWENPAWMAIL_EMAIL": "tester@example.com",
            "QWENPAWMAIL_AUTH_CODE": "secret",
            "QWENPAWMAIL_IMAP_HOST": "imap.qiye.163.com",
            "QWENPAWMAIL_SMTP_HOST": "smtp.qiye.163.com",
            "QWENPAWMAIL_SMTP_PORT": "994",
        },
    )

    assert config.requires_id_command is True
    assert config.capabilities.move is False
    assert config.capabilities.copy is False
    assert config.capabilities.uid_expunge is False
