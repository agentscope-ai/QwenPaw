"""Slack native history, slash, ACL and media effects through the real
host."""

import asyncio
import json
from pathlib import Path

import pytest

from slack_suite import forbid_host_sdk
from slack_support import (
    callback_done,
    eventually,
    fault_runtime,
    finish,
    push,
    route,
    rows,
    runtime,
    send,
    set_mode,
    slack,
    slack_sdk,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mime,name,kind,locator",
    [
        ("image/png", "test.png", "image", "image_url"),
        ("audio/mpeg", "test.mp3", "audio", "data"),
        ("video/mp4", "test.mp4", "video", "video_url"),
        ("application/pdf", "doc.pdf", "file", "file_url"),
    ],
)
async def test_file_share_download_is_authorized_cached_and_reaches_real_agent(
    runtime, slack_sdk, mime, name, kind, locator
):
    rt = await slack(runtime, slack_sdk, proxy="http://proxy:8080")
    push(
        slack_sdk.work,
        subtype="file_share",
        text="shared a file",
        files=[
            {
                "mimetype": mime,
                "name": name,
                "url_private": "https://files.slack.com/" + name,
            }
        ],
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    contents = rt.ws.requests[0].input[0].content
    assert len(contents) >= 1
    assert len(contents) == 2
    assert contents[0].text == "shared a file"
    part = contents[1].model_dump(mode="json")
    assert part["type"] == kind
    path = Path(part[locator])
    assert path.is_relative_to(rt.ws.workspace_dir / "media")
    assert path.suffix == Path(name).suffix
    assert path.read_bytes() == b"file content"
    if kind == "audio":
        assert part["format"] == "mp3"
    request = rows(slack_sdk.work, "http-get")[0]
    assert request["headers"] == {"Authorization": "Bearer local-A"}
    assert request["proxy"] == "http://proxy:8080"
    assert request["timeout"] == 60


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,mode,downloads",
    [
        ("https://evil.example.com/file.png", "", 0),
        ("https://files.slack.com/file.png", "http-get-html", 1),
        ("https://files.slack.com/file.png", "http-get-503-once", 2),
    ],
)
async def test_download_domain_html_rejection_and_transient_retry(
    runtime, slack_sdk, url, mode, downloads
):
    rt = await slack(runtime, slack_sdk)
    set_mode(slack_sdk.work, mode)
    push(
        slack_sdk.work,
        files=[
            {"mimetype": "image/png", "name": "file.png", "url_private": url}
        ],
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    assert len(rows(slack_sdk.work, "http-get")) == downloads
    assert len(rt.ws.requests[0].input[0].content) == (
        2 if downloads == 2 else 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename,want", [(None, "file.pdf"), ("report.pdf", "report.pdf")]
)
async def test_data_url_upload_names_thread_proxy_and_cleanup(
    runtime, slack_sdk, filename, want
):
    rt = await slack(runtime, slack_sdk, proxy="http://proxy:8080")
    handle = await route(rt, "C123:1234567890.123456")
    part = {
        "type": "file",
        "file_url": "data:application/pdf;base64,cGRmLWRhdGE=",
    }
    if filename:
        part["filename"] = filename
    result = await send(rt, handle, parts=[part])
    assert result["state"] == "acknowledged"
    effects = [
        row
        for row in rows(slack_sdk.work)
        if row["kind"]
        in {
            "files.getUploadURLExternal",
            "http-post",
            "files.completeUploadExternal",
        }
    ]
    assert [row["kind"] for row in effects] == [
        "files.getUploadURLExternal",
        "http-post",
        "files.completeUploadExternal",
    ]
    assert effects[0]["arguments"]["filename"] == want
    assert effects[0]["arguments"]["length"] == 8
    assert effects[1]["bytes"] == list(b"pdf-data")
    assert effects[1]["proxy"] == "http://proxy:8080"
    complete = effects[2]["arguments"]
    assert complete["channel_id"] == "C123"
    assert complete["thread_ts"] == "1234567890.123456"
    files = (
        json.loads(complete["files"])
        if isinstance(complete["files"], str)
        else complete["files"]
    )
    assert files == [{"id": "F12345", "title": want}]
    assert list((rt.ws.workspace_dir / "media").iterdir()) == []


@pytest.mark.asyncio
async def test_local_file_upload_and_cross_workspace_path_rejection(
    runtime, slack_sdk, tmp_path
):
    rt = await slack(runtime, slack_sdk)
    path = rt.ws.workspace_dir / "report.pdf"
    path.write_bytes(b"authorized")
    await rt.channel.send_content_parts(
        "C123",
        [{"type": "file", "file_url": str(path), "filename": "report.pdf"}],
    )
    assert rows(slack_sdk.work, "http-post")[-1]["bytes"] == list(
        b"authorized"
    )
    foreign = tmp_path / "foreign.pdf"
    foreign.write_bytes(b"foreign")
    from qwenpaw.app.channels.isolated_proxy import ChannelDeliveryError

    with pytest.raises(ChannelDeliveryError) as caught:
        await rt.channel.send_content_parts(
            "C123", [{"type": "file", "file_url": str(foreign)}]
        )
    assert caught.value.reason_code == "MEDIA_PATH_OUTSIDE_WORKSPACE"
    assert len(rows(slack_sdk.work, "http-post")) == 1


@pytest.mark.asyncio
async def test_remote_url_native_sdk_auth_download_upload(runtime, slack_sdk):
    rt = await slack(runtime, slack_sdk, proxy="http://proxy:8080")
    await rt.channel.send_content_parts(
        "C123",
        [
            {
                "type": "image",
                "image_url": "https://files.slack.com/img.png",
                "filename": "img.png",
            }
        ],
    )
    assert rows(slack_sdk.work, "http-get")[-1]["headers"] == {
        "Authorization": "Bearer local-A"
    }
    assert rows(slack_sdk.work, "http-post")[-1]["bytes"] == list(
        b"file content"
    )
    assert (
        rows(slack_sdk.work, "files.completeUploadExternal")[-1]["arguments"][
            "channel_id"
        ]
        == "C123"
    )


@pytest.mark.asyncio
async def test_real_thread_history_exclusions_wrappers_cache_and_rich_unfurl(
    runtime, slack_sdk
):
    rt = await slack(runtime, slack_sdk)
    directory = slack_sdk.work / "local-A"
    (directory / "history.json").write_text(
        json.dumps(
            [
                {
                    "user": "U111",
                    "text": "previous message",
                    "ts": "1000000000.000000",
                },
                {
                    "user": "U999",
                    "bot_id": "B999",
                    "text": "own reply",
                    "ts": "1000000000.000003",
                },
                {"user": "U222", "text": " ", "ts": "1000000000.000002"},
                {
                    "user": "U456",
                    "text": "current excluded",
                    "ts": "1000000000.000001",
                },
            ]
        )
    )
    push(
        slack_sdk.work,
        callback="app_mention",
        channel="C123",
        thread_ts="1234567890.123456",
        text="follow up",
        attachments=[
            {
                "title": "Page",
                "title_link": "https://example.com",
                "text": "Description",
            }
        ],
    )
    await eventually(lambda: len(rt.ws.requests) == 1)
    text = rt.ws.requests[0].input[0].content[0].text
    assert "[Thread context]" in text and "[Latest message]" in text
    assert text == (
        "[Thread context]\nTesty: previous message\n\n[Latest "
        "message]\nfollow up\n\n📎 [Page](https://example.com)\n"
        "   Description"
    )
    history = rows(slack_sdk.work, "conversations.replies")[0]["arguments"]
    assert {
        key: value for key, value in history.items() if value is not None
    } == {
        "channel": "C123",
        "ts": "1234567890.123456",
        "inclusive": True,
        "limit": 30,
    }
    push(
        slack_sdk.work,
        ident=2,
        callback="app_mention",
        channel="C123",
        thread_ts="1234567890.123456",
        text="next",
    )
    await eventually(lambda: len(rt.ws.requests) == 2)
    assert len(rows(slack_sdk.work, "conversations.replies")) == 1
    assert len(rows(slack_sdk.work, "users.info")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel,text,want",
    [("C123", "something", "/custom something"), ("D123", "", "/custom")],
)
async def test_slash_ephemeral_ack_real_host_actor_route_and_empty_text(
    runtime, slack_sdk, channel, text, want
):
    rt = await slack(runtime, slack_sdk, require_mention=True)
    push(
        slack_sdk.work,
        callback="slash_commands",
        command="/custom",
        channel_id=channel,
        text=text,
    )
    await eventually(
        lambda: len(rt.ws.requests) == 1
        and bool(rows(slack_sdk.work, "platform-ack"))
    )
    ack = rows(slack_sdk.work, "platform-ack")[0]["payload"]
    assert ack["payload"] == {
        "response_type": "ephemeral",
        "text": "Running `/custom`…",
    }
    request = rt.ws.requests[0]
    assert request.input[0].content[0].text == want
    assert request.session_id == (
        "slack:dm:U456" if channel == "D123" else "slack:ch:C123"
    )
    assert request.user_id == "U456"
    assert request.channel_meta["user_name"] == "Human"
    assert request.channel_meta["slack_is_slash_command"] is True
    assert (
        request.channel_meta["slack_response_url"]
        == "https://hooks.slack.com/commands/local"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_real_acl_requires_actual_user_and_denial_targets_native_channel(
    runtime, slack_sdk, group
):
    rt = await slack(
        runtime,
        slack_sdk,
        access_control_dm=not group,
        access_control_group=group,
        deny_message="Denied",
    )
    from qwenpaw.app.channels.access_control import get_access_control_store

    store = get_access_control_store(rt.ws.workspace_dir)
    store.add_to_whitelist("slack", "U456")
    channel = "C123" if group else "D123"
    push(slack_sdk.work, channel=channel, text="<@U999> allowed", user="U456")
    await eventually(lambda: len(rt.ws.requests) == 1)
    push(
        slack_sdk.work,
        ident=2,
        channel=channel,
        text="<@U999> denied",
        user="U789",
    )
    await eventually(lambda: bool(store.get_all_pending()))
    await eventually(
        lambda: any(
            row["arguments"]["text"]
            == "您目前没有访问此智能体的权限，需要审批。\nID: U789"
            for row in rows(slack_sdk.work, "chat.postMessage")
        )
    )
    assert len(rt.ws.requests) == 1
    denial = [
        row
        for row in rows(slack_sdk.work, "chat.postMessage")
        if row["arguments"]["text"]
        == "您目前没有访问此智能体的权限，需要审批。\nID: U789"
    ][-1]
    assert denial["arguments"]["channel"] == channel
    assert store.get_all_pending()[0]["user_id"] == "U789"
