# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-import
"""Authenticated Host HTTP → independent Engine process → Host task result."""

import pytest

from qwenpaw.pawapp.tasks.binding import ActionRegistration
from tests.integration.test_pawapp_data_tasks import (
    engine as engine_fixture,
    TOKEN,
    BRIDGE,
)
from tests.unit.pawapp.test_task_runtime import (
    host as host_fixture,
    settled,
    ACTION,
    BODY,
    PREFIX,
)

engine = engine_fixture
host = host_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "engagement,chat_id",
    [("direct", "direct"), ("delegated", "main")],
)
async def test_host_dispatch_to_engine_process(
    host,
    engine,
    engagement,
    chat_id,
):
    host.registrations[(ACTION.app_id, ACTION.action_id)] = ActionRegistration(
        action=ACTION,
        factory=lambda: BRIDGE.DataTaskAdapter(
            lambda: (engine.base, TOKEN),
            executor_id="integration-engine",
        ),
        settings_entry="/apps/qwenpaw-data",
    )
    body = {**BODY, "engagement": engagement, "chat_id": chat_id}
    response = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=body,
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["task"]["task_id"]
    result = await settled(host, task_id)
    assert result.handle.text_result == "Revenue is 42."
    again = await host.client.post(
        PREFIX + "/actions/analyze/tasks",
        json=body,
    )
    assert again.json()["task"]["task_id"] == task_id
