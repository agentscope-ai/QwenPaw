"""Legacy session persistence, incoming media and owned resource shutdown."""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.register_assert_rewrite("yuanbao_native_support")
from yuanbao_native_support import YuanbaoPlatform, codec, eventually, inbound
from qwenpaw_channel_yuanbao.errors import YuanbaoDeliveryError

pytest_plugins = ["yuanbao_native_support"]


@pytest.mark.parametrize("workspace", [True, False])
async def test_legacy_workspace_and_media_parent_map_resolve_full_native_targets(tmp_path, workspace):
    media = tmp_path / "custom" / "media"
    owner = tmp_path / "workspace" if workspace else media.parent
    owner.mkdir(parents=True)
    original = {
        "12345678": {"chat_type": "c2c", "sender_id": "very-long-native-account-12345678", "group_code": "", "msg_id": "old-dm"},
        "group-session": {"chat_type": "group", "sender_id": "native-speaker", "group_code": "full-native-group", "msg_id": "old-group"},
        "unrelated": {"opaque": "preserve this legacy record"},
    }
    path = owner / "yuanbao_sessions.json"
    raw = json.dumps(original, ensure_ascii=False).encode()
    path.write_bytes(raw)
    async def unused(_value):
        raise AssertionError("disabled map reader emitted external action")
    config = {"enabled": False, "media_dir": str(media)}
    if workspace:
        config["workspace_dir"] = str(owner)
    platform = YuanbaoPlatform(config, unused, unused)
    assert platform._session_map_path() == path
    assert platform.resolve_target("12345678") == original["12345678"]
    assert platform.resolve_target("group-session") == original["group-session"]
    with pytest.raises(YuanbaoDeliveryError, match="OUTBOUND_TARGET_UNKNOWN"):
        platform.resolve_target("guess-me")
    assert path.read_bytes() == raw


async def test_two_live_owners_merge_new_map_entries_without_overwriting_legacy(native_platform):
    first, _, _, external = native_platform
    path = first._session_map_path()
    old = {"legacy": {"chat_type": "c2c", "sender_id": "original-native", "group_code": "", "msg_id": "original-msg"}}
    path.write_text(json.dumps(old))
    async def accepted(_value):
        return True
    async def state(_value):
        pass
    second = YuanbaoPlatform(first.config, accepted, state)
    try:
        await second.start()
        assert second._connected and len(external.connections) == 2
        await asyncio.gather(
            first._handle_chat_message(inbound(msg_id="first-new", sender="raw-account-aaaaaaaa")),
            second._handle_chat_message(inbound(msg_id="second-new", sender="raw-account-bbbbbbbb", group="native-group-new")),
        )
        data = json.loads(path.read_text())
        assert set(data) == {"legacy", "aaaaaaaa", "native-group-new"}
        assert data["legacy"] == old["legacy"]
        assert data["aaaaaaaa"]["sender_id"] == "raw-account-aaaaaaaa"
        assert data["native-group-new"]["group_code"] == "native-group-new"
        assert first.resolve_target("native-group-new") == data["native-group-new"]
        assert second.resolve_target("aaaaaaaa") == data["aaaaaaaa"]
    finally:
        await second.stop()


async def test_corrupt_legacy_map_bytes_are_preserved_during_new_inbound(native_platform):
    platform, events, _, external = native_platform
    path = platform._session_map_path()
    raw = b"{truncated-user-data"
    path.write_bytes(raw)
    await external.push(inbound(msg_id="new-with-corrupt-map"))
    await eventually(lambda: len(events) == 1)
    assert path.read_bytes() == raw
    assert platform.resolve_target("12345678")["sender_id"] == "native-user-12345678"
    assert list(path.parent.glob(".yuanbao-sessions-*")) == []


async def test_inbound_audio_resolves_authenticated_download_and_preserves_bytes(native_platform):
    platform, events, _, external = native_platform
    value = inbound(msg_id="native-audio")
    value["msg_body"] = [{"msg_type": "TIMFileElem", "msg_content": {
        "file_name": "原始录音.mp3", "url": external.base + "/cdn?resourceId=original-resource",
    }}]
    await external.push(value)
    await eventually(lambda: len(events) == 1)
    part = events[0]["content_parts"][0]
    assert part["type"] == "audio"
    location = Path(urlparse(part["data"]).path)
    # URI is percent escaped for CJK names.
    from urllib.parse import unquote
    location = Path(unquote(str(location)))
    assert location.name == "原始录音.mp3" and location.read_bytes() == b"native-audio"
    assert location.is_relative_to(platform._media_dir)
    request = next(row for row in external.calls if row["path"] == "/api/resource/v1/download")
    assert request["query"] == {"resourceId": "original-resource"}
    assert {key: request["headers"][key] for key in ("X-ID", "X-Token", "X-Source")} == {
        "X-ID": "native-bot", "X-Token": "native-token", "X-Source": "bot",
    }
    assert len(list(platform._media_dir.iterdir())) == 1


async def test_media_outside_workspace_is_nonretryable_and_has_zero_native_effect(native_platform, tmp_path):
    platform, _, _, external = native_platform
    outside = tmp_path / "private-outside.pdf"
    outside.write_bytes(b"must never upload")
    route = {"chat_type": "c2c", "sender_id": "native-target", "group_code": "", "msg_id": "old"}
    before = len(external.calls)
    with pytest.raises(YuanbaoDeliveryError) as caught:
        await platform.send_parts(route, [{"type": "file", "file_url": str(outside)}], "parts", "unauthorized")
    assert caught.value.reason_code == "MEDIA_PATH_UNAUTHORIZED"
    assert caught.value.retryable is False and caught.value.side_effect_possible is False
    assert len(external.calls) == before and external.uploads == [] and external.sends == []


async def test_inband_auth_failure_refreshes_and_reauthenticates_before_reconnect_delivery(native_platform):
    platform, _, states, external = native_platform
    old_receive = platform._receive_task
    await external.respond({"cmd": codec.CMD_AUTH_BIND, "msgId": "expired-auth"}, codec.AUTH_BIND_RSP, {"code": 41103})
    await eventually(lambda: len(external.signatures_valid) == 2)
    await eventually(lambda: len(external.connections) == 2 and platform._connected)
    assert old_receive.done()
    assert external.signatures_valid == [True, True]
    assert states[-3:] == ["disconnected", "connecting", "connected"]
    route = {"chat_type": "c2c", "sender_id": "native-target", "group_code": "", "msg_id": "old"}
    assert (await platform.send_parts(route, [{"type": "text", "text": "after refresh"}], "direct", "fresh-delivery"))["business_accepted"] == "true"


async def test_typing_owns_native_route_and_stop_awaits_receive_refresh_and_keepalive(native_platform):
    platform, _, states, external = native_platform
    route = {"chat_type": "group", "sender_id": "native-speaker", "group_code": "native-group", "msg_id": "old"}
    receipt = await platform.start_typing("response-one", route)
    assert receipt.transport_written is True and receipt.business_accepted is None
    await eventually(lambda: any(f["head"]["cmd"] == codec.BIZ_CMD_GROUP_HB for f in external.frames))
    from yuanbao_native_support import decode
    heartbeat = next(f for f in external.frames if f["head"]["cmd"] == codec.BIZ_CMD_GROUP_HB)
    assert decode(codec.SEND_GROUP_HB_REQ, heartbeat["data"]) == {
        "fromAccount": "native-bot", "toAccount": "native-speaker", "groupCode": "native-group", "heartbeat": "HEARTBEAT_RUNNING",
    }
    typing = platform._typing_tasks["response-one"]
    refresh = platform._token_manager._refresh_task
    receive, heartbeat_task = platform._receive_task, platform._heartbeat_task
    await platform.stop_typing("response-one", route)
    assert typing.done() and platform._typing_tasks == {}
    await eventually(lambda: len([f for f in external.frames if f["head"]["cmd"] == codec.BIZ_CMD_GROUP_HB]) == 2)
    final = [f for f in external.frames if f["head"]["cmd"] == codec.BIZ_CMD_GROUP_HB][-1]
    assert decode(codec.SEND_GROUP_HB_REQ, final["data"])["heartbeat"] == "HEARTBEAT_FINISH"
    session, token_session = platform._session, platform._token_manager._session
    await platform.stop()
    assert all(t.done() for t in (refresh, receive, heartbeat_task, typing))
    assert session.closed and token_session.closed
    assert not platform._operations and not platform._tasks
    assert states[-1] == "disconnected" and platform._ws is None
