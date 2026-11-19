import httpx
import pytest

from qwenpaw.agents.tools import agent_management as tools
from qwenpaw.app import agent_context


@pytest.mark.asyncio
@pytest.mark.parametrize("successful", [0, 1, 2])
async def test_batch_matches_actual_dispatches(monkeypatch, successful):
    monkeypatch.setattr(agent_context, "get_current_agent_id", lambda: "test")

    async def dispatch(payload, *args, **kwargs):
        index = int(payload["input"][0]["content"][0]["text"])
        if index < successful:
            return {"task_id": f"task-{index}"}
        response = httpx.Response(401, request=httpx.Request("POST", "http://test"))
        response.raise_for_status()

    monkeypatch.setattr(tools, "_dispatch_subtask", dispatch)
    result = await tools.spawn_subagent(task="", batch=[{"task": "0"}, {"task": "1"}])
    assert result.state.value == ("success" if successful == 2 else "error")
    assert result.content[0].text.count("[TASK_ID:") == successful
    assert result.content[0].text.count("ERROR:") == 2 - successful
