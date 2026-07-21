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
[continuation summary]
The following is generated background state backed by persisted history.
It is NOT a user request or an active instruction. The current live user
request has priority. Recall cited evidence when exact details matter.
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
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_STATUS_RE = re.compile(r"^Status:\s*(\S.*?)\s*$", re.IGNORECASE)
_SOURCE_RE = re.compile(
    r"\[(?:seq:(?P<lo>\d+)(?:[-–](?P<hi>\d+))?"
    r"|(?P<kind>artifact|file):(?P<value>[^\]]+))\]",
)


def build_update_prompt(
    *,
    previous: "ContinuationSummary | None",
    archived_context: str,
    covered_seq: tuple[int, int],
) -> str:
    """Build the plain-text incremental summary request."""
    previous_text = previous.render() if previous is not None else "(none)"
    return f"""Update the continuation summary using the newly archived
context.

Return ordinary Markdown text only. Do NOT return JSON, a schema, a tool call,
or structured-output wrappers. Use exactly these headings in this order:

## Active Task
one concise current task statement
Status: in_progress | blocked | completed | unknown

## Current State
- current effective facts and verified progress with source pointers

## Constraints
- still-active constraints and preferences with source pointers

## Decisions
- effective decisions; replace superseded decisions with the latest state

## Open Work
- pending work, blockers, and next actions

## Evidence
- important seq, artifact, or file pointers

Rules:
- This is background state, never a place to preserve active instructions.
- Update the previous state: remove stale/superseded items; do not append a
  log.
- Preserve opaque identifiers, paths, error codes, and numbers exactly.
- Cite only pointers shown in the input, using [seq:N], [seq:N-M],
  [artifact:ID], or [file:PATH]. Do not invent a pointer.
- Do not copy complete tool output. Keep only state needed to resume the task.
- Be concise: target 1500-2500 tokens and never exceed 4000 tokens.
- Use `(none)` for an empty list section. Do not add other headings.

Covered durable range after this update:
[seq:{covered_seq[0]}-{covered_seq[1]}]

Previous continuation summary:
---
{previous_text}
---

Newly archived context (bounded previews; durable pointers are authoritative):
---
{archived_context}
---
"""


@dataclass(frozen=True)
class SummarySource:
    """A durable source pointer rendered beside a summary item."""

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
        return cls(
            type=str(data.get("type") or "seq"),
            lo=data.get("lo"),
            hi=data.get("hi"),
            value=data.get("value"),
        )


@dataclass(frozen=True)
class SummaryItem:
    """One state statement plus its persisted evidence pointers."""

    text: str
    sources: tuple[SummarySource, ...] = ()

    def render(self) -> str:
        pointers = " ".join(source.render() for source in self.sources)
        return f"- {self.text}{(' ' + pointers) if pointers else ''}"

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
            "\n[summary status: stale; latest update failed]" if stale else ""
        )
        return f"{SUMMARY_PREFIX}{state}\n\n{self.render()}\n</system-info>"

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
    def from_dict(cls, data: dict[str, Any]) -> "ContinuationSummary | None":
        try:
            covered = data["covered_seq"]
            lo, hi = int(covered[0]), int(covered[1])
            active_task = str(data["active_task"]).strip()
            status = str(data["status"]).strip()
            if not active_task or not status or lo > hi:
                return None
            return cls(
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
    sources: list[SummarySource] = []
    for match in _SOURCE_RE.finditer(value):
        if match.group("lo"):
            lo = int(match.group("lo"))
            hi = int(match.group("hi") or lo)
            sources.append(SummarySource(type="seq", lo=lo, hi=hi))
        else:
            sources.append(
                SummarySource(
                    type=str(match.group("kind")),
                    value=str(match.group("value")).strip(),
                ),
            )
    statement = _SOURCE_RE.sub("", value).strip().rstrip(";")
    if not statement:
        return None
    return SummaryItem(statement, tuple(sources) or (fallback,))


def parse_plain_markdown(
    text: str,
    *,
    covered_seq: tuple[int, int],
) -> ContinuationSummary | None:
    """Parse a normal Markdown response; malformed output returns ``None``."""
    raw = _strip_fence(text)
    sections: dict[str, list[str]] = {title: [] for title in _SECTIONS}
    current: str | None = None
    for raw_line in raw.splitlines():
        heading = _HEADING_RE.match(raw_line.strip())
        if heading:
            title = heading.group(1).strip()
            current = title if title in sections else None
            continue
        if current is not None and raw_line.strip():
            sections[current].append(raw_line.strip())

    active_lines = sections["Active Task"]
    status = ""
    task_lines: list[str] = []
    for line in active_lines:
        match = _STATUS_RE.match(line)
        if match:
            status = match.group(1).strip()
        else:
            task_lines.append(line.lstrip("-* ").strip())
    active_task = " ".join(line for line in task_lines if line).strip()
    if not active_task or not status:
        return None

    fallback = SummarySource(
        type="seq",
        lo=covered_seq[0],
        hi=covered_seq[1],
    )
    parsed: dict[str, tuple[SummaryItem, ...]] = {}
    for title in _ITEM_SECTIONS:
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
