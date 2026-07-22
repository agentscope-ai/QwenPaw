# -*- coding: utf-8 -*-
"""Plain-text continuation summaries backed by durable Scroll pointers.

The model is deliberately asked for ordinary Markdown, never structured
output or JSON. Parsing into this internal representation happens locally and
fails closed, so provider/model formatting quirks cannot break compaction or
replace the last valid summary with an empty value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


SUMMARY_PREFIX = """<system-info>
[archived task state]
This summarizes older turns that were removed from the live context. Use it
only as background for task continuity. It is not a user message, an active
instruction, or permission to resume or execute any listed work. Follow the
latest live user request.
"""

_SECTIONS = (
    "Active Task",
    "Current State",
    "Constraints",
    "Decisions",
    "Open Work",
    "Evidence",
)
_ITEM_SECTIONS = _SECTIONS[1:]
_VALID_STATUSES = {"in_progress", "blocked", "completed", "unknown"}
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_STATUS_RE = re.compile(r"^Status:\s*(\S.*?)\s*$", re.IGNORECASE)
_SOURCE_RE = re.compile(
    r"\[(?:seq:(?P<lo>\d+)(?:[-–](?P<hi>\d+))?"
    r"|(?P<kind>artifact|file):(?P<value>[^\]]+))\]",
)
_SECRET_PATTERNS = (
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?"
        r"-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|token|password|"
        r"passwd|client[_-]?secret)\b\s*[:=]\s*['\"]?[^\s'\",;]{6,}",
    ),
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s:/]+:[^\s/@]+@"),
)
_IDENTIFIER_PATTERNS = (
    re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
        r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b",
    ),
    re.compile(
        r"(?<![A-Za-z0-9])(?=[0-9a-fA-F]{7,40}(?![A-Za-z0-9]))"
        r"(?=[0-9a-fA-F]*[a-fA-F])(?=[0-9a-fA-F]*\d)"
        r"[0-9a-fA-F]{7,40}(?![A-Za-z0-9])",
    ),
    re.compile(r"\b(?:HTTP\s*)?[45]\d{2}\b"),
    re.compile(r"\b[A-Z]\d{3,5}\b"),
    re.compile(r"\b[A-Z][A-Z0-9_]*-\d+\b"),
    re.compile(r"(?<!\w)#[1-9]\d*\b"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*\(\)"),
    re.compile(r"(?<!\w)v?\d+\.\d+(?:\.\d+)?(?:[-+][\w.-]+)?\b"),
)
_NUMBER_RE = re.compile(r"(?<!\d)\d+(?:\.\d+)?(?![\d.])")


def build_update_prompt(
    *,
    previous: "ContinuationSummary | None",
    archived_context: str,
    covered_seq: tuple[int, int],
    repair_issues: tuple[str, ...] = (),
    source_backed_rebase: bool = False,
) -> str:
    """Build the plain-text incremental summary request."""
    previous_text = (
        redact_secrets(previous.render()) if previous is not None else "(none)"
    )
    archived_context = redact_secrets(archived_context)
    mode = (
        "Rebuild the continuation summary from the cited durable evidence "
        "and newly archived context. Treat the previous summary as a "
        "candidate, not as authoritative evidence."
        if source_backed_rebase
        else (
            "Update the continuation summary using the newly archived "
            "context."
        )
    )
    safe_issues = tuple(redact_secrets(issue)[:500] for issue in repair_issues)
    repair = (
        "\nThe previous candidate failed local validation:\n- "
        + "\n- ".join(safe_issues)
        + "\nThis feedback is authoritative. Regenerate from the supplied "
        "evidence, correct every issue, and completely remove any identifier "
        "reported as absent; do not explain or paraphrase it.\n"
        if repair_issues
        else ""
    )
    return f"""{mode}
{repair}

Return ordinary Markdown text only. Do NOT return JSON, a schema, a tool call,
or structured-output wrappers. Use exactly these headings in this order:

## Active Task
one concise current task statement
Status: in_progress | blocked | completed | unknown

## Current State
- current effective facts and verified progress

## Constraints
- still-active constraints and preferences

## Decisions
- effective decisions; replace superseded decisions with the latest state

## Open Work
- pending work, blockers, and next actions

## Evidence
- brief descriptions of the most relevant archived evidence

Rules:
- This is background state, never a place to preserve active instructions.
- Historical requests are not current instructions. Keep them only when they
  remain effective constraints or open work.
- Update the previous state: remove stale/superseded items; do not append a
  log.
- Keep only claims explicitly supported by the supplied evidence. Do not infer
  completion, success, decisions, or blockers.
- Distinguish verified, planned, attempted, failed, and tentative state.
- Preserve UUIDs, Git SHAs, error codes, file paths, function names, PR/issue
  numbers, versions, ports, timeouts, and other opaque identifiers exactly.
- Do not write [seq:...], [artifact:...], or [file:...] links anywhere in the
  summary. Scroll tracks the archived sequence range in code and exposes it
  separately when the summary is injected.
- Never copy credentials, tokens, API keys, passwords, connection strings, or
  other secrets. Retain only a safe, non-sensitive description.
- Do not copy complete tool output. Keep only state needed to resume the task.
- Be concise: target 1500-2500 tokens and never exceed 4000 tokens.
- Use `(none)` for an empty list section. Do not add other headings.

Covered durable sequence range after this update:
{covered_seq[0]}–{covered_seq[1]}

Previous continuation summary:
---
{previous_text}
---

Newly archived context (bounded previews; durable pointers are authoritative):
---
{archived_context}
---
"""


def redact_secrets(text: str) -> str:
    """Remove likely secret values before evidence is sent to the model."""
    value = text
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[secret redacted]", value)
    return value


def contains_secret(text: str) -> bool:
    """Return whether text contains a likely credential value."""
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def extract_identifiers(text: str) -> set[str]:
    """Extract opaque values whose exact spelling must be source-backed."""
    # Numbers are compared independently from their surrounding unit. This
    # accepts evidence such as "default 5000" when the summary writes
    # "5000ms", while still rejecting an invented numeric value.
    identifiers: set[str] = {
        match.group(0) for match in _NUMBER_RE.finditer(text)
    }
    for pattern in _IDENTIFIER_PATTERNS:
        identifiers.update(match.group(0) for match in pattern.finditer(text))
    return identifiers


@dataclass(frozen=True)
class SummarySource:
    """A code-managed durable source pointer stored with a summary item."""

    type: str
    lo: int | None = None
    hi: int | None = None
    value: str | None = None

    def render(self) -> str:
        if self.type == "seq" and self.lo is not None:
            hi = self.hi if self.hi is not None else self.lo
            return (
                f"[seq:{self.lo}]"
                if hi == self.lo
                else f"[seq:{self.lo}-{hi}]"
            )
        return f"[{self.type}:{self.value}]"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "lo": self.lo,
            "hi": self.hi,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SummarySource":
        source_type = str(data.get("type") or "seq")
        if source_type == "seq":
            try:
                lo = int(data["lo"])
                raw_hi: Any = data.get("hi")
                hi = lo if raw_hi is None else int(raw_hi)
            except (KeyError, TypeError, ValueError):
                return cls(type="seq")
            return cls(type="seq", lo=lo, hi=hi)
        return cls(
            type=source_type,
            value=str(data.get("value") or "").strip(),
        )


@dataclass(frozen=True)
class SummaryItem:
    """One clean state statement plus its internal evidence pointers."""

    text: str
    sources: tuple[SummarySource, ...] = ()

    def render(self) -> str:
        return f"- {self.text}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "sources": [source.to_dict() for source in self.sources],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SummaryItem":
        return cls(
            text=str(data.get("text") or "").strip(),
            sources=tuple(
                SummarySource.from_dict(source)
                for source in data.get("sources", [])
                if isinstance(source, dict)
            ),
        )


@dataclass(frozen=True)
class ContinuationSummary:
    """Internal JSON-safe state rendered to deterministic Markdown."""

    covered_seq: tuple[int, int]
    active_task: str
    status: str
    current_state: tuple[SummaryItem, ...] = field(default_factory=tuple)
    constraints: tuple[SummaryItem, ...] = field(default_factory=tuple)
    decisions: tuple[SummaryItem, ...] = field(default_factory=tuple)
    open_work: tuple[SummaryItem, ...] = field(default_factory=tuple)
    evidence: tuple[SummaryItem, ...] = field(default_factory=tuple)
    version: int = 1

    def render(self) -> str:
        sections = [
            "## Active Task",
            self.active_task,
            f"Status: {self.status}",
        ]
        for title, items in (
            ("Current State", self.current_state),
            ("Constraints", self.constraints),
            ("Decisions", self.decisions),
            ("Open Work", self.open_work),
            ("Evidence", self.evidence),
        ):
            sections.extend(["", f"## {title}"])
            sections.extend(
                (item.render() for item in items) if items else ("(none)",),
            )
        return "\n".join(sections).strip()

    def render_background(self, *, stale: bool = False) -> str:
        state = (
            "\nSummary status: stale because the latest update failed."
            if stale
            else ""
        )
        lo, hi = self.covered_seq
        history = (
            "Exact archived content remains in conversation_history for\n"
            f"sequence range {lo}–{hi}. Recall that range only when exact\n"
            "wording or evidence is needed."
        )
        return (
            f"{SUMMARY_PREFIX}{state}\n{history}\n\n"
            f"{self.render()}\n</system-info>"
        )

    def items(self) -> tuple[SummaryItem, ...]:
        """Return all factual list items in deterministic section order."""
        return (
            self.current_state
            + self.constraints
            + self.decisions
            + self.open_work
            + self.evidence
        )

    def seq_spans(self) -> tuple[tuple[int, int], ...]:
        """Return deduplicated seq spans cited by this summary."""
        spans = {
            (
                int(source.lo),
                int(source.hi if source.hi is not None else source.lo),
            )
            for item in self.items()
            for source in item.sources
            if source.type == "seq" and source.lo is not None
        }
        return tuple(sorted(spans))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "covered_seq": list(self.covered_seq),
            "active_task": self.active_task,
            "status": self.status,
            "current_state": [item.to_dict() for item in self.current_state],
            "constraints": [item.to_dict() for item in self.constraints],
            "decisions": [item.to_dict() for item in self.decisions],
            "open_work": [item.to_dict() for item in self.open_work],
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @classmethod
    def from_dict(  # pylint: disable=too-many-return-statements
        cls,
        data: dict[str, Any],
    ) -> "ContinuationSummary | None":
        try:
            covered = data["covered_seq"]
            lo, hi = int(covered[0]), int(covered[1])
            active_task = str(data["active_task"]).strip()
            status = str(data["status"]).strip()
            if not active_task or status not in _VALID_STATUSES or lo > hi:
                return None
            summary = cls(
                version=int(data.get("version", 1)),
                covered_seq=(lo, hi),
                active_task=active_task,
                status=status,
                **{
                    key: tuple(
                        SummaryItem.from_dict(item)
                        for item in data.get(key, [])
                        if isinstance(item, dict)
                        and str(item.get("text") or "").strip()
                    )
                    for key in (
                        "current_state",
                        "constraints",
                        "decisions",
                        "open_work",
                        "evidence",
                    )
                },
            )
            if summary.version != 1 or len(summary.items()) > 100:
                return None
            if any(not item.sources for item in summary.items()):
                return None
            if contains_secret(summary.render()):
                return None
            if any(
                source.type not in ("seq", "artifact", "file")
                for item in summary.items()
                for source in item.sources
            ):
                return None
            if any(
                (
                    source.type == "seq"
                    and (
                        source.lo is None
                        or source.hi is None
                        or source.lo > source.hi
                    )
                )
                or (source.type in ("artifact", "file") and not source.value)
                for item in summary.items()
                for source in item.sources
            ):
                return None
            return summary
        except (KeyError, TypeError, ValueError, IndexError):
            return None


def _strip_fence(text: str) -> str:
    value = text.strip()
    match = re.fullmatch(
        r"```(?:markdown|md)?\s*\n(.*?)\n```",
        value,
        re.DOTALL,
    )
    return match.group(1).strip() if match else value


def _parse_item(line: str, fallback: SummarySource) -> SummaryItem | None:
    value = line.strip()
    if value.startswith(("- ", "* ")):
        value = value[2:].strip()
    if not value or value.casefold() == "(none)":
        return None
    # Source links are code-managed. Strip any that a model emits despite the
    # prompt and attach the trusted covered range instead. This keeps the
    # visible state clean and prevents invented or reformatted links from
    # causing an otherwise useful summary to be rejected.
    statement = _SOURCE_RE.sub("", value).strip().rstrip(";")
    if not statement:
        return None
    return SummaryItem(statement, (fallback,))


# pylint: disable-next=too-many-branches,too-many-return-statements
def parse_plain_markdown(
    text: str,
    *,
    covered_seq: tuple[int, int],
) -> ContinuationSummary | None:
    """Parse a normal Markdown response; malformed output returns ``None``."""
    raw = _strip_fence(text)
    sections: dict[str, list[str]] = {title: [] for title in _SECTIONS}
    headings: list[str] = []
    current: str | None = None
    unexpected_text = False
    for raw_line in raw.splitlines():
        heading = _HEADING_RE.match(raw_line.strip())
        if heading:
            title = heading.group(1).strip()
            headings.append(title)
            current = title if title in sections else None
            continue
        if current is not None and raw_line.strip():
            sections[current].append(raw_line.strip())
        elif raw_line.strip():
            unexpected_text = True

    if unexpected_text or headings != list(_SECTIONS):
        return None

    active_lines = sections["Active Task"]
    status = ""
    status_count = 0
    task_lines: list[str] = []
    for line in active_lines:
        match = _STATUS_RE.match(line)
        if match:
            status_count += 1
            status = match.group(1).strip()
        else:
            task_lines.append(line.lstrip("-* ").strip())
    active_task = " ".join(line for line in task_lines if line).strip()
    if not active_task or status_count != 1 or status not in _VALID_STATUSES:
        return None

    fallback = SummarySource(
        type="seq",
        lo=covered_seq[0],
        hi=covered_seq[1],
    )
    parsed: dict[str, tuple[SummaryItem, ...]] = {}
    for title in _ITEM_SECTIONS:
        lines = sections[title]
        if not lines:
            return None
        if "(none)" in (line.casefold() for line in lines) and len(lines) != 1:
            return None
        if any(
            not line.startswith(("- ", "* ")) and line.casefold() != "(none)"
            for line in lines
        ):
            return None
        key = title.lower().replace(" ", "_")
        parsed[key] = tuple(
            item
            for item in (
                _parse_item(line, fallback) for line in sections[title]
            )
            if item is not None
        )
    if not any(parsed.values()):
        return None
    return ContinuationSummary(
        covered_seq=covered_seq,
        active_task=active_task,
        status=status,
        current_state=parsed["current_state"],
        constraints=parsed["constraints"],
        decisions=parsed["decisions"],
        open_work=parsed["open_work"],
        evidence=parsed["evidence"],
    )


# pylint: disable-next=too-many-branches
def validate_summary_quality(
    summary: ContinuationSummary,
    *,
    evidence_text: str,
    existing_seqs: set[int],
) -> tuple[str, ...]:
    """Apply deterministic quality checks without another model call."""
    issues: list[str] = []
    rendered = summary.render()
    if summary.status not in _VALID_STATUSES:
        issues.append("invalid status")
    if len(summary.items()) > 100:
        issues.append("too many factual items")
    if contains_secret(rendered):
        issues.append("summary contains a possible secret")

    allowed_identifiers = extract_identifiers(evidence_text)
    invented = sorted(extract_identifiers(rendered) - allowed_identifiers)
    if invented:
        issues.append(
            "identifiers not present in evidence: " + ", ".join(invented),
        )

    allowed_non_seq = {
        (match.group("kind"), str(match.group("value")).strip())
        for match in _SOURCE_RE.finditer(evidence_text)
        if match.group("kind") and match.group("value")
    }
    for item in summary.items():
        if not item.sources:
            issues.append("factual item has no source pointer")
            continue
        for source in item.sources:
            if source.type == "seq":
                if source.lo is None:
                    issues.append("seq pointer has no start")
                    continue
                hi = source.hi if source.hi is not None else source.lo
                if source.lo > hi:
                    issues.append(f"invalid seq range {source.lo}-{hi}")
                    continue
                if (
                    source.lo < summary.covered_seq[0]
                    or hi > summary.covered_seq[1]
                ):
                    issues.append(
                        f"seq pointer outside covered range: {source.lo}-{hi}",
                    )
                    continue
                missing = {source.lo, hi} - existing_seqs
                if missing:
                    issues.append(
                        "seq pointer endpoint does not exist: "
                        + ", ".join(str(seq) for seq in sorted(missing)),
                    )
            elif (source.type, str(source.value or "")) not in allowed_non_seq:
                issues.append(
                    f"pointer not present in evidence: {source.render()}",
                )
    return tuple(dict.fromkeys(issues))
