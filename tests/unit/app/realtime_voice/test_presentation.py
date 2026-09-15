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
    first = PresentationIntent("status", turn_id="first")
    second = PresentationIntent("converse", turn_id="second")
    assert queue.put(first)
    assert queue.put(second)
    refused = asyncio.get_running_loop().create_future()
    assert not queue.put(PresentationIntent("status", completion=refused))
    assert refused.cancelled()
    assert await queue.get() is first
    assert await queue.get() is second
    assert (await queue.get()).kind == "update"
    queue.close()
    assert await queue.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("feedback_first", [False, True])
async def test_credit_requires_terminal_and_matching_playback(feedback_first):
    credit = OutputCredit()
    task = asyncio.create_task(credit.wait(1))
    credit.acknowledge("other-session-output", "drained")
    credit.acknowledge(
        credit.output_id, "drained"
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
        credit.output_id, "failed"
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
async def test_close_settles_every_pending_question():
    queue = PresentationQueue(2)
    completions = [
        asyncio.get_running_loop().create_future() for _ in range(3)
    ]
    for completion in completions[:2]:
        assert queue.put(PresentationIntent("converse", completion=completion))
    queue.close()
    assert not queue.put(
        PresentationIntent("converse", completion=completions[2])
    )
    assert all(future.cancelled() for future in completions)


@pytest.mark.asyncio
async def test_coalescing_preserves_changed_identities_and_counts_them_against_capacity():
    queue = PresentationQueue(2)
    assert queue.put(PresentationIntent("update", changed_ids=("a",)))
    assert queue.put(PresentationIntent("update", changed_ids=("a", "b")))
    refused = asyncio.get_running_loop().create_future()
    assert not queue.put(
        PresentationIntent("update", changed_ids=("c",), completion=refused)
    )
    assert refused.cancelled()
    assert (await queue.get()).changed_ids == ("a", "b")
