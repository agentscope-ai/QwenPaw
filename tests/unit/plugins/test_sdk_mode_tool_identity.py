# -*- coding: utf-8 -*-
"""A real model/tool/continuation cycle retains the command's trusted identity."""

from qwenpaw.plugins.compliance import check_plugin
from qwenpaw.plugins.testing import PluginTestHost
from .sdk_author_fixture import make_plugin

SOURCE = """
import json
from dataclasses import asdict
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import Message, ContentBlock
from qwenpaw.plugins.modes import ModeSpec
from qwenpaw.plugins.prompts import PromptSpec
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo, ModelChunk
from qwenpaw.plugins.stops import StopSpec, StopResult
from qwenpaw.plugins.tools import ToolSpec, ToolResult


class Plugin:
    def register(self, ctx):
        states = {}

        async def start(call, args):
            states[call.identity] = {"turn": 0, "finished": False}
            return CommandResult(
                "replace_input",
                messages=(
                    Message(
                        "user",
                        (ContentBlock(text="Exercise the active mode"),),
                    ),
                ),
            )

        async def record(call, args):
            rows = ctx.storage.read_json("tools.json", [])
            rows.append(asdict(call.identity))
            ctx.storage.write_json("tools.json", rows)
            states[call.identity]["finished"] = args["finished"]
            return ToolResult.text("Recorded")

        async def stop(call):
            if call.has_tool_calls:
                return StopResult()
            if states[call.identity]["finished"]:
                del states[call.identity]
                return StopResult("stop", reason="Finished")
            return StopResult("continue", "Finish through the same mode tool")

        async def generate(call, request):
            state = states[call.identity]
            state["turn"] += 1
            turn = state["turn"]
            ctx.storage.write_json("last-turn.json", turn)
            if turn in (1, 3):
                block = ContentBlock(
                    "tool_call",
                    id=f"call-{turn}",
                    name="mode_record",
                    arguments=json.dumps({"finished": turn == 3}),
                )
            else:
                block = ContentBlock(text="Turn completed")
            yield ModelChunk((block,), is_last=True)

        ctx.register_command(CommandSpec("identity-mode", start))
        ctx.register_mode(
            ModeSpec(
                "identity-mode",
                lambda call: call.identity in states,
                tools=(
                    ToolSpec(
                        "mode_record",
                        "Record current identity",
                        {
                            "type": "object",
                            "properties": {"finished": {"type": "boolean"}},
                            "required": ["finished"],
                        },
                        record,
                        enabled=True,
                    ),
                ),
                prompts=(
                    PromptSpec(
                        "identity-prompt",
                        render=lambda identity: identity.user_id,
                    ),
                ),
            )
        )
        ctx.register_stop(
            StopSpec(
                "identity-stop", stop, lambda identity: identity in states
            )
        )
        ctx.register_provider(
            ProviderSpec(
                "identity-model",
                "Deterministic model",
                generate,
                models=(ModelInfo("model", "Model"),),
                require_api_key=False,
            )
        )


plugin = Plugin()
"""


async def test_real_mode_tool_preserves_user_workspace_and_session(tmp_path):
    source = make_plugin(
        tmp_path,
        SOURCE,
        [
            "commands",
            "modes",
            "tools",
            "prompts",
            "stops",
            "providers",
            "storage",
        ],
        sdk_version="1.2",
    )
    assert check_plugin(source).ok
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(source)
        identities = []
        for workspace, session, user in (
            ("one", "shared", "alice"),
            ("two", "other", "bob"),
        ):
            await host.configure_chat_model(
                "identity-model",
                "model",
                workspace_id=workspace,
            )
            events = [
                event
                async for event in host.stream_chat(
                    "/identity-mode",
                    workspace_id=workspace,
                    session_id=session,
                    user_id=user,
                )
            ]
            identities.extend(
                [
                    {
                        "workspace_id": workspace,
                        "session_id": session,
                        "user_id": user,
                        "channel": "console",
                    },
                ]
                * 2,
            )
            assert ctx.storage.read_json("tools.json") == identities
            assert ctx.storage.read_json("last-turn.json") == 4
            assert any(event.status == "completed" for event in events)
            assert not any(event.status == "failed" for event in events)
            assert not await host.active_modes(
                workspace_id=workspace,
                session_id=session,
                user_id=user,
            )
        assert (await host.unload("extension-contract")).clean
