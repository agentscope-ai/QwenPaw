# -*- coding: utf-8 -*-
"""Real shadow Git, saved sessions and host-owned exact-user approval."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from qwenpaw.plugins.testing import PluginTestHost
from .sdk_checkpoint_fixture import make_checkpoint_plugin
from .sdk_author_fixture import make_plugin
from qwenpaw.plugins.channels import ChannelMessage
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.checkpoints import CheckpointError
from qwenpaw.plugins.compliance import check_plugin
from qwenpaw.checkpoints.policy import session_file_path
from .timing import WAIT_TIMEOUT


async def pending(host):
    async with asyncio.timeout(WAIT_TIMEOUT):
        while not (requests := await host.approval_requests("conversation")):
            await asyncio.sleep(0.01)
        return requests[0]


async def test_channel_restore_sends_approval_to_original_route(tmp_path):
    channel_name = "checkpoint-notify"
    transport = make_plugin(
        tmp_path,
        """
from qwenpaw.plugins.channels import ChannelSpec
class Transport:
    async def start(self, call): pass
    async def stop(self, call): return True
    async def send(self, call, message): pass
class Plugin:
    def register(self, ctx):
        ctx.register_channel(ChannelSpec(
            'checkpoint-notify', 'Checkpoint notifications', Transport))
plugin = Plugin()
""",
        ["channels"],
    )
    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(make_checkpoint_plugin(tmp_path))).ok
        await host.load(transport)
        await host.start_channel(channel_name, workspace_id="one")
        workspace = await host._workspace("one")
        path = session_file_path(
            workspace.workspace_dir,
            session_id="conversation",
            user_id="alice",
            channel=channel_name,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        original = json.dumps(
            {
                "agent": {
                    "state": {
                        "context": [
                            {"role": "user", "content": "before"},
                        ],
                    },
                },
            },
        )
        path.write_text(original)
        saved = await host.call_control_command(
            "/contract-checkpoint snapshot first",
            workspace_id="one",
            session_id="conversation",
            user_id="alice",
            channel=channel_name,
        )
        target = json.loads(saved.content[0].text)["id"]
        path.write_text(original.replace("before", "after"))
        channel = await workspace.channel_manager.get_channel(channel_name)
        notify = AsyncMock(wraps=channel.send_approval_notification)
        channel.send_approval_notification = notify
        sent = AsyncMock(wraps=channel._backend.send)
        channel._backend.send = sent
        approval = None
        try:
            await host.receive_channel(
                channel_name,
                ChannelMessage(
                    "alice",
                    (
                        ContentBlock(
                            text=f"/contract-checkpoint restore {target}",
                        ),
                    ),
                    session_id="conversation",
                    message_id="restore-42",
                    metadata={"route": "original", "thread_id": "thread-7"},
                ),
                workspace_id="one",
            )
            approval = await pending(host)
            async with asyncio.timeout(3):
                while not sent.await_count:
                    await asyncio.sleep(0.01)
            assert notify.await_count == 1
            values = notify.await_args.kwargs
            assert {
                key: values[key]
                for key in (
                    "session_id",
                    "user_id",
                    "request_id",
                )
            } == {
                "session_id": "conversation",
                "user_id": "alice",
                "request_id": approval.request_id,
            }
            assert {
                key: values["channel_meta"][key]
                for key in (
                    "route",
                    "thread_id",
                )
            } == {"route": "original", "thread_id": "thread-7"}
            message = sent.await_args.args[1]
            assert {
                key: message.metadata[key]
                for key in (
                    "route",
                    "thread_id",
                )
            } == {"route": "original", "thread_id": "thread-7"}
            assert "after" in path.read_text()
            assert await host.resolve_approval(
                approval.request_id,
                approved=True,
            )
            async with asyncio.timeout(WAIT_TIMEOUT):
                while path.read_text() != original:
                    await asyncio.sleep(0.01)
        finally:
            if approval is not None:
                await host.resolve_approval(
                    approval.request_id,
                    approved=False,
                )
            await host.stop_channel(channel_name, workspace_id="one")


async def test_snapshot_timeline_approval_denial_cancel_and_restore(tmp_path):
    source = make_checkpoint_plugin(tmp_path)
    assert check_plugin(source).ok
    async with PluginTestHost(tmp_path / "host") as host:
        assert (await host.install(source)).ok
        workspace = await host._workspace("one")
        path = session_file_path(
            workspace.workspace_dir,
            session_id="conversation",
            user_id="alice",
            channel="console",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        original = json.dumps(
            {
                "agent": {
                    "state": {
                        "context": [{"role": "user", "content": "before"}],
                    },
                },
            },
        )
        path.write_text(original)

        async def command(args, user="alice", workspace_id="one"):
            result = await host.call_control_command(
                "/contract-checkpoint " + args,
                session_id="conversation",
                workspace_id=workspace_id,
                user_id=user,
            )
            return json.loads(result.content[0].text)

        saved = await command("snapshot first")
        chat = await workspace.chat_manager.get_or_create_chat(
            "conversation",
            "alice",
            "console",
        )

        async def request(path, user="alice", method="GET", payload=None):
            return await host.request(
                method,
                "/api/checkpoint-contract/checkpoints/" + path,
                workspace_id="one",
                user_id=user,
                headers={"X-Chat-Id": chat.id},
                json=payload,
            )

        assert (await request("timeline")).json()[0]["id"] == saved["id"]
        assert (await request("timeline", user="bob")).status == 403
        assert (
            await request(
                "restore/preview",
                method="POST",
                payload={"target": saved["id"], "user_id": "alice"},
            )
        ).status == 422
        assert (
            await request(
                "restore/preview",
                method="POST",
                payload={"target": saved["id"]},
            )
        ).json()["dry_run"]
        timeline = await command("timeline")
        assert (
            timeline[0]["id"] == saved["id"] and timeline[0]["name"] == "first"
        )
        assert await command("timeline", user="bob") == []
        assert await command("timeline", workspace_id="two") == []
        path.write_text(original.replace("before", "after"))
        preview = await command("preview " + saved["id"])
        assert preview["dry_run"] and preview["restored_paths"]
        assert "after" in path.read_text()
        with pytest.raises(CheckpointError, match="Unknown restore target"):
            await command("preview " + saved["id"], user="bob")
        denied = asyncio.create_task(command("restore " + saved["id"]))
        approval = await pending(host)
        assert "after" in path.read_text()
        assert await host.resolve_approval(approval.request_id, approved=False)
        with pytest.raises(CheckpointError, match="not confirmed"):
            await denied
        cancelled = asyncio.create_task(command("restore " + saved["id"]))
        await pending(host)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert not await host.approval_requests("conversation")
        assert "after" in path.read_text()
        disconnected = host.open_http(
            "POST",
            "/api/checkpoint-contract/checkpoints/restore",
            workspace_id="one",
            user_id="alice",
            headers={"X-Chat-Id": chat.id},
            json={"target": saved["id"]},
        )
        opening = asyncio.create_task(disconnected.__aenter__())
        await pending(host)
        # Only deliver the ASGI event: do not let TestConnection.close cancel
        # the request task on behalf of the real server.
        await disconnected._incoming.put({"type": "http.disconnect"})
        async with asyncio.timeout(WAIT_TIMEOUT):
            stream = await opening
            assert stream.status == 499
            async for _ in stream.chunks():
                pass
            await disconnected.close()
        assert not await host.approval_requests("conversation")
        assert "after" in path.read_text()
        applying = asyncio.create_task(command("restore " + saved["id"]))
        approval = await pending(host)
        from qwenpaw.app.approvals import get_approval_service
        from qwenpaw.app.approvals.service import (
            ApprovalActor,
            ApprovalIdentityMismatchError,
        )
        from qwenpaw.security.tool_guard.approval import ApprovalDecision

        with pytest.raises(ApprovalIdentityMismatchError):
            await get_approval_service().resolve_request(
                approval.request_id,
                ApprovalDecision.APPROVED,
                actor=ApprovalActor(
                    "conversation",
                    "conversation",
                    "bob",
                    "console",
                    "one",
                ),
            )
        assert "after" in path.read_text()
        assert await host.resolve_approval(approval.request_id, approved=True)
        restored = await applying
        assert not restored["dry_run"]
        assert path.read_text() == original
        assert any(
            item["kind"] == "pre-restore" for item in await command("timeline")
        )
        path.write_text(original.replace("before", "again"))
        applied_http = asyncio.create_task(
            request("restore", method="POST", payload={"target": saved["id"]}),
        )
        approval = await pending(host)
        assert "again" in path.read_text()
        assert await host.resolve_approval(approval.request_id, approved=True)
        assert (await applied_http).status == 200
        assert path.read_text() == original
        path.write_text(original.replace("before", "must remain"))
        changing = asyncio.create_task(
            request(
                "restore",
                method="POST",
                payload={"target": saved["id"], "include_memory": True},
            ),
        )
        approval = await pending(host)
        added = (
            workspace.workspace_dir / "memory" / "added-while-confirming.md"
        )
        added.parent.mkdir(exist_ok=True)
        added.write_text("new memory must not be deleted without preview")
        assert await host.resolve_approval(approval.request_id, approved=True)
        changed = await changing
        assert changed.status == 400 and "impact changed" in changed.text
        assert "must remain" in path.read_text() and added.exists()
        assert (await host.update_config("checkpoint-contract", {})).ok
        assert (await host.reload("checkpoint-contract")).ok
        assert (await request("timeline")).status == 200
        assert (await host.set_enabled("checkpoint-contract", False)).ok
        assert (await request("timeline")).status == 404
        assert (await host.set_enabled("checkpoint-contract", True)).ok
        assert (await request("timeline")).status == 200
        assert (await host.uninstall("checkpoint-contract")).clean
