"""Cron 写操作应进入自动化对象级权限层。"""

from starlette.requests import Request

from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.app.agent_context import allowed_agent_roles_for_request


def test_cron_write_routes_allow_all_agent_roles_to_reach_object_guard():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/agents/shared/cron/jobs",
            "headers": [],
            "query_string": b"",
        }
    )

    assert allowed_agent_roles_for_request(request, "shared") == set(
        AgentResourceRole
    )
