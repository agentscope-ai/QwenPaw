# -*- coding: utf-8 -*-
"""Review prompt templates for QwenPaw AI Review Bot.

The review methodology, coding standards, and anti-pattern checklist
live in the workspace persona files (SOUL.md, AGENTS.md) written by
setup_review_workspace.py.  This module only builds the *task* prompt
that tells the agent which PR to review and what output format to use.
"""


def build_review_prompt(pr_number: int, repo: str) -> str:
    """Build a task-oriented review prompt.

    Instead of embedding the full diff in the prompt, we tell QwenPaw
    to fetch the PR data itself using ``gh`` CLI commands.

    Args:
        pr_number: The pull request number to review.
        repo: The full repository name (owner/repo).
    """
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
dimension-based analysis of the diff.

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
