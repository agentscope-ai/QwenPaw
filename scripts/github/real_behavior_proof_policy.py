# -*- coding: utf-8 -*-
"""Real behavior proof policy for QwenPaw PR checks.

Ported from openclaw's ``real-behavior-proof-policy.mjs``. Parses a PR
body and determines whether an **external contributor** has provided the
two required sections:

1. **What Problem This Solves** — a concrete user/product/operational
   problem description (template comments do not count).
2. **Evidence** — real validation evidence: screenshots, terminal
   transcripts, CI artifact links, test output, etc.

Maintainer / bot PRs are auto-skipped.  The ``proof: override`` label
bypasses the check.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

NEEDS_PR_CONTEXT_LABEL = "triage: needs-pr-context"
PROOF_OVERRIDE_LABEL = "proof: override"
PROOF_SUFFICIENT_LABEL = "proof: sufficient"

# Authors with these associations skip the check entirely.
PRIVILEGED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# Values that count as "not provided" when they are the *only* content in
# a section body.
_MISSING_VALUE_RE = re.compile(
    r"^(?:n/?a|none|not applicable|tbd|todo|unknown|unsure|"
    r"none provided|no evidence|not tested|untested|"
    r"did not test|didn't test|could not test|couldn't test|"
    r"-|(?:-{3,}|\*{3,}|_{3,})|\[[^\]]*\])\.?$",
    re.IGNORECASE,
)

_SECTION_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


class ProofStatus(str, Enum):
    PASSED = "passed"
    MISSING = "missing"
    SKIPPED = "skipped"


@dataclass
class ProofEvaluation:
    status: ProofStatus
    missing_sections: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_line_endings(text: str = "") -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _mask_html_comments(text: str) -> str:
    """Replace HTML comment content with spaces so commented-out template
    text does not count as authored content."""
    return re.sub(
        r"<!--.*?-->",
        lambda m: " " * len(m.group(0)),
        text,
        flags=re.DOTALL,
    )


def _strip_code_fences(text: str) -> str:
    """Remove fenced code blocks so headings/copy-pasted template text
    inside them do not trick the section parser."""
    return re.sub(r"```[^\n]*\n.*?```", "", text, flags=re.DOTALL)


def _extract_sections(body: str) -> dict[str, str]:
    """Split a PR body into a ``{heading: body}`` mapping."""
    body = _normalize_line_endings(body)
    body = _mask_html_comments(body)
    body = _strip_code_fences(body)

    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(body))
    for i, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section_body = body[start:end].strip()
        sections[heading] = section_body
    return sections


def _has_real_content(text: str) -> bool:
    """Return True if *text* has substantive authored content (not just
    template placeholders, separators, or ``None``-like values)."""
    text = text.strip()
    if not text:
        return False
    if _MISSING_VALUE_RE.match(text):
        return False
    # Must have at least one alphanumeric character.
    if not re.search(r"[A-Za-z0-9]", text):
        return False
    return True


# ---------------------------------------------------------------------------
# Section name aliases (support legacy + current template)
# ---------------------------------------------------------------------------

_PROBLEM_ALIASES = [
    "what problem this solves",
    "behavior or issue addressed",
    "issue addressed",
    "behavior addressed",
    "description",
]

_EVIDENCE_ALIASES = [
    "evidence",
    "evidence after fix",
    "after-fix evidence",
    "evidence link or embedded proof",
    "local verification evidence",
    "testing",
    "how to test these changes",
]


def _find_section(sections: dict[str, str], aliases: list[str]) -> str | None:
    for alias in aliases:
        for heading, body in sections.items():
            if alias in heading:
                return body
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_pull_request_context(
    *,
    body: str,
    author_association: str = "CONTRIBUTOR",
    author_type: str = "User",
    labels: list[str] | None = None,
) -> ProofEvaluation:
    """Evaluate whether a PR has the required context and evidence.

    Parameters
    ----------
    body
        The PR body text (markdown).
    author_association
        The GitHub ``author_association`` field — ``OWNER``, ``MEMBER``,
        ``COLLABORATOR``, ``CONTRIBUTOR``, ``NONE``, etc.
    author_type
        The GitHub user ``type`` — ``User``, ``Bot``, etc.
    labels
        List of label names on the PR.

    Returns
    -------
    ProofEvaluation
        ``status=PASSED`` if both sections are present with real content,
        ``status=MISSING`` if either is absent or empty,
        ``status=SKIPPED`` for maintainer/bot PRs.
    """
    labels = labels or []

    # --- Skip rules -------------------------------------------------------
    if author_type == "Bot":
        return ProofEvaluation(status=ProofStatus.SKIPPED)

    if author_association in PRIVILEGED_ASSOCIATIONS:
        return ProofEvaluation(status=ProofStatus.SKIPPED)

    # The override label lets a maintainer force-skip — but it does NOT
    # auto-pass; the PR still needs context unless a maintainer explicitly
    # marks it proof-sufficient.
    if PROOF_SUFFICIENT_LABEL in labels:
        return ProofEvaluation(status=ProofStatus.SKIPPED)

    # --- Parse body -------------------------------------------------------
    sections = _extract_sections(body)

    missing: list[str] = []

    problem_text = _find_section(sections, _PROBLEM_ALIASES)
    if problem_text is None or not _has_real_content(problem_text):
        missing.append("What Problem This Solves")

    evidence_text = _find_section(sections, _EVIDENCE_ALIASES)
    if evidence_text is None or not _has_real_content(evidence_text):
        missing.append("Evidence")

    if missing:
        return ProofEvaluation(
            status=ProofStatus.MISSING,
            missing_sections=missing,
            labels=[NEEDS_PR_CONTEXT_LABEL],
        )

    return ProofEvaluation(
        status=ProofStatus.PASSED,
        labels=[PROOF_SUFFICIENT_LABEL],
    )


def labels_for_pull_request_context(evaluation: ProofEvaluation) -> list[str]:
    """Convenience: return the labels to add/remove for a given evaluation."""
    return evaluation.labels
