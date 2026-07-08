# -*- coding: utf-8 -*-
"""Reproduce #5479: large session (>500KB) blanks the Console Web UI.

Strategy:
- Start a real Chrome (channel=chrome, no extra download).
- Point it at the isolated local backend (port 7077).
- Intercept GET /api/chats/{id} and return a synthetic 500KB / 1MB / 2MB
  ChatHistory payload (messages array of user/assistant turns).
- Open the chat in the Console, wait for render, capture:
    * page screenshot
    * uncaught console errors / page errors
    * whether the "渲染此页面时发生了意外错误" error boundary fired
    * DOM node count + memory approximation

Run:
    /Users/remy/work/QwenPaw/.venv/bin/python scripts/repro_5479.py
"""
from __future__ import annotations

import json
import random
import string
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Route, Request

BACKEND = "http://127.0.0.1:7077"
OUT_DIR = Path("/tmp/repro-5479")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# A real-ish assistant paragraph — repeated to bloat message size.
LOREM = (
    "这是一段用于填充大会话的中文文本。QwenPaw agent 在执行研究任务时会读取文件、"
    "调用 skill，产生大量 assistant 输出。每条消息约 200 字节，"
    "我们要构造一个 >500KB 的会话来复现 #5479。"
)


def build_messages(target_bytes: int, turn_count: int = 60) -> list[dict]:
    """Build a ChatHistory.messages array of approximately target_bytes JSON."""
    per_turn = max(1, target_bytes // (turn_count * 2))
    msgs: list[dict] = []
    for t in range(turn_count):
        # user turn
        msgs.append({
            "id": f"u-{t}",
            "role": "user",
            "content": [{"type": "text", "text": f"用户第 {t} 轮提问：{LOREM * (per_turn // 400)}"}],
            "metadata": {"timestamp": f"2026-06-01 10:{t % 60:02d}:00.000"},
        })
        # assistant turn with 3 streaming segments
        for s in range(3):
            msgs.append({
                "id": f"a-{t}-{s}",
                "role": "assistant",
                "content": [{"type": "text", "text": LOREM * (per_turn // 300)}],
                "metadata": {
                    "timestamp": f"2026-06-01 10:{t % 60:02d}:{s * 10:02d}.000",
                },
            })
    return msgs


def make_history(target_bytes: int) -> dict:
    msgs = build_messages(target_bytes)
    body = {"messages": msgs, "status": "idle"}
    size = len(json.dumps(body))
    return body, size


def run_one(p, label: str, target_bytes: int, chat_id: str) -> dict:
    """Open the chat list, click into a chat, intercept get_chat with big payload."""
    print(f"\n=== {label}: target {target_bytes} bytes ===")
    body, actual_size = make_history(target_bytes)
    print(f"  synthetic ChatHistory size: {actual_size} bytes ({actual_size/1024:.1f} KB)")

    browser = p.chromium.launch(channel="chrome", headless=False)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    errors: list[str] = []
    page_errors: list[str] = []
    api_calls: list[str] = []

    page.on("console", lambda msg: errors.append(f"[{msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.on("request", lambda req: api_calls.append(f"{req.method} {req.url}") if "chats" in req.url else None)

    # Intercept ALL chat detail GETs — return big payload regardless of id.
    def handler(route: Route, request: Request):
        url = request.url
        # Match /api/chats/{uuid} but NOT /api/chats (list) or /api/chats/batch-delete
        if request.method == "GET" and "/chats/" in url:
            # Skip list endpoint (ends with /chats or /chats/)
            after = url.split("/chats/")[-1]
            if after and not after.startswith("batch"):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(body),
                )
                return
        route.continue_()

    page.route("**/api/chats/**", handler)

    # Navigate directly to the chat
    page.goto(f"{BACKEND}/?chat_id={chat_id}", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)

    # Also try clicking the chat in the sidebar in case query param isn't honored
    try:
        page.get_by_text("Large Session Test", exact=False).first.click(timeout=5000)
    except Exception:
        pass

    # Wait for the render to settle (this is where #5479 crashes)
    print("  waiting for render (15s window)...")
    t0 = time.time()
    page.wait_for_timeout(15000)
    elapsed = time.time() - t0

    # Detect the QwenPaw error boundary
    boundary_fired = False
    try:
        boundary_fired = page.get_by_text("渲染此页面时发生了意外错误", exact=False).count() > 0
    except Exception:
        pass
    try:
        boundary_fired = boundary_fired or page.get_by_text("unexpected error", exact=False).count() > 0
    except Exception:
        pass

    # Blank page check
    body_text = ""
    try:
        body_text = page.inner_text("body")
    except Exception:
        pass
    blank = len(body_text.strip()) < 20

    # DOM node count + approx memory
    dom_count = page.evaluate("document.querySelectorAll('*').length")
    mem = page.evaluate(
        "() => performance.memory ? "
        "{used: Math.round(performance.memory.usedJSHeapSize/1048576), "
        "total: Math.round(performance.memory.totalJSHeapSize/1048576)} : null"
    )

    shot = OUT_DIR / f"{label}.png"
    page.screenshot(path=str(shot), full_page=False)

    console_log = OUT_DIR / f"{label}.console.txt"
    console_log.write_text(
        "\n".join(errors + ["---PAGE ERRORS---"] + page_errors + ["---API CALLS---"] + api_calls),
        encoding="utf-8",
    )

    result = {
        "label": label,
        "target_bytes": target_bytes,
        "actual_size_bytes": actual_size,
        "elapsed_s": round(elapsed, 1),
        "boundary_fired": boundary_fired,
        "blank": blank,
        "dom_count": dom_count,
        "memory_mb": mem,
        "console_errors": len([e for e in errors if e.startswith("[error]")]),
        "page_errors": len(page_errors),
        "screenshot": str(shot),
    }
    print(f"  RESULT: {result}")

    context.close()
    browser.close()
    return result


def main():
    # Get a real chat_id from the backend
    import urllib.request
    resp = urllib.request.urlopen(f"{BACKEND}/api/chats")
    chats = json.loads(resp.read())
    target_chat = next((c for c in chats if c.get("name") == "Large Session Test"), None)
    if not target_chat:
        print("ERROR: no 'Large Session Test' chat found; create one first")
        sys.exit(1)
    chat_id = target_chat["id"]
    print(f"Using chat_id: {chat_id}")

    results = []
    with sync_playwright() as p:
        # Ascending sizes — 200KB (control), 500KB, 1MB, 2MB
        for label, kb in [("200kb-control", 200), ("500kb", 500), ("1mb", 1024), ("2mb", 2048)]:
            try:
                results.append(run_one(p, label, kb * 1024, chat_id))
            except Exception as e:
                print(f"  FAILED: {e}")
                results.append({"label": label, "error": str(e)})

    print("\n========== SUMMARY ==========")
    for r in results:
        if "error" in r:
            print(f"  {r['label']}: ERROR {r['error']}")
            continue
        crash = r["boundary_fired"] or r["blank"] or r["page_errors"] > 0
        status = "💥 CRASH" if crash else "✅ OK"
        print(f"  {r['label']:15s} {status}  size={r['actual_size_bytes']/1024:.0f}KB  "
              f"dom={r['dom_count']}  mem={r['memory_mb']}  "
              f"console_err={r['console_errors']}  page_err={r['page_errors']}  "
              f"boundary={r['boundary_fired']}  blank={r['blank']}")

    # Verdict
    print("\n========== VERDICT ==========")
    reproduced = any(
        r.get("boundary_fired") or r.get("blank") or r.get("page_errors", 0) > 0
        for r in results
        if "error" not in r and r.get("label") in ("500kb", "1mb", "2mb")
    )
    print(f"  #5479 reproduced: {'YES' if reproduced else 'NO (could not reproduce locally)'}")
    print(f"  Screenshots: {OUT_DIR}")


if __name__ == "__main__":
    main()