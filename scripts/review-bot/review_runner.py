#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QwenPaw AI Review Bot - Main runner script.

This script runs inside GitHub Actions to:
1. Read PR diff from /tmp/pr_diff.txt
2. Send it to the local QwenPaw instance for review
3. Parse the response and output verdict + review text
"""
import json
import os
import re
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# pylint: disable=wrong-import-position
from prompts import (
    build_review_prompt,
)  # noqa: E402
from qwenpaw.agents.tools.agent_management import (  # noqa: E402
    extract_agent_text_content,
    parse_agent_sse_line,
)

# pylint: enable=wrong-import-position

QWENPAW_URL = "http://localhost:8088"
CHAT_ENDPOINT = f"{QWENPAW_URL}/api/console/chat"
MAX_RETRIES = 3
TIMEOUT_SECONDS = 180


def read_pr_data():
    """Read PR metadata and diff from temp files written by github-script."""
    with open("/tmp/pr_meta.json", encoding="utf-8") as f:
        meta = json.load(f)
    with open("/tmp/pr_diff.txt", encoding="utf-8") as f:
        diff = f.read()
    return meta, diff


def _extract_stream_text(evt: dict) -> str:
    """Extract text from a single SSE payload (streaming or final)."""
    text = extract_agent_text_content(evt)
    if text:
        return text

    content = evt.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
        return "".join(parts)

    fallback = evt.get("text")
    return fallback if isinstance(fallback, str) else ""


def call_qwenpaw(prompt: str, session_id: str) -> str:
    """Send prompt to QwenPaw console chat API and collect SSE response."""
    payload = {
        "channel": "console",
        "user_id": "review-bot",
        "session_id": session_id,
        "input": [{"content": [{"type": "text", "text": prompt}]}],
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[attempt {attempt}/{MAX_RETRIES}] Calling QwenPaw...")
            final_event = None
            stream_errors = []

            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                with client.stream(
                    "POST",
                    CHAT_ENDPOINT,
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        print(f"  HTTP {resp.status_code}, retrying...")
                        time.sleep(5)
                        continue

                    for line in resp.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        if line[6:] == "[DONE]":
                            break

                        parsed = parse_agent_sse_line(line)
                        if not parsed:
                            continue
                        if parsed.get("error"):
                            stream_errors.append(str(parsed["error"]))
                        if parsed.get("type") == "turn_usage":
                            continue
                        final_event = parsed

            if stream_errors:
                print(f"  Stream errors: {'; '.join(stream_errors)}")

            response = _extract_stream_text(final_event or {})
            if response.strip():
                return response

            print("  Empty response, retrying...")
            time.sleep(5)

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            print(f"  Error: {e}, retrying...")
            time.sleep(5)

    return ""


def parse_verdict(response: str) -> str:
    """Extract verdict from the review response JSON block."""
    match = re.search(
        r"```json\s*(\{.*?\})\s*```",
        response,
        re.DOTALL,
    )
    if match:
        try:
            result = json.loads(match.group(1))
            verdict = result.get("verdict", "REQUEST_CHANGES")
            if verdict in ("APPROVE", "REQUEST_CHANGES"):
                return verdict
        except json.JSONDecodeError:
            pass
    return "REQUEST_CHANGES"


def write_outputs(verdict: str, review_text: str):
    """Write results to GITHUB_OUTPUT and temp file for later steps."""
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"verdict={verdict}\n")

    with open("/tmp/review_result.md", "w", encoding="utf-8") as f:
        f.write(review_text)


def main():
    print("=" * 60)
    print("QwenPaw AI Review Bot")
    print("=" * 60)

    meta, diff = read_pr_data()
    print(f"\nPR #{meta['number']}: {meta['title']}")
    print(f"Author: {meta['author']}")
    print(f"Branch: {meta['head']} → {meta['base']}")
    print(
        f"Files: {meta['file_count']}, +{meta['additions']}/-{meta['deletions']}",
    )
    print(f"Diff size: {len(diff)} chars")

    prompt = build_review_prompt(meta, diff)
    print(f"\nPrompt size: {len(prompt)} chars")

    session_id = f"pr-review-{meta['number']}-{int(time.time())}"
    print(f"\nSession: {session_id}")
    print("Sending to QwenPaw...")

    response = call_qwenpaw(prompt, session_id)

    if not response.strip():
        print("\n❌ ERROR: Got empty response from QwenPaw")
        fallback = (
            "AI Review Bot 未能生成审查结果。可能的原因：\n"
            "- LLM API 超时或不可用\n"
            "- diff 内容过大\n\n"
            "请 maintainer 手动审查此 PR。\n\n"
            '```json\n{"verdict": "REQUEST_CHANGES", '
            '"summary": "Review failed"}\n```'
        )
        write_outputs("REQUEST_CHANGES", fallback)
        sys.exit(0)

    verdict = parse_verdict(response)
    print(f"\n{'✅' if verdict == 'APPROVE' else '⚠️'} Verdict: {verdict}")
    print(f"Response length: {len(response)} chars")

    write_outputs(verdict, response)
    print("\n✅ Done! Results written to /tmp/review_result.md")


if __name__ == "__main__":
    main()
