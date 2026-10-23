# -*- coding: utf-8 -*-
"""G3–G5 pure contracts, independent of SDK mocks and platform Drivers."""

from dataclasses import FrozenInstanceError
import importlib
import importlib.util

import pytest

from qwenpaw.channel_protocol.models import InboundEvent
from qwenpaw.channel_protocol.errors import ProtocolValidationError


def api(module):
    name = "qwenpaw.channel_protocol." + module
    assert importlib.util.find_spec(
        name,
    ), f"{module} standard channel contract is missing"
    return importlib.import_module(name)


def event(**changes):
    """
    Literal shared group identity; display/session identity is not the
    actor.
    """
    value = {
        "event_id": "event-one",
        "event_kind": "message",
        "channel_key": "sample_chat",
        "instance_id": "workspace-one",
        "generation": 1,
        "conversation": {
            "id": "room-A",
            "type": "group",
            "thread_id": "thread-B",
        },
        "sender_id": "Alice",
        "acl_sender_id": "actor-17",
        "sender_name": "Alice",
        "content_parts": [
            {"type": "image", "image_url": "https://fixture.invalid/image"},
        ],
        "response_handle": "sample:reply:one",
        "metadata": {
            "session_id": "historic-session",
            "user_id": "group",
            "debounce_key": "historic-session:actor-17",
            "bot_mentioned": True,
        },
        **changes,
    }
    return InboundEvent.from_mapping(value)


def test_normalization_preserves_driver_identity_media_and_authenticated_actor():  # noqa: E501
    payload = api("normalization").normalize_inbound_event(event())
    assert payload["channel_id"] == "sample_chat"
    assert (
        payload["session_id"] == "historic-session"
        and payload["user_id"] == "group"
    )
    assert (
        payload["acl_sender_id"] == "actor-17"
        and payload["sender_id"] == "Alice"
    )
    assert payload["meta"]["debounce_key"] == "historic-session:actor-17"
    assert payload["meta"]["is_group"] is True
    assert payload["meta"]["response_handle"] == "sample:reply:one"
    part = payload["content_parts"][0]
    assert (
        part.get("type") if isinstance(part, dict) else part.type
    ) == "image"


@pytest.mark.parametrize("missing", ["session_id", "user_id", "debounce_key"])
def test_generic_event_requires_driver_computed_identity(missing):
    original = event()
    metadata = dict(original.metadata)
    metadata.pop(missing)
    with pytest.raises(ProtocolValidationError):
        api("normalization").normalize_inbound_event(event(metadata=metadata))


@pytest.mark.parametrize("field", ["session_id", "user_id", "debounce_key"])
@pytest.mark.parametrize("bad", ["", 17, None, True])
def test_normalized_identity_rejects_empty_or_nonstring_values(field, bad):
    metadata = {**event().metadata, field: bad}
    with pytest.raises(ProtocolValidationError):
        api("normalization").normalize_inbound_event(event(metadata=metadata))


def test_platform_metadata_cannot_replace_host_identity_or_route():
    metadata = {
        **event().metadata,
        "is_group": False,
        "acl_sender_id": "forged",
        "response_handle": "forged-route",
        "channel_id": "feishu",
        "feishu_sender_id": "forged-user",
        "feishu_thread_id": "opaque-thread",
        "session_webhook": "opaque-platform-extension",
    }
    payload = api("normalization").normalize_inbound_event(
        event(metadata=metadata),
    )
    assert (
        payload["acl_sender_id"] == "actor-17"
        and payload["channel_id"] == "sample_chat"
    )
    assert payload["meta"]["is_group"] is True
    assert payload["meta"]["response_handle"] == "sample:reply:one"
    assert payload["user_id"] == "group"
    assert payload["meta"]["feishu_thread_id"] == "opaque-thread"


def test_proactive_target_roundtrip_has_only_neutral_identity():
    targets = api("targets")
    encoded = targets.encode_reply_target(
        user_id="member:17_中文",
        session_id="room/thread:42",
    )
    assert isinstance(encoded, str)
    assert targets.decode_reply_target(encoded) == {
        "user_id": "member:17_中文",
        "session_id": "room/thread:42",
    }
    assert targets.decode_reply_target(
        targets.encode_reply_target(user_id="", session_id="cron-room"),
    ) == {
        "user_id": "",
        "session_id": "cron-room",
    }


@pytest.mark.parametrize(
    "legacy",
    [
        "feishu:open_id:old-user",
        "dingtalk:sw:Alice_old-room",
        "opaque-saved-target",
    ],
)
def test_legacy_proactive_targets_remain_opaque(legacy):
    assert api("targets").decode_reply_target(legacy) is None


@pytest.mark.parametrize(
    "field",
    ["streaming", "prepare", "completion_reaction"],
)
def test_response_policy_requires_boolean_data_and_is_immutable(field):
    policy_type = api("response_policy").ResponsePolicy
    data = {"streaming": True, "prepare": False, "completion_reaction": True}
    policy = policy_type.from_mapping(data)
    assert policy.to_mapping() == data
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        setattr(policy, field, False)
    with pytest.raises(ProtocolValidationError):
        policy_type.from_mapping({**data, field: "true"})


@pytest.mark.parametrize(
    "value",
    [
        "qwenpaw-target:v1:broken-json",
        'qwenpaw-target:v99:{"user_id":"u","session_id":"s"}',
        'qwenpaw-target:v1:{"user_id":"u"}',
        (
            'qwenpaw-target:v1:{"user_id":"u","session_id":"s",'
            '"webhook":"secret"}'
        ),
    ],
)
def test_reserved_target_envelopes_fail_closed(value):
    with pytest.raises((ProtocolValidationError, ValueError)):
        api("targets").decode_reply_target(value)


def proxy(tmp_path, config=None, *, legacy=None):
    """Public static factory; no fake admission owner or process transport."""
    import json
    import shutil
    import sys
    from qwenpaw.plugins.architecture import PluginManifest
    from qwenpaw.plugins.channel_adapter import describe_channel
    from extension_sample import ROOT, sample_source

    if legacy:
        source = tmp_path / legacy
        shutil.copytree(
            ROOT / "plugins/channel" / legacy,
            source,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        path = source / "channel.json"
        data = json.loads(path.read_text())
        data["capabilities"] = [
            c for c in data["capabilities"] if c != "channel.generic.v1"
        ]
        path.write_text(json.dumps(data))
    else:
        source = sample_source(tmp_path)
    manifest = PluginManifest.from_dict(
        json.loads((source / "plugin.json").read_text()),
    )

    async def unused_agent(_request):
        raise AssertionError("Static contract called Agent")
        # Preserve async-generator shape for the ProcessHandler contract.
        # pylint: disable-next=unreachable
        yield

    return describe_channel(source, manifest).create_proxy(
        unused_agent,
        config or {},
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="workspace-one",
        generation=1,
        qwenpaw_version="2.2.2b4",
        workspace_dir=tmp_path / "workspace",
    )


def test_proxy_uses_driver_debounce_boundary_for_members_and_threads(tmp_path):
    channel = proxy(tmp_path)
    first = api("normalization").normalize_inbound_event(event())
    second = api("normalization").normalize_inbound_event(
        event(
            sender_id="Bob",
            acl_sender_id="actor-18",
            metadata={
                **event().metadata,
                "debounce_key": "historic-session:actor-18",
            },
        ),
    )
    thread = api("normalization").normalize_inbound_event(
        event(
            metadata={
                **event().metadata,
                "session_id": "historic-thread-B",
                "debounce_key": "historic-thread-B:actor-17",
            },
        ),
    )
    assert channel.get_debounce_key(first) == "historic-session:actor-17"
    assert channel.get_debounce_key(second) == "historic-session:actor-18"
    assert channel.get_debounce_key(thread) == "historic-thread-B:actor-17"
    request = channel.build_agent_request_from_native(first)
    assert (
        request.session_id == "historic-session" and request.user_id == "group"
    )


@pytest.mark.parametrize(
    "command",
    [
        "/approve pending-one",
        "/deny pending-one",
        "/approval approve pending-one",
    ],
)
def test_generic_approval_operator_is_acl_actor_despite_shared_user(
    tmp_path,
    command,
):
    channel = proxy(tmp_path)
    payload = api("normalization").normalize_inbound_event(
        event(content_parts=[{"type": "text", "text": command}]),
    )
    request = channel.build_agent_request_from_native(payload)
    assert request.user_id == "actor-17"
    assert request.channel_meta["response_handle"] == "sample:reply:one"
    assert request.session_id == "historic-session"


@pytest.mark.parametrize(
    "legacy,config,sender,metadata,want_session,want_target",
    [
        (
            "feishu",
            {"app_id": "cli_fixture"},
            "ou-user12345678",
            {"feishu_chat_id": "oc-room12345678", "feishu_chat_type": "group"},
            "ture_12345678",
            "feishu:sw:old-session",
        ),
        (
            "dingtalk",
            {"share_session_in_group": False},
            "Alice#1234",
            {"conversation_id": "cid-room12345678", "is_group": True},
            "12345678",
            "dingtalk:sw:old-user_old-session",
        ),
    ],
)
def test_frozen_official_contract_preserves_old_session_and_cron_target(
    tmp_path,
    legacy,
    config,
    sender,
    metadata,
    want_session,
    want_target,
):
    channel = proxy(tmp_path, config, legacy=legacy)
    assert channel.resolve_session_id(sender, metadata) == want_session
    assert (
        channel.to_handle_from_target(
            user_id="old-user",
            session_id="old-session",
        )
        == want_target
    )


@pytest.mark.parametrize(
    "observed",
    [
        ["media"],
        ["channel.generic.v1", "media", "response.prepare"],
    ],
)
def test_shared_hello_rejects_contract_or_capability_disagreement(observed):
    from packaging.markers import default_environment
    from qwenpaw.channel_protocol.shared import validate_shared_hello

    hello = {
        "protocol_version": 2,
        "dependency_mode": "shared",
        "qwenpaw_version": "2.2.2b4",
        "channel_key": "sample_chat",
        "instance_id": "workspace-one",
        "generation": 1,
        "source_revision": "a" * 64,
        "python_abi": "cp311-cp311",
        "platform_tag": "macosx_11_0_arm64",
        "marker_environment": default_environment(),
        "dependencies": [],
        "capabilities": observed,
    }
    with pytest.raises(ProtocolValidationError) as rejected:
        validate_shared_hello(
            hello,
            channel_key="sample_chat",
            instance_id="workspace-one",
            generation=1,
            source_revision="a" * 64,
            qwenpaw_version="2.2.2b4",
            capabilities=("channel.generic.v1", "media"),
        )
    assert rejected.value.reason_code == "CAPABILITY_MISMATCH"
