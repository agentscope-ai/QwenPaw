# -*- coding: utf-8 -*-
"""Exercise community integration through the real runtime and inbox API."""
import json

import pytest

from tests.integration.helpers import make_event, seed_inbox_events

pytestmark = [pytest.mark.integration, pytest.mark.p1]
APP_SERVER_EXTRA_ENV = {
    "QWENPAW_COMMUNITY_CLIENT_ID": "",
    "QWENPAW_COMMUNITY_SCOPES": "",
    "QWENPAW_COMMUNITY_MESSAGES_ENABLED": "false",
}


def test_community_server_pagination_scope_and_credentials(app_server):
    seed_inbox_events(
        app_server.working_dir,
        [make_event(event_id="local-cron", source_type="cron")],
    )
    directory = app_server.working_dir / "community"
    directory.mkdir(exist_ok=True)
    state = {
        "connection": {
            "account_id": "test-alice",
            "display_name": "Alice",
            "access_token": "fixture-never-sent",
            "sync_enabled": False,
        },
        "sync": {},
        "events": {},
    }
    for index in range(260):
        event_id = f"community:fixture-{index}"
        state["events"][event_id] = {
            "id": event_id,
            "agent_id": "",
            "source_type": "community",
            "source_id": f"reply:{index}",
            "event_type": "reply",
            "status": "info",
            "severity": "info",
            "title": "A reply",
            "body": "Reply body",
            "read": False,
            "created_at": 1000 + index,
            "payload": {
                "sender": {"name": "Bob"},
                "discussion_url": (
                    "https://platform.agentscope.io/community/articles/test"
                ),
            },
        }
    (directory / "state.json").write_text(json.dumps(state), encoding="utf-8")
    response = app_server.api_request(
        "GET",
        "/api/console/inbox/events",
        params={"source_type": "community", "offset": 250, "limit": 10},
    )
    assert response.status_code == 200, app_server.logs_tail()
    body = response.json()
    assert body["total"] == 260
    assert body["unread_count"] == 260
    assert len(body["events"]) == 10
    assert body["events"][0]["id"] == "community:fixture-9"
    assert "fixture-never-sent" not in response.text
    scoped = app_server.api_request(
        "POST",
        "/api/console/inbox/read",
        json={"all": True, "source_types": ["community"]},
    )
    assert scoped.status_code == 200
    assert scoped.json()["updated"] == 260
    local = app_server.api_request(
        "GET",
        "/api/console/inbox/events",
        params={"source_type": "cron"},
    ).json()
    assert local["unread_count"] == 1
    status = app_server.api_request("GET", "/api/community/connection")
    assert status.status_code == 200
    assert "fixture-never-sent" not in status.text
    deleted = app_server.api_request(
        "DELETE",
        "/api/console/inbox/events/community:fixture-0",
    )
    assert deleted.status_code == 200
    persisted = json.loads(
        (directory / "state.json").read_text(encoding="utf-8"),
    )
    assert persisted["events"]["community:fixture-0"] == {
        "id": "community:fixture-0",
        "deleted": True,
    }
