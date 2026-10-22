# -*- coding: utf-8 -*-
"""Authenticated UI decisions and agent answers have different authority."""
# pylint: disable=redefined-outer-name
import pytest

from qwenpaw.pawapp.tasks import ExecutorEvent, ExecutorRunRef
from tests.unit.pawapp.test_approvals import PROPOSAL, decision
from tests.unit.pawapp.test_task_agent_tools import payload, tools
from tests.unit.pawapp.test_task_runtime import (
    host as host_fixture,
    ACTION,
    SCOPE,
    BODY,
    PREFIX,
)

host = host_fixture


@pytest.mark.asyncio
async def test_approval_route_derives_actor_and_rejects_agent_answers(host):
    origin = await host.app.state.pawapp_task_origins.resolve(
        SCOPE,
        "delegated",
        "main",
    )
    task = await host.store.create(
        SCOPE,
        ACTION,
        request_id="approval-route",
        inputs=BODY["inputs"],
        origin=origin,
    )
    task_id = task.handle.task_id
    await host.store.begin_submission(SCOPE, task_id)
    ref = ExecutorRunRef(
        executor_id="engine",
        session_id="approval",
        run_id="approval",
    )
    host.runs[task.handle.submission_id] = ref
    await host.store.record_accepted(SCOPE, task_id, ref)
    await host.store.apply_event(
        SCOPE,
        task_id,
        ExecutorEvent(
            run_ref=ref,
            sequence=0,
            cursor="approval",
            status="waiting_for_approval",
            approval_request=PROPOSAL,
        ),
    )
    host.adapters[0].release.clear()
    bound = tools(host)
    assert "decide_task" not in bound
    answer = payload(
        await bound["answer_task"](
            app_id=SCOPE.app_id,
            task_id=task_id,
            request_id=PROPOSAL.request_id,
            command_id="agent",
            answers=[],
        ),
    )
    assert answer["reason"] == "human_approval_required"
    body = {
        "command_id": "user",
        "decision": decision().model_dump(mode="json"),
    }
    url = PREFIX + f"/tasks/{task_id}/decide"
    forged = await host.client.post(
        url,
        json={**body, "actor": {"principal_id": "bob"}},
    )
    assert forged.status_code == 422
    unauthorized = await host.client.post(
        url,
        json=body,
        headers={"Authorization": "Bearer bob-token"},
    )
    assert unauthorized.status_code == 404
    result = await host.client.post(url, json=body)
    assert result.status_code == 200
    command = result.json()["command"]
    assert command["state"] == "accepted"
    assert command["payload"]["actor"]["principal_id"] == "alice"
    replay = await host.client.post(url, json=body)
    assert replay.json() == result.json()
    refreshed = await host.client.get(PREFIX + f"/tasks/{task_id}")
    assert refreshed.json()["task"]["approval_receipt"]["command_id"] == "user"
