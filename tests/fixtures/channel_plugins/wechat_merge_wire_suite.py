"""Reject malformed raw third-party policies over actual installed RPC."""

import pytest

from qwenpaw.channel_protocol.errors import ProtocolValidationError, RpcError
from extension_process_suite import runtime
from wechat_merge_support import route, sends
from wechat_malicious_policy_source import malicious_policy_source

BASE = {"streaming": False, "prepare": False, "completion_reaction": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, 0])
async def test_unadvertised_raw_field_presence_including_null_is_rejected(
    runtime, value
):
    rt = await runtime(
        "hostile_policy_owner",
        source_factory=malicious_policy_source,
        capabilities=["channel.generic.v1"],
        raw_policy={**BASE, "text_merge_delay_ms": value},
    )
    target, meta = await route(rt)
    with pytest.raises((ProtocolValidationError, RpcError)) as raised:
        await rt.channel._response_policy(target, meta)
    error = raised.value
    reason = getattr(error, "reason_code", None)
    if isinstance(getattr(error, "data", None), dict):
        reason = error.data.get("reason_code", reason)
    assert reason == "CAPABILITY_REQUIRED"
    assert await sends(rt) == []
    assert rt.ws.requests == []


@pytest.mark.asyncio
async def test_advertised_owner_cannot_send_a_noninteger_raw_merge_policy(
    runtime,
):
    rt = await runtime(
        "hostile_policy_owner",
        source_factory=malicious_policy_source,
        capabilities=["channel.generic.v1", "channel.text_merge.v1"],
        raw_policy={**BASE, "text_merge_delay_ms": "0"},
    )
    target, meta = await route(rt)
    with pytest.raises(ProtocolValidationError):
        await rt.channel._response_policy(target, meta)
    assert await sends(rt) == []
