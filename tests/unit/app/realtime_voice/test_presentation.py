# -*- coding: utf-8 -*-
import asyncio

import pytest

from qwenpaw.app.realtime_voice.presentation import (
    OutputCredit,
    PresentationIntent,
    PresentationQueue,
)


@pytest.mark.asyncio
async def test_bounded_coalescing_and_direct_fifo():
    queue = PresentationQueue(3)
    for _ in range(100):
        assert queue.put(PresentationIntent("update"))
    first = PresentationIntent("rejected", turn_id="first")
    second = PresentationIntent("rejected", turn_id="second")
    assert queue.put(first)
    assert queue.put(second)
    refused = asyncio.get_running_loop().create_future()
    assert not queue.put(PresentationIntent("rejected", completion=refused))
    assert refused.cancelled()
    assert await queue.get() is first
    assert await queue.get() is second
    assert (await queue.get()).kind == "update"
    queue.close()
    assert await queue.get() is None


@pytest.mark.asyncio
async def test_update_speech_coalesces_without_losing_reply_identities():
    queue = PresentationQueue(10)
    for index in range(10):
        assert queue.put(
            PresentationIntent("update", changed_ids=(f"reply-{index}",)),
        )
    queued = await queue.get()
    assert queued.kind == "update"
    assert queued.changed_ids == tuple(f"reply-{index}" for index in range(10))


def test_output_wording_is_bounded_and_cancelled_text_cannot_change_it():
    credit = OutputCredit()
    credit.observe_transcript("开始", final=False)
    credit.observe_transcript("处理", final=False)
    assert credit.transcript == "开始处理"
    credit.observe_transcript("已经保存", final=True)
    credit.cancel()
    credit.observe_transcript("不能接纳的迟到文本", final=True)
    assert credit.transcript == "已经保存"
    assert credit.playback == "interrupted"
    other = OutputCredit()
    other.observe_transcript("字" * 5000, final=True)
    assert len(other.transcript) == 2000


@pytest.mark.asyncio
@pytest.mark.parametrize("feedback_first", [False, True])
async def test_credit_requires_terminal_and_matching_playback(feedback_first):
    credit = OutputCredit()
    task = asyncio.create_task(credit.wait(1))
    credit.acknowledge("other-session-output", "drained")
    credit.acknowledge(
        credit.output_id,
        "drained",
    )  # Cannot drain before seal.
    assert not credit.playback
    if feedback_first:
        credit.acknowledge(credit.output_id, "interrupted")
    else:
        credit.seal()
    await asyncio.sleep(0)
    assert not task.done()
    if feedback_first:
        credit.seal()
    else:
        credit.acknowledge(credit.output_id, "drained")
    await task
    credit.acknowledge(
        credit.output_id,
        "failed",
    )  # Duplicate cannot change it.
    assert credit.playback != "failed"


@pytest.mark.asyncio
async def test_failed_or_missing_feedback_does_not_release_credit():
    credit = OutputCredit()
    credit.seal()
    with pytest.raises(TimeoutError):
        await credit.wait(0.001)
    credit.acknowledge(credit.output_id, "failed")
    with pytest.raises(RuntimeError, match="browser"):
        await credit.wait(1)


@pytest.mark.asyncio
async def test_cancel_is_irreversible_but_still_waits_for_provider_terminal():
    credit = OutputCredit()
    credit.cancel()
    credit.cancel()
    credit.acknowledge(credit.output_id, "drained")
    assert credit.cancelled
    assert credit.playback == "interrupted"
    with pytest.raises(TimeoutError):
        await credit.wait(0.001)
    credit.seal()
    await credit.wait(1)
    assert credit.cancelled


@pytest.mark.asyncio
async def test_close_settles_every_pending_question():
    queue = PresentationQueue(2)
    completions = [
        asyncio.get_running_loop().create_future() for _ in range(3)
    ]
    for completion in completions[:2]:
        assert queue.put(PresentationIntent("rejected", completion=completion))
    queue.close()
    assert not queue.put(
        PresentationIntent("rejected", completion=completions[2]),
    )
    assert all(future.cancelled() for future in completions)


@pytest.mark.asyncio
async def test_coalescing_preserves_changed_identities_and_capacity():
    queue = PresentationQueue(2)
    assert queue.put(PresentationIntent("update", changed_ids=("a",)))
    assert queue.put(PresentationIntent("update", changed_ids=("a", "b")))
    refused = asyncio.get_running_loop().create_future()
    assert not queue.put(
        PresentationIntent("update", changed_ids=("c",), completion=refused),
    )
    assert refused.cancelled()
    assert (await queue.get()).changed_ids == ("a", "b")
