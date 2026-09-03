# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-import,unused-variable
"""Unit tests for the visual compression pipeline modules.

Covers the deterministic, in-process pipeline stages that turn native
message content into rendered visual pages: token budgeting and
profitability policy (budget), recovery bookkeeping (receipt), exact-value
factsheet extraction (precision), message serialization (messages),
tool-result paging (tool_results), history collapse planning (history),
system/tool static imaging (static_context), tool documentation planning
(tool_schemas), and the end-to-end request transform (request).
"""

from __future__ import annotations

import json

import pytest
from agentscope.message import (
    Base64Source,
    DataBlock,
    Msg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultState,
)

from qwenpaw.agents.context.visual_compression.config import (
    LOW_EFFORT_PRESET,
    EffortPreset,
    effort_preset,
)
from qwenpaw.agents.context.visual_compression.pipeline import (
    history as history_mod,
)
from qwenpaw.agents.context.visual_compression.pipeline import (
    messages as messages_mod,
)
from qwenpaw.agents.context.visual_compression.pipeline import (
    request as request_mod,
)
from qwenpaw.agents.context.visual_compression.pipeline import (
    static_context as static_mod,
)
from qwenpaw.agents.context.visual_compression.pipeline import (
    tool_results as tool_results_mod,
)
from qwenpaw.agents.context.visual_compression.pipeline import (
    tool_schemas as tool_schemas_mod,
)
from qwenpaw.agents.context.visual_compression.pipeline.budget import (
    RequestBudget,
    count_text_tokens,
    estimate_image_tokens,
    estimate_visual_replacement_tokens,
    profitable,
)
from qwenpaw.agents.context.visual_compression.pipeline.precision import (
    FactEntry,
    extract_fact_entries,
    factsheet_text,
)
from qwenpaw.agents.context.visual_compression.pipeline.receipt import (
    CompressionReceipt,
    make_recovery_id,
    record_pages,
)
from qwenpaw.agents.context.visual_compression.rendering import (
    RenderedPage,
    estimate_text_pages,
    measure_content_columns,
    page_count_for_text,
    prepare_render_text,
)
from qwenpaw.constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)

LOW = effort_preset("low")

BIG_TOOL_TEXT = "\n".join(
    f"line {i}: deterministic content used for paging behaviour"
    for i in range(400)
)


def make_page(width: int, height: int) -> RenderedPage:
    return RenderedPage(
        png=b"\x89PNG",
        width=width,
        height=height,
        dropped_chars=0,
        dropped_codepoints=0,
    )


def text_message(role: str, text: str, **kwargs) -> Msg:
    return Msg(name=role, role=role, content=[TextBlock(text=text)], **kwargs)


def assistant_tool_result(block: ToolResultBlock) -> Msg:
    return Msg(name="assistant", role="assistant", content=[block])


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------


class TestCountTextTokens:
    def test_empty_text_is_zero(self):
        assert count_text_tokens("") == 0

    def test_ascii_bytes_round_to_tokens(self):
        # 400 ASCII bytes / 4 chars-per-token = 100 tokens exactly.
        assert count_text_tokens("a" * 400) == 100

    def test_minimum_one_token_for_short_text(self):
        assert count_text_tokens("a") == 1

    def test_multibyte_counts_utf8_bytes(self):
        # Each CJK char is 3 UTF-8 bytes: 30 chars = 90 bytes -> 23 tokens.
        assert count_text_tokens("\u4e2d" * 30) == 23

    def test_custom_chars_per_token(self):
        assert count_text_tokens("abcdefgh", chars_per_token=2.0) == 4


class TestRequestBudget:
    def test_generated_images_allowance(self):
        budget = RequestBudget.from_image_count(64, images=10)
        assert budget.max_total_images == 64
        assert budget.original_images == 10
        assert budget.generated_images == 54

    def test_oversized_original_images_yield_zero_generated(self):
        budget = RequestBudget.from_image_count(10, images=100)
        assert budget.generated_images == 0


class TestEstimateImageTokens:
    def test_single_patch_image(self):
        # One 28x28 patch -> ceil(1 * 1.10 safety margin) = 2 tokens.
        tokens = estimate_image_tokens([make_page(28, 28)])
        assert tokens == 2

    def test_multiple_pages_sum_patches(self):
        tokens = estimate_image_tokens([make_page(28, 28), make_page(56, 56)])
        # (1 + 4) patches * 1.10 = 5.5 -> 6
        assert tokens == 6


class TestProfitable:
    def test_large_baseline_accepts_small_replacement(self):
        baseline = "x" * 200_000
        accepted = profitable(
            baseline,
            "short rendered",
            columns=40,
            preset=LOW,
            replacement_text="marker",
            estimated_pages=[make_page(28, 28)],
        )
        assert accepted is True

    def test_tiny_baseline_rejects_replacement(self):
        accepted = profitable(
            "tiny",
            "tiny",
            columns=40,
            preset=LOW,
            replacement_text="marker that is longer than the source",
            estimated_pages=[make_page(1568, 728)],
        )
        assert accepted is False

    def test_image_count_cap_limits_generated_images(self):
        # Uncapped estimate needs many images; a cap of 1 keeps cost low.
        rendered = "\n".join(f"row {i}" for i in range(500))
        accepted = profitable(
            "y" * 100_000,
            rendered,
            columns=40,
            preset=LOW,
            image_count_cap=1,
            replacement_text="",
        )
        assert accepted is True


class TestEstimateVisualReplacementTokens:
    def test_combines_text_and_image_costs(self):
        pages = [make_page(28, 28)]
        total = estimate_visual_replacement_tokens("abcd", pages)
        assert total == count_text_tokens("abcd") + estimate_image_tokens(
            pages,
        )


# ---------------------------------------------------------------------------
# receipt
# ---------------------------------------------------------------------------


class TestRecoveryId:
    def test_id_format(self):
        recovery_id = make_recovery_id("some text", "tool_result", "call_1")
        assert recovery_id.startswith("vctx_")
        assert len(recovery_id) == len("vctx_") + 12

    def test_equal_text_different_provenance_never_collide(self):
        first = make_recovery_id("same", "tool_result", "call_1")
        second = make_recovery_id("same", "tool_result", "call_2")
        assert first != second

    def test_equal_text_different_region_never_collide(self):
        first = make_recovery_id("same", "tool_result", "")
        second = make_recovery_id("same", "history", "")
        assert first != second


class TestRecordPages:
    def test_aggregates_totals_and_regions(self):
        receipt = CompressionReceipt()
        record_pages(
            receipt,
            2,
            "source text",
            "tool_result",
            "call_9",
            source_estimated_tokens=100,
            replacement_estimated_tokens=40,
        )
        record_pages(
            receipt,
            1,
            "more",
            "history",
            source_estimated_tokens=10,
            replacement_estimated_tokens=5,
        )
        assert receipt.image_count == 3
        assert receipt.compressed_chars == len("source text") + len("more")
        assert receipt.source_estimated_tokens == 110
        assert receipt.replacement_estimated_tokens == 45
        assert receipt.regions == {"tool_result": 1, "history": 1}
        assert len(receipt.recoverable) == 2

    def test_negative_token_inputs_clamped_to_zero(self):
        receipt = CompressionReceipt()
        record_pages(
            receipt,
            1,
            "t",
            "history",
            source_estimated_tokens=-5,
            replacement_estimated_tokens=-3,
        )
        assert receipt.source_estimated_tokens == 0
        assert receipt.replacement_estimated_tokens == 0

    def test_provenance_omitted_when_empty(self):
        receipt = CompressionReceipt()
        record_pages(receipt, 1, "t", "static_slab")
        assert "provenance" not in receipt.recoverable[0]

    def test_provenance_kept_when_given(self):
        receipt = CompressionReceipt()
        record_pages(receipt, 1, "t", "history", "0:10")
        assert receipt.recoverable[0]["provenance"] == "0:10"
        assert receipt.recoverable[0]["text"] == "t"


# ---------------------------------------------------------------------------
# precision
# ---------------------------------------------------------------------------


class TestExtractFactEntries:
    def test_empty_text_and_zero_limit(self):
        assert extract_fact_entries("") == []
        assert extract_fact_entries("uuid 1234", limit=0) == []

    def test_uuid_email_and_currency_extracted(self):
        uuid = "123e4567-e89b-42d3-a456-426614174000"
        text = (
            f"contact admin@example.com about {uuid} "
            "and pay $1,234.56 today"
        )
        values = {entry.value for entry in extract_fact_entries(text)}
        assert uuid in values
        assert "admin@example.com" in values
        assert "$1,234.56" in values

    def test_counts_repeated_tokens(self):
        text = "ticket AB-123 again ticket AB-123 end"
        entries = extract_fact_entries(text)
        repeated = [entry for entry in entries if entry.value == "AB-123"]
        assert len(repeated) == 1
        assert repeated[0].count == 2

    def test_limit_caps_entries(self):
        text = " ".join(f"token_{i}X" for i in range(50))
        assert len(extract_fact_entries(text, limit=5)) <= 5

    def test_short_chunks_are_ignored(self):
        # Chunks shorter than 3 chars carry no facts.
        assert extract_fact_entries("a bb c") == []


class TestFactsheetText:
    def test_empty_when_no_facts(self):
        assert factsheet_text("nothing interesting here !!!") == ""

    def test_opener_and_joined_body(self):
        text = "version 1.2.3 released"
        sheet = factsheet_text(text)
        assert sheet.startswith("[Exact identifiers")
        assert "1.2.3" in sheet
        assert sheet.endswith("]")

    def test_repeated_token_marked_with_count(self):
        text = "hash abc123def and again abc123def"
        sheet = factsheet_text(text)
        assert "\u00d72" in sheet


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------


def data_block(media_type: str = "image/png") -> DataBlock:
    return DataBlock(
        source=Base64Source(data="aGk=", media_type=media_type),
    )


class TestMediaKind:
    @pytest.mark.parametrize(
        ("media_type", "expected"),
        [
            ("image/png", "image"),
            ("audio/mp3", "audio"),
            ("video/mp4", "video"),
            ("application/pdf", "file"),
            ("text/plain", "file"),
            ("weird/unknown", "unknown"),
            ("", "unknown"),
        ],
    )
    def test_classification(self, media_type, expected):
        assert messages_mod.media_kind(data_block(media_type)) == expected


class TestMessageDataBlocks:
    def test_collects_top_level_and_tool_result_media(self):
        result = ToolResultBlock(
            id="t1",
            name="fetch",
            state=ToolResultState.SUCCESS,
            output=[TextBlock(text="see"), data_block("image/jpeg")],
        )
        message = Msg(
            name="assistant",
            role="assistant",
            content=[data_block(), result],
        )
        blocks = messages_mod.message_data_blocks(message)
        assert len(blocks) == 2

    def test_message_without_media(self):
        message = text_message("user", "plain")
        assert messages_mod.message_data_blocks(message) == []
        assert messages_mod.message_has_native_media(message) is False

    def test_message_has_native_media_true(self):
        message = Msg(
            name="user",
            role="user",
            content=[TextBlock(text="pic"), data_block()],
        )
        assert messages_mod.message_has_native_media(message) is True


class TestInspectMedia:
    def test_counts_every_kind(self):
        messages = [
            Msg(
                name="user",
                role="user",
                content=[
                    data_block("image/png"),
                    data_block("audio/wav"),
                    data_block("video/webm"),
                    data_block("application/pdf"),
                    data_block("mystery/type"),
                ],
            ),
        ]
        inventory = messages_mod.inspect_media(messages)
        assert inventory.images == 1
        assert inventory.audio == 1
        assert inventory.video == 1
        assert inventory.files == 1
        assert inventory.unknown == 1


class TestUserText:
    def test_joins_only_text_blocks(self):
        message = Msg(
            name="user",
            role="user",
            content=[
                TextBlock(text="first"),
                data_block(),
                TextBlock(text="second"),
            ],
        )
        assert messages_mod.user_text(message) == "first\n\nsecond"


class TestBlockText:
    def test_text_block_passthrough(self):
        assert messages_mod.block_text(TextBlock(text="hello")) == "hello"

    def test_data_block_becomes_kind_marker(self):
        assert messages_mod.block_text(data_block()) == "[image]"

    def test_tool_call_block_format(self):
        block = ToolCallBlock(id="call_7", name="search", input="query")
        text = messages_mod.block_text(block)
        assert "tool_call id=call_7" in text
        assert "name=search" in text
        assert "query" in text

    def test_tool_result_str_output_replaces_stale_freshness_hint(self):
        stale = (
            "done (file state is current in your "
            "context — no need to Read it back)"
        )
        block = ToolResultBlock(
            id="r1",
            name="write",
            state=ToolResultState.SUCCESS,
            output=stale,
        )
        text = messages_mod.block_text(block)
        assert "no need to Read it back" not in text
        assert "state as of this PRIOR turn" in text
        assert "tool_result id=r1" in text
        assert "state=success" in text

    def test_tool_result_list_output_joins_text_and_media(self):
        block = ToolResultBlock(
            id="r2",
            name="fetch",
            state=ToolResultState.ERROR,
            output=[TextBlock(text="body"), data_block()],
        )
        text = messages_mod.block_text(block)
        assert "body" in text
        assert "[image]" in text
        assert "state=error" in text

    def test_unknown_block_renders_empty(self):
        block = ThinkingBlock(type="thinking", thinking="internal")
        assert messages_mod.block_text(block) == ""


class TestMessageBodyAndSegments:
    def test_message_body_skips_empty_blocks(self):
        message = Msg(
            name="assistant",
            role="assistant",
            content=[
                TextBlock(text="visible"),
                ThinkingBlock(type="thinking", thinking="gone"),
            ],
        )
        assert messages_mod.message_body(message) == "visible"

    def test_segments_tag_turn_and_role(self):
        message = Msg(
            name="assistant",
            role="assistant",
            content=[
                ToolCallBlock(id="c1", name="run", input="x"),
                ToolResultBlock(
                    id="c1",
                    name="run",
                    state=ToolResultState.SUCCESS,
                    output="ok",
                ),
            ],
        )
        text, slots = messages_mod.message_segments(message, turn=4)
        assert '<assistant t="4">' in text
        assert "</assistant>" in text
        # ToolResultBlock belongs to the user side of the wire protocol.
        assert '<user t="4">' in text
        # Slot text mirrors the group structure: same segment count,
        # padded with the role marks of both observed roles.
        assert slots.count("\n\n") == text.count("\n\n")
        assert "\x01" in slots
        assert "\x02" in slots

    def test_user_role_message_keeps_user_groups(self):
        message = text_message("user", "hello")
        text, _ = messages_mod.message_segments(message, turn=1)
        assert '<user t="1">' in text
        assert "</user>" in text


class TestEstimateNativeMessageTokens:
    def test_includes_role_and_tools(self):
        messages = [text_message("user", "hi")]
        with_tools = messages_mod.estimate_native_message_tokens(
            messages,
            [{"type": "function", "function": {"name": "f"}}],
        )
        without_tools = messages_mod.estimate_native_message_tokens(
            messages,
            None,
        )
        assert with_tools > without_tools
        assert without_tools >= 1


class TestCompactSlabWhitespace:
    def test_strips_trailing_whitespace_per_line(self):
        assert messages_mod.compact_slab_whitespace("a  \nb\t\n") == "a\nb\n"

    def test_collapses_blank_runs_but_keeps_structure(self):
        out = messages_mod.compact_slab_whitespace("a\n\n\n\nb")
        assert out == "a\n\nb"

    def test_interior_whitespace_preserved(self):
        assert messages_mod.compact_slab_whitespace("a  b") == "a  b"


# ---------------------------------------------------------------------------
# tool_results
# ---------------------------------------------------------------------------


class TestContentClassification:
    def test_object_literal_is_structured(self):
        assert tool_results_mod._classify_content('{"key": 1}') == "structured"

    def test_array_literal_is_structured(self):
        assert tool_results_mod._classify_content("[1, 2, 3]") == "structured"

    def test_yaml_document_marker_is_structured(self):
        assert (
            tool_results_mod._classify_content("---\ntitle: x") == "structured"
        )

    def test_diff_header_is_structured(self):
        text = "diff --git a/x b/x\n--- a/x\n+++ b/x"
        assert tool_results_mod._classify_content(text) == "structured"

    def test_log_lines_are_log(self):
        lines = [
            "2026-01-01T00:00:00 boot",
            "2026-01-01T00:00:01 ready",
            "2026-01-01T00:00:02 serve",
            "2026-01-01T00:00:03 stop",
        ]
        assert tool_results_mod._classify_content("\n".join(lines)) == "log"

    def test_plain_prose_is_other(self):
        assert tool_results_mod._classify_content("hello world") == "other"

    def test_leading_whitespace_trimmed_before_shape_check(self):
        text = "\u3000 \ufeff" + '{"a": 1}'
        assert tool_results_mod._classify_content(text) == "structured"


class TestPagingMarker:
    def test_marker_reports_omitted_and_shown(self):
        marker = tool_results_mod._paging_marker(
            original_chars=1000,
            original_lines=50,
            omitted_chars=800,
            omitted_lines=40,
            head_lines=5,
            tail_lines=5,
            original_images=2,
        )
        assert "Visual Compact paging" in marker
        assert "40 lines" in marker
        assert "first 5 lines and last 5 lines" in marker

    def test_marker_without_tail(self):
        marker = tool_results_mod._paging_marker(
            original_chars=100,
            original_lines=10,
            omitted_chars=80,
            omitted_lines=8,
            head_lines=2,
            tail_lines=0,
            original_images=1,
        )
        assert "tail elided" in marker


class TestTruncateForBudget:
    def test_text_within_budget_unchanged(self):
        text = "short enough"
        out, omitted = tool_results_mod._truncate_for_budget(text, 10, LOW)
        assert out == text
        assert omitted == 0

    def test_multiline_text_paged_head_and_tail(self):
        text = "\n".join(f"line {i} data" for i in range(2000))
        out, omitted = tool_results_mod._truncate_for_budget(text, 1, LOW)
        assert omitted > 0
        assert "[ Visual Compact paging" in out
        assert len(out) < len(text)

    def test_structured_text_keeps_head_only(self):
        lines = ['{"rows": ['] + [f'  "value {i}",' for i in range(2000)]
        text = "\n".join(lines)
        out, omitted = tool_results_mod._truncate_for_budget(
            text,
            1,
            LOW,
            shape="structured",
        )
        assert omitted > 0
        assert out.startswith('{"rows": [')
        assert "tail elided" in out

    def test_single_huge_line_split_head_tail(self):
        text = "x" * 100_000
        out, omitted = tool_results_mod._truncate_for_budget(text, 1, LOW)
        assert omitted > 0
        assert len(out) < len(text)


class TestCompressToolResults:
    def test_large_success_result_replaced_with_pages(self):
        block = ToolResultBlock(
            id="call_big",
            name="search",
            state=ToolResultState.SUCCESS,
            output=BIG_TOOL_TEXT,
        )
        receipt = CompressionReceipt()
        left = tool_results_mod.compress_tool_results(
            [assistant_tool_result(block)],
            receipt,
            10,
            LOW,
        )
        assert left < 10
        assert receipt.image_count >= 1
        assert len(receipt.recoverable) == 1
        assert receipt.recoverable[0]["region"] == "tool_result"
        assert isinstance(block.output, list)
        kinds = [type(part).__name__ for part in block.output]
        assert kinds[0] == "DataBlock"
        marker = block.output[-1]
        assert isinstance(marker, TextBlock)
        assert "Visual pages associated with output from search" in marker.text
        assert receipt.recoverable[0]["id"] in marker.text

    def test_short_result_below_min_chars_untouched(self):
        block = ToolResultBlock(
            id="c_short",
            name="search",
            state=ToolResultState.SUCCESS,
            output="tiny",
        )
        tool_results_mod.compress_tool_results(
            [assistant_tool_result(block)],
            CompressionReceipt(),
            10,
            LOW,
        )
        assert block.output == "tiny"

    def test_error_state_never_compressed(self):
        block = ToolResultBlock(
            id="c_err",
            name="search",
            state=ToolResultState.ERROR,
            output=BIG_TOOL_TEXT,
        )
        tool_results_mod.compress_tool_results(
            [assistant_tool_result(block)],
            CompressionReceipt(),
            10,
            LOW,
        )
        assert block.output == BIG_TOOL_TEXT

    def test_recovery_tool_output_kept_native(self):
        block = ToolResultBlock(
            id="c_rec",
            name="recover_visual_context",
            state=ToolResultState.SUCCESS,
            output=BIG_TOOL_TEXT,
        )
        tool_results_mod.compress_tool_results(
            [assistant_tool_result(block)],
            CompressionReceipt(),
            10,
            LOW,
        )
        assert block.output == BIG_TOOL_TEXT

    def test_zero_budget_returns_zero_immediately(self):
        block = ToolResultBlock(
            id="c_zero",
            name="search",
            state=ToolResultState.SUCCESS,
            output=BIG_TOOL_TEXT,
        )
        left = tool_results_mod.compress_tool_results(
            [assistant_tool_result(block)],
            CompressionReceipt(),
            0,
            LOW,
        )
        assert left == 0
        assert block.output == BIG_TOOL_TEXT

    def test_list_output_compresses_eligible_parts_only(self):
        block = ToolResultBlock(
            id="c_list",
            name="search",
            state=ToolResultState.SUCCESS,
            output=[TextBlock(text=BIG_TOOL_TEXT), TextBlock(text="keep me")],
        )
        tool_results_mod.compress_tool_results(
            [assistant_tool_result(block)],
            CompressionReceipt(),
            10,
            LOW,
        )
        assert isinstance(block.output, list)
        last = block.output[-1]
        assert isinstance(last, TextBlock)
        assert last.text == "keep me"


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


def conversation_turns(count: int) -> list[Msg]:
    messages = []
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        text = f"turn {index}: " + "conversation detail. " * 20
        messages.append(text_message(role, text))
    return messages


class TestPlanHistory:
    def test_short_conversation_not_collapsed(self):
        assert history_mod.plan_history(conversation_turns(4), LOW) is None

    def test_long_conversation_yields_plan(self):
        plan = history_mod.plan_history(conversation_turns(30), LOW)
        assert plan is not None
        assert plan.first == 0
        assert plan.chunks
        assert plan.chunks[0][0] == 0

    def test_system_prefix_skipped(self):
        messages = [text_message("system", "rules")] + conversation_turns(30)
        plan = history_mod.plan_history(messages, LOW)
        assert plan is not None
        assert plan.first == 1

    def test_cutoff_never_passes_active_user_turn(self):
        messages = conversation_turns(30)
        plan = history_mod.plan_history(messages, LOW)
        last_user = max(
            index
            for index, message in enumerate(messages)
            if message.role == "user"
        )
        assert plan is not None
        assert plan.chunks[-1][1] <= last_user

    def test_synthetic_user_messages_not_active_anchor(self):
        from qwenpaw.constant import SYNTHETIC_USER_MESSAGE_TAGS

        messages = conversation_turns(30)
        last_user = max(
            index
            for index, message in enumerate(messages)
            if message.role == "user"
        )
        # Replace the final user turn with a runtime-injected continuation
        # stub: it must not count as the active turn anchor.
        messages[last_user] = Msg(
            name="user",
            role="user",
            content=[TextBlock(text="continuation stub")],
            metadata={
                QWENPAW_MESSAGE_TAG_KEY: next(
                    iter(SYNTHETIC_USER_MESSAGE_TAGS),
                ),
            },
        )
        active = history_mod._active_user_index(messages)
        assert active is not None
        assert active < last_user
        metadata = messages[active].metadata or {}
        assert metadata.get(QWENPAW_MESSAGE_TAG_KEY) not in (
            SYNTHETIC_USER_MESSAGE_TAGS
        )


class TestProtocolClosedBoundary:
    def test_unmatched_tool_call_cuts_before_it(self):
        messages = conversation_turns(14)
        messages.append(
            Msg(
                name="assistant",
                role="assistant",
                content=[ToolCallBlock(id="open", name="run", input="q")],
            ),
        )
        end = history_mod._last_protocol_closed_end(messages, 0, len(messages))
        assert end == 14

    def test_matched_pair_is_closed(self):
        messages = conversation_turns(14)
        messages.append(
            Msg(
                name="assistant",
                role="assistant",
                content=[ToolCallBlock(id="pair", name="run", input="q")],
            ),
        )
        messages.append(
            Msg(
                name="assistant",
                role="assistant",
                content=[
                    ToolResultBlock(
                        id="pair",
                        name="run",
                        state=ToolResultState.SUCCESS,
                        output="done",
                    ),
                ],
            ),
        )
        end = history_mod._last_protocol_closed_end(messages, 0, len(messages))
        assert end == len(messages)

    def test_media_message_is_a_barrier(self):
        messages = conversation_turns(10)
        messages.append(
            Msg(
                name="user",
                role="user",
                content=[TextBlock(text="pic"), data_block()],
            ),
        )
        messages.append(text_message("user", "after image"))
        end = history_mod._last_protocol_closed_end(messages, 0, len(messages))
        assert end == 10


class TestCompressHistory:
    def test_long_history_collapsed_into_visual_message(self):
        messages = conversation_turns(30)
        receipt = CompressionReceipt()
        out, left = history_mod.compress_history(
            list(messages),
            receipt,
            20,
            LOW,
        )
        assert left < 20
        assert receipt.image_count >= 1
        collapsed = [
            message for message in out if message.name == "visual_history"
        ]
        assert len(collapsed) == 1
        assert receipt.recoverable[0]["region"] == "history"
        # The live tail stays native and ordered after the collapsed block.
        tail = out[out.index(collapsed[0]) + 1 :]
        assert all(message.name != "visual_history" for message in tail)

    def test_short_history_unchanged(self):
        messages = conversation_turns(4)
        receipt = CompressionReceipt()
        out, left = history_mod.compress_history(
            list(messages),
            receipt,
            20,
            LOW,
        )
        assert len(out) == 4
        assert left == 20
        assert receipt.image_count == 0

    def test_zero_budget_short_circuits(self):
        messages = conversation_turns(30)
        out, left = history_mod.compress_history(
            list(messages),
            CompressionReceipt(),
            0,
            LOW,
        )
        assert len(out) == 30
        assert left == 0

    def test_latest_user_pointer_present(self):
        messages = conversation_turns(30)
        receipt = CompressionReceipt()
        out, _ = history_mod.compress_history(list(messages), receipt, 20, LOW)
        collapsed = next(m for m in out if m.name == "visual_history")
        texts = [b.text for b in collapsed.content if isinstance(b, TextBlock)]
        assert any("Most recent collapsed user turn" in t for t in texts)


# ---------------------------------------------------------------------------
# static_context
# ---------------------------------------------------------------------------


ENV_BLOCK = (
    "====================\n"
    "- About: You are a personal AI assistant.\n"
    "- GitHub: https://github.com/agentscope-ai/QwenPaw\n"
    "- Docs: https://qwenpaw.agentscope.io/\n"
    "- Current date: 2026-08-27\n"
    "===================="
)


class TestWrapEnvTail:
    def test_wraps_with_host_markers(self):
        wrapped = static_mod.wrap_env_tail("host context")
        assert wrapped.startswith("[QwenPaw environment context")
        assert "host context" in wrapped
        assert wrapped.endswith("[End QwenPaw environment context.]")

    def test_blank_input_returns_empty(self):
        assert static_mod.wrap_env_tail("   \n") == ""


class TestExtractEnvContext:
    def test_extracts_single_env_block(self):
        prompt = "You are Mozi.\n\n" + ENV_BLOCK + "\n\nMore rules."
        remaining, env = static_mod._extract_qwenpaw_env_context(prompt)
        assert env.startswith("====")
        assert "Mozi" in remaining
        assert "Current date" not in remaining
        assert "More rules." in remaining

    def test_no_env_block_returns_text_unchanged(self):
        remaining, env = static_mod._extract_qwenpaw_env_context(
            "plain prompt",
        )
        assert env == ""
        assert remaining == "plain prompt"

    def test_multiple_env_blocks_rejected(self):
        prompt = ENV_BLOCK + "\n\n" + ENV_BLOCK
        remaining, env = static_mod._extract_qwenpaw_env_context(prompt)
        assert env == ""
        assert remaining == prompt


class TestCompressStaticContext:
    def test_large_system_prompt_imaged(self):
        big = "".join(
            f"Operating rule {i}: deterministic behaviour for suites.\n"
            for i in range(400)
        )
        messages = [text_message("system", big)]
        receipt = CompressionReceipt()
        out, tools, left, env = static_mod.compress_static_context(
            messages,
            None,
            receipt,
            10,
            LOW,
            relocate_env_tail=False,
        )
        assert left < 10
        assert receipt.image_count >= 1
        visual = [
            message for message in out if message.name == "visual_context"
        ]
        assert len(visual) == 1
        # The system message is replaced with the pointer text.
        system = next(message for message in out if message.role == "system")
        assert "visual" in system.content[0].text.lower()
        assert env == ""

    def test_small_system_prompt_below_gate_unchanged(self):
        messages = [text_message("system", "short rules")]
        out, tools, left, env = static_mod.compress_static_context(
            list(messages),
            None,
            CompressionReceipt(),
            10,
            LOW,
        )
        assert len(out) == 1
        assert out[0].content[0].text == "short rules"
        assert left == 10

    def test_zero_budget_unchanged(self):
        big = "rule. " * 2000
        messages = [text_message("system", big)]
        out, _, left, env = static_mod.compress_static_context(
            list(messages),
            None,
            CompressionReceipt(),
            0,
            LOW,
        )
        assert len(out) == 1
        assert left == 0

    def test_env_tail_relocated_when_requested(self):
        filler = "".join(
            f"Session operating rule {i}: deterministic behaviour.\n"
            for i in range(200)
        )
        prompt = filler + "\n" + ENV_BLOCK
        messages = [text_message("system", prompt)]
        receipt = CompressionReceipt()
        out, _, left, env = static_mod.compress_static_context(
            messages,
            None,
            receipt,
            10,
            LOW,
            relocate_env_tail=True,
        )
        assert env.startswith("====")
        assert receipt.image_count >= 1


# ---------------------------------------------------------------------------
# tool_schemas
# ---------------------------------------------------------------------------


def sample_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search the index.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Required query text.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional page size.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    ]


class TestPlanToolDocumentation:
    def test_optional_description_moved_out_of_schema(self):
        tools = sample_tools()
        copied, rendered = tool_schemas_mod.plan_qwenpaw_tool_documentation(
            tools,
        )
        properties = copied[0]["function"]["parameters"]["properties"]
        assert "description" not in properties["limit"]
        assert properties["query"]["description"] == "Required query text."
        assert "## Optional parameters: search" in rendered
        assert "limit" in rendered
        assert rendered.startswith("=== TOOL REFERENCE ===")
        assert rendered.endswith("=== END TOOL REFERENCE ===")

    def test_original_tools_not_mutated(self):
        tools = sample_tools()
        tool_schemas_mod.plan_qwenpaw_tool_documentation(tools)
        properties = tools[0]["function"]["parameters"]["properties"]
        assert properties["limit"]["description"] == "Optional page size."

    def test_defer_loading_tools_skipped(self):
        tools = sample_tools()
        tools[0]["defer_loading"] = True
        _, rendered = tool_schemas_mod.plan_qwenpaw_tool_documentation(tools)
        assert rendered == ""

    def test_non_function_entries_skipped(self):
        _, rendered = tool_schemas_mod.plan_qwenpaw_tool_documentation(
            [{"type": "other"}],
        )
        assert rendered == ""

    def test_empty_tools_yield_empty_render(self):
        copied, rendered = tool_schemas_mod.plan_qwenpaw_tool_documentation([])
        assert copied == []
        assert rendered == ""

    def test_missing_required_key_treats_all_as_optional(self):
        # Without a required list every parameter is optional, so its
        # description is moved into the rendered reference.
        tools = sample_tools()
        del tools[0]["function"]["parameters"]["required"]
        copied, rendered = tool_schemas_mod.plan_qwenpaw_tool_documentation(
            tools,
        )
        properties = copied[0]["function"]["parameters"]["properties"]
        assert "description" not in properties["limit"]
        assert "description" not in properties["query"]
        assert "query" in rendered
        assert "limit" in rendered

    def test_invalid_required_list_keeps_descriptions_native(self):
        tools = sample_tools()
        tools[0]["function"]["parameters"]["required"] = "query"
        copied, rendered = tool_schemas_mod.plan_qwenpaw_tool_documentation(
            tools,
        )
        assert rendered == ""
        properties = copied[0]["function"]["parameters"]["properties"]
        assert properties["limit"]["description"] == "Optional page size."
        assert properties["query"]["description"] == "Required query text."


# ---------------------------------------------------------------------------
# request (end-to-end transform)
# ---------------------------------------------------------------------------


class TestExternalUserDetection:
    def test_tagged_user_message_detected(self):
        message = Msg(
            name="user",
            role="user",
            content=[TextBlock(text="live request")],
            metadata={
                QWENPAW_MESSAGE_TAG_KEY: EXTERNAL_USER_QUERY_MESSAGE_TAG,
            },
        )
        assert request_mod._is_external_user(message) is True

    def test_plain_user_message_not_external(self):
        assert (
            request_mod._is_external_user(text_message("user", "hi")) is False
        )


class TestAppendEnvTail:
    def test_appended_to_external_user_message(self):
        external = Msg(
            name="user",
            role="user",
            content=[TextBlock(text="live request")],
            metadata={
                QWENPAW_MESSAGE_TAG_KEY: EXTERNAL_USER_QUERY_MESSAGE_TAG,
            },
        )
        request_mod._append_env_tail([external], "host context")
        assert len(external.content) == 2
        assert "host context" in external.content[1].text

    def test_falls_back_to_system_without_external_user(self):
        system = text_message("system", "rules")
        request_mod._append_env_tail([system], "host context")
        assert len(system.content) == 2
        assert "host context" in system.content[1].text

    def test_blank_env_tail_appends_nothing(self):
        external = Msg(
            name="user",
            role="user",
            content=[TextBlock(text="live request")],
            metadata={
                QWENPAW_MESSAGE_TAG_KEY: EXTERNAL_USER_QUERY_MESSAGE_TAG,
            },
        )
        request_mod._append_env_tail([external], "   ")
        assert len(external.content) == 1


class TestValidateMediaInvariants:
    def test_lost_audio_raises(self):
        original = messages_mod.MediaInventory(images=1, audio=1)
        final_messages = [
            Msg(name="user", role="user", content=[data_block()]),
        ]
        budget = RequestBudget.from_image_count(64, images=1)
        with pytest.raises(RuntimeError, match="changed original media"):
            request_mod._validate_media_invariants(
                final_messages,
                original,
                budget,
            )

    def test_excess_generated_images_raises(self):
        original = messages_mod.MediaInventory(images=0)
        final_messages = [
            Msg(
                name="user",
                role="user",
                content=[data_block(), data_block(), data_block()],
            ),
        ]
        budget = RequestBudget.from_image_count(2, images=0)
        with pytest.raises(RuntimeError, match="exceeded image allowance"):
            request_mod._validate_media_invariants(
                final_messages,
                original,
                budget,
            )


class TestTransformModelRequest:
    def build_request(self) -> list[Msg]:
        big_system = "".join(
            f"Operating rule {i}: deterministic behaviour for suites.\n"
            for i in range(400)
        )
        messages = [text_message("system", big_system)]
        messages.extend(conversation_turns(30))
        messages.append(
            assistant_tool_result(
                ToolResultBlock(
                    id="call_e2e",
                    name="search",
                    state=ToolResultState.SUCCESS,
                    output=BIG_TOOL_TEXT,
                ),
            ),
        )
        messages.append(
            Msg(
                name="user",
                role="user",
                content=[TextBlock(text="live request")],
                metadata={
                    QWENPAW_MESSAGE_TAG_KEY: (EXTERNAL_USER_QUERY_MESSAGE_TAG),
                },
            ),
        )
        return messages

    def test_end_to_end_transform_compresses_and_keeps_live_tail(self):
        messages = self.build_request()
        tools = sample_tools()
        cloned, copied_tools, receipt = request_mod.transform_model_request(
            messages,
            tools,
            effort_preset=LOW,
        )
        assert receipt.image_count >= 1
        assert any(m.name == "visual_context" for m in cloned)
        # The live external user request stays native and last.
        assert cloned[-1].role == "user"
        assert cloned[-1].content[0].text == "live request"
        # Deep copies: originals untouched.
        assert messages[0].role == "system"
        assert "Operating rule" in messages[0].content[0].text
        assert tools[0]["function"]["parameters"]["properties"]["limit"][
            "description"
        ]
        assert copied_tools is not tools

    def test_empty_request_passthrough(self):
        cloned, copied_tools, receipt = request_mod.transform_model_request(
            [],
            None,
            effort_preset=LOW,
        )
        assert cloned == []
        assert copied_tools is None
        assert receipt.image_count == 0

    def test_image_heavy_request_gets_no_extra_pages(self):
        # Native images own the budget; a saturated request adds nothing.
        content = [TextBlock(text="album")] + [data_block() for _ in range(64)]
        messages = [
            Msg(name="user", role="user", content=content),
            text_message("user", "describe"),
        ]
        cloned, _, receipt = request_mod.transform_model_request(
            messages,
            None,
            effort_preset=LOW,
        )
        assert receipt.image_count == 0
