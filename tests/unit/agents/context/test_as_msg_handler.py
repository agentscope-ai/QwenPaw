# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=line-too-long,unused-argument,unused-variable
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for AsMsgHandler context_check with tool_use/tool_result alignment."""

import pytest
from agentscope.message import Msg

from qwenpaw.agents.context.as_msg_handler import AsMsgHandler
from qwenpaw.agents.context.light_context_manager import LightContextManager
from qwenpaw.agents.utils.estimate_token_counter import EstimatedTokenCounter
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper


class MockTokenCounter(EstimatedTokenCounter):
    """Mock token counter for testing."""

    def __init__(self, token_map: dict[str, int] | None = None):
        super().__init__()
        self.token_map = token_map or {}
        self.count_calls = 0

    async def count(self, text: str = "", messages: list | None = None) -> int:
        """Count tokens based on text length or predefined mapping."""
        self.count_calls += 1
        if text in self.token_map:
            return self.token_map[text]
        # Simple estimation: roughly 4 chars per token for Chinese
        return len(text) // 4 if text else 0


class TestAsMsgHandlerToolAlignment:
    """Test tool_use/tool_result alignment in context_check."""

    @pytest.mark.asyncio
    async def test_tool_use_result_pair_aligned_when_both_fit(self):
        """When both tool_use and tool_result fit within reserve, they should both be kept."""
        token_counter = MockTokenCounter()
        handler = AsMsgHandler(token_counter)

        tool_id = "tool-001"
        messages = [
            Msg(name="user", role="user", content="Hello", metadata={}),
            Msg(
                name="assistant",
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": "test_tool",
                        "input": {},
                    },
                ],
                metadata={},
            ),
            Msg(
                name="system",
                role="system",
                content=[
                    {
                        "type": "tool_result",
                        "id": tool_id,
                        "name": "test_tool",
                        "output": "small result",
                    },
                ],
                metadata={},
            ),
            Msg(
                name="assistant",
                role="assistant",
                content="Done",
                metadata={},
            ),
        ]

        result = await handler.context_check(
            messages=messages,
            context_compact_threshold=100,
            context_compact_reserve=100,
        )

        msgs_to_compact, msgs_to_keep, total_tokens, keep_tokens = result

        # Both tool_use and tool_result should be in keep (last 2 messages)
        assert len(msgs_to_keep) >= 2

        # Verify tool_use and tool_result ids are aligned in kept messages
        tool_use_ids = set()
        tool_result_ids = set()
        for msg in msgs_to_keep:
            for block in msg.get_content_blocks("tool_use"):
                if tid := block.get("id"):
                    tool_use_ids.add(tid)
            for block in msg.get_content_blocks("tool_result"):
                if tid := block.get("id"):
                    tool_result_ids.add(tid)
        assert tool_use_ids == tool_result_ids

    @pytest.mark.asyncio
    async def test_tool_use_result_pair_excluded_when_result_too_large(self):
        """
        Bug scenario: tool_use in assistant msg, large tool_result in system msg.
        When tool_result exceeds reserve, both should be excluded (not just result).

        This is the exact scenario from the bug report where:
        - message 7 (tool_result) has 12592 tokens
        - reserve is only 2000
        - message with tool_use was kept but tool_result excluded
        - tools_aligned was False (bug)
        """
        # Simulate the exact token counts from the bug report
        # kept_tokens: 897, reserve: 2000, message 7 has 12592 tokens
        token_counter = MockTokenCounter(
            {
                "thinking content": 100,
                "tool input": 50,
                # tool_result is huge - 12592 tokens worth of text
                "huge tool result content that exceeds reserve": 12592,
            },
        )

        handler = AsMsgHandler(token_counter)

        tool_id = "toolu_tool-797d2483e17642da8838b446d0c5c2bd"
        tool_id2 = "toolu_tool-62baeaf121b44f4d97c72aaa2c828ea6"

        # Simulate the message structure from the bug report
        # Last assistant message with tool_use, followed by system messages with tool_result
        messages = [
            Msg(
                name="user",
                role="user",
                content="Earlier message",
                metadata={},
            ),
            Msg(
                name="assistant",
                role="assistant",
                content="Earlier response",
                metadata={},
            ),
            Msg(
                name="Friday",
                role="assistant",
                content=[
                    {"type": "thinking", "thinking": "thinking content"},
                    {"type": "text", "text": "Some text"},
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": "grep_search",
                        "input": {"pattern": "卷"},
                    },
                    {
                        "type": "tool_use",
                        "id": tool_id2,
                        "name": "read_file",
                        "input": {"file_path": "test"},
                    },
                ],
                metadata={},
            ),
            Msg(
                name="system",
                role="system",
                content=[
                    {
                        "type": "tool_result",
                        "id": tool_id,
                        "name": "grep_search",
                        "output": "huge tool result content that exceeds reserve",
                    },
                ],
                metadata={},
            ),
            Msg(
                name="system",
                role="system",
                content=[
                    {
                        "type": "tool_result",
                        "id": tool_id2,
                        "name": "read_file",
                        "output": "huge tool result content that exceeds reserve",
                    },
                ],
                metadata={},
            ),
        ]

        # threshold and reserve similar to bug report
        result = await handler.context_check(
            messages=messages,
            context_compact_threshold=14000,  # total tokens: 13945 in bug report
            context_compact_reserve=2000,  # reserve: 2000 in bug report
        )

        (
            msgs_to_compact,
            msgs_to_keep,
            total_tokens,
            keep_tokens,
        ) = result

        # Verify: if tool_use is in keep, corresponding tool_result must also be in keep
        tool_use_ids_in_keep = set()
        tool_result_ids_in_keep = set()

        for msg in msgs_to_keep:
            for block in msg.get_content_blocks("tool_use"):
                if tid := block.get("id"):
                    tool_use_ids_in_keep.add(tid)
            for block in msg.get_content_blocks("tool_result"):
                if tid := block.get("id"):
                    tool_result_ids_in_keep.add(tid)

        assert tool_use_ids_in_keep == tool_result_ids_in_keep, (
            f"tool_use ids in keep: {tool_use_ids_in_keep}, "
            f"tool_result ids in keep: {tool_result_ids_in_keep}"
        )

    @pytest.mark.asyncio
    async def test_partial_tool_result_kept_with_tool_use(self):
        """
        When tool_result can fit with tool_use within reserve,
        both should be kept and aligned.
        """
        token_counter = MockTokenCounter(
            {
                "medium result": 500,
            },
        )

        handler = AsMsgHandler(token_counter)

        tool_id = "tool-partial"
        messages = [
            Msg(name="user", role="user", content="Query", metadata={}),
            Msg(
                name="assistant",
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": "search",
                        "input": {},
                    },
                ],
                metadata={},
            ),
            Msg(
                name="system",
                role="system",
                content=[
                    {
                        "type": "tool_result",
                        "id": tool_id,
                        "name": "search",
                        "output": "medium result",
                    },
                ],
                metadata={},
            ),
        ]

        result = await handler.context_check(
            messages=messages,
            context_compact_threshold=1000,
            context_compact_reserve=700,  # Should fit tool_use + tool_result
        )

        msgs_to_compact, msgs_to_keep, total_tokens, keep_tokens = result

        # All messages should be kept since they fit within reserve
        # The exact count depends on token calculation, but alignment must be True
        assert len(msgs_to_keep) >= 2

        # Verify tool_use and tool_result ids are aligned in kept messages
        tool_use_ids = set()
        tool_result_ids = set()
        for msg in msgs_to_keep:
            for block in msg.get_content_blocks("tool_use"):
                if tid := block.get("id"):
                    tool_use_ids.add(tid)
            for block in msg.get_content_blocks("tool_result"):
                if tid := block.get("id"):
                    tool_result_ids.add(tid)
        assert tool_use_ids == tool_result_ids

    @pytest.mark.asyncio
    async def test_multiple_tool_pairs_in_same_message(self):
        """
        When a message contains multiple tool_use calls,
        all corresponding tool_results must be aligned.
        """
        token_counter = MockTokenCounter(
            {
                "result1": 100,
                "result2": 100,
            },
        )

        handler = AsMsgHandler(token_counter)

        tool_id1 = "tool-multi-1"
        tool_id2 = "tool-multi-2"

        messages = [
            Msg(
                name="assistant",
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": tool_id1,
                        "name": "tool1",
                        "input": {},
                    },
                    {
                        "type": "tool_use",
                        "id": tool_id2,
                        "name": "tool2",
                        "input": {},
                    },
                ],
                metadata={},
            ),
            Msg(
                name="system",
                role="system",
                content=[
                    {
                        "type": "tool_result",
                        "id": tool_id1,
                        "name": "tool1",
                        "output": "result1",
                    },
                ],
                metadata={},
            ),
            Msg(
                name="system",
                role="system",
                content=[
                    {
                        "type": "tool_result",
                        "id": tool_id2,
                        "name": "tool2",
                        "output": "result2",
                    },
                ],
                metadata={},
            ),
        ]

        result = await handler.context_check(
            messages=messages,
            context_compact_threshold=500,
            context_compact_reserve=400,
        )

        msgs_to_compact, msgs_to_keep, total_tokens, keep_tokens = result

        # Either all 3 messages are kept, or none of them
        if len(msgs_to_keep) > 0:
            assert (
                len(msgs_to_keep) == 3
            ), f"Expected 3 messages kept or 0, got {len(msgs_to_keep)}"

    @pytest.mark.asyncio
    async def test_reverse_dependency_tool_use_needs_tool_result(self):
        """
        Core test: When iterating backwards, if we encounter a message with tool_use,
        we must also include the corresponding tool_result message.

        Before fix: Only tool_result -> tool_use dependency was checked.
        After fix: Both directions are checked.

        This test verifies that when tool_result exceeds reserve,
        both tool_use and tool_result are excluded together.
        """

        # Use a simpler mock that returns fixed large value for any text
        class LargeResultTokenCounter(MockTokenCounter):
            async def count(
                self,
                text: str = "",
                messages: list | None = None,
            ) -> int:
                # Return a large value to simulate exceeding reserve
                if text and len(text) > 100:
                    return 5000  # Large tool result
                return len(text) // 4 if text else 0

        token_counter = LargeResultTokenCounter()
        handler = AsMsgHandler(token_counter)

        tool_id = "tool-reverse-dep"

        # Create a large tool result that exceeds reserve
        large_result = (
            "This is a very large tool result that will exceed the reserve limit and should not be kept alone. "
            * 50
        )

        messages = [
            Msg(
                name="user",
                role="user",
                content="First message",
                metadata={},
            ),
            Msg(
                name="assistant",
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": "test",
                        "input": {},
                    },
                ],
                metadata={},
            ),
            Msg(
                name="system",
                role="system",
                content=[
                    {
                        "type": "tool_result",
                        "id": tool_id,
                        "name": "test",
                        "output": large_result,
                    },
                ],
                metadata={},
            ),
            Msg(
                name="assistant",
                role="assistant",
                content="Final",
                metadata={},
            ),
        ]

        # Threshold triggers compaction, reserve is very small
        result = await handler.context_check(
            messages=messages,
            context_compact_threshold=100,  # Low threshold to trigger compaction
            context_compact_reserve=50,  # Very small reserve
        )

        msgs_to_compact, msgs_to_keep, total_tokens, keep_tokens = result

        # Verify tool_use and tool_result ids match in kept messages
        tool_use_ids_in_keep = set()
        tool_result_ids_in_keep = set()

        for msg in msgs_to_keep:
            for block in msg.get_content_blocks("tool_use"):
                if tid := block.get("id"):
                    tool_use_ids_in_keep.add(tid)
            for block in msg.get_content_blocks("tool_result"):
                if tid := block.get("id"):
                    tool_result_ids_in_keep.add(tid)

        assert (
            tool_use_ids_in_keep == tool_result_ids_in_keep
        ), f"tool_use ids: {tool_use_ids_in_keep}, tool_result ids: {tool_result_ids_in_keep}"


class TestAsMsgHandlerTokenOverride:
    """Test request-level token overrides."""

    @pytest.mark.asyncio
    async def test_context_check_uses_total_tokens_override(self):
        token_counter = MockTokenCounter()
        handler = AsMsgHandler(token_counter)
        messages = [
            Msg(name="user", role="user", content="abcd", metadata={}),
            Msg(
                name="assistant",
                role="assistant",
                content="efgh",
                metadata={},
            ),
        ]

        result = await handler.context_check(
            messages=messages,
            context_compact_threshold=10,
            context_compact_reserve=1,
            total_tokens_override=20,
        )

        msgs_to_compact, msgs_to_keep, total_tokens, keep_tokens = result
        assert total_tokens == 20
        assert msgs_to_compact == messages[:1]
        assert msgs_to_keep == messages[1:]
        assert keep_tokens == 1

    @pytest.mark.asyncio
    async def test_context_check_override_under_threshold_skips_full_count(
        self,
    ):
        token_counter = MockTokenCounter()
        handler = AsMsgHandler(token_counter)
        messages = [
            Msg(name="user", role="user", content="abcd", metadata={}),
            Msg(
                name="assistant",
                role="assistant",
                content="efgh",
                metadata={},
            ),
        ]

        result = await handler.context_check(
            messages=messages,
            context_compact_threshold=10,
            context_compact_reserve=1,
            total_tokens_override=2,
        )

        msgs_to_compact, msgs_to_keep, total_tokens, keep_tokens = result
        assert msgs_to_compact == []
        assert msgs_to_keep == messages
        assert total_tokens == 2
        assert keep_tokens == 2
        assert token_counter.count_calls == 0


class TestLightContextManagerTokenSnapshot:
    """Test request-level prompt usage reuse."""

    @pytest.mark.asyncio
    async def test_uses_latest_prompt_usage_for_matching_snapshot(
        self,
        tmp_path,
    ):
        TokenRecordingModelWrapper._latest_usage_by_session.clear()
        manager = LightContextManager(str(tmp_path), "default")
        token_counter = MockTokenCounter()
        handler = AsMsgHandler(token_counter)
        session_id = "session-1"
        first_messages = [
            Msg(name="user", role="user", content="abcd", metadata={}),
        ]

        first = await manager._resolve_context_total_override(
            session_id=session_id,
            messages=first_messages,
            msg_handler=handler,
        )
        assert first is None

        TokenRecordingModelWrapper._latest_usage_by_session[session_id] = {
            "prompt_tokens": 10,
            "sequence": 1,
        }
        current_messages = [
            *first_messages,
            Msg(
                name="assistant",
                role="assistant",
                content="efgh",
                metadata={},
            ),
        ]

        override = await manager._resolve_context_total_override(
            session_id=session_id,
            messages=current_messages,
            msg_handler=handler,
        )

        assert override == 11
        assert token_counter.count_calls == 1

    @pytest.mark.asyncio
    async def test_snapshots_are_kept_per_session(self, tmp_path):
        TokenRecordingModelWrapper._latest_usage_by_session.clear()
        manager = LightContextManager(str(tmp_path), "default")
        token_counter = MockTokenCounter()
        handler = AsMsgHandler(token_counter)
        session_a = "session-a"
        session_b = "session-b"
        messages_a = [
            Msg(name="user", role="user", content="abcd", metadata={}),
        ]
        messages_b = [
            Msg(name="user", role="user", content="ijkl", metadata={}),
        ]

        await manager._resolve_context_total_override(
            session_id=session_a,
            messages=messages_a,
            msg_handler=handler,
        )
        await manager._resolve_context_total_override(
            session_id=session_b,
            messages=messages_b,
            msg_handler=handler,
        )

        TokenRecordingModelWrapper._latest_usage_by_session[session_a] = {
            "prompt_tokens": 10,
            "sequence": 1,
        }
        override = await manager._resolve_context_total_override(
            session_id=session_a,
            messages=[
                *messages_a,
                Msg(
                    name="assistant",
                    role="assistant",
                    content="efgh",
                    metadata={},
                ),
            ],
            msg_handler=handler,
        )

        assert override == 11

    @pytest.mark.asyncio
    async def test_latest_usage_without_snapshot_is_not_used(self, tmp_path):
        TokenRecordingModelWrapper._latest_usage_by_session.clear()
        manager = LightContextManager(str(tmp_path), "default")
        token_counter = MockTokenCounter()
        handler = AsMsgHandler(token_counter)
        session_id = "session-1"
        TokenRecordingModelWrapper._latest_usage_by_session[session_id] = {
            "prompt_tokens": 10,
            "sequence": 1,
        }

        override = await manager._resolve_context_total_override(
            session_id=session_id,
            messages=[
                Msg(name="user", role="user", content="abcd", metadata={}),
            ],
            msg_handler=handler,
        )

        assert override is None
        assert token_counter.count_calls == 0

    @pytest.mark.asyncio
    async def test_missing_prompt_usage_falls_back_to_full_estimate(
        self,
        tmp_path,
    ):
        TokenRecordingModelWrapper._latest_usage_by_session.clear()
        manager = LightContextManager(str(tmp_path), "default")
        token_counter = MockTokenCounter()
        handler = AsMsgHandler(token_counter)
        session_id = "session-1"
        messages = [
            Msg(name="user", role="user", content="abcd", metadata={}),
        ]

        await manager._resolve_context_total_override(
            session_id=session_id,
            messages=messages,
            msg_handler=handler,
        )
        TokenRecordingModelWrapper._latest_usage_by_session[session_id] = {
            "prompt_tokens": 0,
            "sequence": 1,
        }

        override = await manager._resolve_context_total_override(
            session_id=session_id,
            messages=[
                *messages,
                Msg(
                    name="assistant",
                    role="assistant",
                    content="efgh",
                    metadata={},
                ),
            ],
            msg_handler=handler,
        )

        assert override is None
        assert token_counter.count_calls == 0

    @pytest.mark.asyncio
    async def test_malformed_prompt_usage_falls_back_to_full_estimate(
        self,
        tmp_path,
    ):
        TokenRecordingModelWrapper._latest_usage_by_session.clear()
        manager = LightContextManager(str(tmp_path), "default")
        token_counter = MockTokenCounter()
        handler = AsMsgHandler(token_counter)
        session_id = "session-1"
        messages = [
            Msg(name="user", role="user", content="abcd", metadata={}),
        ]

        await manager._resolve_context_total_override(
            session_id=session_id,
            messages=messages,
            msg_handler=handler,
        )
        TokenRecordingModelWrapper._latest_usage_by_session[session_id] = {
            "prompt_tokens": "bad",
            "sequence": 1,
        }

        override = await manager._resolve_context_total_override(
            session_id=session_id,
            messages=[
                *messages,
                Msg(
                    name="assistant",
                    role="assistant",
                    content="efgh",
                    metadata={},
                ),
            ],
            msg_handler=handler,
        )

        assert override is None
        assert token_counter.count_calls == 0

    @pytest.mark.asyncio
    async def test_prompt_usage_override_ignores_static_estimate(
        self,
        tmp_path,
    ):
        TokenRecordingModelWrapper._latest_usage_by_session.clear()
        manager = LightContextManager(str(tmp_path), "default")
        token_counter = MockTokenCounter()
        handler = AsMsgHandler(token_counter)
        session_id = "session-1"
        messages = [
            Msg(name="user", role="user", content="abcd", metadata={}),
        ]

        await manager._resolve_context_total_override(
            session_id=session_id,
            messages=messages,
            msg_handler=handler,
        )
        TokenRecordingModelWrapper._latest_usage_by_session[session_id] = {
            "prompt_tokens": 10,
            "sequence": 1,
        }

        override = await manager._resolve_context_total_override(
            session_id=session_id,
            messages=[
                *messages,
                Msg(
                    name="assistant",
                    role="assistant",
                    content="efgh",
                    metadata={},
                ),
            ],
            msg_handler=handler,
        )

        assert override == 11
        assert token_counter.count_calls == 1
