# -*- coding: utf-8 -*-
"""Local test cho group-chat support (T5).

Mock Zalo event GROUP + PRIVATE, gọi build_agent_request_from_native /
resolve_session_id / _safe_on_reply, assert:
  - GROUP  → session_id == 'zalo:group:{chat_id}', content có prefix.
  - PRIVATE → session_id == 'zalo:{sender_id}', content không đổi.
  - 2 group khác nhau → 2 session khác nhau.
  - Cùng user 2 group → không lẫn.
  - _safe_on_reply session khớp resolve_session_id (consistency).

Chạy: python3 tests/test_group_chat.py
Không cần real Zalo — dùng mock event dict + stub build_agent_request.
"""

from __future__ import annotations

import sys
import os
from types import SimpleNamespace
from typing import Any, Dict, List

# Bootstrap: add the plugin dir (containing the ``zalo`` package) to the
# import path so ``from zalo.channel import ...`` works when run as a script.
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from qwenpaw.app.channels.base import TextContent

from zalo.channel import ZaloChannel, _dispatch_text_actions


# ---------------------------------------------------------------------------
# Helpers: tạo instance không qua __init__ (tránh cần bot token / process).
# ---------------------------------------------------------------------------
def make_channel() -> ZaloChannel:
    """ZaloChannel instance tối thiểu — chỉ để test pure logic."""
    ch = ZaloChannel.__new__(ZaloChannel)

    captured: Dict[str, Any] = {}

    # Stub base-class heavy lifting: chỉ capture args, trả namespace giả.
    def fake_build(channel_id, sender_id, session_id, content_parts, channel_meta):
        captured["session_id"] = session_id
        captured["sender_id"] = sender_id
        captured["content_parts"] = list(content_parts)
        captured["channel_meta"] = channel_meta
        req = SimpleNamespace(
            session_id=session_id,
            channel_meta=dict(channel_meta),
            _captured=content_parts,
        )
        return req

    ch.build_agent_request_from_user_content = fake_build  # type: ignore[assignment]
    ch._captured = captured  # type: ignore[attr-defined]
    ch._on_reply_sent = None  # mặc định noop
    return ch


def group_payload(group_id: str, sender_id: str, sender_name: str, text: str) -> Dict[str, Any]:
    """Mock native payload cho tin nhắn GROUP."""
    return {
        "channel_id": "zalo",
        "sender_id": sender_id,
        "content_parts": [TextContent(text=text)],
        "meta": {
            "chat_id": group_id,
            "message_id": "msg-" + group_id,
            "from": sender_id,
            "from_name": sender_name,
            "chat_type": "GROUP",
        },
    }


def private_payload(sender_id: str, sender_name: str, text: str) -> Dict[str, Any]:
    """Mock native payload cho tin nhắn PRIVATE."""
    return {
        "channel_id": "zalo",
        "sender_id": sender_id,
        "content_parts": [TextContent(text=text)],
        "meta": {
            "chat_id": sender_id,
            "message_id": "msg-priv-" + sender_id,
            "from": sender_id,
            "from_name": sender_name,
            "chat_type": "PRIVATE",
        },
    }


def text_of(req: Any) -> str:
    """Ghép text từ content_parts để kiểm tra prefix."""
    parts: List[str] = []
    for blk in req._captured:
        t = getattr(blk, "text", None)
        if t:
            parts.append(str(t))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
results: List[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f" — {detail}"
    results.append(line)
    print(line)


def main() -> int:
    ch = make_channel()

    # --- resolve_session_id trực tiếp ---------------------------------
    sid_group = ch.resolve_session_id("u1", {"chat_type": "GROUP", "chat_id": "gABC"})
    sid_priv = ch.resolve_session_id("c70a1a04e851010f5840", {"chat_type": "PRIVATE", "chat_id": "c70a1a04e851010f5840"})
    sid_novalue = ch.resolve_session_id("u1", {"chat_type": "GROUP"})  # GROUP nhưng thiếu chat_id
    check("resolve GROUP → zalo:group:gABC", sid_group == "zalo:group:gABC", f"got {sid_group!r}")
    check("resolve PRIVATE → zalo:{sender_id}", sid_priv == "zalo:c70a1a04e851010f5840", f"got {sid_priv!r}")
    # GROUP mà không có chat_id → fallback private (an toàn)
    check("resolve GROUP thiếu chat_id → fallback zalo:u1", sid_novalue == "zalo:u1", f"got {sid_novalue!r}")

    # --- build_agent_request_from_native: GROUP ----------------------
    req_g = ch.build_agent_request_from_native(
        group_payload("gABC", "u1", "An", "xin chào cả nhà")
    )
    check(
        "GROUP session_id == zalo:group:gABC",
        req_g.session_id == "zalo:group:gABC",
        f"got {req_g.session_id!r}",
    )
    gtext = text_of(req_g)
    check(
        "GROUP content bắt đầu bằng '[An trong nhóm gABC]: '",
        gtext.startswith("[An trong nhóm gABC]: "),
        f"got {gtext!r}",
    )
    check(
        "GROUP content còn giữ text gốc",
        "xin chào cả nhà" in gtext,
        f"got {gtext!r}",
    )

    # --- build_agent_request_from_native: PRIVATE --------------------
    req_p = ch.build_agent_request_from_native(
        private_payload("c70a1a04e851010f5840", "An", "hello private")
    )
    check(
        "PRIVATE session_id == zalo:{sender_id}",
        req_p.session_id == "zalo:c70a1a04e851010f5840",
        f"got {req_p.session_id!r}",
    )
    ptext = text_of(req_p)
    check(
        "PRIVATE content KHÔNG có prefix nhóm",
        not ptext.startswith("["),
        f"got {ptext!r}",
    )
    check(
        "PRIVATE content giữ nguyên 'hello private'",
        ptext == "hello private",
        f"got {ptext!r}",
    )

    # --- 2 group khác nhau → 2 session khác nhau ---------------------
    req_g2 = ch.build_agent_request_from_native(
        group_payload("gXYZ", "u2", "Bình", "group khác")
    )
    check(
        "2 group khác nhau → 2 session khác nhau",
        req_g.session_id != req_g2.session_id
        and req_g.session_id == "zalo:group:gABC"
        and req_g2.session_id == "zalo:group:gXYZ",
        f"{req_g.session_id!r} vs {req_g2.session_id!r}",
    )

    # --- Cùng user 2 group → không lẫn session ----------------------
    req_same_a = ch.build_agent_request_from_native(
        group_payload("gABC", "uSame", "Trung", "nhắn group A")
    )
    req_same_b = ch.build_agent_request_from_native(
        group_payload("gXYZ", "uSame", "Trung", "nhắn group B")
    )
    check(
        "Cùng user 2 group → session khác nhau (không lẫn)",
        req_same_a.session_id == "zalo:group:gABC"
        and req_same_b.session_id == "zalo:group:gXYZ"
        and req_same_a.session_id != req_same_b.session_id,
        f"{req_same_a.session_id!r} vs {req_same_b.session_id!r}",
    )
    # Prefix phải ghi đúng tên/nguồn riêng từng group
    check(
        "Cùng user: prefix group A đúng '[Trung trong nhóm gABC]'",
        text_of(req_same_a).startswith("[Trung trong nhóm gABC]: "),
        f"got {text_of(req_same_a)!r}",
    )
    check(
        "Cùng user: prefix group B đúng '[Trung trong nhóm gXYZ]'",
        text_of(req_same_b).startswith("[Trung trong nhóm gXYZ]: "),
        f"got {text_of(req_same_b)!r}",
    )

    # --- Private vs group cùng user → session khác nhau ---------------
    req_priv_same = ch.build_agent_request_from_native(
        private_payload("uSame", "Trung", "inbox riêng")
    )
    check(
        "Cùng user: private vs group session khác nhau",
        req_priv_same.session_id == "zalo:uSame"
        and req_same_a.session_id == "zalo:group:gABC"
        and req_priv_same.session_id != req_same_a.session_id,
        f"{req_priv_same.session_id!r} vs {req_same_a.session_id!r}",
    )

    # --- _safe_on_reply: session khớp resolve_session_id -------------
    captured_reply: Dict[str, Any] = {}

    def fake_on_reply_sent(channel, real_chat_id, session_id):
        captured_reply["channel"] = channel
        captured_reply["real_chat_id"] = real_chat_id
        captured_reply["session_id"] = session_id

    ch._on_reply_sent = fake_on_reply_sent

    # Reply cho group: real_chat_id = raw group id, session = zalo:group:{id}
    ch._safe_on_reply("gABC", is_group=True)
    check(
        "_safe_on_reply GROUP → session 'zalo:group:gABC'",
        captured_reply.get("session_id") == "zalo:group:gABC"
        and captured_reply.get("real_chat_id") == "gABC",
        f"got {captured_reply!r}",
    )
    # Khớp resolve_session_id của group
    check(
        "_safe_on_reply GROUP session == resolve_session_id",
        captured_reply.get("session_id") == ch.resolve_session_id("u1", {"chat_type": "GROUP", "chat_id": "gABC"}),
        f"reply={captured_reply.get('session_id')!r}",
    )

    # Reply cho private: session = zalo:{sender_id}
    ch._safe_on_reply("c70a1a04e851010f5840", is_group=False)
    check(
        "_safe_on_reply PRIVATE → session 'zalo:{id}'",
        captured_reply.get("session_id") == "zalo:c70a1a04e851010f5840",
        f"got {captured_reply!r}",
    )
    check(
        "_safe_on_reply PRIVATE session == resolve_session_id",
        captured_reply.get("session_id") == ch.resolve_session_id(
            "c70a1a04e851010f5840",
            {"chat_type": "PRIVATE", "chat_id": "c70a1a04e851010f5840"},
        ),
        f"reply={captured_reply.get('session_id')!r}",
    )

    # --- send(): reply routing (real_chat_id strip prefix) ----------
    # Mock async client — chỉ capture chat_id thật mà Zalo nhận được.
    sent: List[Dict[str, Any]] = []

    class _MockClient:
        async def send_message(self, chat_id, text, **kw):
            sent.append({"chat_id": chat_id, "text": text})

    ch._client = _MockClient()
    ch._stop_typing = lambda *a, **k: None  # type: ignore[attr-defined]
    ch._is_processing = {}  # type: ignore[attr-defined]

    reply_sessions: List[str] = []
    ch._on_reply_sent = lambda c, r, s: reply_sessions.append(s)

    import asyncio

    # GROUP reply: chat_id = session 'zalo:group:gABC', meta có chat_id raw
    asyncio.get_event_loop().run_until_complete(
        ch.send("zalo:group:gABC", TextContent(text="reply nhóm"), meta={
            "chat_id": "gABC", "chat_type": "GROUP",
        })
    )
    check(
        "send() GROUP → Zalo nhận raw 'gABC' (không 'group:gABC')",
        sent and sent[-1]["chat_id"] == "gABC",
        f"got {sent[-1] if sent else None!r}",
    )
    check(
        "send() GROUP → _safe_on_reply session 'zalo:group:gABC'",
        reply_sessions and reply_sessions[-1] == "zalo:group:gABC",
        f"got {reply_sessions!r}",
    )

    # PRIVATE reply: backward-compat, chat_id = 'zalo:{sender_id}'
    asyncio.get_event_loop().run_until_complete(
        ch.send("zalo:c70a1a04e851010f5840", TextContent(text="reply private"), meta={
            "chat_id": "c70a1a04e851010f5840", "chat_type": "PRIVATE",
        })
    )
    check(
        "send() PRIVATE → Zalo nhận raw sender id",
        sent[-1]["chat_id"] == "c70a1a04e851010f5840",
        f"got {sent[-1]!r}",
    )
    check(
        "send() PRIVATE → _safe_on_reply session 'zalo:{sender_id}'",
        reply_sessions[-1] == "zalo:c70a1a04e851010f5840",
        f"got {reply_sessions[-1]!r}",
    )

    # Fallback: meta thiếu chat_id → strip 'zalo:group:' đúng
    asyncio.get_event_loop().run_until_complete(
        ch.send("zalo:group:gABC", TextContent(text="fallback strip"), meta={})
    )
    check(
        "send() fallback (meta rỗng) → strip 'zalo:group:' → 'gABC'",
        sent[-1]["chat_id"] == "gABC",
        f"got {sent[-1]!r}",
    )
    # Fallback private session-only → strip 'zalo:'
    asyncio.get_event_loop().run_until_complete(
        ch.send("zalo:c70a1a04e851010f5840", TextContent(text="fb private"), meta={})
    )
    check(
        "send() fallback private → strip 'zalo:' → sender id",
        sent[-1]["chat_id"] == "c70a1a04e851010f5840",
        f"got {sent[-1]!r}",
    )

    # --- Summary -----------------------------------------------------
    n_pass = sum(1 for r in results if r.startswith("[PASS]"))
    n_fail = sum(1 for r in results if r.startswith("[FAIL]"))
    print(f"\n=== {n_pass} pass / {n_fail} fail / {len(results)} total ===")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
