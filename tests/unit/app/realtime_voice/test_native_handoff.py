import asyncio
from unittest.mock import Mock

import pytest

from qwenpaw.app.realtime_voice.native_handoff import (
    NativeDelegationCommitter,
    NativeDelegationRejected,
)
from qwenpaw.app.realtime_voice.turn_commit import CommittedSpokenTurn


@pytest.mark.asyncio
@pytest.mark.parametrize("call_first", [False, True])
async def test_native_delegation_waits_for_call_and_final_transcript(call_first):
    committer = NativeDelegationCommitter(continuation_grace_ms=0)
    committer.on_commit = Mock()
    try:
        if call_first:
            await committer.delegation_requested("source", "call")
            await committer.add_segment("source", "最终原文")
        else:
            await committer.add_segment("source", "最终原文")
            await committer.delegation_requested("source", "call")

        event = await anext(committer.events())
        assert isinstance(event, CommittedSpokenTurn)
        assert event.text == "最终原文"
        assert event.source_ids == ("source",)
        assert event.delegation_ids == ("call",)
        committer.on_commit.assert_called_once_with(event)
    finally:
        await committer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_native_delegation_rejects_missing_authoritative_text(failed):
    committer = NativeDelegationCommitter(continuation_grace_ms=0)
    committer.on_commit = Mock()
    try:
        await committer.delegation_requested("source", "call")
        if failed:
            await committer.input_failed("source")
        else:
            await committer.add_segment("source", "")

        event = await anext(committer.events())
        assert event == NativeDelegationRejected(
            "source",
            "call",
            "voice_transcription_failed",
        )
        committer.on_commit.assert_not_called()
    finally:
        await committer.close()


@pytest.mark.asyncio
async def test_duplicate_native_call_is_rejected_without_replacing_first_call():
    committer = NativeDelegationCommitter(continuation_grace_ms=0)
    try:
        await committer.delegation_requested("source", "first")
        await committer.delegation_requested("source", "second")
        rejected = await anext(committer.events())
        assert rejected == NativeDelegationRejected(
            "source",
            "second",
            "duplicate_native_delegation",
        )

        await committer.add_segment("source", "执行任务")
        committed = await anext(committer.events())
        assert isinstance(committed, CommittedSpokenTurn)
        assert committed.delegation_ids == ("first",)
    finally:
        await committer.close()


@pytest.mark.asyncio
async def test_native_delegation_flushes_continuing_asr_items_once():
    committer = NativeDelegationCommitter(continuation_grace_ms=30)
    try:
        await committer.delegation_requested("source-1", "call-1")
        await committer.add_segment("source-1", "请执行下面的长任务。")
        await asyncio.sleep(0.01)
        await committer.speech_started("source-2")
        await committer.add_segment("source-2", "等待后输出931。")

        committed = await asyncio.wait_for(anext(committer.events()), 1)
        assert isinstance(committed, CommittedSpokenTurn)
        assert committed.text == "请执行下面的长任务。\n等待后输出931。"
        assert committed.source_ids == ("source-1", "source-2")
        assert committed.delegation_ids == ("call-1",)
    finally:
        await committer.close()


@pytest.mark.asyncio
async def test_native_delegation_settles_every_call_in_one_speech_window():
    committer = NativeDelegationCommitter(continuation_grace_ms=0)
    try:
        await committer.speech_started("source-1")
        await committer.delegation_requested("source-1", "call-1")
        await committer.speech_started("source-2")
        await committer.delegation_requested("source-2", "call-2")
        await committer.add_segment("source-1", "任务前半段")
        await committer.add_segment("source-2", "任务后半段")

        committed = await asyncio.wait_for(anext(committer.events()), 1)
        assert isinstance(committed, CommittedSpokenTurn)
        assert committed.text == "任务前半段\n任务后半段"
        assert committed.delegation_ids == ("call-1", "call-2")
    finally:
        await committer.close()


@pytest.mark.asyncio
async def test_direct_response_fragment_stays_buffered_during_handoff():
    committer = NativeDelegationCommitter(continuation_grace_ms=0)
    try:
        await committer.delegation_requested("source-1", "call-1")
        await committer.add_segment("source-1", "请运行命令")
        await committer.speech_started("source-2")
        await committer.add_segment("source-2", "然后输出结果")

        assert committer.finish_source("source-2") is False
        committed = await asyncio.wait_for(anext(committer.events()), 1)
        assert isinstance(committed, CommittedSpokenTurn)
        assert committed.text == "请运行命令\n然后输出结果"
    finally:
        await committer.close()


@pytest.mark.asyncio
async def test_direct_conversation_is_released_before_later_handoff():
    committer = NativeDelegationCommitter(continuation_grace_ms=0)
    try:
        await committer.add_segment("greeting", "你好")
        assert committer.finish_source("greeting") is True
        await committer.delegation_requested("task", "call")
        await committer.add_segment("task", "检查项目")

        committed = await asyncio.wait_for(anext(committer.events()), 1)
        assert isinstance(committed, CommittedSpokenTurn)
        assert committed.text == "检查项目"
        assert committed.source_ids == ("task",)
    finally:
        await committer.close()
