#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QwenPaw AI Review Bot - Main runner script.

This script runs inside GitHub Actions to:
1. Read PR number and repo from environment variables
2. Send a task prompt to the local QwenPaw instance
3. QwenPaw autonomously fetches PR data via `gh` CLI
4. Parse the response and output verdict + review text
"""
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Sequence

try:  # ``fcntl`` is Unix-only; without it the repo lock is a no-op.
    import fcntl
except ImportError:  # pragma: no cover - non-Unix platforms
    fcntl = None

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
# Max characters kept per *line*. A minified or single-line generated file
# puts its whole diff on one line, where a line budget alone caps nothing,
# so the streaming reader needs a width cap as well as a height cap.
MAP_MAX_LINE_CHARS = int(os.environ.get("MAP_MAX_LINE_CHARS", "2000"))
# Overall cap on the whole change map (safety valve for huge PRs).
MAP_MAX_LINES = int(os.environ.get("MAP_MAX_LINES", "6000"))
# Context ladder tried (ascending) when a file fits at MAP_CONTEXT and
# there is spare per-file budget to show more surrounding code.
MAP_CONTEXT_LADDER = (40, 80, 160, 320, 640)
# "-U<this>" ~ whole-file context (git caps at the file length).
MAP_FULL_CONTEXT = 100000
# Wall-clock ceiling for git clone/fetch operations (seconds).
GIT_TIMEOUT = int(os.environ.get("GIT_TIMEOUT", "600"))
# Per-call ceiling for the many small `git diff` reads used to build the
# map. Far below GIT_TIMEOUT (these are local) but generous enough for a
# file's first diff, which lazily fetches its blobs from the remote.
DIFF_TIMEOUT = int(os.environ.get("DIFF_TIMEOUT", "120"))
# Overall ceiling for building the whole map. On expiry the remaining
# files are reported as omitted, exactly as when the size cap is hit.
MAP_BUILD_DEADLINE = int(os.environ.get("MAP_BUILD_DEADLINE", "300"))

# A "degenerate" reply is non-empty text that is NOT a real review: the agent
# hit its internal iteration cap and emitted a warning stub, or returned almost
# nothing. These are treated as failures and retried (see call_qwenpaw).
MIN_REVIEW_CHARS = 200
# Stubs run 1-3 lines and the shortest complete 6-section report seen is
# ~16, so this sits in the gap between them rather than at either edge.
MIN_REVIEW_LINES = 10


def _is_degenerate_review(text: str) -> bool:
    """True if the reply is too small to be a review.

    Judged purely on size. An earlier version also searched the text for
    the agent's iteration-limit phrasing, which discarded *valid* reviews
    that merely quoted it -- a review of a PR adding "maximum number of
    iterations" handling describes the phrase in its own prose. Since
    call_qwenpaw retries on a degenerate reply, such a review was thrown
    away up to MAX_RETRIES times and the job reported "Review Failed"
    while holding five usable reports. Size alone loses nothing: a real
    stub is one to three lines, so it fails both checks below anyway.
    """
    body = re.sub(
        r"^\s*#.*\n",
        "",
        text,
        count=1,
    ).strip()  # drop a leading title line
    return (
        len(body) < MIN_REVIEW_CHARS
        or len(body.splitlines()) < MIN_REVIEW_LINES
    )


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
            encoding="utf-8",
            errors="replace",
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
def _git(
    repo_dir: str,
    *args: str,
    timeout: int = GIT_TIMEOUT,
    errors: str = "replace",
) -> str:
    """Run a git command in ``repo_dir`` and return trimmed stdout.

    The encoding is pinned rather than inherited from the locale, and
    decoding never raises: a diff may legitimately contain bytes that are
    not valid UTF-8 (git treats a NUL-free latin-1 file as text), and a
    ``UnicodeDecodeError`` here would abort the whole run.

    ``errors`` defaults to ``"replace"``, which is right for diff *text*.
    Callers reading **paths** must pass ``"surrogateescape"`` instead, so
    the value round-trips back into a later argv unchanged.

    Only for commands with small, bounded output (rev-parse, merge-base,
    fetch). Diffs must go through :func:`_git_bounded`, which caps how
    much is read into memory.
    """
    result = subprocess.run(
        ["git", "-C", repo_dir, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors=errors,
        timeout=timeout,
        check=True,
    )
    return result.stdout.strip()


def _git_bounded(
    repo_dir: str,
    args: Sequence[str],
    *,
    max_chars: int,
    timeout: float,
    errors: str = "replace",
) -> tuple[str, bool]:
    """Run git and read at most ``max_chars`` of stdout, then stop it.

    Returns ``(text, truncated)``. Unlike :func:`_git`, peak memory is
    bounded by ``max_chars`` no matter how large the real output is: the
    cap is applied *while* reading rather than to an already-buffered
    string. That distinction is the whole point here -- a diff taken at
    near-whole-file context can be tens of megabytes, and decoding it in
    full just to throw most of it away is what spiked memory before.

    stderr is spooled to a temp file rather than a second pipe, because
    draining only stdout would deadlock as soon as stderr filled its own
    64 KiB buffer.
    """
    argv = ["git", "-C", repo_dir, *args]
    expired = threading.Event()

    with tempfile.TemporaryFile("w+b") as err_file:
        watchdog: threading.Timer | None = None
        try:
            with subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=err_file,
                text=True,
                encoding="utf-8",
                errors=errors,
            ) as proc:

                def _expire() -> None:
                    # git can also stall while producing *nothing* -- a
                    # blobless clone fetching this file's blob over the
                    # network -- where the read below blocks
                    # indefinitely. Killing the child is what makes the
                    # timeout real.
                    expired.set()
                    proc.kill()

                watchdog = threading.Timer(timeout, _expire)
                watchdog.start()
                # A single bounded read: ``TextIOWrapper.read(n)`` returns
                # exactly n characters or everything up to EOF, so this is
                # already the streaming cap -- no chunk loop needed. The
                # one extra character is how we tell "output happens to
                # end exactly at the cap" from "there is more to come".
                text = proc.stdout.read(max_chars + 1)

                truncated = len(text) > max_chars
                if truncated:
                    text = text[:max_chars]
                    # Kill before the context manager waits: git is
                    # blocked writing into a pipe nobody will drain.
                    proc.kill()
            # The timer stays armed across ``Popen.__exit__``, whose
            # ``wait()`` takes no timeout of its own.
        finally:
            if watchdog is not None:
                watchdog.cancel()

        if proc.returncode == 0 or truncated:
            # Either a clean read, or we stopped git ourselves -- a
            # non-zero code from our own kill is not a failure. Checked
            # before ``expired`` so a watchdog that fires in the moment
            # between a completed read and ``cancel()`` cannot discard
            # output we already hold.
            return text, truncated

        err_file.seek(0)
        stderr_text = err_file.read().decode("utf-8", "replace").strip()

    if expired.is_set():
        raise subprocess.TimeoutExpired(argv, timeout, stderr=stderr_text)
    raise subprocess.CalledProcessError(
        proc.returncode,
        argv,
        stderr=stderr_text,
    )


@contextlib.contextmanager
def _repo_lock(lock_path: str):
    """Serialize clone/fetch between workers sharing one clone.

    Degrades to a no-op where ``fcntl`` is unavailable (Windows), which
    assumes a single process — acceptable because the shared clone only
    exists to help concurrent CI workers.
    """
    if fcntl is None:
        yield
        return
    with open(lock_path, "w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def prepare_repo(
    repo: str,
    pr_number: int,
    base_ref: str,
) -> tuple[str, str, str]:
    """Clone/refresh the repo and resolve the diff range for the PR.

    Clones are shared per repo under ``QWENPAW_ENH_WORK_DIR/repos`` and
    guarded by a file lock, so parallel workers reviewing PRs from the
    *same* repo do not corrupt the clone. The lock is held only for the
    clone/fetch/resolve phase; the returned SHAs are immutable, so
    building the change map runs lock-free.

    Both endpoints are fetched into local refs under
    ``refs/qwenpaw-review/`` rather than read back from ``FETCH_HEAD``.
    That keeps the commits *reachable*: with a bare ``FETCH_HEAD`` fetch
    the objects belong to no ref, so a concurrent worker's fetch could
    trigger an auto-gc that prunes them mid-review. The refs are named
    per PR so concurrent reviews of the same repo cannot clobber them.

    Returns ``(repo_dir, from_sha, to_sha)`` where ``from_sha`` is the
    merge-base of the base branch and PR head (matching ``gh pr diff``)
    and ``to_sha`` is the PR head commit.
    """
    repos_root = os.path.join(QWENPAW_ENH_WORK_DIR, "repos")
    os.makedirs(repos_root, exist_ok=True)
    slug = repo.replace("/", "__")
    repo_dir = os.path.join(repos_root, slug)
    clone_url = f"https://github.com/{repo}.git"
    base_local = f"refs/qwenpaw-review/base/{pr_number}"
    head_local = f"refs/qwenpaw-review/head/{pr_number}"

    with _repo_lock(os.path.join(repos_root, f".{slug}.lock")):
        if not os.path.isdir(os.path.join(repo_dir, ".git")):
            print(f"  Cloning {repo} (blobless) ...")
            # Clone into a scratch dir and move it into place only on
            # success. A clone killed by the timeout leaves a .git behind
            # but no usable repo, which would otherwise be mistaken for a
            # good cache on every later run and poison it permanently.
            tmp_dir = f"{repo_dir}.tmp"
            shutil.rmtree(tmp_dir, ignore_errors=True)
            try:
                # Blobless partial clone: full commit graph (needed for
                # merge-base) but blobs fetched on demand.
                subprocess.run(
                    [
                        "git",
                        "clone",
                        "--filter=blob:none",
                        "--no-checkout",
                        clone_url,
                        tmp_dir,
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=GIT_TIMEOUT,
                    check=True,
                )
                # Safe under the lock: we know there is no .git here.
                shutil.rmtree(repo_dir, ignore_errors=True)
                os.replace(tmp_dir, repo_dir)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        # Fetch the base branch tip and the PR head. The PR head is
        # exposed on the base repo at refs/pull/<n>/head even for
        # forks, so this works without knowing the fork remote.
        _git(
            repo_dir,
            "fetch",
            "--no-tags",
            "--force",
            "origin",
            f"{base_ref}:{base_local}",
        )
        base_tip = _git(repo_dir, "rev-parse", base_local)

        _git(
            repo_dir,
            "fetch",
            "--no-tags",
            "--force",
            "origin",
            f"refs/pull/{pr_number}/head:{head_local}",
        )
        head_sha = _git(repo_dir, "rev-parse", head_local)

        merge_base = _git(repo_dir, "merge-base", base_tip, head_sha)

    return repo_dir, merge_base, head_sha


def _safe_display(path: str) -> str:
    """Render a git path for the prompt with no lone surrogates.

    Git paths are bytes and need not be valid UTF-8, so :func:`_numstat`
    reads them with ``surrogateescape`` to keep them round-trippable into
    a later argv. Those surrogates must never reach the prompt: httpx
    encodes the JSON body with ``ensure_ascii=False`` and then UTF-8, so a
    single one raises ``UnicodeEncodeError`` from inside the HTTP call --
    long after :func:`resolve_change_map` returned, with its fallback
    already skipped and only ``TimeoutException``/``ConnectError`` caught
    around the request.

    Undecodable bytes become ``\\xNN`` text: valid UTF-8, unambiguous, and
    still legible to the agent. Genuine UTF-8 paths (``café.py``) are
    passed through untouched. The display value is therefore NOT a usable
    pathspec -- that is what the separate ``pathspecs`` field is for.
    """
    return path.encode("utf-8", "surrogateescape").decode(
        "utf-8",
        "backslashreplace",
    )


def _numstat(
    repo_dir: str,
    from_sha: str,
    to_sha: str,
) -> list[tuple[str, str, list[str]]]:
    """Return ``[(display, "+add -del", pathspecs)]`` per changed file.

    ``-z`` is required, not a nicety: the default format is *not*
    round-trippable into a pathspec. It C-quotes any path holding
    non-ASCII bytes (``"caf\\303\\251.py"``) and collapses a detected
    rename into one ``old => new`` field. Feeding either back to
    ``git diff -- <path>`` matches nothing, and git reports that by
    printing nothing and exiting 0 — so the file would silently render
    as an empty diff with no truncation marker to flag it.

    With ``-z`` each record is ``add TAB del TAB path NUL``; for a
    rename/copy the path field is empty and two more NUL-separated
    fields follow with the real old and new paths. Renames carry both as
    pathspecs, which is what makes git emit the rename diff rather than
    treating the new path as a wholly new file.
    """
    raw = _git(
        repo_dir,
        "diff",
        "--numstat",
        "-z",
        from_sha,
        to_sha,
        errors="surrogateescape",
    )
    fields = raw.split("\0")
    entries: list[tuple[str, str, list[str]]] = []
    i = 0
    while i < len(fields):
        parts = fields[i].split("\t")
        if len(parts) != 3:
            i += 1
            continue
        add, dele, path = parts
        # ``pathspecs`` keeps the raw surrogate form so it can go back
        # into git's argv; ``display`` is sanitised for the prompt.
        if path:
            display, pathspecs = _safe_display(path), [path]
            i += 1
        else:
            if i + 2 >= len(fields):
                break
            old, new = fields[i + 1], fields[i + 2]
            display = f"{_safe_display(old)} => {_safe_display(new)}"
            pathspecs = [old, new]
            i += 3
        # Binary files show "-" for counts; keep them but mark n/a.
        stat = "binary" if add == "-" or dele == "-" else f"+{add} -{dele}"
        entries.append((display, stat, pathspecs))
    return entries


def _file_diff(
    repo_dir: str,
    from_sha: str,
    to_sha: str,
    pathspecs: list[str],
    context: int,
    max_lines: int = MAP_PER_FILE_LINES,
) -> tuple[list[str], bool]:
    """Return ``(diff_lines, overflowed)`` for one file at a context width.

    ``overflowed`` means git had more to give than the budget allowed --
    more than ``max_lines`` lines, or more characters than the streaming
    cap. Callers treat the two identically: the file does not fit at this
    context width.

    Because the read itself is capped, ``-U{MAP_FULL_CONTEXT}`` is now
    safe to probe: git is stopped as soon as it exceeds the budget
    instead of being allowed to hand us a whole large file first.
    """
    text, char_truncated = _git_bounded(
        repo_dir,
        [
            "diff",
            f"-U{context}",
            from_sha,
            to_sha,
            "--",
            *pathspecs,
        ],
        max_chars=max_lines * MAP_MAX_LINE_CHARS,
        timeout=DIFF_TIMEOUT,
    )
    lines = text.splitlines()
    overflowed = char_truncated or len(lines) > max_lines
    # Every line is capped to the same width, so a line the character cap
    # happened to slice is no more misleading than a legitimately long one
    # -- and keeping it preserves the start of the change. The caller
    # appends a truncation marker whenever ``overflowed`` is set, so a
    # partial tail is never presented as the whole story.
    kept = [line[:MAP_MAX_LINE_CHARS] for line in lines[:max_lines]]
    return kept, overflowed


def _diff_with_adaptive_context(
    repo_dir: str,
    from_sha: str,
    to_sha: str,
    pathspecs: list[str],
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
    floor, overflowed = _file_diff(
        repo_dir,
        from_sha,
        to_sha,
        pathspecs,
        MAP_CONTEXT,
    )

    # Case 1: even minimum context overflows -> keep the truncated floor.
    if overflowed:
        floor.append(
            f"... (diff truncated: showing the first {MAP_PER_FILE_LINES} "
            f"lines at {MAP_CONTEXT}-line context; more changes follow — "
            f'read the complete file with the "Full-file fetch" command '
            f"in Step 2) ...",
        )
        return floor, True

    # Case 2: room to spare -> prefer whole-file context if it fits.
    full, full_overflowed = _file_diff(
        repo_dir,
        from_sha,
        to_sha,
        pathspecs,
        MAP_FULL_CONTEXT,
    )
    if not full_overflowed:
        return full, False

    # Case 3: whole file too big -> climb the ladder, keep the widest fit.
    best = floor
    for ctx in MAP_CONTEXT_LADDER:
        if ctx <= MAP_CONTEXT:
            continue
        widened, widened_overflowed = _file_diff(
            repo_dir,
            from_sha,
            to_sha,
            pathspecs,
            ctx,
        )
        if widened_overflowed:
            break  # context is monotonic; nothing larger will fit
        best = widened
    return best, False


def _render_file_chunk(
    repo_dir: str,
    from_sha: str,
    to_sha: str,
    entry: tuple[str, str, list[str]],
) -> tuple[str, int, bool]:
    """Render one file's change-map chunk.

    ``entry`` is one ``(display, stat, pathspecs)`` record from
    :func:`_numstat`.

    Deleted files are flagged in the header. Without that flag a truncated
    deletion is a dead end: the marker sends the agent to the full-file
    fetch, but the file does not exist at the PR head, so the fetch can
    only 404 -- while the prompt still demands it read the full file
    before asserting anything. The flag tells it to use the base revision
    instead (spelled out once in the prompt's Step 2).

    Returns ``(chunk_text, line_count, truncated)`` where ``truncated``
    marks that the diff was cut to the per-file budget.
    """
    display, stat, pathspecs = entry
    if stat == "binary":
        # No diff body to inspect, so the change type is unknown here; the
        # prompt's Step 2 covers the 404-means-deleted case.
        return (
            f"### {display} ({stat})\n(binary file — diff omitted)\n",
            2,
            False,
        )
    try:
        diff_lines, truncated = _diff_with_adaptive_context(
            repo_dir,
            from_sha,
            to_sha,
            pathspecs,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as e:
        return (
            f"### {display} ({stat})\n(could not read diff: {e})\n",
            0,
            False,
        )

    # git puts "deleted file mode <mode>" right after the "diff --git"
    # line, so this is reliable even when the body was truncated.
    deleted = any(
        line.startswith("deleted file mode") for line in diff_lines[:5]
    )
    note = f"{stat} · DELETED in this PR" if deleted else stat
    header = f"### {display} ({note})"

    block = "\n".join(diff_lines)
    return f"{header}\n```diff\n{block}\n```\n", len(diff_lines) + 3, truncated


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
    entries = _numstat(repo_dir, from_sha, to_sha)
    if not entries:
        return ""

    chunks: list[str] = []
    total_lines = 0
    truncated_files: list[str] = []
    skipped_files: list[str] = []
    deadline_hit = False
    deadline = time.monotonic() + MAP_BUILD_DEADLINE

    for entry in entries:
        display = entry[0]
        # Widening context costs several `git diff` calls per file, so a
        # very wide PR can run long even though each call is cheap. Stop
        # at the deadline and let the remaining files fall through to the
        # existing "omitted" notice, which already points at Step 2.
        if total_lines < MAP_MAX_LINES and time.monotonic() > deadline:
            deadline_hit = True
        if total_lines >= MAP_MAX_LINES or deadline_hit:
            skipped_files.append(display)
            continue

        chunk, n_lines, truncated = _render_file_chunk(
            repo_dir,
            from_sha,
            to_sha,
            entry,
        )
        if truncated:
            truncated_files.append(display)
        chunks.append(chunk)
        total_lines += n_lines

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
        reason = (
            f"after the {MAP_BUILD_DEADLINE}s build deadline"
            if deadline_hit
            else f"over the {MAP_MAX_LINES}-line total cap"
        )
        print(
            f"  change map: omitted {len(skipped_files)} file(s) {reason}",
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


def _collect_sse(resp) -> tuple[dict | None, list]:
    """Read an SSE stream, returning ``(final_event, stream_errors)``."""
    final_event = None
    stream_errors: list = []
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
    return final_event, stream_errors


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

                    final_event, stream_errors = _collect_sse(resp)

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


def resolve_change_map(pr_number: int, repo: str) -> tuple[str, str, str]:
    """Resolve the PR's change map + both SHAs, degrading gracefully.

    Pre-computes a per-file change map from an internal blobless clone. The
    clone is an implementation detail — it is never surfaced to the model;
    only the resulting diff text and the two SHAs used in the full-file
    fetch instructions go into the prompt. Returns
    ``(change_map, head_sha, base_sha)``, all ``""`` on any failure so the
    caller falls back to the self-fetch prompt.

    ``base_sha`` (the merge-base) is needed as well as the head: a deleted
    file does not exist at the head, so fetching its full source there
    always 404s.
    """
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
        # The prompt travels as a JSON body that httpx encodes as UTF-8.
        # Verifying that here means a stray surrogate costs us only the
        # map (this except clause) instead of raising deep inside
        # call_qwenpaw's request, which catches only timeout/connect
        # errors. _safe_display already sanitises paths; this is the
        # backstop for any future source of undecodable text.
        change_map.encode("utf-8")
        if change_map:
            print(
                f"  change map: {len(change_map)} chars "
                f"({change_map.count(chr(10)) + 1} lines)",
            )
        else:
            print("  change map empty; using self-fetch prompt")
        return change_map, head_sha, from_sha
    # Deliberately broad: the change map is an optimisation, and this is
    # the single point where its failure must never fail the CI job. An
    # allow-list of exception types silently made that promise
    # conditional -- e.g. a UnicodeDecodeError (a ValueError, so not
    # covered) aborted the whole run instead of degrading. The type name
    # is logged so a real defect is still visible rather than swallowed.
    except Exception as e:
        print(
            f"  ⚠️  Could not build change map "
            f"({type(e).__name__}: {e}); "
            f"falling back to self-fetch prompt",
        )
        return "", "", ""


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

    change_map, head_sha, base_sha = resolve_change_map(pr_number, repo)

    prompt = build_review_prompt(
        pr_number,
        repo,
        change_map,
        head_sha,
        base_sha,
    )
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
