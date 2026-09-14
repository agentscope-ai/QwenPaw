# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Slash-command feedback preserves skill and plugin execution contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agentscope.message import DataBlock, Msg, TextBlock, URLSource

from qwenpaw.agents.skill_system import registry as skill_registry
from qwenpaw.runtime import builtin_commands as commands
from qwenpaw.runtime.slash_command_registry import (
    CommandSpec,
    SlashCommandRegistry,
)


@pytest.fixture
def context(tmp_path, monkeypatch):
    registry = SlashCommandRegistry()
    registry.register(
        CommandSpec("new", AsyncMock(return_value=None), aliases=("fresh",)),
    )
    for name in ("help", "写 文档", "missing"):
        skill_dir = tmp_path / "skills" / name
        skill_dir.mkdir(parents=True)
        if name != "missing":
            (skill_dir / "SKILL.md").write_text(
                "---\ndescription: Local skill.\n---\nKeep data local.",
                encoding="utf-8",
            )
    available = Mock(return_value=["help", "写 文档", "missing"])
    monkeypatch.setattr(skill_registry, "resolve_effective_skills", available)
    return SimpleNamespace(
        workspace=SimpleNamespace(
            workspace_dir=tmp_path,
            plugins=SimpleNamespace(slash_command_registry=registry),
        ),
        request=SimpleNamespace(channel="qq"),
        input_msgs=[
            Msg(name="user", role="user", content=[TextBlock(text="/mew")]),
        ],
    )


def test_catalog_and_suggestions_use_available_commands(context):
    catalog = commands._command_catalog(context, ["写 文档", "missing"])
    assert catalog["new"] == catalog["fresh"] == ("/new", "")
    assert catalog["写 文档"][0] == "/[写 文档]"
    assert not {"missing", "help"} & catalog.keys()
    feedback = commands._command_feedback
    assert "/new" in feedback("mew", catalog).get_text_content()
    for name in ("news", "newer", "newest", "renew"):
        catalog[name] = (f"/{name}", "")
    catalog["newx"] = catalog["new"]
    text = feedback("neww", catalog).get_text_content()
    suggested = text.split("Did you mean ", 1)[1].splitlines()[0]
    names = [part.strip("`?") for part in suggested.split(", ")]
    assert 1 <= len(names) <= 3 and len(names) == len(set(names))
    reversed_catalog = dict(reversed(catalog.items()))
    assert text == feedback("neww", reversed_catalog).get_text_content()


@pytest.mark.parametrize(
    "text,name,expected",
    [
        ("", "", False),
        ("hello", "hello", False),
        ("/", "", False),
        ("/tmp/file", "tmp/file", False),
        ("/tmp/", "tmp/", False),
        ("//server/share", "/server/share", False),
        ("/[data]/file", "data", False),
        ("/[data]\\file", "data", False),
        ("/.", ".", False),
        ("/mew", "mew", True),
        ("/写作", "写作", True),
        ("/[my skill] task", "my skill", True),
        ("/" + "a" * 256, "a" * 256, True),
    ],
)
def test_command_input_boundaries(text, name, expected):
    assert commands._is_command_candidate(text, name) is expected


@pytest.mark.parametrize("name", ["fresh", "help"])
async def test_registered_handler_none_preserves_fallthrough(context, name):
    registry = context.workspace.plugins.slash_command_registry
    if name == "help":
        registry.register(CommandSpec(name, AsyncMock(return_value=None)))
    fallback = AsyncMock(side_effect=AssertionError("Must not run fallback"))
    registry.register_fallback(fallback)
    assert await registry.dispatch(f"/{name} arguments", context) is None
    fallback.assert_not_called()


@pytest.mark.parametrize("text", ["/help 'Exact Args'", "/[写 文档] 简介"])
async def test_skill_injection_keeps_original_input(context, text):
    context.input_msgs[-1].content = [TextBlock(text=text)]
    assert await commands._skill_fallback_handler(text, context) is None
    injected = context.input_msgs[-1].get_text_content()
    assert injected.startswith(text + "\n\n<skill>")
    assert "Keep data local." in injected


@pytest.mark.parametrize("text", ["/mew", "/missing", "/" + "a" * 256])
async def test_unknown_commands_return_feedback(context, text):
    context.input_msgs[-1].content = [TextBlock(text=text)]
    reply = await commands._skill_fallback_handler(text, context)
    assert "Unknown or unavailable command" in reply.get_text_content()
    assert "a" * 256 not in reply.get_text_content()


@pytest.mark.parametrize(
    "skills,expected",
    [([], "Available commands:"), (["help"], "Local skill.")],
)
async def test_help_skill_takes_precedence(context, skills, expected):
    skill_registry.resolve_effective_skills.return_value = skills
    reply = await commands._skill_fallback_handler("/help", context)
    assert expected in reply.get_text_content()


async def test_unknown_command_with_attachment_passes_through(context):
    source = URLSource(url="https://x.invalid/a", media_type="image/png")
    context.input_msgs[-1].content.append(DataBlock(source=source))
    assert await commands._skill_fallback_handler("/mew", context) is None


async def test_lookup_failure_has_distinct_diagnostic(context):
    skill_registry.resolve_effective_skills.side_effect = OSError(
        "private path",
    )
    reply = await commands._skill_fallback_handler("/mew", context)
    assert "Command lookup unavailable" in reply.get_text_content()
    assert "private path" not in reply.get_text_content()
