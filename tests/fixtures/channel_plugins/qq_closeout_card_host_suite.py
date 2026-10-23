"""QQ authenticated native callback through actual Core approval authority."""

import json

import pytest

from extension_process_suite import eventually, identity
from qq_closeout_formal_support import (
    external,
    official_qq_zip,
    qq_host_import_guard,
    runtime,
)
from real_host_runtime import bind_real_runtime

__all__ = ["external", "qq_host_import_guard", "runtime"]


@pytest.mark.asyncio
async def test_native_card_ack_actor_binding_and_actual_core_decision(
    runtime, external, monkeypatch
):
    from qwenpaw.app.approvals import service
    from qwenpaw.app.approvals.models import ApprovalRequestSummary
    from qwenpaw.app.approvals.service import ApprovalIdentityPolicy

    approvals = service.ApprovalService()
    monkeypatch.setattr(service, "_approval_service", approvals)
    rt = await runtime(
        "qq",
        source_factory=official_qq_zip,
        app_id="card-app",
        client_secret="card-secret",
    )
    host = await bind_real_runtime(rt, monkeypatch)
    from qwenpaw.runtime.builtin_commands import collect_builtin_command_specs

    for spec in collect_builtin_command_specs():
        rt.ws.plugins.slash_command_registry.register(spec)
    await rt.channel._wait_connected()
    record = await approvals.create_pending_summary(
        session_id="qq:group:group-A",
        root_session_id="qq:group:group-A",
        user_id="requesting-actor",
        channel="qq",
        agent_id=rt.ws.agent_id,
        owner_agent_id=rt.ws.agent_id,
        identity_policy=ApprovalIdentityPolicy("exact_requester"),
        summary=ApprovalRequestSummary(source_type="test", name="shell"),
    )
    handle = (
        await rt.process.call(
            "channel.response.open",
            {
                **identity(rt),
                "to_handle": "qq:group:group-A",
                "meta": {
                    "session_id": "qq:group:group-A",
                    "root_session_id": "qq:group:group-A",
                    "user_id": "requesting-actor",
                    "sender_id": "requesting-actor",
                    "message_id": "original-request",
                },
            },
        )
    )["response_handle"]
    path = "/v2/groups/group-A/messages"
    native_id = "native-card-source"
    external.queue("POST", path, (200, {"id": native_id}))
    result = await rt.process.call(
        "channel.send",
        {
            **identity(rt),
            "to_handle": handle,
            "delivery_id": "authentic-card-source",
            "operation": "message.create",
            "content_source": "content_parts",
            "content_parts": [{"type": "text", "text": "approve this?"}],
            "approval": {
                "request_id": record.request_id,
                "tool_name": "shell",
                "severity": "high",
            },
        },
    )
    assert result["state"] == "acknowledged"
    await rt.process.call(
        "channel.response.finish",
        {**identity(rt), "response_handle": handle, "outcome": "completed"},
    )
    card = external.rows(path)[0]["body"]
    buttons = card["keyboard"]["content"]["rows"][0]["buttons"]
    assert [b["render_data"]["visited_label"] for b in buttons] == [
        "Received",
        "Received",
    ]
    button_data = json.loads(buttons[0]["action"]["data"])
    assert button_data["rid"] == record.request_id and button_data["bid"]
    # Untrusted payload identity/tool/session never becomes host authority.
    button_data.update(sender="requesting-actor", sid="forged", tool="forged")
    acks = []

    def ack(row):
        acks.append((row["body"], record.future.done()))
        return 200, {}

    def click(mid, actor, seq):
        external.queue("PUT", "/interactions/" + mid, ack)
        external.push(
            {
                "op": 0,
                "s": seq,
                "t": "INTERACTION_CREATE",
                "d": {
                    "id": mid,
                    "group_member_openid": actor,
                    "group_openid": "group-A",
                    "message_id": native_id,
                    "data": {
                        "resolved": {"button_data": json.dumps(button_data)}
                    },
                },
            }
        )

    click("wrong-actor", "other-actor", 2)
    await eventually(lambda: len(external.rows(path)) == 2)
    assert await rt.ws.task_tracker.wait_all_done(timeout=8)
    assert not record.future.done()
    assert await approvals.get_request(record.request_id) is record
    assert rt.ws.requests[-1].user_id == "other-actor"
    assert rt.ws.requests[-1].session_id == "qq:group:group-A"
    denied = external.rows(path)[-1]["body"]["markdown"]["content"]
    assert "权限不足" in denied and "Approved" not in denied
    assert acks == [({"code": 0}, False)]
    click("valid-actor", "requesting-actor", 3)
    await eventually(
        lambda: record.future.done() and len(external.rows(path)) == 3
    )
    assert await rt.ws.task_tracker.wait_all_done(timeout=8)
    assert record.future.result().value == "approved"
    assert await approvals.get_request(record.request_id) is None
    assert rt.ws.requests[-1].user_id == "requesting-actor"
    assert rt.ws.requests[-1].root_session_id == "qq:group:group-A"
    assert acks == [({"code": 0}, False), ({"code": 0}, False)]
    assert external.rows(path)[-1]["body"]["markdown"]["content"] == (
        "✅ **Approved** by **-actor**\nTool: `shell`"
    )
    assert external.rows(path)[-1]["body"]["msg_id"] == "original-request"
    assert len(rt.ws.requests) == 2 and host.calls == host.builds == []
    click("duplicate", "requesting-actor", 4)
    await eventually(lambda: len(acks) == 3)
    assert acks[-1] == ({"code": 3}, True)
    assert len(external.rows(path)) == 3 and len(rt.ws.requests) == 2
    receipt = await rt.manager.stop_one("qq")
    assert receipt.stopped and receipt.exited and not receipt.residual
    assert not rt.loader.registry.runtime_owners.leases("qq")
