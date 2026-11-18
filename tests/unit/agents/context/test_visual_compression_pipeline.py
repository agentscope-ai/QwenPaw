# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-import,unused-variable,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for history-only visual compression.

Covers token budgeting, aggregate receipts, exact-value factsheets, message
serialization, protocol-closed history planning, and request preservation.
"""

from __future__ import annotations

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
from qwenpaw.agents.context.visual_compression.pipeline.budget import (
    RequestBudget,
    count_text_tokens,
    estimate_image_tokens,
    estimate_visual_replacement_tokens,
    profitable,
)
from qwenpaw.agents.context.visual_compression.pipeline.precision import (
    extract_fact_entries,
    factsheet_text,
)
from qwenpaw.agents.context.visual_compression.pipeline.receipt import (
    CompressionReceipt,
    record_pages,
)
from qwenpaw.agents.context.visual_compression.rendering import (
    RenderedPage,
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
        accepted = profitable(
            count_text_tokens("x" * 200_000),
            "marker",
            [make_page(28, 28)],
        )
        assert accepted is True

    def test_tiny_baseline_rejects_replacement(self):
        accepted = profitable(
            count_text_tokens("tiny"),
            "marker that is longer than the source",
            [make_page(1568, 728)],
        )
        assert accepted is False


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


class TestRecordPages:
    def test_aggregates_totals_and_regions(self):
        receipt = CompressionReceipt()
        record_pages(
            receipt,
            2,
            "source text",
            "history",
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
        assert receipt.regions == {"history": 2}

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

    def test_segments_preserve_roles(self):
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
        text, slots = messages_mod.message_segments(message)
        assert "<assistant>" in text
        assert "</assistant>" in text
        # ToolResultBlock belongs to the user side of the wire protocol.
        assert "<user>" in text
        # Slot text mirrors the group structure: same segment count,
        # padded with the role marks of both observed roles.
        assert slots.count("\n\n") == text.count("\n\n")
        assert "\x01" in slots
        assert "\x02" in slots

    def test_user_role_message_keeps_user_groups(self):
        message = text_message("user", "hello")
        text, _ = messages_mod.message_segments(message)
        assert "<user>" in text
        assert "</user>" in text


class TestEstimateNativeMessageTokens:
    def test_includes_role_and_tool_content(self):
        messages = [text_message("user", "hi")]
        plain_tokens = messages_mod.estimate_native_message_tokens(messages)
        assert plain_tokens == count_text_tokens("user\nhi")
        messages.append(
            assistant_tool_result(
                ToolResultBlock(
                    id="c1",
                    name="search",
                    state=ToolResultState.SUCCESS,
                    output=BIG_TOOL_TEXT,
                ),
            ),
        )
        assert messages_mod.estimate_native_message_tokens(messages) > (
            plain_tokens
        )


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
        messages = conversation_turns(4)
        assert (
            history_mod.plan_history(
                messages,
                context_message_ids=frozenset(m.id for m in messages),
            )
            is None
        )

    def test_long_conversation_yields_plan(self):
        messages = conversation_turns(30)
        plan = history_mod.plan_history(
            messages,
            context_message_ids=frozenset(m.id for m in messages),
        )
        assert plan is not None
        assert plan.first == 0
        assert plan.ends == tuple(range(2, 27, 2))

    def test_system_prefix_skipped(self):
        messages = [text_message("system", "rules")] + conversation_turns(30)
        plan = history_mod.plan_history(
            messages,
            context_message_ids=frozenset(m.id for m in messages),
        )
        assert plan is not None
        assert plan.first == 1

    def test_cutoff_preserves_two_recent_user_turns(self):
        messages = conversation_turns(30)
        plan = history_mod.plan_history(
            messages,
            context_message_ids=frozenset(m.id for m in messages),
        )
        assert plan is not None
        assert plan.ends[-1] == 26

    def test_synthetic_user_messages_not_active_anchor(self):
        from qwenpaw.constant import SYNTHETIC_USER_MESSAGE_TAGS

        messages = conversation_turns(30)
        messages[28] = Msg(
            name="user",
            role="user",
            content=[TextBlock(text="continuation stub")],
            metadata={
                QWENPAW_MESSAGE_TAG_KEY: next(
                    iter(SYNTHETIC_USER_MESSAGE_TAGS),
                ),
            },
        )
        plan = history_mod.plan_history(
            messages,
            context_message_ids=frozenset(m.id for m in messages),
        )
        assert plan is not None
        assert plan.ends[-1] == 24


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
        ends = history_mod._protocol_closed_ends(messages, 0, len(messages))
        assert ends[-1] == 14
        assert len(messages) not in ends

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
        ends = history_mod._protocol_closed_ends(messages, 0, len(messages))
        assert ends[-1] == len(messages)
        assert len(messages) - 1 not in ends

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
        ends = history_mod._protocol_closed_ends(messages, 0, len(messages))
        assert ends[-1] == 10


class TestCompressHistory:
    def test_long_history_collapsed_into_visual_message(self):
        messages = conversation_turns(30)
        receipt = CompressionReceipt()
        out, left = history_mod.compress_history(
            list(messages),
            receipt,
            20,
            LOW,
            context_message_ids=frozenset(m.id for m in messages),
        )
        assert left < 20
        assert receipt.image_count >= 1
        collapsed = [
            message for message in out if message.name == "visual_history"
        ]
        assert len(collapsed) == 1
        assert receipt.regions.keys() == {"history"}
        # The live tail stays native and ordered after the collapsed block.
        tail = out[out.index(collapsed[0]) + 1 :]
        assert all(message.name != "visual_history" for message in tail)
        assert [m.model_dump(mode="json") for m in tail[-4:]] == [
            m.model_dump(mode="json") for m in messages[-4:]
        ]

    def test_short_history_unchanged(self):
        messages = conversation_turns(4)
        receipt = CompressionReceipt()
        out, left = history_mod.compress_history(
            list(messages),
            receipt,
            20,
            LOW,
            context_message_ids=frozenset(m.id for m in messages),
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
            context_message_ids=frozenset(m.id for m in messages),
        )
        assert len(out) == 30
        assert left == 0


# ---------------------------------------------------------------------------
# request (end-to-end transform)
# ---------------------------------------------------------------------------


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
            Msg(
                name="assistant",
                role="assistant",
                content=[
                    ToolCallBlock(id="call_e2e", name="search", input="query"),
                    ToolResultBlock(
                        id="call_e2e",
                        name="search",
                        state=ToolResultState.SUCCESS,
                        output=BIG_TOOL_TEXT,
                    ),
                ],
            ),
        )
        messages.append(
            Msg(
                name="user",
                role="user",
                content=[TextBlock(text="live request")],
                metadata={
                    QWENPAW_MESSAGE_TAG_KEY: EXTERNAL_USER_QUERY_MESSAGE_TAG,
                },
            ),
        )
        return messages

    def test_end_to_end_transform_compresses_and_keeps_live_tail(self):
        messages = self.build_request()
        original = [m.model_dump(mode="json") for m in messages]
        cloned, receipt = request_mod.transform_model_request(
            messages,
            context_message_ids=frozenset(m.id for m in messages),
            effort_preset=LOW,
        )
        assert receipt.image_count >= 1
        assert receipt.regions.keys() == {"history"}
        assert any(m.name == "visual_history" for m in cloned)
        # System text and the two latest real user turns remain native.
        assert cloned[0].model_dump(mode="json") == original[0]
        assert [m.model_dump(mode="json") for m in cloned[-4:]] == (
            original[-4:]
        )
        assert [m.model_dump(mode="json") for m in messages] == original
        assert cloned[0] is not messages[0]

    def test_empty_request_passthrough(self):
        cloned, receipt = request_mod.transform_model_request(
            [],
            context_message_ids=frozenset(),
            effort_preset=LOW,
        )
        assert cloned == []
        assert receipt.image_count == 0

    def test_image_heavy_request_gets_no_extra_pages(self):
        # Native images own the budget; a saturated request adds nothing.
        messages = self.build_request()
        messages[-1].content.extend(data_block() for _ in range(64))
        original = [m.model_dump(mode="json") for m in messages]
        cloned, receipt = request_mod.transform_model_request(
            messages,
            context_message_ids=frozenset(m.id for m in messages),
            effort_preset=LOW,
        )
        assert receipt.image_count == 0
        assert [m.model_dump(mode="json") for m in cloned] == original
