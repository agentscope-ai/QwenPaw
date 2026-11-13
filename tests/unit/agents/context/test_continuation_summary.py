# -*- coding: utf-8 -*-
"""Tests for Scroll's plain-Markdown continuation summary protocol."""

from qwenpaw.agents.context.scroll.continuation_summary import (
    ContinuationSummary,
    SummarySource,
    build_update_prompt,
    extract_identifiers,
    redact_secrets,
    parse_plain_markdown,
    validate_summary_quality,
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
```"""

    summary = parse_plain_markdown(raw, covered_seq=(10, 30))

    assert summary is not None
    assert summary.active_task == "Fix provider discovery."
    assert summary.status == "in_progress"
    # All items receive the real, code-supplied durable range internally.
    assert summary.constraints[0].sources[0].render() == "[seq:10-30]"
    rendered = summary.render()
    assert rendered.index("## Current State") < rendered.index("## Open Work")
    assert "## Evidence" not in rendered
    assert "[seq:" not in rendered
    assert "[artifact:" not in rendered
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
    duplicate = """## Active Task
Task
Status: in_progress
## Current State
- state
## Constraints
(none)
## Decisions
(none)
## Open Work
(none)
## Open Work
- duplicate
"""
    assert parse_plain_markdown(duplicate, covered_seq=(1, 2)) is None


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
    assert "not a user message" in background
    assert "Summary status: stale" in background
    assert "sequence range 1–8" in background


def test_legacy_checkpoint_evidence_is_ignored_on_load():
    summary = ContinuationSummary.from_dict(
        {
            "version": 1,
            "covered_seq": [1, 3],
            "active_task": "Resume migration.",
            "status": "in_progress",
            "current_state": [
                {
                    "text": "Migration started.",
                    "sources": [{"type": "seq", "lo": 1, "hi": 3}],
                },
            ],
            "constraints": [],
            "decisions": [],
            "open_work": [],
            "evidence": [
                {
                    "text": "Legacy evidence entry.",
                    "sources": [{"type": "seq", "lo": 1, "hi": 3}],
                },
            ],
        },
    )

    assert summary is not None
    assert "Legacy evidence entry" not in summary.render()
    assert "evidence" not in summary.to_dict()


def test_prompt_and_redaction_encode_quality_constraints():
    prompt = build_update_prompt(
        mode="update",
        previous=None,
        archived_context="[seq:1] token=secret-value-123",
        covered_seq=(1, 1),
        repair_issues=("invalid status",),
        focus_hint="Prioritize HTTP failures; token=hint-secret-123",
    )

    assert "Do NOT return JSON" in prompt
    assert "completion, success, decisions, or blockers" in prompt
    assert "Never copy credentials" in prompt
    assert "Do not write [seq:...]" in prompt
    assert "invalid status" in prompt
    assert "previous summary as the baseline" in prompt
    assert "Replace an unsupported identifier with the exact value" in prompt
    assert "remove only the unsupported claim" in prompt
    assert "One-shot compaction focus hint" in prompt
    assert "Prioritize HTTP failures" in prompt
    assert "It is not evidence, conversation state" in prompt
    assert "Prioritize independent user constraints" in prompt
    assert "Do not speculate that more tasks" in prompt
    assert "bounded previews are incomplete" in prompt
    assert "evidence that something did not happen" in prompt
    assert "reconcile Current State with Open Work" in prompt
    assert "tests pass; implementation status unknown" in prompt
    assert "Constraints describe effective" in prompt
    assert "requirements, not implementation progress" in prompt
    assert "Current State to 5-8 high-value bullets" in prompt
    assert "hint-secret-123" not in prompt
    assert "secret-value-123" not in redact_secrets(
        "token=secret-value-123",
    )


def test_prompt_modes_share_one_output_protocol():
    initial = build_update_prompt(
        mode="initial",
        previous=None,
        archived_context="[seq:1] task state",
        covered_seq=(1, 1),
    )
    update = build_update_prompt(
        mode="update",
        previous=None,
        archived_context="[seq:1] task state",
        covered_seq=(1, 1),
    )
    assert "Create the first continuation summary" in initial
    assert "Update the previous continuation summary" in update
    assert "previous summary as the baseline" in update
    assert "prefer the newer state" in update
    for prompt in (initial, update):
        assert "## Open Work" in prompt
        assert "## Evidence" not in prompt


def test_chinese_prompt_localizes_instructions_but_keeps_protocol_headings():
    prompt = build_update_prompt(
        mode="update",
        previous=None,
        archived_context="[seq:1] 修复 provider discovery",
        covered_seq=(1, 1),
        repair_issues=("invalid status",),
        focus_hint="优先保留用户约束",
        language="zh",
    )

    assert "更新上一份 continuation summary" in prompt
    assert "所有自然语言内容均使用中文" in prompt
    assert "本次压缩的临时关注提示" in prompt
    assert "上一份候选 summary 未通过本地校验" in prompt
    assert "独立的用户约束和未解决要求优先" in prompt
    assert "不要猜测将来还会出现更多任务" in prompt
    assert "“没有看到”不是“没有发生”的证据" in prompt
    assert "协调 Current State 与" in prompt
    assert "测试通过；实现状态未知" in prompt
    assert "Constraints 描述仍然有效的要求" in prompt
    assert "Current State 通常最多保留 5～8 个" in prompt
    assert "## Active Task" in prompt
    assert "Status: in_progress | blocked | completed | unknown" in prompt
    assert "## Open Work" in prompt


def test_unknown_summary_language_falls_back_to_english():
    prompt = build_update_prompt(
        mode="initial",
        previous=None,
        archived_context="[seq:1] task state",
        covered_seq=(1, 1),
        language="ru",
    )

    assert "Create the first continuation summary" in prompt
    assert "write natural-language content in English" in prompt


def test_quality_guard_rejects_only_exact_duplicate_state_items():
    summary = parse_plain_markdown(
        """## Active Task
Fix discovery.
Status: in_progress

## Current State
- DashScope passes.

## Constraints
(none)

## Decisions
- dashscope   PASSES.

## Open Work
- Fix OpenAI.
""",
        covered_seq=(1, 2),
    )
    assert summary is not None

    issues = validate_summary_quality(
        summary,
        evidence_text="[seq:1-2] DashScope passes. Fix OpenAI.",
        existing_seqs={1, 2},
    )

    assert "summary contains duplicate state items" in issues


def test_quality_guard_rejects_missing_endpoints_identifiers_and_secrets():
    summary = parse_plain_markdown(
        """## Active Task
Fix request #999 using token=secret-value-123.
Status: in_progress

## Current State
- Broken at HTTP 403. [seq:1-2]

## Constraints
(none)

## Decisions
(none)

## Open Work
(none)
""",
        covered_seq=(1, 2),
    )
    assert summary is not None

    issues = validate_summary_quality(
        summary,
        evidence_text="[seq:1-2] source says HTTP 403",
        existing_seqs={1},
    )

    assert "summary contains a possible secret" in issues
    assert any("#999" in issue for issue in issues)
    assert any("endpoint does not exist: 2" in issue for issue in issues)
    assert not any("artifact:invented" in issue for issue in issues)


def test_model_source_links_are_replaced_by_the_trusted_covered_range():
    summary = parse_plain_markdown(
        """## Active Task
Fix discovery.
Status: in_progress

## Current State
- DashScope passes. [seq:999]

## Constraints
(none)

## Decisions
(none)

## Open Work
- Verify the adapter. [file:invented.py]
""",
        covered_seq=(10, 20),
    )
    assert summary is not None
    assert all(
        item.sources == (SummarySource(type="seq", lo=10, hi=20),)
        for item in summary.items()
    )
    assert "[seq:" not in summary.render()
    assert "[file:" not in summary.render()
    assert "[artifact:" not in summary.render()


def test_identifier_validation_ignores_ordinary_numbers():
    assert "5000" not in extract_identifiers("timeout defaults to 5000")
    assert "5000" not in extract_identifiers("timeout is 5000ms")
    assert "src/qwenpaw/models" not in extract_identifiers(
        "code under src/qwenpaw/models",
    )
    assert "HIT/MISS" not in extract_identifiers("cache was HIT/MISS")

    summary = parse_plain_markdown(
        """## Active Task
Tune the timeout.
Status: in_progress

## Current State
- The timeout is 5000ms. [seq:1]

## Constraints
(none)

## Decisions
(none)

## Open Work
(none)
""",
        covered_seq=(1, 1),
    )
    assert summary is not None

    issues = validate_summary_quality(
        summary,
        evidence_text="[seq:1] timeout defaults to 5000",
        existing_seqs={1},
    )

    assert not any("identifiers not present" in issue for issue in issues)


def test_identifier_validation_still_rejects_invented_opaque_values():
    summary = parse_plain_markdown(
        """## Active Task
Fix request #999.
Status: in_progress

## Current State
- The provider returns HTTP 403.

## Constraints
(none)

## Decisions
(none)

## Open Work
(none)
""",
        covered_seq=(1, 1),
    )
    assert summary is not None

    issues = validate_summary_quality(
        summary,
        evidence_text="[seq:1] Fix request #123 after HTTP 403.",
        existing_seqs={1},
    )

    assert any("#999" in issue for issue in issues)
    assert not any("403" in issue for issue in issues)
