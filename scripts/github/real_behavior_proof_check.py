#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=wrong-import-position
"""CI check entry point: evaluate real-behavior-proof for the current PR.

Reads PR metadata from the GitHub Actions event payload, runs the policy
check, and exits non-zero if the PR is missing required context/evidence.

Environment variables:
    GITHUB_TOKEN         — GitHub token with ``pull-requests: read``
    PR_NUMBER            — Pull request number (auto-detected from event)
    PR_BODY              — PR body (auto-detected from event)
    PR_AUTHOR_ASSOC      — Author association (auto-detected)
    PR_AUTHOR_TYPE       — Author type (auto-detected)
    PR_LABELS            — Comma-separated label names (auto-detected)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add scripts/ to path so we can import the policy module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from real_behavior_proof_policy import (  # noqa: E402
    ProofStatus,
    evaluate_pull_request_context,
)


def _load_event() -> dict:
    """Load the GitHub Actions event payload."""
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if event_path and Path(event_path).is_file():
        return json.loads(Path(event_path).read_text("utf-8"))
    return {}


def main() -> int:
    event = _load_event()
    pr = event.get("pull_request") or {}

    body: str = pr.get("body") or os.environ.get("PR_BODY", "")
    author_association: str = pr.get("author_association") or os.environ.get(
        "PR_AUTHOR_ASSOC",
        "CONTRIBUTOR",
    )
    author_type = (pr.get("user") or {}).get("type") or os.environ.get(
        "PR_AUTHOR_TYPE",
        "User",
    )
    labels = [lbl.get("name", "") for lbl in (pr.get("labels") or [])] or [
        name.strip()
        for name in os.environ.get("PR_LABELS", "").split(",")
        if name.strip()
    ]

    pr_number = pr.get("number") or os.environ.get("PR_NUMBER", "?")
    pr_url = pr.get("html_url", "")

    print(f"Checking real-behavior-proof for PR #{pr_number}")
    print(f"  author_association: {author_association}")
    print(f"  author_type:        {author_type}")
    print(f"  labels:             {labels}")
    print(f"  body length:        {len(body)} chars")

    evaluation = evaluate_pull_request_context(
        body=body,
        author_association=author_association,
        author_type=author_type,
        labels=labels,
    )

    print(f"  status:             {evaluation.status.value}")

    if evaluation.status == ProofStatus.SKIPPED:
        print("  → SKIPPED (maintainer/bot/override)")
        return 0

    if evaluation.status == ProofStatus.PASSED:
        print("  → PASSED ✓")
        return 0

    # MISSING
    print(f"  → MISSING sections: {evaluation.missing_sections}")
    print()
    print("This PR is from an external contributor and is missing required")
    print("context or evidence. Please update the PR body to include:")
    print()
    for section in evaluation.missing_sections:
        print(f"  ## {section}")
        print("  [Describe/show real behavior — not template comments]")
        print()
    print("See the PR template for guidance. Template HTML comments do NOT")
    print("count as authored content.")
    print()
    print(f"PR: {pr_url}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
