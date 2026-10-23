"""Minimal generic merge preference contracts and actual worker controls."""

from copy import deepcopy

import pytest

from extension_process_suite import runtime
from qwenpaw.channel_protocol.errors import ProtocolValidationError, RpcError
from qwenpaw.channel_protocol.response_policy import ResponsePolicy
from wechat_malicious_policy_source import malicious_policy_source
from wechat_merge_support import route, sends

BASE = {"streaming": False, "prepare": False, "completion_reaction": False}
PREFERENCES = {
    "text_merge_flush_before_media": False,
    "text_merge_separator_newlines": 3,
    "text_merge_format_on_flush": True,
}
__all__ = ["runtime"]


def test_merge_preferences_roundtrip_and_old_defaults_omit_new_wire_fields():
    policy = ResponsePolicy.from_mapping(BASE)
    assert policy.text_merge_flush_before_media is True
    assert policy.text_merge_separator_newlines == 1
    assert policy.text_merge_format_on_flush is False
    assert policy.to_mapping() == BASE
    explicit = {
        **BASE,
        "text_merge_flush_before_media": True,
        "text_merge_separator_newlines": 1,
        "text_merge_format_on_flush": False,
    }
    assert ResponsePolicy.from_mapping(explicit).to_mapping() == BASE
    source = {**BASE, "text_merge_delay_ms": 0, **PREFERENCES}
    expected = dict(source)
    parsed = ResponsePolicy.from_mapping(source)
    source["text_merge_separator_newlines"] = 1
    assert parsed.to_mapping() == expected


def test_merge_preference_constructor_and_parser_both_reject_invalid_types():
    invalid = {
        "text_merge_flush_before_media": [None, 0, 1, "false", []],
        "text_merge_format_on_flush": [None, 0, 1, "true", {}],
        "text_merge_separator_newlines": [None, True, False, 0, 4, 1.0, "3"],
    }
    for name, values in invalid.items():
        for value in values:
            with pytest.raises(ProtocolValidationError):
                ResponsePolicy(**{name: value})
            with pytest.raises(ProtocolValidationError):
                ResponsePolicy.from_mapping({**BASE, name: value})


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(PREFERENCES))
async def test_each_nondefault_merge_preference_requires_capability(
    runtime, name
):
    rt = await runtime(
        "hostile_policy_owner",
        source_factory=malicious_policy_source,
        capabilities=["channel.generic.v1"],
        raw_policy={**BASE, name: PREFERENCES[name]},
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


async def preferred_runtime(runtime):
    return await runtime(
        "hostile_policy_owner",
        source_factory=malicious_policy_source,
        capabilities=["channel.generic.v1", "channel.text_merge.v1", "media"],
        raw_policy={**BASE, "text_merge_delay_ms": 0, **PREFERENCES},
    )


@pytest.mark.asyncio
async def test_raw_whitespace_is_charged_without_early_send_or_old_overwrite(
    runtime,
):
    rt = await preferred_runtime(runtime)
    target, meta = await route(rt)
    await rt.channel.send_content_parts(
        target, [{"type": "text", "text": "A" + " " * 300000}], meta
    )
    handle = meta["response_handle"]
    state = rt.channel._text_merge[handle]
    previous = deepcopy(state.fields)
    raw, size, total = state.raw_text, state.size, rt.channel._text_merge_bytes
    assert raw == "A" + " " * 300000
    assert previous["content_parts"] == [{"type": "text", "text": "A"}]
    assert size >= len(raw.encode())
    with pytest.raises(ValueError, match="TEXT_MERGE_CAPACITY"):
        await rt.channel.send_content_parts(
            target, [{"type": "text", "text": " " * 800000 + "B"}], meta
        )
    assert await sends(rt) == []
    assert state.fields == previous
    assert state.raw_text == raw and state.size == size
    assert rt.channel._text_merge_bytes == total
    with pytest.raises(ValueError, match="TEXT_MERGE_CAPACITY"):
        await rt.channel._finish_route(meta, "completed")
    await rt.channel._cancel_response_text(handle)


@pytest.mark.asyncio
async def test_unknown_media_never_automatically_replays_or_flushes_text(
    runtime,
):
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    rt = await preferred_runtime(runtime)
    target, meta = await route(rt)
    await rt.channel.send_content_parts(
        target, [{"type": "text", "text": "pending A"}], meta
    )
    await rt.process.call("fixture.fault", {"mode": "unknown"})
    with pytest.raises(ChannelDeliveryError) as raised:
        await rt.channel.send_media(
            target,
            {"type": "image", "image_url": "https://asset.test/a.png"},
            meta,
        )
    assert raised.value.side_effect_possible
    pending = deepcopy(meta["_pending_delivery"])
    effects = await sends(rt)
    assert len(effects) == 1
    assert effects[0]["content_parts"] == [
        {"type": "image", "image_url": "https://asset.test/a.png"}
    ]
    assert effects[0]["delivery_id"] == pending["delivery_id"]
    with pytest.raises(ChannelDeliveryError):
        await rt.channel._finish_route(meta, "completed")
    assert await sends(rt) == effects
    assert meta["_pending_delivery"] == pending
    assert meta["response_handle"] in rt.channel._text_merge
    await rt.channel._cancel_response_text(meta["response_handle"])
