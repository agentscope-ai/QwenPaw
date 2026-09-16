"""自动化工具调用必须落在长期授权快照内。"""

from types import SimpleNamespace

import pytest

from qwenpaw.governance.tool_adapter import (
    _automation_tool_allowed,
    _policy_tool_check_permissions,
)
from qwenpaw.governance.policy import ToolCallSpec
from qwenpaw.hooks.request_setup.contextvars_hook import (
    _trusted_automation_context,
)


def test_automation_tool_allows_only_exact_granted_capability():
    context = {
        "actor_type": "automation",
        "automation_authorization": {
            "schedule_id": "job-1",
            "config_version": 2,
            "authorization_digest": "a" * 64,
            "grants": [
                {"capability": "automation.execute"},
                {"capability": "tool:Read"},
            ],
        },
    }

    assert _automation_tool_allowed(context, "Read") is True
    assert _automation_tool_allowed(context, "Write") is False


def test_non_automation_context_does_not_apply_snapshot_filter():
    assert _automation_tool_allowed({}, "Write") is None
    assert _automation_tool_allowed({"actor_type": "user"}, "Write") is None


def test_request_setup_preserves_only_complete_automation_context():
    authorization = {
        "schedule_id": "job-1",
        "config_version": 2,
        "authorization_digest": "a" * 64,
        "grants": [{"capability": "tool:Read"}],
    }
    assert _trusted_automation_context(
        {"actor_type": "automation", "automation_authorization": authorization}
    ) == {"actor_type": "automation", "automation_authorization": authorization}
    assert _trusted_automation_context(
        {"actor_type": "automation", "automation_authorization": {}}
    ) == {}


def test_request_setup_preserves_restricted_heartbeat_automation_identity():
    assert _trusted_automation_context(
        {
            "actor_type": "automation",
            "automation_kind": "agent_automation",
            "authorized_by_user_id": "user-1",
        }
    ) == {
        "actor_type": "automation",
        "automation_kind": "agent_automation",
        "authorized_by_user_id": "user-1",
    }
    assert _automation_tool_allowed(
        {
            "actor_type": "automation",
            "automation_kind": "agent_automation",
        },
        "Read",
    ) is False


@pytest.mark.asyncio
async def test_automation_context_cannot_bypass_snapshot_with_off_level():
    class FakeTool:
        name = "Write"
        _qp_governor = SimpleNamespace(
            policy=SimpleNamespace(execution_level="off")
        )
        _qp_request_context = {
            "actor_type": "automation",
            "approval_level": "off",
            "automation_authorization": {
                "schedule_id": "job-1",
                "config_version": 1,
                "authorization_digest": "a" * 64,
                "grants": [{"capability": "tool:Read"}],
            },
        }

        def _build_tc_spec(self):
            return ToolCallSpec(
                tool_name=self.name,
                target="",
                agent_id="agent",
                session_id="session",
            )

    decision = await _policy_tool_check_permissions(FakeTool(), {})

    assert decision.behavior.value == "deny"
    assert "automation grant" in decision.message
