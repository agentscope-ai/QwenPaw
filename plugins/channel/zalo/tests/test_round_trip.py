# -*- coding: utf-8 -*-
"""Round-trip tests for Zalo channel — outbound 2-way verification.

Verifies that whatever the LLM emits as ``TextContent`` is correctly turned
into Zalo API calls in BOTH directions:

  text in   →   text + photo/sticker/voice/file calls out
  command in →   stripped token out (no null/think leak)

Covers:

- routing._extract_actions: markdown image, bare URL (with trailing punct),
  magic tokens, voice/sticker/file markers, mixed scenarios.
- thinking._strip_thinking / _strip_null_tokens: think blocks, lone tags,
  leading null-leak, label-only "Thinking:" lines.
- dispatch._dispatch_local_file: real file → size+path report; missing file
  → error text.
- dispatch._dispatch_text_actions: full 2-way — text-only, photo-only,
  sticker (meme), voice, file, and all-mixed combos. Verifies the
  correct ``ZaloClient`` method is called with the exact payload and that
  ``_safe_on_reply`` fires the right number of times.

Run: ``python3 tests/test_round_trip.py``
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

# Bootstrap: add the plugin dir (containing the ``zalo`` package) to the
# import path so ``from zalo.channel import ...`` works when run as a script.
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from zalo.channel import ZaloChannel  # noqa: E402
from zalo.routing import (           # noqa: E402
    Action,
    _extract_actions,
)
from zalo.thinking import (         # noqa: E402
    _strip_thinking,
    _strip_null_tokens,
)
from zalo.dispatch import (         # noqa: E402
    _dispatch_text_actions,
    _dispatch_local_file,
)


# ===========================================================================
# Test infrastructure — captured calls + mock ZaloClient
# ===========================================================================

class MockClient:
    """Captures every outbound Zalo API call into ``calls``."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    async def send_message(self, *, chat_id: str, text: str) -> Dict[str, Any]:
        self.calls.append(("send_message", {"chat_id": chat_id, "text": text}))
        return {"ok": True}

    async def send_photo(self, *, chat_id: str, photo: str) -> Dict[str, Any]:
        self.calls.append(("send_photo", {"chat_id": chat_id, "photo": photo}))
        return {"ok": True}

    async def send_sticker(self, *, chat_id: str, sticker: str) -> Dict[str, Any]:
        self.calls.append(("send_sticker", {"chat_id": chat_id, "sticker": sticker}))
        return {"ok": True}

    async def send_voice(self, *, chat_id: str, voice_url: str) -> Dict[str, Any]:
        self.calls.append(("send_voice", {"chat_id": chat_id, "voice": voice_url}))
        return {"ok": True}


def make_channel() -> Tuple[ZaloChannel, MockClient, List[Tuple[str, bool]]]:
    """Build a ZaloChannel instance without running __init__.

    Returns ``(channel, mock_client, on_reply_log)`` where ``on_reply_log``
    records every ``_safe_on_reply(chat_id, is_group=...)`` invocation.
    """
    ch = ZaloChannel.__new__(ZaloChannel)
    client = MockClient()
    ch._client = client  # type: ignore[attr-defined]

    on_reply_log: List[Tuple[str, bool]] = []

    def fake_safe_on_reply(real_chat_id: str, *, is_group: bool = False) -> None:
        on_reply_log.append((real_chat_id, is_group))

    ch._safe_on_reply = fake_safe_on_reply  # type: ignore[assignment]
    return ch, client, on_reply_log


# ===========================================================================
# Tiny test harness (no external test framework)
# ===========================================================================

PASS = 0
FAIL = 0
FAILURES: List[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
        return True
    FAIL += 1
    msg = f"[FAIL] {name} — {detail}"
    print(msg)
    FAILURES.append(msg)
    return False


def eq(a: Any, b: Any, name: str) -> bool:
    ok = a == b
    detail = "" if ok else f"a={a!r} b={b!r}"
    return check(name, ok, detail)


# ===========================================================================
# 1) routing._extract_actions
# ===========================================================================

def test_extract_actions() -> None:
    print("\n── routing._extract_actions ──")

    # Plain text → no actions
    actions, leftover = _extract_actions("Hello, how are you?")
    eq(actions, [], "plain text → 0 actions")
    eq(leftover, "Hello, how are you?", "plain text kept verbatim")

    # Markdown image
    actions, leftover = _extract_actions("Nhìn nè ![alt](https://x.com/pic.png)")
    eq(len(actions), 1, "markdown image → 1 action")
    eq(actions[0].kind, "photo", "markdown image → kind=photo")
    eq(actions[0].payload, "https://x.com/pic.png", "markdown image → URL preserved")
    eq(leftover, "Nhìn nè", "markdown removed from leftover")

    # Bare image URL with trailing comma — should strip comma
    actions, leftover = _extract_actions("xem https://x.com/pic.jpg, nó đẹp")
    eq(len(actions), 1, "bare URL with comma → 1 action")
    eq(actions[0].payload, "https://x.com/pic.jpg",
       "bare URL stripped trailing comma")
    eq(leftover, "xem , nó đẹp", "bare URL removed from leftover")

    # Bare URL without image extension → not picked up
    actions, leftover = _extract_actions("trang https://example.com chính hãng")
    eq(actions, [], "non-image URL → 0 actions")
    eq(leftover, "trang https://example.com chính hãng",
       "non-image URL kept in leftover")

    # Magic [IMAGE: url]
    actions, leftover = _extract_actions("Đây [IMAGE: https://x.com/y.png] nhé")
    eq(len(actions), 1, "magic IMAGE → 1 action")
    eq(actions[0].kind, "photo", "magic IMAGE → photo")
    eq(actions[0].payload, "https://x.com/y.png", "magic IMAGE URL preserved")

    # Magic [STICKER: id] — this is the meme/emoji path
    actions, leftover = _extract_actions("haha [STICKER: 12345]")
    eq(len(actions), 1, "magic STICKER → 1 action")
    eq(actions[0].kind, "sticker", "magic STICKER → sticker kind")
    eq(actions[0].payload, "12345", "magic STICKER id preserved")

    # Magic [VOICE: url]
    actions, leftover = _extract_actions("nghe [VOICE: https://x.com/a.mp3] đi")
    eq(len(actions), 1, "magic VOICE → 1 action")
    eq(actions[0].kind, "voice", "magic VOICE → voice kind")
    eq(actions[0].payload, "https://x.com/a.mp3", "magic VOICE URL preserved")

    # Magic [FILE: path]
    actions, leftover = _extract_actions("file [FILE: /tmp/foo.txt] đây")
    eq(len(actions), 1, "magic FILE → 1 action")
    eq(actions[0].kind, "local_file", "magic FILE → local_file kind")
    eq(actions[0].payload, "/tmp/foo.txt", "magic FILE path preserved")

    # Mixed: text + sticker + markdown image + bare image
    actions, leftover = _extract_actions(
        "Reply nè ![caption](https://i.io/a.png) và https://i.io/b.jpg, "
        "kèm [STICKER: 999]"
    )
    kinds = [a.kind for a in actions]
    eq(kinds, ["sticker", "photo", "photo"], "mixed order: sticker, photo, photo")

    # Empty input
    actions, leftover = _extract_actions("")
    eq(actions, [], "empty input → 0 actions")
    eq(leftover, "", "empty input → empty leftover")

    # Whitespace / blank line cleanup
    actions, leftover = _extract_actions("A\n\n\n\nB")
    eq(leftover, "A\n\nB", "4+ blank lines collapsed to 2")

    # PNG with query string
    actions, leftover = _extract_actions("see https://x.com/p.png?token=abc")
    eq(len(actions), 1, "PNG + query string → 1 action")
    eq(actions[0].payload, "https://x.com/p.png?token=abc",
       "PNG + query string URL kept intact")


# ===========================================================================
# 2) thinking._strip_thinking / _strip_null_tokens
# ===========================================================================

def test_thinking_strip() -> None:
    print("\n── thinking._strip_thinking / _strip_null_tokens ──")

    # Single-line text without think block: kept verbatim (double-space stays).
    s = _strip_thinking("hello  world")
    eq(s, "hello  world", "text without think block kept verbatim")

    # Multi-line text without think block: kept verbatim.
    s = _strip_thinking("before\n\nline1\nline2\n\nafter")
    eq(s, "before\n\nline1\nline2\n\nafter",
       "text without think block kept verbatim (multi-line)")

    # Lone <think> line
    s = _strip_thinking("a\n<think>\nb")
    eq(s, "a\nb", "lone <think> line removed")

    # Lone </think> line
    s = _strip_thinking("a\n</think>\nb")
    eq(s, "a\nb", "lone </think> line removed")

    # Thinking: label-only line (collapsed to single newline)
    s = _strip_thinking("real\nThinking:\nmore real")
    eq(s, "real\nmore real", "Thinking: label-only removed")

    # Reasoning: label-only (collapsed to single newline)
    s = _strip_thinking("x\nReasoning:\ny")
    eq(s, "x\ny", "Reasoning: label-only removed")

    # Null token leak (line of just "null")
    s = _strip_null_tokens("hello\nnull\nworld")
    eq(s, "hello\nworld", "lone 'null' line removed")

    # Leading null leak
    s = _strip_null_tokens("null\n\nactual reply")
    eq(s, "actual reply", "leading null leak stripped")

    # Multiple null-ish tokens (collapsed to single newline)
    s = _strip_null_tokens("a\nNone\nb\nundefined\nc\nnil\nd")
    eq(s, "a\nb\nc\nd", "all null-ish lines removed")


# ===========================================================================
# 3) dispatch._dispatch_local_file — direct file handling
# ===========================================================================

def test_dispatch_local_file() -> None:
    print("\n── dispatch._dispatch_local_file ──")

    async def run() -> None:
        ch, client, _on_reply = make_channel()

        # Real temp file
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"hello world" * 100)
            tmppath = f.name
        try:
            await _dispatch_local_file(ch, "real-chat-id", tmppath)
            eq(len(client.calls), 1, "real file → 1 send_message")
            method, payload = client.calls[0]
            eq(method, "send_message", "real file → send_message (text info)")
            ok = "File:" in payload["text"] and tmppath in payload["text"]
            check("real file → text contains 'File:' + path", ok, payload["text"][:200])
        finally:
            os.unlink(tmppath)

        # Missing file
        client.calls.clear()
        await _dispatch_local_file(ch, "real-chat-id", "/no/such/path/xyz.png")
        eq(len(client.calls), 1, "missing file → 1 send_message")
        method, payload = client.calls[0]
        ok = "not found" in payload["text"].lower()
        check("missing file → 'not found' message", ok, payload["text"][:120])

        # Unresolvable path (tilde garbage) — exception-safe
        client.calls.clear()
        await _dispatch_local_file(ch, "real-chat-id", "::::")
        eq(len(client.calls), 1, "garbage path → 1 send_message")
        method, payload = client.calls[0]
        ok = ("Cannot resolve" in payload["text"] or "not found" in payload["text"].lower())
        check("garbage path → safe error message", ok, payload["text"][:120])

    asyncio.run(run())


# ===========================================================================
# 4) dispatch._dispatch_text_actions — full 2-way
# ===========================================================================

async def _run_text_only() -> None:
    ch, client, on_reply = make_channel()
    await _dispatch_text_actions(ch, "u1", "Hello world!", is_group=False)
    eq(len(client.calls), 1, "text-only → 1 call")
    method, payload = client.calls[0]
    eq(method, "send_message", "text-only → send_message")
    eq(payload["chat_id"], "u1", "text-only chat_id forwarded")
    eq(payload["text"], "Hello world!", "text-only text verbatim")
    eq(len(on_reply), 1, "text-only → _safe_on_reply fired once")
    eq(on_reply[0], ("u1", False), "text-only _safe_on_reply args")


async def _run_photo_only() -> None:
    ch, client, on_reply = make_channel()
    await _dispatch_text_actions(
        ch, "u1", "xem ![a](https://x.com/a.png)",
        is_group=False,
    )
    eq(len(client.calls), 2, "photo-only → 2 calls (text + photo)")
    eq(client.calls[0][0], "send_message", "photo: text first")
    eq(client.calls[0][1]["text"], "xem", "photo: leftover text")
    eq(client.calls[1][0], "send_photo", "photo: send_photo second")
    eq(client.calls[1][1]["photo"], "https://x.com/a.png", "photo: URL preserved")
    eq(len(on_reply), 2, "photo → 2 _safe_on_reply")


async def _run_sticker_meme() -> None:
    """Sticker is Zalo's meme/emoji path.

    Input ``"hihi [STICKER: aabbcc]"`` splits into leftover text ``hihi``
    + one sticker action, so the dispatch fires ``send_message`` (text)
    first, then ``send_sticker`` — 2 calls and 2 _safe_on_reply.
    """
    ch, client, on_reply = make_channel()
    await _dispatch_text_actions(
        ch, "u1", "hihi [STICKER: aabbcc]",
        is_group=False,
    )
    eq(len(client.calls), 2, "sticker (meme) → 2 calls (text + sticker)")
    eq(client.calls[0][0], "send_message", "sticker: leftover text first")
    eq(client.calls[0][1]["text"], "hihi", "sticker: leftover text content")
    eq(client.calls[1][0], "send_sticker", "sticker: send_sticker second")
    eq(client.calls[1][1]["sticker"], "aabbcc", "sticker id preserved")
    eq(len(on_reply), 2, "sticker → 2 _safe_on_reply")


async def _run_voice() -> None:
    ch, client, on_reply = make_channel()
    await _dispatch_text_actions(
        ch, "u1", "nghe [VOICE: https://x.com/v.mp3]",
        is_group=False,
    )
    eq(len(client.calls), 2, "voice → 2 calls (text + voice)")
    eq(client.calls[0][0], "send_message", "voice: leftover text first")
    eq(client.calls[0][1]["text"], "nghe", "voice: leftover text content")
    eq(client.calls[1][0], "send_voice", "voice: send_voice second")
    eq(client.calls[1][1]["voice"], "https://x.com/v.mp3", "voice URL preserved")
    eq(len(on_reply), 2, "voice → 2 _safe_on_reply")


async def _run_file_marker() -> None:
    ch, client, on_reply = make_channel()
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(b"x" * 2048)
        tmppath = f.name
    try:
        await _dispatch_text_actions(
            ch, "u1", f"đây [FILE: {tmppath}] nè",
            is_group=False,
        )
        # Behavior: leftover "đây  nè" sent first, then file info message.
        eq(len(client.calls), 2, "file marker → 2 calls (text + file info)")
        eq(client.calls[0][0], "send_message", "file: leftover text first")
        ok = "File:" in client.calls[1][1]["text"]
        check("file marker → info message format",
              ok, client.calls[1][1]["text"][:120])
        # Per original semantics: local_file does NOT fire _safe_on_reply
        # (preserved exactly from channel.py refactor).
        eq(len(on_reply), 1, "file marker → 1 _safe_on_reply (text only)")
    finally:
        os.unlink(tmppath)


async def _run_mixed_text_photo_sticker() -> None:
    """Realistic LLM reply: caption + photo + meme sticker."""
    ch, client, on_reply = make_channel()
    await _dispatch_text_actions(
        ch, "u1",
        "Đây nha ![anh](https://i.io/x.png) [STICKER: 42]",
        is_group=False,
    )
    eq(len(client.calls), 3, "mixed text+photo+sticker → 3 calls")
    eq(client.calls[0][0], "send_message", "mixed: text first")
    eq(client.calls[0][1]["text"], "Đây nha", "mixed: leftover text")
    eq(client.calls[1][0], "send_sticker", "mixed: sticker second (action order)")
    eq(client.calls[1][1]["sticker"], "42", "mixed: sticker id")
    eq(client.calls[2][0], "send_photo", "mixed: photo third (action order)")
    eq(client.calls[2][1]["photo"], "https://i.io/x.png", "mixed: photo URL")
    eq(len(on_reply), 3, "mixed → 3 _safe_on_reply")


async def _run_group_chat() -> None:
    """is_group=True should propagate to _safe_on_reply."""
    ch, client, on_reply = make_channel()
    await _dispatch_text_actions(
        ch, "gGroup1", "alo nhóm", is_group=True,
    )
    eq(len(client.calls), 1, "group → 1 send_message")
    eq(client.calls[0][1]["chat_id"], "gGroup1", "group → raw chat_id (no prefix)")
    eq(on_reply[0], ("gGroup1", True), "group → _safe_on_reply is_group=True")


async def _run_no_actions_no_text() -> None:
    """Empty input → no calls at all."""
    ch, client, on_reply = make_channel()
    await _dispatch_text_actions(ch, "u1", "", is_group=False)
    eq(client.calls, [], "empty input → 0 calls")
    eq(on_reply, [], "empty input → 0 _safe_on_reply")


async def _run_only_actions_no_text() -> None:
    """Just an action, no surrounding text → no send_message, only photo."""
    ch, client, on_reply = make_channel()
    await _dispatch_text_actions(
        ch, "u1", "![a](https://x.com/q.png)", is_group=False,
    )
    eq(len(client.calls), 1, "photo-only-no-text → 1 call")
    eq(client.calls[0][0], "send_photo", "photo-only → send_photo")
    eq(len(on_reply), 1, "photo-only-no-text → 1 _safe_on_reply")


def test_dispatch_text_actions() -> None:
    print("\n── dispatch._dispatch_text_actions (2-way) ──")
    asyncio.run(_run_text_only())
    asyncio.run(_run_photo_only())
    asyncio.run(_run_sticker_meme())
    asyncio.run(_run_voice())
    asyncio.run(_run_file_marker())
    asyncio.run(_run_mixed_text_photo_sticker())
    asyncio.run(_run_group_chat())
    asyncio.run(_run_no_actions_no_text())
    asyncio.run(_run_only_actions_no_text())


# ===========================================================================
# Main
# ===========================================================================

def main() -> int:
    test_extract_actions()
    test_thinking_strip()
    test_dispatch_local_file()
    test_dispatch_text_actions()

    print(f"\n=== {PASS} pass / {FAIL} fail / {PASS + FAIL} total ===")
    if FAILURES:
        print("\nFailures:")
        for f in FAILURES:
            print(" -", f)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
