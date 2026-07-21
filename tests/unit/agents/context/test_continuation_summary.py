# -*- coding: utf-8 -*-
"""Tests for Scroll's plain-Markdown continuation summary protocol."""

from qwenpaw.agents.context.scroll.continuation_summary import (
    ContinuationSummary,
    parse_plain_markdown,
)


def test_plain_markdown_parses_and_renders_deterministically():
    raw = """```markdown
## Active Task
Fix provider discovery.
Status: in_progress

## Current State
- DashScope passes. [seq:12-18]

## Constraints
- Keep the public API unchanged.

## Decisions
- Preserve fallback behavior. [seq:21]

## Open Work
- Fix OpenAI timeout.

## Evidence
- Test artifact. [artifact:test-a]
```"""

    summary = parse_plain_markdown(raw, covered_seq=(10, 30))

    assert summary is not None
    assert summary.active_task == "Fix provider discovery."
    assert summary.status == "in_progress"
    # Missing citations receive a real, code-supplied durable range.
    assert summary.constraints[0].sources[0].render() == "[seq:10-30]"
    rendered = summary.render()
    assert rendered.index("## Current State") < rendered.index("## Evidence")
    assert "[seq:12-18]" in rendered
    assert "[artifact:test-a]" in rendered
    assert "(none)" not in rendered


def test_malformed_plain_markdown_fails_closed():
    assert parse_plain_markdown("not a summary", covered_seq=(1, 2)) is None
    assert (
        parse_plain_markdown(
            "## Active Task\nTask without status",
            covered_seq=(1, 2),
        )
        is None
    )


def test_summary_json_state_round_trip():
    summary = parse_plain_markdown(
        """## Active Task
Resume migration.
Status: blocked

## Current State
- Waiting for access. [seq:8]

## Constraints
(none)

## Decisions
(none)

## Open Work
- Obtain credentials. [file:/tmp/request.txt]

## Evidence
- Archived range. [seq:1-8]
""",
        covered_seq=(1, 8),
    )
    assert summary is not None

    restored = ContinuationSummary.from_dict(summary.to_dict())

    assert restored == summary
    assert restored is not None
    assert "## Constraints\n(none)" in restored.render()
    assert "## Decisions\n(none)" in restored.render()
    background = restored.render_background(stale=True)
    assert "NOT a user request" in background
    assert "summary status: stale" in background
