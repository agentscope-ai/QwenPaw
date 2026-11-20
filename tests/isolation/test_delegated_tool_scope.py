"""同一工作区的并发请求各自保留用户身份、资源策略与技能范围。"""

import asyncio
from types import SimpleNamespace

import pytest
from agentscope.exception import ToolNotFoundError
from agentscope.tool import FunctionTool, Toolkit

from qwenpaw.agents.tools.load_skill import load_skill
from qwenpaw.app.workspace.local_workspace import QwenPawLocalWorkspace
from qwenpaw.config.context import current_request_context, current_workspace_dir
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.tool_registry import ToolDescriptor, ToolRegistry


async def ordinary_tool():
    """Ordinary tool."""


async def optional_tool():
    """Opt-in tool."""


@pytest.mark.asyncio
async def test_two_members_share_workspace_but_never_share_tool_policy(tmp_path):
    registry = ToolRegistry()
    registry.register(ToolDescriptor("ordinary_tool", ordinary_tool))
    registry.register(ToolDescriptor("optional_tool", optional_tool, enabled_by_default=False))
    first_entered, second_entered = asyncio.Event(), asyncio.Event()

    class ConcurrentWorkspace(QwenPawLocalWorkspace):
        async def list_tools(self, **kwargs):
            if kwargs["request_context"]["user_id"] == "member-a":
                first_entered.set()
                await second_entered.wait()
            else:
                await first_entered.wait()
                second_entered.set()
            return await super().list_tools(**kwargs)

    ws = ConcurrentWorkspace(registry, workdir=str(tmp_path))
    ctx = SimpleNamespace(workspace=SimpleNamespace(local_workspace=ws))
    builder = AgentBuilder()

    async def build_for(member):
        policy = object()
        toolkit = await builder.build_toolkit(
            None, ctx=ctx, governor=policy,
            request_context={"user_id": member, "subagent_allowed_tools": ["ordinary_tool", "optional_tool"]},
        )
        tools = toolkit.tool_groups[0].tools
        assert [tool.name for tool in tools] == ["ordinary_tool"]
        assert tools[0]._qp_governor is policy
        assert tools[0]._qp_request_context["user_id"] == member

    await asyncio.wait_for(asyncio.gather(build_for("member-a"), build_for("member-b")), 10)


@pytest.mark.asyncio
async def test_sdk_viewer_obeys_final_whitelist_and_skill_metadata_survives(tmp_path):
    skill_dir = tmp_path / "skills" / "design"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: design\ndescription: Design slides.\n---\n\nDesign instructions.", encoding="utf-8",
    )
    allowed = await AgentBuilder().build_toolkit(
        None, effective_skills=["design"], workspace_dir=str(tmp_path),
        extra_tools=[FunctionTool(load_skill)], request_context={"subagent_allowed_tools": ["load_skill"]},
    )
    assert "design" in await allowed.get_skill_instructions()
    assert [row["function"]["name"] for row in await allowed.get_tool_schemas()] == ["load_skill"]
    with pytest.raises(ToolNotFoundError):
        await allowed.check_tool_available("Skill", [])
    inherited = Toolkit(skills_or_loaders=[str(skill_dir)])
    assert "Skill" in {row["function"]["name"] for row in await inherited.get_tool_schemas()}


@pytest.mark.asyncio
async def test_skill_loader_uses_canonical_identity_for_each_member(tmp_path):
    from tests.unit.agents.test_skill_runtime import _write_skill

    _write_skill(tmp_path, "design", "Design slides.")
    _write_skill(tmp_path, "chart", "Chart data.")
    path = tmp_path / "skills" / "chart" / "SKILL.md"
    path.write_text(path.read_text(encoding="utf-8").replace("name: chart", "name: chart-alias"), encoding="utf-8")

    async def read_for(skills, success):
        workspace = current_workspace_dir.set(tmp_path)
        scope = current_request_context.set({"subagent_skills": skills})
        try:
            await asyncio.sleep(0)
            chunk = await load_skill("chart-alias")
            assert (chunk.state != "error") is success
            if not success:
                assert "Follow chart instructions." not in chunk.content[0].text
        finally:
            current_request_context.reset(scope)
            current_workspace_dir.reset(workspace)

    await asyncio.gather(read_for(["chart"], True), read_for(["design"], False), read_for([], False))


@pytest.mark.asyncio
async def test_legacy_fork_refuses_multiuser_before_touching_files(monkeypatch):
    from fastapi import HTTPException
    from qwenpaw.app.routers import fork
    from qwenpaw.agents.tools import agent_management

    monkeypatch.setattr(fork, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_management, "is_multi_user_enabled", lambda: True)
    with pytest.raises(HTTPException) as unavailable:
        await fork.fork_agent(fork.ForkAgentRequest(agent_id="office", parent_session_id="sample"), None)
    assert unavailable.value.detail == "multi_user_fork_unavailable"
    result = await agent_management._spawn_forked_subagent("design", "office", "sample", False, 10)
    assert result.state == "error"
    assert "fork=false" in result.content[0].text


@pytest.mark.parametrize("tool", ["chat_with_agent", "submit_to_agent"])
async def test_cross_agent_calls_without_a_parent_return_a_business_error(monkeypatch, tool):
    from qwenpaw.agents.tools import agent_management

    monkeypatch.setattr(agent_management, "is_multi_user_enabled", lambda: True)
    result = await getattr(agent_management, tool)("office", "review")
    assert result.state == "error"
    assert "跨智能体" in result.content[0].text
