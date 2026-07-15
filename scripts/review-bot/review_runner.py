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
    structure_markers = ["### 1.", "### 2.", "### 3."]
    missing = [m for m in structure_markers if m not in response]
    if missing:
        warnings.append(
            f"Missing expected sections: {', '.join(missing)}",
        )
    return warnings


def parse_verdict(response: str) -> dict:
    """Extract verdict and issue counts from the Summary section.

    Scopes the search to ``### 6. Summary`` to avoid matching
    unrelated JSON code blocks elsewhere in the review.
    """
    default = {
        "verdict": "REQUEST_CHANGES",
        "high_count": -1,
        "medium_count": -1,
        "low_count": -1,
    }
    summary_match = re.search(r"###\s*6[.\s]", response)
    search_text = (
        response[summary_match.start() :] if summary_match else response
    )

    match = re.search(
        r"```json\s*(\{[\s\S]*?\})\s*```",
        search_text,
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


def _strip_summary_verdict_json(text: str) -> str:
    """Strip the verdict JSON block from the '### 6. Summary' section only.

    Matches a ```json ... ``` block that contains a "verdict" key
    and appears after the '### 6' heading.  Other JSON blocks
    elsewhere in the review (e.g. code examples) are preserved.
    """
    summary_match = re.search(r"(###\s*6[.\s])", text)
    if not summary_match:
        return text

    before = text[: summary_match.start()]
    summary_section = text[summary_match.start() :]

    cleaned = re.sub(
        r"\n*```json\s*\{[\s\S]*?\"verdict\"[\s\S]*?\}\s*```\n*",
        "\n",
        summary_section,
    )
    return (before + cleaned).rstrip()


_FENCE_RE = re.compile(r"^(`{3,})(.*)")


def _scan_fence_block(
    lines: list[str],
    start: int,
    tick_len: int,
) -> tuple[list[str], int]:
    """Find the matching closer for a code fence.

    Tracks open/close depth so that LLM-produced
    pseudo-nested fences are handled correctly.

    Returns ``(body_lines, close_index)``.
    ``close_index`` is ``-1`` if no closer is found.
    """
    depth = 1
    body: list[str] = []
    for j in range(start, len(lines)):
        fm = re.match(rf"^`{{{tick_len},}}", lines[j])
        if fm:
            rest = lines[j][len(fm.group(0)) :].strip()
            if rest:
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return body, j
        body.append(lines[j])
    return body, -1


def _fix_nested_code_fences(text: str) -> str:
    """Bump outer fence width when content has inner fences.

    LLMs often produce pseudo-nested fences where inner
    ````` ``` ````` markers break the outer block.  This
    function uses depth tracking to find the intended
    closer, then increases the outer fence length so
    inner fences become harmless content.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue

        info = m.group(2).strip()
        n = len(m.group(1))
        body, close = _scan_fence_block(lines, i + 1, n)

        max_inner = 0
        for bline in body:
            im = re.match(r"^(`{3,})", bline)
            if im and len(im.group(1)) > max_inner:
                max_inner = len(im.group(1))

        if max_inner >= n:
            fence = "`" * (max_inner + 1)
            tag = f"{fence}{info}" if info else fence
            out.append(tag)
            out.extend(body)
            if close >= 0:
                out.append(fence)
        else:
            out.append(lines[i])
            out.extend(body)
            if close >= 0:
                out.append(lines[close])

        i = close + 1 if close >= 0 else len(lines)

    return "\n".join(out)


_SECRET_ENV_NAMES = [
    "DASHSCOPE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "HUGGINGFACE_TOKEN",
    "HF_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
]

_SECRET_PREFIXES = ("sk-", "ghp_", "gho_", "ghu_", "ghs_", "ghr_")


def _scan_for_leaked_secrets(text: str) -> list[str]:
    """Check review text for potential secret values.

    Returns a list of warning messages for each detected leak.
    """
    warnings = []
    for name in _SECRET_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value and len(value) >= 8 and value in text:
            warnings.append(
                f"Review text contains value of ${name}",
            )
    for prefix in _SECRET_PREFIXES:
        pattern = re.compile(
            re.escape(prefix) + r"[A-Za-z0-9_\-]{20,}",
        )
        if pattern.search(text):
            warnings.append(
                f"Review text contains token-like string "
                f"matching prefix '{prefix}'",
            )
    return warnings


def _redact_secrets(text: str) -> str:
    """Replace known secret values in text with [REDACTED]."""
    result = text
    for name in _SECRET_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value and len(value) >= 8:
            result = result.replace(value, "[REDACTED]")
    for prefix in _SECRET_PREFIXES:
        result = re.sub(
            re.escape(prefix) + r"[A-Za-z0-9_\-]{20,}",
            "[REDACTED]",
            result,
        )
    return result


def write_outputs(verdict_info: dict, review_text: str):
    """Write results to GITHUB_OUTPUT and temp file for later steps."""
    output_file = os.environ.get("GITHUB_OUTPUT", "")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"verdict={verdict_info['verdict']}\n")
            f.write(f"high_count={verdict_info['high_count']}\n")
            f.write(f"medium_count={verdict_info['medium_count']}\n")

    clean_text = _strip_summary_verdict_json(review_text)
    clean_text = _fix_nested_code_fences(clean_text)

    leak_warnings = _scan_for_leaked_secrets(clean_text)
    if leak_warnings:
        for w in leak_warnings:
            print(f"  🚨 SECRET LEAK DETECTED: {w}")
        clean_text = _redact_secrets(clean_text)
        print("  Secrets have been redacted from review output.")

    with open("/tmp/review_result.md", "w", encoding="utf-8") as f:
        f.write(clean_text)


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
        sys.exit(1)

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
