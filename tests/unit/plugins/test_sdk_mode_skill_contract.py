# -*- coding: utf-8 -*-
"""Author-facing Mode and Skill contracts on real workspace projections."""

import pytest

from .sdk_author_fixture import make_plugin


async def test_mode_selection_gates_tools_hooks_and_prompts(tmp_path):
    from qwenpaw.plugins.messages import ContentBlock, Message
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.modes import ModeSpec
from qwenpaw.plugins.tools import ToolSpec, ToolResult
from qwenpaw.plugins.hooks import HookSpec, HookPhase, HookResult
from qwenpaw.plugins.prompts import PromptSpec


class Plugin:
    def register(self, ctx):
        def active(call):
            assert not hasattr(call, "workspace") and not hasattr(
                call, "agent"
            )
            return bool(
                call.messages
                and call.messages[0].content[0].text == "activate"
            )

        async def echo(call, args):
            return ToolResult.text("mode tool")

        async def hook(call):
            ctx.storage.write_json("hook.json", call.workspace_id)
            return HookResult()

        async def turn(call):
            ctx.storage.write_json(
                "turn.json",
                [
                    call.mode_name,
                    call.workspace_id,
                    call.session_id,
                ],
            )

        async def reset(call):
            ctx.storage.write_json("reset.json", True)

        ctx.register_mode(
            ModeSpec(
                name="sdk_focus",
                is_active=active,
                tools=(
                    ToolSpec(
                        "mode_echo",
                        "mode echo",
                        {"type": "object"},
                        echo,
                        enabled=True,
                    ),
                ),
                hooks=(
                    HookSpec(
                        "mode_hook", HookPhase.PRE_EXECUTE, hook
                    ),
                ),
                prompts=(
                    PromptSpec("mode_prompt", "MODE_PUBLIC_MARKER"),
                ),
                on_turn_start=turn,
                on_reset=reset,
            )
        )


plugin = Plugin()
"""
    active = (Message("user", (ContentBlock(text="activate"),)),)
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["modes", "tools", "hooks", "prompts", "storage"],
            ),
        )
        assert "sdk_focus" in await host.mode_names()
        assert "sdk_focus" not in await host.active_modes()
        assert "sdk_focus" in await host.active_modes(messages=active)
        assert "mode_echo" not in await host.available_tools()
        assert "mode_echo" in await host.available_tools(messages=active)
        assert "MODE_PUBLIC_MARKER" not in await host.build_prompt()
        assert "MODE_PUBLIC_MARKER" in await host.build_prompt(messages=active)
        await host.run_hooks("pre_execute")
        assert ctx.storage.read_json("hook.json", None) is None
        await host.run_hooks(
            "pre_execute",
            messages=active,
            workspace_id="one",
        )
        assert ctx.storage.read_json("hook.json") == "one"
        await host.run_mode(
            "sdk_focus",
            "turn_start",
            messages=active,
            workspace_id="one",
            session_id="chat",
        )
        assert ctx.storage.read_json("turn.json") == [
            "sdk_focus",
            "one",
            "chat",
        ]
        await host.run_mode("sdk_focus", "reset")
        assert ctx.storage.read_json("reset.json") is True
        assert (await host.reload("extension-contract")).ok
        assert (await host.mode_names()).count("sdk_focus") == 1
        await host.unload("extension-contract")
        assert "sdk_focus" not in await host.mode_names()
        assert "mode_echo" not in await host.available_tools(messages=active)
        assert "MODE_PUBLIC_MARKER" not in await host.build_prompt(
            messages=active,
        )


async def test_skill_projects_into_existing_and_new_workspaces(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.skills import SkillSpec
class Plugin:
    def register(self, ctx):
        ctx.register_skills(SkillSpec())
plugin = Plugin()
"""
    root = make_plugin(tmp_path, source, ["skills"])
    skill = root / "skills" / "sdk-sample" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    contents = (
        "---\nname: sdk-sample\ndescription: Public SDK test "
        "skill\n---\nUse the sample.\n"
    )
    skill.write_text(contents)
    async with PluginTestHost(tmp_path / "host") as host:
        assert "sdk-sample/SKILL.md" not in await host.skill_files(
            workspace_id="one",
        )
        await host.load(root)
        for workspace in ("one", "two"):
            assert "sdk-sample/SKILL.md" in await host.skill_files(
                workspace_id=workspace,
            )
            assert (
                await host.read_skill(
                    "sdk-sample/SKILL.md",
                    workspace_id=workspace,
                )
                == contents
            )
        assert (await host.reload("extension-contract")).ok
        assert (
            await host.read_skill("sdk-sample/SKILL.md", workspace_id="one")
            == contents
        )


async def test_skill_directory_must_be_inside_package(tmp_path):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.skills import SkillSpec
class Plugin:
    def register(self, ctx):
        ctx.register_skills(SkillSpec(directory="../outside"))
plugin = Plugin()
"""
    (tmp_path / "outside").mkdir()
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(SDKError, match="inside"):
            await host.load(make_plugin(tmp_path, source, ["skills"]))


async def test_skill_handle_removes_owned_files_and_future_projection(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.skills import SkillSpec
from qwenpaw.plugins.commands import CommandSpec, CommandResult
class Plugin:
    def register(self, ctx):
        handle = ctx.register_skills(SkillSpec())
        async def revoke(call, args):
            await handle.close()
            await handle.close()
            return CommandResult()
        ctx.register_command(CommandSpec("revokeskills", revoke))
plugin = Plugin()
"""
    root = make_plugin(tmp_path, source, ["skills", "commands"])
    skill = root / "skills" / "sdk-owned" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        (
            "---\nname: sdk-owned\ndescription: Test "
            "skill\n---\nOwned instructions.\n"
        ),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(root)
        assert "sdk-owned/SKILL.md" in await host.skill_files(
            workspace_id="one",
        )
        await host.call_command("/revokeskills", workspace_id="one")
        assert "sdk-owned/SKILL.md" not in await host.skill_files(
            workspace_id="one",
        )
        assert "sdk-owned/SKILL.md" not in await host.skill_files(
            workspace_id="new",
        )
