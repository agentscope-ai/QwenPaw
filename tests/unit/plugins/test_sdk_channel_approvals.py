# -*- coding: utf-8 -*-
"""Actual approval service and control queue, with a public-only child driver."""

import asyncio
import json

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
        self.sent = 0
        await ch.report_status("connected")
        ch.resources.task(self.listen(ch), "platform-callbacks")

    async def listen(self, ch):
        while True:
            action = await ch.storage.aread_json("action.json", None)
            if action:
                await ch.storage.adelete("action.json")
                ack = f"ack-{action['id']}.json"
                message = ChannelMessage(
                    "display",
                    (),
                    session_id=action["session"],
                    message_id=action["id"],
                    acl_sender_id=action["actor"],
                    is_group=True,
                    session_scope="group",
                    mentioned=False,
                )
                try:
                    result = await ch.approvals.resolve(
                        ChannelApprovalAction(
                            action["request_id"], action["decision"], message
                        )
                    )
                except Exception as exc:
                    await ch.storage.awrite_json(ack, {"error": repr(exc)})
                    raise
                await ch.storage.awrite_json(ack, {"status": result.status})
            await asyncio.sleep(0.01)

    async def send(self, ch, response):
        async with self.lock:
            self.sent += 1
            await ch.storage.awrite_json(
                f"sent-{self.sent:04d}.json",
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
        return ChannelSendResult(response.delivery_id)
"""


@pytest.mark.asyncio
async def test_platform_approval_action_is_scoped_and_bypasses_only_mention(
    tmp_path,
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

        def rows(workspace):
            return [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(stores[workspace].glob("sent-*.json"))
            ]

        async def create_request():
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
            await eventually(
                lambda: any(
                    row["card"]
                    and row["card"]["request_id"] == pending.request_id
                    for row in rows("one")
                ),
                timeout=10,
            )
            return pending

        async def action(
            request_id,
            label,
            *,
            decision="approve",
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
                        "request_id": request_id,
                        "decision": decision,
                    },
                ),
                encoding="utf-8",
            )
            temporary.replace(path)
            # Each action publishes one result, so the worker never replaces
            # a file that the test is concurrently reading on Windows.
            ack = stores[workspace] / f"ack-{label}.json"
            await eventually(ack.exists, timeout=10)
            result = json.loads(ack.read_text(encoding="utf-8"))
            assert "status" in result, (label, workspace, result)
            assert await workspaces[
                workspace
            ].channel_manager._queue_manager.drain()
            return result["status"]

        pending = await create_request()
        first_id = pending.request_id
        assert (
            await action(first_id, "blocked", actor="intruder") == "rejected"
        )
        assert not pending.future.done()
        for label, kwargs in (
            ("wrong-user", {"actor": "bob"}),
            ("wrong-workspace", {"workspace": "two"}),
            ("wrong-session", {"session": "other-room"}),
        ):
            assert await action(first_id, label, **kwargs) == "accepted"
            assert (
                not pending.future.done()
            ), "Admission must not bypass approval identity"
            assert (
                rows(kwargs.get("workspace", "one"))[-1]["resolution"][
                    "outcome"
                ]
                == "forbidden"
            )
        for decision, expected in (
            ("approve", ApprovalDecision.APPROVED),
            ("deny", ApprovalDecision.DENIED),
        ):
            if decision == "deny":
                pending = await create_request()
                assert pending.request_id != first_id
            request_id = pending.request_id
            assert (
                await action(
                    request_id,
                    f"valid-{decision}",
                    decision=decision,
                )
                == "accepted"
            )
            assert (
                await asyncio.wait_for(asyncio.shield(pending.future), 10)
                is expected
            )
            await eventually(
                lambda: any(
                    row["resolution"]
                    and row["resolution"]["request_id"] == request_id
                    and row["resolution"]["outcome"] == expected.value
                    and row["resolution"]["actor_user_id"] == "alice"
                    for row in rows("one")
                ),
                timeout=10,
            )
            assert (
                await action(
                    request_id,
                    f"replay-{decision}",
                    decision=decision,
                )
                == "accepted"
            )
            assert pending.future.result() is expected
            replay = rows("one")[-1]["resolution"]
            assert replay["request_id"] == request_id
            assert replay["outcome"] == "unavailable"
        assert (await host.uninstall(key)).clean
