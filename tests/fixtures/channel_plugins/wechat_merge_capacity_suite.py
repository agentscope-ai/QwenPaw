"""Proxy-local buffer capacity negative control, distinct from child routes.

Direct accepted buffer entrypoint units use local handles deliberately: they
exercise the proxy budget, not child route admission or authentication. Actual
UTF-8 aggregate capacity also has a separate real-route pipeline test.
"""

import pytest

from extension_process_suite import runtime
from wechat_merge_support import merge_runtime, sends


@pytest.mark.asyncio
async def test_proxy_local_129th_pending_response_is_rejected_without_dispatch(
    runtime,
):
    rt = await merge_runtime(runtime)
    fields = {"content_parts": [{"type": "text", "text": "buffered"}]}
    for number in range(128):
        await rt.channel._buffer_response_text(
            "room-A", {"response_handle": f"unit-local-{number}"}, fields
        )
    with pytest.raises(ValueError, match="TEXT_MERGE_CAPACITY"):
        await rt.channel._buffer_response_text(
            "room-A", {"response_handle": "unit-local-129"}, fields
        )
    assert await sends(rt) == []
    await rt.channel._cancel_response_text("unit-local-0")
    await rt.channel._buffer_response_text(
        "room-A", {"response_handle": "unit-local-replacement"}, fields
    )
    assert await sends(rt) == []
    for number in range(1, 128):
        await rt.channel._cancel_response_text(f"unit-local-{number}")
    await rt.channel._cancel_response_text("unit-local-replacement")
