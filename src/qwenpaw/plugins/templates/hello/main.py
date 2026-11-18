# -*- coding: utf-8 -*-
"""A complete public-SDK plugin with workspace-local persistent data."""

import asyncio
from collections import defaultdict

from qwenpaw.plugins import PluginContext
from qwenpaw.plugins.messages import Message, ContentBlock
from qwenpaw.plugins.tools import ToolContext, ToolResult, ToolSpec


class Plugin:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def greet(
        self,
        context: ToolContext,
        arguments: dict,
    ) -> ToolResult:
        async with self._locks[context.workspace_id]:
            count = await context.storage.aread_json("count.json", 0) + 1
            await context.storage.awrite_json("count.json", count)
        context.logger.info("Greeting completed", fields={"count": count})
        text = f"Hello {arguments['name']} ({count})"
        if arguments.get("use_model", False):
            answer = await context.models.complete(
                (Message("user", (ContentBlock(text=text),)),),
                timeout=20,
            )
            text = "".join(
                block.text for block in answer.content if block.type == "text"
            )
        return ToolResult.text(text)

    def register(self, context: PluginContext) -> None:
        context.register_tool(
            ToolSpec(
                name="hello_sdk",
                description=(
                    "Greet someone and count greetings in this workspace"
                ),
                handler=self.greet,
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "use_model": {"type": "boolean", "default": False},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
                enabled=True,
            ),
        )


plugin = Plugin()
