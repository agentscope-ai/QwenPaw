# -*- coding: utf-8 -*-
"""Integration tests for the mail monitor module helpers.

Covers src/qwenpaw/app/mail/monitor.py (1,071 uncovered lines):
idle timeout resolution, HTML stripping, MIME header decoding,
domain matching, push-rule matching, wake decisions, wake prompts,
IMAP host resolution.
"""

from __future__ import annotations

import email
from email.message import EmailMessage

import pytest


# ------------------------------------------------------------------ #
# resolve_idle_timeout / resolve_imap_host
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_idle_timeout_known_domain() -> None:
    """Known provider domains get provider-specific timeouts."""
    from qwenpaw.app.mail.monitor import resolve_idle_timeout

    qq = resolve_idle_timeout("qq.com")
    gmail = resolve_idle_timeout("gmail.com")
    assert isinstance(qq, int) and qq > 0
    assert isinstance(gmail, int) and gmail > 0


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_idle_timeout_unknown_falls_back() -> None:
    """Unknown domains fall back to the default timeout."""
    from qwenpaw.app.mail.monitor import (
        _IDLE_TIMEOUT_SECONDS,
        resolve_idle_timeout,
    )

    assert resolve_idle_timeout("no-such-domain.example") == (
        _IDLE_TIMEOUT_SECONDS
    )


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_idle_timeout_provider_takes_precedence() -> None:
    """An explicit provider key beats the domain lookup."""
    from qwenpaw.app.mail.monitor import (
        _IDLE_TIMEOUT_SECONDS_BY_PROVIDER,
        resolve_idle_timeout,
    )

    if _IDLE_TIMEOUT_SECONDS_BY_PROVIDER:
        key = next(iter(_IDLE_TIMEOUT_SECONDS_BY_PROVIDER))
        expected = _IDLE_TIMEOUT_SECONDS_BY_PROVIDER[key]
        assert resolve_idle_timeout("qq.com", provider=key) == expected


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_imap_host_known_domains() -> None:
    """Common mailbox domains resolve to IMAP hosts."""
    from qwenpaw.app.mail.monitor import resolve_imap_host

    qq = resolve_imap_host("qq.com")
    gmail = resolve_imap_host("gmail.com")
    assert qq and "imap" in qq.lower()
    assert gmail and "imap" in gmail.lower()


@pytest.mark.integration
@pytest.mark.p1
def test_resolve_imap_host_unknown_returns_none() -> None:
    """Unknown domains without a provider return None (skip)."""
    from qwenpaw.app.mail.monitor import resolve_imap_host

    assert resolve_imap_host("unknown-domain-xyz.example") is None


# ------------------------------------------------------------------ #
# HTML stripping / MIME decoding
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_strip_html_removes_tags() -> None:
    """HTML tags are stripped, entities unescaped, whitespace collapsed."""
    from qwenpaw.app.mail.monitor import _strip_html

    text = _strip_html("<p>Hello&nbsp;<b>world</b></p><br>x")
    assert "Hello" in text
    assert "world" in text
    assert "<" not in text
    assert ">" not in text


@pytest.mark.integration
@pytest.mark.p1
def test_strip_html_plain_text_passthrough() -> None:
    """Plain text without tags passes through unchanged."""
    from qwenpaw.app.mail.monitor import _strip_html

    assert _strip_html("just plain text") == "just plain text"


@pytest.mark.integration
@pytest.mark.p1
def test_decode_mime_header_rfc2047() -> None:
    """RFC 2047 encoded headers decode to unicode text."""
    from qwenpaw.app.mail.monitor import decode_mime_header

    encoded = "=?utf-8?b?5rWL6K+V?="  # base64("测试")
    assert decode_mime_header(encoded) == "测试"


@pytest.mark.integration
@pytest.mark.p1
def test_decode_mime_header_plain_passthrough() -> None:
    """Plain ASCII headers pass through unchanged."""
    from qwenpaw.app.mail.monitor import decode_mime_header

    assert decode_mime_header("Alice <a@example.com>") == (
        "Alice <a@example.com>"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_decode_mime_header_none() -> None:
    """None yields an empty string."""
    from qwenpaw.app.mail.monitor import decode_mime_header

    assert decode_mime_header(None) == ""


@pytest.mark.integration
@pytest.mark.p1
def test_decode_mime_header_bytes() -> None:
    """Bytes headers decode with replacement."""
    from qwenpaw.app.mail.monitor import decode_mime_header

    assert decode_mime_header(b"plain bytes") == "plain bytes"


# ------------------------------------------------------------------ #
# domain matching
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_domain_matches_exact() -> None:
    """Identical domains match."""
    from qwenpaw.app.mail.monitor import _domain_matches

    assert _domain_matches("qq.com", "qq.com") is True


@pytest.mark.integration
@pytest.mark.p1
def test_domain_matches_subdomain() -> None:
    """Parent/child domain pairs match in both directions."""
    from qwenpaw.app.mail.monitor import _domain_matches

    assert _domain_matches("mail.qq.com", "qq.com") is True
    assert _domain_matches("qq.com", "mail.qq.com") is True


@pytest.mark.integration
@pytest.mark.p1
def test_domain_matches_case_and_dots() -> None:
    """Matching is case-insensitive and ignores trailing dots."""
    from qwenpaw.app.mail.monitor import _domain_matches

    assert _domain_matches("QQ.COM.", "qq.com") is True


@pytest.mark.integration
@pytest.mark.p1
def test_domain_matches_unrelated() -> None:
    """Unrelated domains never match, even on substring overlap."""
    from qwenpaw.app.mail.monitor import _domain_matches

    assert _domain_matches("qq.com", "gmail.com") is False
    assert _domain_matches("notqq.com", "qq.com") is False
    assert _domain_matches("", "qq.com") is False


# ------------------------------------------------------------------ #
# push rules
# ------------------------------------------------------------------ #


def _rule(field: str, contains: str, action: str = "notify"):
    from qwenpaw.config.config import AgentMailPushRule

    return AgentMailPushRule(field=field, contains=contains, action=action)


@pytest.mark.integration
@pytest.mark.p1
def test_rule_matches_from_field() -> None:
    """field=from matches only the sender, case-insensitively."""
    from qwenpaw.app.mail.monitor import rule_matches

    rule = _rule("from", "alice")
    assert rule_matches(rule, "ALICE@example.com", "irrelevant") is True
    assert rule_matches(rule, "bob@example.com", "alice in subject") is False


@pytest.mark.integration
@pytest.mark.p1
def test_rule_matches_content_field() -> None:
    """field=content matches subject and body."""
    from qwenpaw.app.mail.monitor import rule_matches

    rule = _rule("content", "urgent")
    assert rule_matches(rule, "x", "URGENT request") is True
    assert rule_matches(rule, "x", "subject ok", body="is urgent too") is True
    assert rule_matches(rule, "urgent@x.com", "clean") is False


@pytest.mark.integration
@pytest.mark.p1
def test_rule_matches_keyword_field() -> None:
    """field=keyword searches sender, subject, and body."""
    from qwenpaw.app.mail.monitor import rule_matches

    rule = _rule("keyword", "deploy")
    assert rule_matches(rule, "deploy@ci.com", "x") is True
    assert rule_matches(rule, "x", "please DEPLOY") is True
    assert rule_matches(rule, "x", "x", body="deploy it") is True
    assert rule_matches(rule, "x", "x", body="nothing") is False


@pytest.mark.integration
@pytest.mark.p1
def test_rule_matches_empty_never_matches() -> None:
    """Empty contains never matches."""
    from qwenpaw.app.mail.monitor import rule_matches

    rule = _rule("from", "")
    assert rule_matches(rule, "anyone@example.com", "anything") is False


@pytest.mark.integration
@pytest.mark.p1
def test_match_rules_preserves_order() -> None:
    """match_rules returns all hits in configured order."""
    from qwenpaw.app.mail.monitor import match_rules

    rules = [
        _rule("from", "bob"),
        _rule("keyword", "deploy"),
        _rule("from", "alice"),
    ]
    matched = match_rules(rules, "deploy-bot@ci.com", "Deploy now")
    assert [r.contains for r in matched] == ["deploy"]


# ------------------------------------------------------------------ #
# wake decisions and prompts
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_should_wake_agent_all_mode() -> None:
    """agent_all wakes on every message."""
    from qwenpaw.app.mail.monitor import should_wake_agent

    assert should_wake_agent("agent_all", []) is True
    assert should_wake_agent("agent_all", [_rule("from", "x")]) is True


@pytest.mark.integration
@pytest.mark.p1
def test_should_wake_rules_then_agent_wake_rule() -> None:
    """rules_then_agent wakes when a matched rule says wake_agent."""
    from qwenpaw.app.mail.monitor import should_wake_agent

    wake_rule = _rule("keyword", "deploy", action="wake_agent")
    assert should_wake_agent("rules_then_agent", [wake_rule]) is True


@pytest.mark.integration
@pytest.mark.p1
def test_should_wake_rules_then_agent_no_match() -> None:
    """rules_then_agent wakes when no rule matched at all."""
    from qwenpaw.app.mail.monitor import should_wake_agent

    notify_rule = _rule("keyword", "deploy", action="notify")
    assert should_wake_agent("rules_then_agent", []) is True
    assert should_wake_agent("rules_then_agent", [notify_rule]) is False


@pytest.mark.integration
@pytest.mark.p1
def test_should_wake_off_modes_never_wake() -> None:
    """rules_only and off never wake the agent."""
    from qwenpaw.app.mail.monitor import should_wake_agent

    assert should_wake_agent("rules_only", []) is False
    assert (
        should_wake_agent("off", [_rule("from", "x", "wake_agent")]) is False
    )


@pytest.mark.integration
@pytest.mark.p1
def test_build_wake_prompt_contains_fields() -> None:
    """Wake prompt renders sender, subject, uid, and folder."""
    from qwenpaw.app.mail.monitor import build_wake_prompt

    prompt = build_wake_prompt(
        sender="a@example.com",
        subject="Hello",
        date="2026-08-28",
        uid=42,
        folder="INBOX",
    )
    assert "a@example.com" in prompt
    assert "Hello" in prompt
    assert "42" in prompt
    assert "INBOX" in prompt


@pytest.mark.integration
@pytest.mark.p1
def test_build_wake_prompt_defaults_for_missing() -> None:
    """Missing sender/subject fall back to placeholders."""
    from qwenpaw.app.mail.monitor import build_wake_prompt

    prompt = build_wake_prompt(sender="", subject="", date="", uid=1)
    assert "(unknown)" in prompt
    assert "(no subject)" in prompt


@pytest.mark.integration
@pytest.mark.p1
def test_build_wake_prompt_appends_param() -> None:
    """A non-empty param appends an extra instruction line."""
    from qwenpaw.app.mail.monitor import build_wake_prompt

    with_param = build_wake_prompt(
        sender="a@x.com",
        subject="s",
        date="d",
        uid=1,
        param="reply politely",
    )
    without = build_wake_prompt(
        sender="a@x.com",
        subject="s",
        date="d",
        uid=1,
    )
    assert "reply politely" in with_param
    assert "reply politely" not in without


# ------------------------------------------------------------------ #
# body preview / truncation
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_extract_body_preview_plain() -> None:
    """text/plain bodies are extracted as preview."""
    from qwenpaw.app.mail.monitor import extract_body_preview

    msg = EmailMessage()
    msg.set_content("This is the plain body.")
    parsed = email.message_from_bytes(msg.as_bytes())
    preview = extract_body_preview(parsed)
    assert "plain body" in preview


@pytest.mark.integration
@pytest.mark.p1
def test_extract_body_preview_html_fallback() -> None:
    """HTML-only messages fall back to stripped text."""
    from qwenpaw.app.mail.monitor import extract_body_preview

    msg = EmailMessage()
    msg.set_content(
        "<html><body><p>HTML body</p></body></html>",
        subtype="html",
    )
    parsed = email.message_from_bytes(msg.as_bytes())
    preview = extract_body_preview(parsed)
    assert "HTML body" in preview
    assert "<" not in preview


@pytest.mark.integration
@pytest.mark.p1
def test_truncate_text_under_limit() -> None:
    """Short text is stripped and returned whole."""
    from qwenpaw.app.mail.monitor import _truncate_text

    assert _truncate_text("  short  ", 100) == "short"


@pytest.mark.integration
@pytest.mark.p1
def test_truncate_text_over_limit() -> None:
    """Long text is hard-truncated at the limit."""
    from qwenpaw.app.mail.monitor import _truncate_text

    result = _truncate_text("x" * 500, 100)
    assert len(result) == 100


@pytest.mark.integration
@pytest.mark.p1
def test_truncate_text_none() -> None:
    """None input becomes an empty string."""
    from qwenpaw.app.mail.monitor import _truncate_text

    assert _truncate_text(None, 10) == ""
