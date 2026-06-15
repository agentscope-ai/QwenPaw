# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Any

from qwenpaw.app.approvals.serialize import pending_approval_to_console_dict
from qwenpaw.app.approvals.service import PendingApproval
from qwenpaw.security.tool_guard.approval import ApprovalDecision


def test_pending_approval_to_console_dict_includes_file_baseline_write() -> None:
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    future.set_result(ApprovalDecision.APPROVED)

    pending = PendingApproval(
        request_id="req-1",
        session_id="sess-1",
        root_session_id="root-1",
        owner_agent_id="default",
        user_id="user-1",
        channel="console",
        agent_id="default",
        tool_name="write_file",
        created_at=1.0,
        future=future,
        extra={
            "file_baseline_write": {
                "relative_path": "SOUL.md",
                "proposed_content": "new soul",
                "current_content": "old soul",
            },
        },
    )

    payload: dict[str, Any] = pending_approval_to_console_dict(pending)
    assert payload["request_id"] == "req-1"
    assert payload["approval_kind"] == "file_baseline_write"
    assert payload["file_baseline_write"]["relative_path"] == "SOUL.md"
    assert payload["file_baseline_write"]["proposed_content"] == "new soul"
    assert payload["tool_params"]["proposed_content"] == "new soul"
    assert payload["tool_params"]["file_path"] == "SOUL.md"
