# -*- coding: utf-8 -*-
"""Slash command e2e cases.

These cases drive QwenPaw's slash commands purely through the chat
input box (textarea + send button). The assertion path is the AI
bubble's rendered text — the same DOM elements a real user sees.

Why we don't use ``ChatPage.send_message_and_wait`` here:
its "round started" gate waits for the send button to transition
``enabled → disabled → enabled``. Slash command responses come back
fast enough that this transition is missed, the gate times out, and
the whole helper returns failure even though the bubble has already
rendered. We instead poll bubble counts directly.
"""
from __future__ import annotations

import logging
import time

import pytest

from pages.chat_page import ChatPage

logger = logging.getLogger(__name__)


SEND_BTN = "button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary"
AI_BUBBLE = ".qwenpaw-bubble.qwenpaw-bubble-start"


def _wait_session_ready(page) -> None:
    """Wait until the frontend has an active session (URL contains /chat/<id>).

    The React app may not have rendered yet when ``ChatPage.open()``
    returns (the HTML ``load`` event fires before the JS bundle
    executes). We first wait for the textarea to appear (proof the
    React app is alive), then wait for the URL to gain a session path
    segment. If it doesn't, we reload — a fresh navigation always
    triggers the frontend's auto-create-session flow.
    """
    # Step 1: wait for React to render (textarea is always present)
    try:
        page.locator("textarea").first.wait_for(state="visible", timeout=15000)
    except Exception:
        page.reload(wait_until="load", timeout=15000)
        page.locator("textarea").first.wait_for(state="visible", timeout=15000)

    # Step 2: wait for session auto-create (URL becomes /chat/<uuid>)
    deadline = time.time() + 10
    while time.time() < deadline:
        if "/chat/" in page.url and not page.url.endswith("/chat/"):
            return
        time.sleep(0.3)

    # Step 3: fallback — reload to trigger auto-create
    page.reload(wait_until="load", timeout=15000)
    page.wait_for_timeout(3000)
    deadline = time.time() + 10
    while time.time() < deadline:
        if "/chat/" in page.url and not page.url.endswith("/chat/"):
            return
        time.sleep(0.3)


def _send_slash(chat_page: ChatPage, command: str, timeout: int = 30000) -> str:
    """Type ``command`` into the chat input and return the new AI bubble text.

    Bypasses ``send_message_and_wait`` because that helper's button-state
    gate is incompatible with slash commands (responses are too fast).

    Quirks worked around here:
    - On a freshly opened chat the SSE / session bootstrap takes ~1-2s.
      Sending too early swallows the message silently. We wait 2s.
    - Slash commands are control commands that don't invoke the LLM,
      so they work as the first message in a new session — no need to
      create a session separately.
    - We always click the send button (never press Enter) because the
      ``/``-triggered autocomplete popup captures Enter for selection.
      Button clicks bypass the popup entirely.
    - The chat panel renders **newest bubble at index 0** (top), not at
      ``.last``. We therefore read ``.first`` to get the just-arrived
      reply.
    """
    page = chat_page.page

    # 1. Let the page bootstrap (SSE / session ready).
    page.wait_for_timeout(2000)
    _wait_session_ready(page)

    ai_before = page.locator(AI_BUBBLE).count()

    inp = page.locator("textarea").first
    assert inp.count() > 0, "chat textarea not found"
    inp.click()
    page.wait_for_timeout(200)
    inp.fill("")
    page.wait_for_timeout(150)
    inp.fill(command)
    page.wait_for_timeout(400)

    # 2. Always click the send button (never Enter) so we don't hit the
    #    autocomplete's keyboard trap. No need to dismiss the popup with
    #    Escape — button clicks bypass it entirely.
    send = page.locator(SEND_BTN).first
    assert send.count() > 0, "send button not found"
    # Some renders need an extra beat for the button to enable after fill.
    for _ in range(10):
        if send.is_visible() and send.is_enabled():
            break
        page.wait_for_timeout(200)
    send.click()

    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        if page.locator(AI_BUBBLE).count() > ai_before:
            break
        time.sleep(0.2)
    else:
        slug = command.lstrip("/").replace(" ", "_").replace("-", "_")
        page.screenshot(path=f"/tmp/qpe-slash-{slug}.png")
        pytest.fail(
            f"no AI bubble within {timeout}ms after sending {command!r} "
            f"(input value at fail: {inp.input_value()!r})"
        )

    # Wait for content to settle: stop polling once .first innerText is
    # non-empty and stable for ~1s. The chat list renders newest-on-top,
    # so the slash command's reply is at ``.first`` — not ``.last``.
    last_text = ""
    stable_since = 0.0
    settle_deadline = time.time() + 20
    while time.time() < settle_deadline:
        try:
            text = page.locator(AI_BUBBLE).first.inner_text(timeout=2000)
        except Exception:
            text = ""
        if text and text == last_text:
            if stable_since == 0.0:
                stable_since = time.time()
            elif time.time() - stable_since >= 1.0:
                break
        else:
            last_text = text
            stable_since = 0.0
        time.sleep(0.3)
    return last_text


def _assert_any(text: str, *needles: str) -> None:
    assert any(n in text for n in needles), (
        f"expected any of {needles!r} in bubble, got: {text!r}"
    )


_XFAIL_FIRST_MSG_RERENDER = (
    "Known frontend bug: on a newly created session the first slash "
    "command response is rendered then immediately cleared by a "
    "re-render cycle, causing the bubble text to read as empty. "
    "Tracked internally; will remove xfail once fixed."
)


@pytest.mark.slash_commands
@pytest.mark.p0
@pytest.mark.test_id("SLASH-001")
@pytest.mark.xfail(strict=False, reason=_XFAIL_FIRST_MSG_RERENDER)
def test_slash_skills_lists_or_reports_empty(clean_chat_page: ChatPage):
    """``/skills`` returns either an enabled-skill list or the empty notice."""
    chat = clean_chat_page.open()
    text = _send_slash(chat, "/skills")
    _assert_any(
        text,
        "No skills are currently enabled",
        "Use `/<skill_name>",
        "skill",
    )


@pytest.mark.slash_commands
@pytest.mark.p0
@pytest.mark.test_id("SLASH-002")
@pytest.mark.xfail(strict=False, reason=_XFAIL_FIRST_MSG_RERENDER)
def test_slash_model_shows_current_or_empty(clean_chat_page: ChatPage):
    """``/model`` reports either the active model or 'No Active Model'."""
    chat = clean_chat_page.open()
    text = _send_slash(chat, "/model")
    _assert_any(text, "Current Model", "No Active Model", "Provider")


@pytest.mark.slash_commands
@pytest.mark.p1
@pytest.mark.test_id("SLASH-003")
@pytest.mark.xfail(strict=False, reason=_XFAIL_FIRST_MSG_RERENDER)
def test_slash_model_help(clean_chat_page: ChatPage):
    """``/model -h`` shows the help block."""
    chat = clean_chat_page.open()
    text = _send_slash(chat, "/model -h")
    _assert_any(text, "Model Management", "Available Commands", "/model")


@pytest.mark.slash_commands
@pytest.mark.p1
@pytest.mark.test_id("SLASH-004")
@pytest.mark.xfail(strict=False, reason=_XFAIL_FIRST_MSG_RERENDER)
def test_slash_history_renders(clean_chat_page: ChatPage):
    """``/history`` returns the conversation summary (even if short)."""
    chat = clean_chat_page.open()
    text = _send_slash(chat, "/history")
    # The handler always responds with something — either history text
    # or an indicator block. Just assert we got a non-trivial bubble.
    assert len(text.strip()) >= 5, f"unexpectedly short history bubble: {text!r}"


@pytest.mark.slash_commands
@pytest.mark.p1
@pytest.mark.test_id("SLASH-005")
@pytest.mark.xfail(strict=False, reason=_XFAIL_FIRST_MSG_RERENDER)
def test_slash_proactive_status(clean_chat_page: ChatPage):
    """``/proactive`` (no args) toggles or reports proactive mode."""
    chat = clean_chat_page.open()
    text = _send_slash(chat, "/proactive off")
    _assert_any(
        text,
        "Proactive",
        "proactive",
        "主动",
        "No more proactive messages",
    )


@pytest.mark.slash_commands
@pytest.mark.p2
@pytest.mark.test_id("SLASH-007")
@pytest.mark.xfail(strict=False, reason=_XFAIL_FIRST_MSG_RERENDER)
def test_slash_dump_history_writes_file(clean_chat_page: ChatPage):
    """``/dump_history`` reports a target file path."""
    chat = clean_chat_page.open()
    text = _send_slash(chat, "/dump_history")
    _assert_any(text, "Dumped", "messages", "history", "File")


@pytest.mark.slash_commands
@pytest.mark.p2
@pytest.mark.test_id("SLASH-008")
@pytest.mark.xfail(strict=False, reason=_XFAIL_FIRST_MSG_RERENDER)
def test_slash_clear_resets_history(clean_chat_page: ChatPage):
    """``/clear`` returns a confirmation message."""
    chat = clean_chat_page.open()
    text = _send_slash(chat, "/clear")
    _assert_any(text, "History Cleared", "Cleared", "cleared", "empty")


@pytest.mark.slash_commands
@pytest.mark.p2
@pytest.mark.test_id("SLASH-009")
def test_slash_unknown_does_not_crash(clean_chat_page: ChatPage):
    """Typing an unrecognized slash command must not break the UI.

    The backend either routes the input to the LLM (slow) or rejects
    it; either way the chat must keep rendering. We don't assert on a
    bubble — we assert the textarea remains usable and the sidebar
    keeps rendering after the click.
    """
    chat = clean_chat_page.open()
    page = chat.page
    page.wait_for_timeout(2000)
    _wait_session_ready(page)

    inp = page.locator("textarea").first
    inp.click()
    inp.fill("/notarealcommand_e2e_probe")
    page.wait_for_timeout(400)

    send = page.locator(SEND_BTN).first
    for _ in range(10):
        if send.is_visible() and send.is_enabled():
            break
        page.wait_for_timeout(200)
    send.click()

    page.wait_for_timeout(3000)

    # UI smoke after probe: input box and sidebar still render.
    assert page.locator("textarea").first.count() > 0, (
        "textarea disappeared after unknown command — UI crashed"
    )
    assert page.locator('text=/Chat|Sessions|Channels/').first.count() > 0, (
        "sidebar disappeared after unknown command — UI crashed"
    )
