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


def call_qwenpaw(prompt: str, session_id: str) -> str:
    """Send prompt to QwenPaw console chat API and collect SSE response."""
    payload = {
        "channel": "console",
        "user_id": "review-bot",
        "session_id": session_id,
        "input": [{"content": [{"type": "text", "text": prompt}]}],
    }

    full_response = ""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[attempt {attempt}/{MAX_RETRIES}] Calling QwenPaw...")
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
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            evt = json.loads(data)
                            if evt.get("error"):
                                print(f"  Stream error: {evt['error']}")
                            chunk = evt.get("content", evt.get("text", ""))
                            full_response += chunk
                        except json.JSONDecodeError:
                            pass

            if full_response.strip():
                return full_response

            print("  Empty response, retrying...")
            time.sleep(5)

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            print(f"  Error: {e}, retrying...")
            time.sleep(5)

    return full_response


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
