# -*- coding: utf-8 -*-
"""All existing approval state transitions reach isolated SDK observers."""

# Inspect host ownership and cleanup state at the tested bridge boundary.
# pylint: disable=protected-access

import asyncio
import time

import pytest

from .sdk_author_fixture import make_plugin

from .timing import WAIT_TIMEOUT

SOURCE = """
from dataclasses import FrozenInstanceError
from qwenpaw.plugins.events import EventSubscription


class Plugin:
    def register(self, ctx):
        async def observe(call, event):
            try:
                event.approval.name = "changed"
            except FrozenInstanceError:
                pass
            else:
                raise AssertionError("approval snapshot is mutable")
            trace = ctx.storage.read_json("approvals.json", [])
            trace.append(
                [
                    event.approval.request_id,
                    event.kind,
                    event.approval.name,
                ]
            )
            ctx.storage.write_json("approvals.json", trace)
            if ctx.config.get("raise"):
                raise RuntimeError("approval observer failure")

        ctx.on_activate(
            lambda active: active.subscribe_events(
                EventSubscription(observe)
            )
        )


plugin = Plugin()
"""


@pytest.mark.parametrize("observer_raises", [False, True])
async def test_approval_resolve_supersede_cancel_and_gc_results(
    tmp_path,
    observer_raises,
):
    from qwenpaw.plugins.testing import PluginTestHost
    from qwenpaw.app.approvals.service import (
        ApprovalService,
        _GC_PENDING_MAX_AGE_SECONDS,
    )
    from qwenpaw.app.approvals.models import ApprovalRequestSummary
    from qwenpaw.security.tool_guard.approval import ApprovalDecision
    from qwenpaw.security.tool_guard.models import ToolGuardResult

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, SOURCE, ["events", "config", "storage"]),
            config={"raise": observer_raises},
        )
        service = ApprovalService()
        identity = {
            "session_id": "chat",
            "root_session_id": "root",
            "owner_agent_id": "one",
            "user_id": "test-user",
            "channel": "console",
            "agent_id": "one",
        }
        direct = await service.create_pending(
            **identity,
            tool_name="tool-probe",
            result=ToolGuardResult(
                tool_name="tool-probe",
                params={},
                findings=[],
            ),
        )
        resolved = await service.resolve_request(
            direct.request_id,
            ApprovalDecision.APPROVED,
        )
        assert (
            resolved.status == "approved"
            and await direct.future == ApprovalDecision.APPROVED
        )
        summary = ApprovalRequestSummary("sdk-test", "summary-probe")
        stale = await service.create_pending_summary(
            **identity,
            summary=summary,
            extra={"tool_call": {"id": "call-stale"}},
        )
        assert (
            await service.cancel_stale_pending_for_tool_call(
                "chat",
                "call-stale",
            )
            == 1
        )
        assert await stale.future == ApprovalDecision.TIMEOUT
        cancelled = await service.create_pending_summary(
            **identity,
            summary=summary,
        )
        assert await service.cancel_all_pending_by_root_session("root") == 1
        assert await cancelled.future == ApprovalDecision.DENIED
        expired = await service.create_pending_summary(
            **identity,
            summary=summary,
        )
        expired.created_at = time.time() - _GC_PENDING_MAX_AGE_SECONDS - 1
        async with service._lock:
            service._gc_pending_locked()
        assert await expired.future == ApprovalDecision.TIMEOUT
        expected = {
            direct.request_id: "approval.approved",
            stale.request_id: "approval.superseded",
            cancelled.request_id: "approval.cancelled",
            expired.request_id: "approval.timeout",
        }
        async with asyncio.timeout(WAIT_TIMEOUT):
            while True:
                observed = ctx.storage.read_json("approvals.json", [])
                if len(observed) >= 8:
                    break
                await asyncio.sleep(0.01)
        for request_id, terminal in expected.items():
            rows = [row for row in observed if row[0] == request_id]
            assert [row[1] for row in rows] == ["approval.pending", terminal]
        assert direct.tool_name == "tool-probe"
