# -*- coding: utf-8 -*-
"""Actual approval service and control queue, with a public-only child driver."""

import asyncio
import json
from pathlib import Path

import pytest

from qwenpaw.plugins.channel_workers import ChannelDefinition
from qwenpaw.plugins.testing import PluginTestHost
from tests.channel_support.sdk import make_channel, workspace_store
from tests.channel_support.process import eventually

SOURCE = """
import asyncio
from dataclasses import asdict
from qwenpaw.plugins.channel_workers import (
    ChannelDriver,
    ChannelApprovalAction,
    ChannelSendResult,
)
from qwenpaw.plugins.channels import ChannelMessage


class Driver(ChannelDriver):
    async def start(self, ch):
        self.lock = asyncio.Lock()
        await ch.report_status("connected")
        ch.resources.task(self.listen(ch), "platform-callbacks")

    async def listen(self, ch):
        seen = None
        while True:
            action = await ch.storage.aread_json("action.json", None)
            if action and action["id"] != seen:
                seen = action["id"]
                message = ChannelMessage(
                    "display",
                    (),
                    session_id=action["session"],
                    message_id=seen,
                    acl_sender_id=action["actor"],
                    is_group=True,
                    session_scope="group",
                    mentioned=False,
                )
                result = await ch.approvals.resolve(
                    ChannelApprovalAction(
                        action["request_id"], action["decision"], message
                    )
                )
                await ch.storage.awrite_json(
                    "ack.json", {"id": seen, "status": result.status}
                )
            await asyncio.sleep(0.01)

    async def send(self, ch, response):
        async with self.lock:
            sent = await ch.storage.aread_json("sent.json", [])
            sent.append(
                {
                    "card": (
                        asdict(response.approval)
                        if response.approval
                        else None
                    ),
                    "resolution": (
                        asdict(response.approval_resolution)
                        if response.approval_resolution
                        else None
                    ),
                }
            )
            await ch.storage.awrite_json("sent.json", sent)
        return ChannelSendResult(response.delivery_id)
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["approve", "deny"])
async def test_platform_approval_action_is_scoped_and_bypasses_only_mention(
    tmp_path,
    decision,
):
    from qwenpaw.app.approvals import service
    from qwenpaw.app.approvals.models import ApprovalRequestSummary
    from qwenpaw.app.approvals.service import ApprovalIdentityPolicy
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    key = "sdk-approvals"
    source = tmp_path / "source"
    definition = ChannelDefinition(
        key,
        {"en": "Approvals", "zh": "审批"},
        "driver:Driver",
        {"type": "object", "properties": {}},
        (),
        ("channel.generic.v1", "send.approval_resolution.v1"),
    )
    make_channel(
        source,
        SOURCE,
        definition,
        capabilities=["channels", "resources", "storage"],
    )
    async with PluginTestHost(
        tmp_path / "host",
        process_channels=(key,),
    ) as host:
        approvals = service.get_approval_service()
        assert (await host.install(source)).ok
        workspaces, stores = {}, {}
        for name in ("one", "two"):
            await host.set_channel_access(
                key,
                "alice",
                True,
                workspace_id=name,
            )
            await host.set_channel_access(key, "bob", True, workspace_id=name)
            await host.set_channel_access(
                key,
                "intruder",
                False,
                workspace_id=name,
            )
            await host.start_channel(
                key,
                {"require_mention": True, "access_control_group": True},
                workspace_id=name,
            )
            workspace = await host._workspace(name)
            workspaces[name] = workspace
            stores[name] = workspace_store(host.root, key, name)
        channel = await workspaces["one"].channel_manager.get_channel(key)
        pending = await approvals.create_pending_summary(
            session_id="room",
            root_session_id="room",
            owner_agent_id="one",
            user_id="alice",
            channel=key,
            agent_id="one",
            summary=ApprovalRequestSummary("test", "test-effect"),
            extra={"_channel_instance": channel},
            identity_policy=ApprovalIdentityPolicy.EXACT_REQUESTER,
        )

        def rows(workspace):
            path = stores[workspace] / "sent.json"
            return json.loads(path.read_text()) if path.exists() else []

        await eventually(
            lambda: any(row["card"] for row in rows("one")),
            timeout=10,
        )
        assert (
            next(row["card"] for row in rows("one") if row["card"])[
                "request_id"
            ]
            == pending.request_id
        )

        async def action(
            label,
            workspace="one",
            actor="alice",
            session="room",
        ):
            path = stores[workspace] / "action.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".new")
            temporary.write_text(
                json.dumps(
                    {
                        "id": label,
                        "actor": actor,
                        "session": session,
                        "request_id": pending.request_id,
                        "decision": decision,
                    },
                ),
            )
            temporary.replace(path)
            ack = stores[workspace] / "ack.json"
            await eventually(
                lambda: ack.exists()
                and json.loads(ack.read_text())["id"] == label,
                timeout=10,
            )
            assert await workspaces[
                workspace
            ].channel_manager._queue_manager.drain()
            return json.loads(ack.read_text())["status"]

        assert await action("blocked", actor="intruder") == "rejected"
        assert not pending.future.done()
        for label, kwargs in (
            ("wrong-user", {"actor": "bob"}),
            ("wrong-workspace", {"workspace": "two"}),
            ("wrong-session", {"session": "other-room"}),
        ):
            assert await action(label, **kwargs) == "accepted"
            assert (
                not pending.future.done()
            ), "Admission must not bypass approval identity"
            assert (
                rows(kwargs.get("workspace", "one"))[-1]["resolution"][
                    "outcome"
                ]
                == "forbidden"
            )
        assert await action("valid") == "accepted"
        expected = (
            ApprovalDecision.APPROVED
            if decision == "approve"
            else ApprovalDecision.DENIED
        )
        outcome = "approved" if decision == "approve" else "denied"
        assert (
            await asyncio.wait_for(asyncio.shield(pending.future), 10)
            is expected
        )
        await eventually(
            lambda: any(
                row["resolution"] and row["resolution"]["outcome"] == outcome
                for row in rows("one")
            ),
            timeout=10,
        )
        resolved = next(
            row["resolution"]
            for row in rows("one")
            if row["resolution"] and row["resolution"]["outcome"] == outcome
        )
        assert resolved["actor_user_id"] == "alice"
        assert await action("replay") == "accepted"
        assert pending.future.result() is expected
        assert rows("one")[-1]["resolution"]["outcome"] == "unavailable"
        assert (await host.uninstall(key)).clean
