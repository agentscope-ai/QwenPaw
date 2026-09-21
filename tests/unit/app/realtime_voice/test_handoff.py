import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.realtime_voice.contracts import VoiceTaskReceipt
from qwenpaw.app.realtime_voice.handoff import (
    VoiceHandoffController,
    VoiceHandoffError,
)
from qwenpaw.app.realtime_voice.task_bridge import VoiceAdmissionHandle
from qwenpaw.providers.realtime_voice import ProviderEvent


def event(
    call_id: str = "call-1",
    *,
    name: str = "handoff_to_chat",
    arguments: str | None = None,
) -> ProviderEvent:
    return ProviderEvent(
        "tool.call",
        "event-1",
        {
            "call_id": call_id,
            "name": name,
            "arguments": arguments
            if arguments is not None
            else json.dumps({"request_text": "完成这个任务"}),
            "input_item_id": "input-1",
        },
        correlation_id=call_id,
        response_origin="provider_auto",
    )


def admission(receipt: VoiceTaskReceipt) -> VoiceAdmissionHandle:
    completion = asyncio.get_running_loop().create_future()
    completion.set_result(receipt)
    return VoiceAdmissionHandle(completion)


@pytest.mark.asyncio
async def test_duplicate_call_reuses_one_admission_and_one_provider_receipt():
    receipt = VoiceTaskReceipt("task-1", "请求一", True, "processing")
    provider = AsyncMock()
    bridge = AsyncMock()
    bridge.enqueue_input.return_value = admission(receipt)
    controller = VoiceHandoffController(provider, bridge)

    first, second = await asyncio.gather(
        controller.handle(event()),
        controller.handle(event()),
    )

    assert not first.replayed
    assert second.replayed
    bridge.enqueue_input.assert_awaited_once()
    provider.complete_tool_call.assert_awaited_once()
    assert first.work.input_id == second.work.input_id


@pytest.mark.parametrize(
    "bad_event",
    [
        event(name="unknown"),
        event(arguments="not json"),
        event(arguments=json.dumps({"request_text": "ok", "extra": True})),
        event(arguments=json.dumps({"request_text": ""})),
    ],
)
def test_invalid_native_call_is_rejected_before_chat_admission(bad_event):
    with pytest.raises(VoiceHandoffError):
        VoiceHandoffController.parse(bad_event)


@pytest.mark.asyncio
async def test_admission_failure_is_returned_to_native_model():
    provider = AsyncMock()
    bridge = AsyncMock()
    bridge.enqueue_input.side_effect = OverflowError("too many pending requests")
    controller = VoiceHandoffController(provider, bridge)

    result = await controller.handle(event())

    assert not result.receipt.accepted
    provider.complete_tool_call.assert_awaited_once_with(
        "call-1",
        {
            "accepted": False,
            "action": "handoff",
            "task_ref": "",
            "status": "failed",
            "message": "too many pending requests",
        },
    )
