import httpx
import pytest
from types import SimpleNamespace

from qwenpaw.agents.tools import agent_management as tools
from qwenpaw.app import agent_context
from qwenpaw.runtime.builder import AgentBuilder


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_subtask_qualified_tool_names_select_only_requested_tools(monkeypatch, batch):
    names = ["load_skill", "read_file", "execute_shell_command", "view_image"]
    requested = ["functions." + name for name in names] + ["other.write_file", "functions.extra.write_file"]
    monkeypatch.setattr(agent_context, "get_current_agent_id", lambda: "ppt")

    async def dispatch(payload, agent_id, timeout, *, background):
        rc = payload["request_context"]
        assert rc["subagent_skills"] == ["imagegen"]
        available = [SimpleNamespace(name=n) for n in [*names, "write_file"]]
        assert [t.name for t in AgentBuilder.apply_subagent_tool_whitelist(available, rc)] == names
        assert background is batch
        return {"task_id": "task-test"} if background else {"status": "completed"}

    monkeypatch.setattr(tools, "_dispatch_subtask", dispatch)
    spec = {"task": "generate slide 1", "fork": False, "allowed_tools": requested, "skills": ["imagegen"]}
    result = await tools.spawn_subagent(task="", batch=[spec]) if batch else await tools.spawn_subagent(**spec)
    assert result.state.value == "success"


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
