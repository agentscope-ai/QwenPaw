#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QwenPaw AI Review Bot - Main runner script.

This script runs inside GitHub Actions to:
1. Read PR number and repo from environment variables
2. Send a task prompt to the local QwenPaw instance
3. QwenPaw autonomously fetches PR data via `gh` CLI
4. Parse the response and output verdict + review text
"""
import json
import os
import re
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# pylint: disable=wrong-import-position
from prompts import build_review_prompt  # noqa: E402
from qwenpaw.agents.tools.agent_management import (  # noqa: E402
    extract_agent_text_content,
    parse_agent_sse_line,
)

# pylint: enable=wrong-import-position

QWENPAW_URL = "http://localhost:8088"
CHAT_ENDPOINT = f"{QWENPAW_URL}/api/console/chat"
MAX_RETRIES = 3
TIMEOUT_SECONDS = 300


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


def validate_response(response: str, pr_number: int) -> list[str]:
    """Check that the response contains signs of real PR data.

    Returns a list of warning messages (empty = all checks passed).
    """
    warnings = []
    if f"#{pr_number}" not in response and str(pr_number) not in response:
        warnings.append(
            f"Response does not mention PR #{pr_number} — "
            f"agent may not have fetched PR data",
        )
    structure_markers = ["### 1.", "### 2.", "### 3.", "verdict"]
    missing = [m for m in structure_markers if m not in response]
    if missing:
        warnings.append(
            f"Missing expected sections: {', '.join(missing)}",
        )
    return warnings


def parse_verdict(response: str) -> dict:
    """Extract verdict and issue counts from the review response JSON block.

    Returns a dict with keys: verdict, high_count, medium_count, low_count.
    """
    default = {
        "verdict": "REQUEST_CHANGES",
        "high_count": -1,
        "medium_count": -1,
        "low_count": -1,
    }
    match = re.search(
        r"```json\s*(\{.*?\})\s*```",
        response,
        re.DOTALL,
    )
    if not match:
        return default
    try:
        result = json.loads(match.group(1))
    except json.JSONDecodeError:
        return default

    verdict = result.get("verdict", "REQUEST_CHANGES")
    if verdict not in ("APPROVE", "REQUEST_CHANGES"):
        verdict = "REQUEST_CHANGES"

    return {
        "verdict": verdict,
        "high_count": int(result.get("high_count", -1)),
        "medium_count": int(result.get("medium_count", -1)),
        "low_count": int(result.get("low_count", -1)),
    }


def write_outputs(verdict_info: dict, review_text: str):
    """Write results to GITHUB_OUTPUT and temp file for later steps."""
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"verdict={verdict_info['verdict']}\n")
            f.write(f"high_count={verdict_info['high_count']}\n")
            f.write(f"medium_count={verdict_info['medium_count']}\n")

    with open("/tmp/review_result.md", "w", encoding="utf-8") as f:
        f.write(review_text)


def main():
    print("=" * 60)
    print("QwenPaw AI Review Bot")
    print("=" * 60)

    pr_number = os.environ.get("PR_NUMBER")
    repo = os.environ.get("PR_REPO")

    if not pr_number or not repo:
        print(
            "ERROR: PR_NUMBER and PR_REPO environment variables "
            "are required.",
        )
        sys.exit(1)

    pr_number = int(pr_number)
    print(f"\nTarget: {repo} PR #{pr_number}")

    prompt = build_review_prompt(pr_number, repo)
    print(f"Prompt size: {len(prompt)} chars")

    session_id = f"pr-review-{pr_number}-{int(time.time())}"
    print(f"Session: {session_id}")
    print("Sending task to QwenPaw (agent will fetch PR data via gh)...")

    response = call_qwenpaw(prompt, session_id)

    if not response.strip():
        print("\n❌ ERROR: Got empty response from QwenPaw")
        fallback = (
            "AI Review Bot 未能生成审查结果。可能的原因：\n"
            "- LLM API 超时或不可用\n"
            "- `gh` CLI 认证失败\n"
            "- diff 内容过大\n\n"
            "请 maintainer 手动审查此 PR。\n\n"
            '```json\n{"verdict": "REQUEST_CHANGES", '
            '"high_count": -1, "medium_count": -1, "low_count": -1, '
            '"summary": "Review failed"}\n```'
        )
        fail_info = {
            "verdict": "REQUEST_CHANGES",
            "high_count": -1,
            "medium_count": -1,
            "low_count": -1,
        }
        write_outputs(fail_info, fallback)
        sys.exit(0)

    warnings = validate_response(response, pr_number)
    if warnings:
        for w in warnings:
            print(f"  ⚠️  {w}")

    verdict_info = parse_verdict(response)
    verdict = verdict_info["verdict"]
    high = verdict_info["high_count"]
    medium = verdict_info["medium_count"]

    print(f"\n{'✅' if verdict == 'APPROVE' else '⚠️'} Verdict: {verdict}")
    print(f"Issues: High={high}, Medium={medium}")
    print(f"Response length: {len(response)} chars")

    write_outputs(verdict_info, response)
    print("\n✅ Done! Results written to /tmp/review_result.md")


if __name__ == "__main__":
    main()
