#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QwenPaw AI Review Bot - Main runner script.

This script runs inside GitHub Actions to:
1. Read PR number and repo from environment variables
2. Send a task prompt to the local QwenPaw instance
3. QwenPaw autonomously fetches PR data via `gh` CLI
4. Parse the response and output verdict + review text
"""
import fcntl
import json
import os
import re
import subprocess
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

QWENPAW_URL = os.environ.get("QWENPAW_URL", "http://localhost:8088")
CHAT_ENDPOINT = f"{QWENPAW_URL}/api/console/chat"
MAX_RETRIES = 5
TIMEOUT_SECONDS = 300

# ---- change-map (per-file diff) configuration ----
# The runner pre-computes a compact per-file diff ("change map") from an
# internal blobless clone and embeds it in the prompt. The clone is an
# implementation detail — it is NOT exposed to the model. Any failure
# building the map degrades gracefully to the self-fetch prompt.
QWENPAW_ENH_WORK_DIR = os.environ.get(
    "QWENPAW_ENH_WORK_DIR",
    os.path.join(os.path.expanduser("~"), ".qwenpaw-review-bot-cache"),
)
# MINIMUM lines of context around each hunk. The map starts here and
# widens toward full-file context whenever the per-file budget allows.
MAP_CONTEXT = int(os.environ.get("MAP_CONTEXT", "20"))
# Max lines kept per file in the change map.
MAP_PER_FILE_LINES = int(os.environ.get("MAP_PER_FILE_LINES", "500"))
# Overall cap on the whole change map (safety valve for huge PRs).
MAP_MAX_LINES = int(os.environ.get("MAP_MAX_LINES", "6000"))
# Context ladder tried (ascending) when a file fits at MAP_CONTEXT and
# there is spare per-file budget to show more surrounding code.
MAP_CONTEXT_LADDER = (40, 80, 160, 320, 640)
# "-U<this>" ~ whole-file context (git caps at the file length).
MAP_FULL_CONTEXT = 100000
# Wall-clock ceiling for git clone/fetch operations (seconds).
GIT_TIMEOUT = int(os.environ.get("GIT_TIMEOUT", "600"))

# A "degenerate" reply is non-empty text that is NOT a real review: the agent
# hit its internal iteration cap and emitted a warning stub, or returned almost
# nothing. These are treated as failures and retried (see call_qwenpaw).
ITERATION_LIMIT_MARKERS = (
    "maximum number of iterations",
    "reached the maximum",
)
MIN_REVIEW_CHARS = 200


def _is_degenerate_review(text: str) -> bool:
    """True if the response is an iteration-limit stub or too short to be a review."""
    low = text.lower()
    if any(m in low for m in ITERATION_LIMIT_MARKERS):
        return True
    body = re.sub(
        r"^\s*#.*\n", "", text, count=1
    ).strip()  # drop a leading title line
    return len(body) < MIN_REVIEW_CHARS


def fetch_base_branch(pr_number: int, repo: str) -> str:
    """Fetch the PR's target (base) branch name via `gh` (read-only).

    Needed to compute the merge-base for the change map. Returns an
    empty string on failure so the caller can degrade gracefully.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                repo,
                "--json",
                "baseRefName",
                "--jq",
                ".baseRefName",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return result.stdout.strip()
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
    ) as e:
        print(f"  ⚠️  Could not fetch base branch via gh: {e}")
        return ""


# ----------------------------------------------------------------------
# Change map: pre-computed per-file diff embedded in the prompt
# ----------------------------------------------------------------------
def _git(repo_dir: str, *args: str, timeout: int = GIT_TIMEOUT) -> str:
    """Run a git command in ``repo_dir`` and return trimmed stdout."""
    result = subprocess.run(
        ["git", "-C", repo_dir, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return result.stdout.strip()


def prepare_repo(
    repo: str,
    pr_number: int,
    base_ref: str,
) -> tuple[str, str, str]:
    """Clone/refresh the repo and resolve the diff range for the PR.

    Clones are shared per repo under ``QWENPAW_ENH_WORK_DIR/repos`` and
    guarded by a file lock, so parallel workers reviewing PRs from the
    *same* repo do not corrupt the clone or race on ``FETCH_HEAD``. The
    lock is held only for the clone/fetch/resolve phase; the returned
    SHAs are immutable, so building the change map runs lock-free.

    Returns ``(repo_dir, from_sha, to_sha)`` where ``from_sha`` is the
    merge-base of the base branch and PR head (matching ``gh pr diff``)
    and ``to_sha`` is the PR head commit.
    """
    repos_root = os.path.join(QWENPAW_ENH_WORK_DIR, "repos")
    os.makedirs(repos_root, exist_ok=True)
    slug = repo.replace("/", "__")
    repo_dir = os.path.join(repos_root, slug)
    clone_url = f"https://github.com/{repo}.git"

    lock_path = os.path.join(repos_root, f".{slug}.lock")
    with open(lock_path, "w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            if not os.path.isdir(os.path.join(repo_dir, ".git")):
                print(f"  Cloning {repo} (blobless) ...")
                # Blobless partial clone: full commit graph (needed for
                # merge-base) but blobs fetched on demand.
                subprocess.run(
                    [
                        "git",
                        "clone",
                        "--filter=blob:none",
                        "--no-checkout",
                        clone_url,
                        repo_dir,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=GIT_TIMEOUT,
                    check=True,
                )

            # Fetch the base branch tip and the PR head. The PR head is
            # exposed on the base repo at refs/pull/<n>/head even for
            # forks, so this works without knowing the fork remote.
            _git(repo_dir, "fetch", "--no-tags", "origin", base_ref)
            base_tip = _git(repo_dir, "rev-parse", "FETCH_HEAD")

            _git(
                repo_dir,
                "fetch",
                "--no-tags",
                "origin",
                f"refs/pull/{pr_number}/head",
            )
            head_sha = _git(repo_dir, "rev-parse", "FETCH_HEAD")

            merge_base = _git(repo_dir, "merge-base", base_tip, head_sha)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)

    return repo_dir, merge_base, head_sha


def _numstat(repo_dir: str, from_sha: str, to_sha: str) -> dict[str, str]:
    """Return ``{path: "+add -del"}`` for each changed file."""
    raw = _git(repo_dir, "diff", "--numstat", from_sha, to_sha)
    stats: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        # Binary files show "-" for counts; keep them but mark n/a.
        if add == "-" or dele == "-":
            stats[path] = "binary"
        else:
            stats[path] = f"+{add} -{dele}"
    return stats


def _file_diff(
    repo_dir: str,
    from_sha: str,
    to_sha: str,
    path: str,
    context: int,
) -> list[str]:
    """Return the diff lines for one file at a given context width."""
    diff = _git(
        repo_dir,
        "diff",
        f"-U{context}",
        from_sha,
        to_sha,
        "--",
        path,
    )
    return diff.splitlines()


def _diff_with_adaptive_context(
    repo_dir: str,
    from_sha: str,
    to_sha: str,
    path: str,
) -> tuple[list[str], bool]:
    """Pick the widest diff context that fits the per-file line budget.

    Strategy: always show at least ``MAP_CONTEXT`` lines of context. If
    the diff at that floor already fits ``MAP_PER_FILE_LINES``, try to
    widen — first to whole-file context, else climbing ``MAP_CONTEXT_LADDER``
    and keeping the largest width that still fits. If even the floor
    overflows the budget, the diff is truncated to the budget.

    Returns ``(diff_lines, truncated)``. When truncated, the caller
    appends a marker pointing at the full-file fetch instruction.
    """
    floor = _file_diff(repo_dir, from_sha, to_sha, path, MAP_CONTEXT)

    # Case 1: even minimum context overflows -> truncate the floor diff.
    if len(floor) > MAP_PER_FILE_LINES:
        total = len(floor)
        kept = floor[:MAP_PER_FILE_LINES]
        kept.append(
            f"... (diff truncated: {total} lines at {MAP_CONTEXT}-line "
            f"context, showing the first {MAP_PER_FILE_LINES} — read the "
            f'complete file with the "Full-file fetch" command in Step 2) ...',
        )
        return kept, True

    # Case 2: room to spare -> prefer whole-file context if it fits.
    full = _file_diff(repo_dir, from_sha, to_sha, path, MAP_FULL_CONTEXT)
    if len(full) <= MAP_PER_FILE_LINES:
        return full, False

    # Case 3: whole file too big -> climb the ladder, keep the widest fit.
    best = floor
    for ctx in MAP_CONTEXT_LADDER:
        if ctx <= MAP_CONTEXT:
            continue
        widened = _file_diff(repo_dir, from_sha, to_sha, path, ctx)
        if len(widened) <= MAP_PER_FILE_LINES:
            best = widened
        else:
            break  # context is monotonic; nothing larger will fit
    return best, False


def build_change_map(repo_dir: str, from_sha: str, to_sha: str) -> str:
    """Build a compact per-file change map for the diff range.

    For each changed file, emit a header (``path (+add -del)``) followed
    by a fenced ```diff block. Context is adaptive: at least
    ``MAP_CONTEXT`` lines, widened toward the whole file when the
    per-file budget (``MAP_PER_FILE_LINES``) allows, and truncated (with
    a marker pointing to the Step 2 full-file fetch) only when the file
    overflows the budget even at minimum context. The whole map is
    capped at ``MAP_MAX_LINES``. Returns "" if there are no changes.
    """
    stats = _numstat(repo_dir, from_sha, to_sha)
    if not stats:
        return ""

    chunks: list[str] = []
    total_lines = 0
    truncated_files: list[str] = []
    skipped_files: list[str] = []

    for path, stat in stats.items():
        if total_lines >= MAP_MAX_LINES:
            skipped_files.append(path)
            continue

        header = f"### {path} ({stat})"
        if stat == "binary":
            chunks.append(f"{header}\n(binary file — diff omitted)\n")
            total_lines += 2
            continue

        try:
            diff_lines, truncated = _diff_with_adaptive_context(
                repo_dir,
                from_sha,
                to_sha,
                path,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as e:
            chunks.append(f"{header}\n(could not read diff: {e})\n")
            continue

        if truncated:
            truncated_files.append(path)

        block = "\n".join(diff_lines)
        chunks.append(f"{header}\n```diff\n{block}\n```\n")
        total_lines += len(diff_lines) + 3

    if skipped_files:
        chunks.append(
            "### (change map truncated)\n"
            f"{len(skipped_files)} more changed file(s) omitted to stay "
            f"within the size limit; read them with the Step 2 full-file "
            f"fetch: {', '.join(skipped_files)}\n",
        )
    if truncated_files:
        print(
            f"  change map: truncated {len(truncated_files)} large file(s): "
            f"{', '.join(truncated_files)}",
        )
    if skipped_files:
        print(
            f"  change map: omitted {len(skipped_files)} file(s) over the "
            f"{MAP_MAX_LINES}-line total cap",
        )

    return "\n".join(chunks)


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
    """Send prompt to QwenPaw console chat API and collect SSE response.

    Retries on HTTP errors, empty replies, AND degenerate replies (the agent's
    iteration-limit stub / too-short output). Each attempt uses a FRESH session --
    resuming a session that already hit its iteration cap would just continue the
    stuck run instead of starting over.
    """
    base_payload = {
        "channel": "console",
        "user_id": "review-bot",
        "input": [{"content": [{"type": "text", "text": prompt}]}],
    }

    for attempt in range(1, MAX_RETRIES + 1):
        payload = {**base_payload, "session_id": f"{session_id}-try{attempt}"}
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
            if response.strip() and not _is_degenerate_review(response):
                return response

            if not response.strip():
                print("  Empty response, retrying...")
            else:
                print(
                    "  Degenerate response (iteration-limit stub / too short), "
                    "retrying with a fresh session...",
                )
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

    # Pre-compute a per-file change map from an internal blobless clone.
    # This is an implementation detail — the clone is never surfaced to the
    # model; only the resulting diff text (and the head SHA, used in the
    # full-file fetch instruction) go into the prompt. Any failure here
    # degrades gracefully to the self-fetch (gh pr diff) prompt.
    change_map = ""
    head_sha = ""
    try:
        base_ref = fetch_base_branch(pr_number, repo)
        if not base_ref:
            raise RuntimeError("could not resolve PR base branch")
        print("Preparing local clone + change map ...")
        repo_dir, from_sha, head_sha = prepare_repo(
            pr_number=pr_number,
            repo=repo,
            base_ref=base_ref,
        )
        change_map = build_change_map(repo_dir, from_sha, head_sha)
        if change_map:
            print(
                f"  change map: {len(change_map)} chars "
                f"({change_map.count(chr(10)) + 1} lines)",
            )
        else:
            print("  change map empty; using self-fetch prompt")
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        RuntimeError,
        OSError,
    ) as e:
        print(
            f"  ⚠️  Could not build change map ({e}); "
            f"falling back to self-fetch prompt"
        )
        change_map = ""
        head_sha = ""

    prompt = build_review_prompt(pr_number, repo, change_map, head_sha)
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
