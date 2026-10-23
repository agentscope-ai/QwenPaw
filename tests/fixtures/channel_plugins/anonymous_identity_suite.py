"""Host-only anonymous identity provenance and ordinary fallback controls."""

import json
from types import SimpleNamespace as NS

import pytest

from raw_actor_test_support import actor_source, actor_without_cap_source

pytest_plugins = ["extension_process_suite"]


@pytest.mark.parametrize("parse", ["constructor", "validate", "json"])
def test_input_private_identity_and_control_keys_are_stripped(parse):
    from qwenpaw.runtime.runtime import Runtime
    from qwenpaw.schemas import AgentRequest

    value = {
        "session_id": "console-session",
        "user_id": "",
        "_channel_actor_unknown": True,
        "_channel_control_state": {"forged": True},
        "channel_meta": {"actor_unknown": True},
    }
    if parse == "constructor":
        request = AgentRequest(**value)
    elif parse == "validate":
        request = AgentRequest.model_validate(value)
    else:
        request = AgentRequest.model_validate_json(json.dumps(value))
    assert request._channel_actor_unknown is False
    assert request._channel_control_state is None
    assert "_channel_actor_unknown" not in request.model_dump()
    assert "_channel_control_state" not in request.model_dump()
    assert Runtime._normalize(request).user_id == "console-session"
    assert value["_channel_actor_unknown"] is True


@pytest.mark.parametrize("kind", ["dict", "request", "fake_private_attr", "known"])
def test_normal_requests_keep_session_fallback_and_known_identity(kind):
    from qwenpaw.runtime.runtime import Runtime
    from qwenpaw.schemas import AgentRequest

    if kind == "dict":
        request = {"session_id": "ordinary-session"}
    elif kind == "request":
        request = AgentRequest(session_id="ordinary-session", user_id="")
    elif kind == "fake_private_attr":
        request = NS(
            session_id="ordinary-session", user_id="", _channel_actor_unknown=True
        )
    else:
        request = AgentRequest(session_id="ordinary-session", user_id="known-user")
    normalized = Runtime._normalize(request)
    assert normalized.session_id == "ordinary-session"
    assert normalized.user_id == (
        "known-user" if kind == "known" else "ordinary-session"
    )


def native(**changes):
    return {
        "actor_unknown": True,
        "sender_id": "",
        "acl_sender_id": "",
        "user_id": "",
        "session_id": "real-call-session",
        "content_parts": [{"type": "text", "text": "ordinary conversation"}],
        "meta": {"user_id": "", "actor_unknown": True},
        **changes,
    }


@pytest.mark.asyncio
async def test_actual_proxy_marker_is_private_and_checks_all_actor_fields(runtime):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.runtime.runtime import Runtime
    from qwenpaw.schemas import AgentRequest

    rt = await runtime(source_factory=actor_source)
    request = rt.channel.build_agent_request_from_native(native())
    assert request._channel_actor_unknown is True
    assert Runtime._normalize(request).user_id == ""
    assert request.session_id == "real-call-session"
    wire = request.model_dump(mode="json")
    assert "_channel_actor_unknown" not in wire
    assert Runtime._normalize(AgentRequest.model_validate(wire)).user_id == "real-call-session"

    for field in ("sender_id", "acl_sender_id", "user_id"):
        with pytest.raises(ProtocolValidationError, match="Invalid anonymous actor"):
            rt.channel.build_agent_request_from_native(native(**{field: "forged-user"}))
    with pytest.raises(ProtocolValidationError, match="Invalid anonymous actor"):
        rt.channel.build_agent_request_from_native(native(meta={"user_id": "forged-user"}))

    metadata_only = rt.channel.build_agent_request_from_native(native(actor_unknown=False))
    assert metadata_only._channel_actor_unknown is False
    assert Runtime._normalize(metadata_only).user_id == "real-call-session"
    state = await rt.process.call("fixture.inspect", {})
    assert state["effects"] == []


@pytest.mark.asyncio
async def test_actual_proxy_without_unknown_capability_cannot_mint_marker(runtime):
    from qwenpaw.channel_protocol.errors import ProtocolValidationError

    rt = await runtime(source_factory=actor_without_cap_source)
    with pytest.raises(ProtocolValidationError, match="Invalid anonymous actor"):
        rt.channel.build_agent_request_from_native(native())
    state = await rt.process.call("fixture.inspect", {})
    assert state["effects"] == []
