"""Existing empty-caller facts; no invented unknown-identity protocol."""

import pytest

pytest_plugins = ["extension_process_suite"]


@pytest.mark.parametrize("field", ["sender_id", "acl_sender_id"])
def test_existing_inbound_dto_rejects_empty_identity(field):
    from qwenpaw.channel_protocol.models import InboundEvent
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    value = {
        "channel_key": "voice",
        "instance_id": "instance",
        "generation": 1,
        "event_id": "event",
        "event_kind": "message.query",
        "conversation": {"id": "voice:CA-original", "type": "dm", "thread_id": None},
        "sender_id": "+15550001",
        "acl_sender_id": "+15550001",
        "sender_name": "",
        "content_parts": [{"type": "text", "text": "hello"}],
        "metadata": {},
        "response_handle": "voice:reply:original",
    }
    value[field] = ""
    with pytest.raises(ProtocolValidationError):
        InboundEvent.from_mapping(value)


@pytest.mark.asyncio
async def test_real_proxy_default_open_allowlist_and_approval_identity_boundaries(
    runtime,
):
    rt = await runtime()
    channel = rt.channel
    payload = {
        "sender_id": "",
        "acl_sender_id": "",
        "session_id": "voice:CA-original",
        "content_parts": [{"type": "text", "text": "hello"}],
        "meta": {"is_group": False},
    }
    request = channel.build_agent_request_from_native(payload)
    assert request.user_id == "" and request.session_id == "voice:CA-original"
    assert not await channel._access_control_gate(payload)
    channel.access_control_dm = True
    store = channel._get_acl_store()
    store.set_whitelist(channel.channel, ["known-caller"])
    known = {**payload, "sender_id": "known-caller", "acl_sender_id": "known-caller"}
    denied = {
        **payload,
        "sender_id": "unlisted-caller",
        "acl_sender_id": "unlisted-caller",
    }
    assert not await channel._access_control_gate(known)
    assert await channel._access_control_gate(denied)
    assert not store.is_whitelisted(channel.channel, "unlisted-caller")
    assert not store.is_whitelisted(channel.channel, "")
    # Enabling DM access control rejects unknown callers without enrollment.
    assert await channel._access_control_gate(payload)
    for command in [
        "/approve pending-one",
        "/deny pending-one",
        "/approval approve pending-one",
    ]:
        for operator in ["", "   ", None]:
            with pytest.raises(ValueError, match="APPROVAL_OPERATOR_UNAVAILABLE"):
                channel.build_agent_request_from_native(
                    {
                        **payload,
                        "sender_id": "display-or-session",
                        "acl_sender_id": operator,
                        "content_parts": [{"type": "text", "text": command}],
                    }
                )
        actual = channel.build_agent_request_from_native(
            {
                **payload,
                "sender_id": "display-or-session",
                "acl_sender_id": "known-caller",
                "content_parts": [{"type": "text", "text": command}],
            }
        )
        assert actual.user_id == "known-caller"
    assert not rt.ws.requests  # No fake Agent response used for these checks.
