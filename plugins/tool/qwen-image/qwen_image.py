# -*- coding: utf-8 -*-
"""Register Qwen-Image tools through the public Plugin SDK."""

import json
from pathlib import Path

from qwenpaw.plugins import PluginContext
from qwenpaw.plugins.tools import ToolSpec

# The host loads this entry as an isolated package.
# pylint: disable-next=relative-beyond-top-level
from .qwen_image_tool import edit_image_qwen, generate_image_qwen


async def _generate(context, arguments):
    return await generate_image_qwen(context, **arguments)


async def _edit(context, arguments):
    return await edit_image_qwen(context, **arguments)


def _schema(edit):
    properties = {
        "prompt": {
            "type": "string",
            "description": "Image generation or editing instructions.",
        },
        "size": {
            "type": "string",
            "default": "" if edit else "2048*2048",
            "description": "Output width*height; empty detects edit size.",
        },
        "n": {"type": "integer", "default": 1, "minimum": 1, "maximum": 6},
        "negative_prompt": {"type": "string", "default": ""},
        "prompt_extend": {"type": "boolean", "default": True},
    }
    required = ["prompt"]
    if edit:
        properties["reference_images"] = {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "HTTP(S) URLs or local PNG/JPEG/WebP file paths.",
        }
        required.append("reference_images")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


class QwenImageToolPlugin:
    def register(self, context: PluginContext) -> None:
        manifest = json.loads(
            Path(__file__)
            .with_name("plugin.json")
            .read_text(
                encoding="utf-8",
            ),
        )
        for tool in manifest["meta"]["tools"]:
            edit = tool["name"] == "edit_image_qwen"
            context.register_tool(
                ToolSpec(
                    name=tool["name"],
                    description=tool["description"],
                    input_schema=_schema(edit),
                    handler=_edit if edit else _generate,
                    icon=tool["icon"],
                    config_fields=tuple(tool["config_fields"]),
                ),
            )


plugin = QwenImageToolPlugin()
