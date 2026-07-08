# -*- coding: utf-8 -*-
"""Unit tests for the real-behavior-proof policy.

Ported from openclaw's ``real-behavior-proof-policy.test.ts`` and adapted
to QwenPaw's Python implementation.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
# pylint: disable=wrong-import-position,line-too-long
# flake8: noqa: E501
from __future__ import annotations

import sys
from pathlib import Path

# Add scripts/github to path so we can import the policy module.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "scripts" / "github"),
)

from real_behavior_proof_policy import (  # noqa: E402
    NEEDS_PR_CONTEXT_LABEL,
    PROOF_SUFFICIENT_LABEL,
    ProofStatus,
    _has_real_content,
    _mask_html_comments,
    evaluate_pull_request_context,
    labels_for_pull_request_context,
)


def _external_pr(body: str, **overrides) -> dict:
    pr = {
        "body": body,
        "author_association": "CONTRIBUTOR",
        "author_type": "User",
        "labels": [],
    }
    pr.update(overrides)
    return pr


def _proof_body(
    evidence: str,
    problem: str = "The gateway crashed on startup.",
) -> str:
    return f"""## Description

{problem}

## Evidence

{evidence}
"""


class TestExternalPrPass:
    """External PRs with real evidence should pass."""

    @staticmethod
    def test_passes_with_screenshot_evidence():
        ev = evaluate_pull_request_context(
            **_external_pr(
                _proof_body(
                    "![after](https://github.com/user-attachments/assets/abc123)",
                ),
            ),
        )
        assert ev.status == ProofStatus.PASSED
        assert labels_for_pull_request_context(ev) == [PROOF_SUFFICIENT_LABEL]

    @staticmethod
    def test_passes_with_terminal_transcript():
        ev = evaluate_pull_request_context(
            **_external_pr(
                _proof_body(
                    "Terminal transcript:\n```text\n$ pytest -q\n4 passed\n```",
                ),
            ),
        )
        assert ev.status == ProofStatus.PASSED

    @staticmethod
    def test_passes_with_test_output():
        ev = evaluate_pull_request_context(
            **_external_pr(_proof_body("pytest passed: 4 files, 67 cases.")),
        )
        assert ev.status == ProofStatus.PASSED

    @staticmethod
    def test_passes_with_ci_artifact_link():
        ev = evaluate_pull_request_context(
            **_external_pr(
                _proof_body(
                    "CI artifact: https://github.com/agentscope-ai/QwenPaw/actions/runs/123/artifacts/456",
                ),
            ),
        )
        assert ev.status == ProofStatus.PASSED


class TestMissingSections:
    """PRs missing required sections should be flagged."""

    @staticmethod
    def test_fails_without_any_context():
        ev = evaluate_pull_request_context(
            **_external_pr("## Summary\n\n- Fixed a bug."),
        )
        assert ev.status == ProofStatus.MISSING
        assert "What Problem This Solves" in ev.missing_sections
        assert "Evidence" in ev.missing_sections
        assert NEEDS_PR_CONTEXT_LABEL in labels_for_pull_request_context(ev)

    @staticmethod
    def test_fails_without_evidence():
        ev = evaluate_pull_request_context(
            **_external_pr("## Description\n\nFixed the cron DOW bug."),
        )
        assert ev.status == ProofStatus.MISSING
        assert "Evidence" in ev.missing_sections

    @staticmethod
    def test_fails_with_template_comment_only():
        ev = evaluate_pull_request_context(
            **_external_pr(
                "<!-- Describe what this PR does and why -->\n## Evidence\n\n<!-- paste result -->",
            ),
        )
        assert ev.status == ProofStatus.MISSING

    @staticmethod
    def test_fails_with_not_tested():
        ev = evaluate_pull_request_context(
            **_external_pr(_proof_body("not tested")),
        )
        assert ev.status == ProofStatus.MISSING
        assert "Evidence" in ev.missing_sections

    @staticmethod
    def test_fails_with_none_evidence():
        ev = evaluate_pull_request_context(
            **_external_pr(_proof_body("None")),
        )
        assert ev.status == ProofStatus.MISSING

    @staticmethod
    def test_fails_with_separator_only():
        ev = evaluate_pull_request_context(
            **_external_pr(_proof_body("---", problem="***")),
        )
        assert ev.status == ProofStatus.MISSING


class TestSkipRules:
    """Maintainer and bot PRs should be skipped."""

    @staticmethod
    def test_skips_member():
        ev = evaluate_pull_request_context(
            **_external_pr("", author_association="MEMBER"),
        )
        assert ev.status == ProofStatus.SKIPPED

    @staticmethod
    def test_skips_owner():
        ev = evaluate_pull_request_context(
            **_external_pr("", author_association="OWNER"),
        )
        assert ev.status == ProofStatus.SKIPPED

    @staticmethod
    def test_skips_bot():
        ev = evaluate_pull_request_context(
            **_external_pr("", author_type="Bot"),
        )
        assert ev.status == ProofStatus.SKIPPED

    @staticmethod
    def test_skips_proof_sufficient_label():
        ev = evaluate_pull_request_context(
            **_external_pr("", labels=[PROOF_SUFFICIENT_LABEL]),
        )
        assert ev.status == ProofStatus.SKIPPED


class TestHtmlCommentMasking:
    """HTML comments should be masked so commented template text doesn't count."""

    @staticmethod
    def test_html_comment_does_not_count_as_content():
        ev = evaluate_pull_request_context(
            **_external_pr(
                "## Description\n\n<!-- Describe what this PR does and why -->\n## Evidence\n\n<!-- paste result -->",
            ),
        )
        assert ev.status == ProofStatus.MISSING

    @staticmethod
    def test_real_content_alongside_html_comments_passes():
        ev = evaluate_pull_request_context(
            **_external_pr(
                "## Description\n\n<!-- old -->Fixed the DOW bug.\n## Evidence\n\n<!-- old -->pytest passed.",
            ),
        )
        assert ev.status == ProofStatus.PASSED


class TestHelperFunctions:
    @staticmethod
    def test_has_real_content_rejects_empty():
        assert not _has_real_content("")

    @staticmethod
    def test_has_real_content_rejects_none():
        assert not _has_real_content("None")
        assert not _has_real_content("none")
        assert not _has_real_content("N/A")
        assert not _has_real_content("n/a")

    @staticmethod
    def test_has_real_content_rejects_not_tested():
        assert not _has_real_content("not tested")
        assert not _has_real_content("untested")

    @staticmethod
    def test_has_real_content_rejects_separator():
        assert not _has_real_content("---")
        assert not _has_real_content("***")

    @staticmethod
    def test_has_real_content_accepts_real_text():
        assert _has_real_content("pytest passed: 4 files, 67 cases")
        assert _has_real_content("![screenshot](url)")

    @staticmethod
    def test_mask_html_comments():
        text = "Before <!-- comment --> After"
        result = _mask_html_comments(text)
        assert "comment" not in result
        assert "Before" in result
        assert "After" in result
