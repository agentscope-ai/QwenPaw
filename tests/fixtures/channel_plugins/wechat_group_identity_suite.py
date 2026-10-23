"""Native group identity through real Runner IPC, Host admission and queue."""

from importlib.util import module_from_spec, spec_from_file_location
import os
from pathlib import Path

import pytest

from extension_process_suite import durable_snapshot, eventually
from wechat_w4_formal_support import (
    native_ilink,
    official_wechat_zip,
    runtime,
    wechat_host_import_guard,
)

__all__ = ["native_ilink", "runtime", "wechat_host_import_guard"]


async def start(runtime, external, tmp_path, monkeypatch, **settings):
    from qwenpaw.__version__ import __version__
    from qwenpaw.plugins import official_channels

    root = Path(__file__).resolve().parents[3]
    spec = spec_from_file_location(
        "group_identity_bundle",
        root / "scripts/pack/generate_plugin_metadata.py",
    )
    builder = module_from_spec(spec)
    spec.loader.exec_module(builder)
    resources = tmp_path / "official-bundle"
    builder.build_official_channel_bundle(
        root, resources, host_version=__version__
    )
    monkeypatch.setattr(official_channels, "_resource_root", lambda: resources)
    rt = await runtime(
        "wechat",
        source_factory=official_wechat_zip,
        bot_token="temporary-file-token",
        bot_token_file=str(tmp_path / "token"),
        media_dir=str(tmp_path / "media"),
        base_url=external.mock.base_url,
        **settings,
    )
    relative = Path("qwenpaw_channel_wechat/platform.py")
    assert (rt.source / relative).read_bytes() == (
        root / "plugins/channel/wechat" / relative
    ).read_bytes()
    batches = []
    admit = rt.channel._admit_batch

    async def observe(params):
        snapshots = [
            durable_snapshot(rt, event.response_handle)
            for event in params.events
        ]
        ack = await admit(params)  # Keep actual normalization, ACL and queue.
        batches.append((params.to_mapping(), ack, snapshots))
        return ack

    monkeypatch.setattr(rt.channel, "_admit_batch", observe)
    assert rt.process.health_snapshot()["pid"] != os.getpid()
    return rt, batches


@pytest.mark.asyncio
async def test_group_members_share_history_identity_and_keep_reply_routes(
    runtime, native_ilink, tmp_path, monkeypatch
):
    rt, batches = await start(runtime, native_ilink, tmp_path, monkeypatch)
    # Empty group user_id, member-based history or crossed reply routes break
    # these hand-derived identities; DM still uses its real sender.
    cases = [
        ("room-A", "member-A", "wechat:group:room-A", "wechat:group:room-A"),
        ("room-A", "member-B", "wechat:group:room-A", "wechat:group:room-A"),
        ("room-B", "member-A", "wechat:group:room-B", "wechat:group:room-B"),
        (None, "member-A", "wechat:member-A", "member-A"),
    ]
    for index, (group, sender, session, user) in enumerate(cases, 1):
        context = f"native-context-{index}"
        push = (
            native_ilink.mock.push_group_text_message
            if group
            else native_ilink.mock.push_text_message
        )
        push(
            text=f"native message {index}",
            from_user_id=sender,
            context_token=context,
            **({"group_id": group} if group else {}),
        )
        await eventually(lambda: len(batches) == index)
        params, ack, snapshots = batches[-1]
        event = params["events"][0]
        assert ack["rejected_events"] == [], ack
        assert ack["accepted_event_ids"] == [event["event_id"]]
        assert (event["sender_id"], event["acl_sender_id"]) == (sender, sender)
        assert not event.get("actor_unknown", False)
        await eventually(lambda: len(rt.ws.requests) == index)
        request = rt.ws.requests[-1]
        assert (request.session_id, request.user_id) == (session, user)
        assert request.channel_meta["wechat_from_user_id"] == sender
        assert request.channel_meta["wechat_context_token"] == context
        assert request.channel_meta["wechat_group_id"] == (group or "")
        await eventually(lambda: len(native_ilink.mock.sent_messages) == index)
        sent = native_ilink.mock.sent_messages[-1]
        assert (sent["to_user_id"], sent["context_token"]) == (sender, context)
        assert "host answer" in sent["item_list"][0]["text_item"]["text"]
        snapshot = snapshots[0]
        route = next(
            ref["attributes"]
            for ref in snapshot["route_refs"]
            if ref["kind"] == "wechat.route"
        )
        assert (route["session_id"], route["user_id"]) == (session, user)
        assert (
            route["wechat_from_user_id"],
            route["wechat_context_token"],
        ) == (
            sender,
            context,
        )


@pytest.mark.asyncio
async def test_group_acl_uses_members_rather_than_shared_history_identity(
    runtime, native_ilink, tmp_path, monkeypatch
):
    rt, batches = await start(
        runtime, native_ilink, tmp_path, monkeypatch, access_control_group=True
    )
    store = rt.channel._get_acl_store()
    store.add_to_whitelist("wechat", "member-A")
    store.add_to_whitelist("wechat", "wechat:group:room-A")
    for index, sender in enumerate(("member-A", "member-B"), 1):
        native_ilink.mock.push_group_text_message(
            text="member ACL input",
            group_id="room-A",
            from_user_id=sender,
            context_token=f"acl-context-{index}",
        )
        await eventually(lambda: len(batches) == index)
        params, ack, _snapshots = batches[-1]
        event = params["events"][0]
        assert event["acl_sender_id"] == sender
        if sender == "member-A":
            assert ack["rejected_events"] == [], ack
            assert ack["accepted_event_ids"] == [event["event_id"]]
        else:
            assert ack["accepted_event_ids"] == []
            assert ack["rejected_events"] == [
                {
                    "event_id": event["event_id"],
                    "reason_code": "ACCESS_DENIED",
                    "retryable": False,
                }
            ]
        await eventually(lambda: len(native_ilink.mock.sent_messages) == index)
        sent = native_ilink.mock.sent_messages[-1]
        assert (sent["to_user_id"], sent["context_token"]) == (
            sender,
            f"acl-context-{index}",
        )
    assert len(rt.ws.requests) == 1
    assert [
        (row["channel"], row["user_id"]) for row in store.get_all_pending()
    ] == [("wechat", "member-B")]


def test_known_member_with_empty_user_id_still_fails_common_normalization():
    from qwenpaw.channel_protocol.errors import ProtocolValidationError
    from qwenpaw.channel_protocol.models import InboundEvent
    from qwenpaw.channel_protocol.normalization import normalize_inbound_event

    event = InboundEvent(
        event_id="malformed-group",
        channel_key="wechat",
        instance_id="known-member-instance",
        generation=1,
        conversation={"id": "room-A", "type": "group", "thread_id": None},
        sender_id="member-A",
        acl_sender_id="member-A",
        sender_name="member-A",
        content_parts=({"type": "text", "text": "invalid identity"},),
        event_kind="message",
        metadata={
            "session_id": "wechat:group:room-A",
            "user_id": "",
            "debounce_key": "wechat:group:room-A",
        },
    )
    with pytest.raises(
        ProtocolValidationError,
        match="Standard inbound identity missing: user_id",
    ):
        normalize_inbound_event(event)


@pytest.mark.parametrize(
    "session,user,expected",
    [
        ("wechat:group:room-A", "", "wechat--group--room-A.json"),
        (
            "wechat:group:room-A",
            "wechat:group:room-A",
            "wechat--group--room-A.json",
        ),
        ("wechat:member-A", "member-A", "member-A_wechat--member-A.json"),
    ],
)
def test_history_filename_remains_compatible(session, user, expected):
    from qwenpaw.app.chats.session import session_filename

    assert session_filename(session, user) == expected
