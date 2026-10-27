# -*- coding: utf-8 -*-
"""Public author contract for complete, incrementally produced tool results."""

import json

import pytest

SOURCE = """
from qwenpaw.plugins.messages import Attachment, ContentBlock
from qwenpaw.plugins.tools import ToolEvent, ToolResult, ToolSpec


class Plugin:
    def register(self, ctx):
        async def stream(call, arguments):
            mode = arguments["mode"]
            yield ToolEvent(
                "delta", (ContentBlock(text="prefix:"),)
            )
            if mode == "delta":
                yield ToolEvent(
                    "delta", (ContentBlock(text="last"),)
                )
                return
            if mode == "terminal":
                yield ToolEvent(
                    "result",
                    result=ToolResult(
                        (ContentBlock(text="tail"),),
                        metadata={"terminal": True},
                    ),
                )
                yield ToolEvent("end")
                return
            yield ToolEvent(
                "result",
                result=ToolResult(
                    (ContentBlock(text="first"),),
                    is_error=arguments["error"],
                    metadata={"first": 1, "collision": "old"},
                ),
            )
            yield ToolEvent(
                "result",
                result=ToolResult(
                    (
                        ContentBlock(
                            type="file",
                            attachment=Attachment(
                                url="https://example.invalid/result.txt",
                                name="result.txt",
                                preview_url=(
                                    "/api/files/preview?path=result.txt"
                                ),
                            ),
                        ),
                        ContentBlock(text="last"),
                    ),
                    metadata={"last": 2, "collision": "new"},
                ),
            )

        ctx.register_tool(
            ToolSpec(
                "sdk_public_aggregate",
                "stream",
                {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string"},
                        "error": {"type": "boolean"},
                    },
                    "required": ["mode", "error"],
                },
                stream,
                enabled=True,
            )
        )


plugin = Plugin()
"""


def aggregation_plugin(root):
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "public-aggregate",
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
                "sdk": {"version": "1.0", "capabilities": ["tools"]},
            },
        ),
    )
    (root / "main.py").write_text(SOURCE)
    return root


@pytest.mark.parametrize("error", [False, True])
@pytest.mark.parametrize("part", ["content", "error", "metadata"])
async def test_call_tool_preserves_all_incremental_results(
    tmp_path,
    error,
    part,
):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.install(aggregation_plugin(tmp_path / "plugin"))
        result = await host.call_tool(
            "sdk_public_aggregate",
            {"mode": "mixed", "error": error},
        )
        if part == "content":
            assert [block.type for block in result.content] == [
                "text",
                "file",
                "text",
            ]
            assert [block.text for block in result.content] == [
                "prefix:first",
                "",
                "last",
            ]
            assert (
                result.content[1].attachment.url
                == "https://example.invalid/result.txt"
            )
            assert (
                result.content[1].attachment.preview_url
                == "/api/files/preview?path=result.txt"
            )
        elif part == "error":
            assert result.is_error is error
        else:
            assert result.metadata == {
                "first": 1,
                "last": 2,
                "collision": "new",
            }


@pytest.mark.parametrize(
    "mode, text, metadata",
    [
        ("delta", "prefix:last", {}),
        ("terminal", "prefix:tail", {"terminal": True}),
    ],
)
async def test_call_tool_aggregates_delta_and_terminal_content_once(
    tmp_path,
    mode,
    text,
    metadata,
):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.install(aggregation_plugin(tmp_path / "plugin"))
        result = await host.call_tool(
            "sdk_public_aggregate",
            {"mode": mode, "error": False},
        )
        assert [(block.type, block.text) for block in result.content] == [
            ("text", text),
        ]
        assert result.metadata == metadata
        assert not result.is_error
