# -*- coding: utf-8 -*-
"""Review prompt templates for QwenPaw AI Review Bot (enhanced).

The review methodology, coding standards, and anti-pattern checklist
live in the workspace persona files (SOUL.md, AGENTS.md) written by
setup_review_workspace.py.  This module builds the *task* prompt that
tells the agent which PR to review and what output format to use.

Enhancement over the base bot: the runner pre-computes a per-file
**change map** (each changed file's diff with adaptive context — at
least a floor of context lines, widened toward the whole file when the
per-file budget allows) and embeds it in the prompt. The change map is
the agent's starting point; the prompt also gives ONE full-file fetch
command (the "Full-file fetch" in Step 2) that the agent uses whenever a
file was truncated or it needs more context than the map shows. That
single command is the only place the fetch is spelled out — the change
map's truncation markers merely point back to it, never repeating it.

If no change map is available (the runner couldn't build one), we fall
back to the original self-fetch prompt so the bot still works.
"""


def build_review_prompt(
    pr_number: int,
    repo: str,
    change_map: str = "",
    head_sha: str = "",
    base_sha: str = "",
) -> str:
    """Build a task-oriented review prompt.

    Args:
        pr_number: The pull request number to review.
        repo: The full repository name (owner/repo).
        change_map: Optional pre-computed per-file change map (adaptive-
            context diffs, capped per file). When present, the prompt
            embeds it and switches to the enhanced workflow.
        head_sha: The PR head commit SHA, used in the full-file fetch
            command so the agent reads the exact reviewed revision.
        base_sha: The merge-base SHA. Required for files the change map
            marks DELETED: they are absent from the head revision, so
            fetching them there can only 404.
    """
    if change_map.strip():
        return _build_enhanced_prompt(
            pr_number,
            repo,
            change_map,
            head_sha,
            base_sha,
        )
    return _build_fallback_prompt(pr_number, repo)


# ----------------------------------------------------------------------
# Enhanced prompt: change map is provided up front
# ----------------------------------------------------------------------
def _build_enhanced_prompt(
    pr_number: int,
    repo: str,
    change_map: str,
    head_sha: str,
    base_sha: str = "",
) -> str:
    # The contents API needs a concrete ref. Prefer the pinned head SHA;
    # if the runner couldn't resolve it, tell the agent to look it up.
    ref = head_sha or "<HEAD_SHA>"
    ref_hint = (
        ""
        if head_sha
        else (
            " (first resolve <HEAD_SHA> once with "
            f"`gh pr view {pr_number} --repo {repo} "
            "--json headRefOid --jq .headRefOid`)"
        )
    )
    base_ref = base_sha or f"{repo.split('/')[-1]}-base"
    # A deleted file is absent from the head revision, so it can only be
    # read at the merge-base. Without this the change map's truncation
    # marker points at a fetch that is guaranteed to 404, while the rules
    # below still require reading the full file before raising anything.
    deleted_rule = (
        f"""
**Deleted files** — any file the change map marks `DELETED in this PR` \
(and any binary file whose fetch below returns 404) no longer exists at \
`{ref}`. Read its PRE-DELETION source from the base revision instead:
   `gh api -H "Accept: application/vnd.github.raw" \
"repos/{repo}/contents/<PATH>?ref={base_ref}"`
   Judge a deletion by whether the removed code is still referenced \
elsewhere — use `gh search code` to check before approving it.
"""
        if base_sha
        else """
**Deleted files** — a file the change map marks `DELETED in this PR` is \
absent from the revision above, so that fetch will 404. Read its \
pre-deletion source with \
`gh pr diff <PR> --repo <REPO>` or at the PR's base branch instead.
"""
    )
    return f"""\
Please perform a thorough yet precise code review for \
**PR #{pr_number}** in the **{repo}** repository.

## Step 1: PR Metadata and the Change Map

First, fetch the PR's intent (title, description, author, related issue):
   `gh pr view {pr_number} --repo {repo} --json \
number,title,body,author,baseRefName,headRefName,additions,deletions,files`

Below is a **per-file change map** for this PR: for each changed file it \
shows its diff with surrounding context. Most files include generous \
context; very large files are truncated, and a marker inside the diff \
tells you where and points you at the Full-file fetch (Step 2). Treat \
this as your starting point — it tells you WHICH files changed and \
WHERE, but a truncated file is not the whole story.

<change_map>
{change_map}
</change_map>

## Step 2: Read Before You Conclude

The change map shows the touched regions (and, for large files, only \
part of them). Before you assert that something is a bug — or that a \
change is safe — you MUST read the surrounding code, not just the hunk.

**Full-file fetch** — to read the COMPLETE source of any file at this \
PR's revision, run{ref_hint}:
   `gh api -H "Accept: application/vnd.github.raw" \
"repos/{repo}/contents/<PATH>?ref={ref}"`
   (replace `<PATH>` with the repo-relative file path, e.g. \
`src/cache.py`). Use this whenever a file is marked truncated/omitted or \
you need more context than the change map shows.
{deleted_rule}
Rules you must follow:
- **Read the full file for any non-trivial finding.** If a hunk calls a \
function, mutates shared state, or changes a signature, use the Full-file \
fetch to confirm the surrounding logic actually behaves the way you claim.
- **Trace cross-file impact.** When a changed symbol (function, class, \
constant, config key) is used elsewhere, find its other call sites with \
`gh search code --repo {repo} "<symbol>"` (or read the importing files) \
and check whether the change breaks or requires updating them.
- **Cite evidence.** Every issue must quote the exact offending code and \
give a `path:line` reference. If you did not read the code, do not raise \
the issue.
- **Do not speculate.** If you cannot verify a concern from the actual \
source, phrase it as "consider verifying" rather than asserting a defect.

**Security & concurrency blocker checklist** — for EVERY changed file, \
actively scan for the high-severity classes below, even when the diff looks \
benign. These are the defects that are easiest to miss by reading only the \
hunk. An existing guard is NOT proof it is correct: when a hunk matches a \
class, read the full file and verify the actual comparison/logic before \
concluding the code is safe.

- **Path traversal / Zip Slip**: archive extraction (zip/tar), file writes or \
paths built from user- or plugin-supplied names/IDs, joins involving `..`. \
Confirm the guard uses a real boundary test (`Path.is_relative_to`, a \
resolved-prefix check that includes the path separator) — a bare `startswith` \
or `in`-substring match is bypassable.
- **TLS / certificate verification disabled**: `verify=False`, \
`rejectUnauthorized: false`, `InsecureSkipVerify`, a custom \
TrustManager, or disabled hostname checks → MITM.
- **SSRF / unbounded fetch**: server-side requests to user-controlled URLs; \
missing size, redirect, or timeout limits; reachability of internal IPs.
- **Missing origin / auth checks**: `postMessage` handlers that don't validate \
`event.origin` (or send with target origin `'*'`); endpoints missing \
authorization; fail-open on 401/error (reporting "ready"/"connected" without \
raising).
- **Unsafe deserialization / injection**: `pickle`/`yaml.load`, `eval`/`Function`, \
SQL or shell command string concatenation, template injection.
- **Concurrency / TOCTOU races**: shared mutable state read-then-written across \
concurrent requests or callbacks; check-then-act without atomicity; a \
"success" path that resets state an in-flight request still depends on. Reason \
through 2–3 interleaved requests — do not stop at "is there a lock".
- **Refactor fallout**: constants/handlers left unreferenced after a rewrite \
(dead code / linter breakage); a validator or helper whose logic has drifted \
from the runtime loader/consumer it is meant to mirror (read BOTH and compare).

## Step 3: Output the Review Report

Please strictly follow this structure:

### 1. Overview

| Item | Details |
|------|---------|
| PR Number | (from gh) |
| Author | @username format, e.g. @lalaliat |
| Changes | (from gh) |
| Merge Target | (from gh) |
| Related Issue | (extract from PR body, if any) |

### 2. Background

Describe the problem this PR solves and the motivation.

### 3. Core Changes

Summarize what this PR does (in list form), grouped by file/area using \
the change map.

### 4. Strengths

List what was done well, with specific file and code details.

### 5. Issues and Suggestions

Output by severity:

#### High
#### Medium
#### Low

Each issue should include:
- **Code reference**: The problematic code snippet + `path:line`
- **Explanation**: Why this is an issue (grounded in code you read)

If no issues at a given level, write "None".

### 5.5 Cross-file Impact Analysis

For each changed public symbol / signature / config key, state whether \
its other usages were checked and whether they need updating. If the PR \
is fully self-contained, say so explicitly (e.g. "No external call sites \
affected — symbol X is only used within the changed file"). Do NOT invent \
impacts you did not verify.

### 6. Summary

- One-sentence qualitative assessment
- N items that must be addressed before merge (if any)
- Items that can be followed up later

Finally, output a JSON code block with the conclusion \
(include issue counts per severity):

```json
{{
  "verdict": "APPROVE or REQUEST_CHANGES",
  "high_count": 0,
  "medium_count": 0,
  "low_count": 0,
  "summary": "One-sentence summary of the review conclusion"
}}
```

## Key Principles

- **Focus on changes**: Only review code in the diff; use the full files \
only as context to judge those changes.
- **Verify before flagging**: Read the real code behind every finding.
- **Distinguish blockers from suggestions**: Be clear about what must \
change vs. what can be improved later.
- **Provide concrete fixes**: Include improvement code examples for each \
issue.
- **Acknowledge strengths**: Explicitly praise good design decisions.
"""


# ----------------------------------------------------------------------
# Fallback prompt: no change map (identical intent to the base bot)
# ----------------------------------------------------------------------
def _build_fallback_prompt(pr_number: int, repo: str) -> str:
    return f"""\
Please perform a thorough yet precise code review for \
**PR #{pr_number}** in the **{repo}** repository.

## Step 1: Fetch PR Information

Use the following commands to retrieve PR data:

1. Fetch PR metadata:
   `gh pr view {pr_number} --repo {repo} --json \
number,title,body,author,baseRefName,headRefName,\
additions,deletions,files`

2. Fetch the full diff:
   `gh pr diff {pr_number} --repo {repo}`

## Step 2: Analyze and Review

Follow the review methodology in AGENTS.md to perform a \
dimension-based analysis of the diff. Before flagging any non-trivial \
issue, read the surrounding source: resolve the head commit with \
`gh pr view {pr_number} --repo {repo} --json headRefOid --jq .headRefOid`, \
then read the full file via `gh api -H "Accept: \
application/vnd.github.raw" "repos/{repo}/contents/<PATH>?ref=<HEAD_SHA>"` \
so every finding is grounded in the actual code, and check other call \
sites of any changed symbol with `gh search code --repo {repo} "<symbol>"`.

## Step 3: Output the Review Report

Please strictly follow this structure:

### 1. Overview

| Item | Details |
|------|---------|
| PR Number | (from gh) |
| Author | @username format, e.g. @lalaliat |
| Changes | (from gh) |
| Merge Target | (from gh) |
| Related Issue | (extract from PR body, if any) |

### 2. Background

Describe the problem this PR solves and the motivation.

### 3. Core Changes

Summarize what this PR does (in list form).

### 4. Strengths

List what was done well, with specific file and code details.

### 5. Issues and Suggestions

Output by severity:

#### High
#### Medium
#### Low

Each issue should include:
- **Code reference**: Show the problematic code snippet
- **Explanation**: Why this is an issue

If no issues at a given level, write "None".

### 6. Summary

- One-sentence qualitative assessment
- N items that must be addressed before merge (if any)
- Items that can be followed up later

Finally, output a JSON code block with the conclusion \
(include issue counts per severity):

```json
{{
  "verdict": "APPROVE or REQUEST_CHANGES",
  "high_count": 0,
  "medium_count": 0,
  "low_count": 0,
  "summary": "One-sentence summary of the review conclusion"
}}
```

## Key Principles

- **Focus on changes**: Only review code in the diff
- **Distinguish blockers from suggestions**: Be clear about \
what must change vs. what can be improved later
- **Provide concrete fixes**: Include improvement code examples \
for each issue
- **Acknowledge strengths**: Explicitly praise good design decisions
- **Do not assume**: Use "consider verifying" for uncertain cases
"""
