# -*- coding: utf-8 -*-
"""Tests for built-in slash command helpers and skill fallback dispatch.

Covers the previously untested skill query parser, block text
extraction, skill injection formatting, and the filesystem-based skill
fallback handler paths (info display, input injection, and all the
early-return guards).
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.runtime.builtin_commands import (
    _build_skill_injection,
    _extract_block_text,
    _parse_skill_query,
    _skill_fallback_handler,
)


# ---------------------------------------------------------------------------
# _parse_skill_query
# ---------------------------------------------------------------------------


class TestParseSkillQuery:
    def test_plain_name_without_input(self):
        assert _parse_skill_query("/deploy") == ("deploy", "")

    def test_plain_name_with_input(self):
        assert _parse_skill_query("/deploy prod") == ("deploy", "prod")

    def test_input_keeps_inner_whitespace(self):
        assert _parse_skill_query("/deploy prod --force") == (
            "deploy",
            "prod --force",
        )

    def test_name_lowercased(self):
        assert _parse_skill_query("/Deploy") == ("deploy", "")

    def test_bracketed_name_with_spaces(self):
        assert _parse_skill_query("/[my skill] go now") == (
            "my skill",
            "go now",
        )

    def test_bracketed_name_without_input(self):
        assert _parse_skill_query("/[my skill]") == ("my skill", "")

    def test_bracketed_unclosed_returns_none(self):
        assert _parse_skill_query("/[broken") is None

    def test_bracketed_empty_name_returns_none(self):
        assert _parse_skill_query("/[] input") is None

    def test_no_leading_slash_returns_none(self):
        assert _parse_skill_query("deploy") is None

    def test_empty_string_returns_none(self):
        assert _parse_skill_query("") is None

    def test_bare_slash_returns_none(self):
        assert _parse_skill_query("/") is None

    def test_whitespace_trimmed(self):
        assert _parse_skill_query("  /deploy  arg  ") == ("deploy", "arg")


# ---------------------------------------------------------------------------
# _extract_block_text
# ---------------------------------------------------------------------------


class TestExtractBlockText:
    def test_dict_block(self):
        assert _extract_block_text({"type": "text", "text": "hi"}) == "hi"

    def test_dict_block_missing_text(self):
        assert _extract_block_text({"type": "image"}) == ""

    def test_object_block(self):
        block = SimpleNamespace(text="hello")
        assert _extract_block_text(block) == "hello"

    def test_object_without_text_attribute(self):
        assert _extract_block_text(SimpleNamespace()) == ""

    def test_none_text_returns_empty(self):
        assert _extract_block_text({"text": None}) == ""


# ---------------------------------------------------------------------------
# _build_skill_injection
# ---------------------------------------------------------------------------


class TestBuildSkillInjection:
    def test_structure_contains_all_fields(self):
        result = _build_skill_injection(
            "/deploy go",
            "Deploy Skill",
            "Deploys things",
            Path("/ws/skills/deploy"),
            "skill body content",
        )
        assert result.startswith("/deploy go")
        assert "<skill>" in result
        assert "<name>Deploy Skill</name>" in result
        assert "<description>Deploys things</description>" in result
        assert "<dir>/ws/skills/deploy</dir>" in result
        assert "skill body content" in result

    def test_empty_original_text_still_has_block(self):
        result = _build_skill_injection(
            "",
            "S",
            "D",
            Path("/d"),
            "body",
        )
        assert "<skill>" in result
        assert "body" in result


# ---------------------------------------------------------------------------
# _skill_fallback_handler
# ---------------------------------------------------------------------------


def _workspace_ctx(tmp_path: Path, text_blocks=None, content=None):
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(exist_ok=True)
    workspace = SimpleNamespace(workspace_dir=workspace_dir)
    request = SimpleNamespace(channel="console")
    ctx = SimpleNamespace(workspace=workspace, request=request)
    if content is not None:
        message = SimpleNamespace(content=content)
        ctx.input_msgs = [message]
    return ctx


def _install_skill(workspace_dir: Path, name: str, front: dict, body: str):
    """Create a skill dir + manifest entry so the skill is enabled."""
    skills_dir = workspace_dir / "skills" / name
    skills_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in front.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append(body)
    (skills_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")
    manifest = {
        "schema_version": "workspace-skill-manifest.v1",
        "version": 1,
        "skills": {name: {"enabled": True}},
    }
    (workspace_dir / "skill.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return skills_dir


class TestSkillFallbackHandlerGuards:
    async def test_no_workspace_returns_none(self):
        ctx = SimpleNamespace(workspace=None, request=None)
        assert await _skill_fallback_handler("/x", ctx) is None

    async def test_no_workspace_dir_returns_none(self):
        ctx = SimpleNamespace(
            workspace=SimpleNamespace(workspace_dir=None),
            request=None,
        )
        assert await _skill_fallback_handler("/x", ctx) is None

    async def test_non_skill_text_returns_none(self, tmp_path):
        ctx = _workspace_ctx(tmp_path)
        assert await _skill_fallback_handler("hello world", ctx) is None

    async def test_unknown_skill_returns_none(self, tmp_path):
        ctx = _workspace_ctx(tmp_path)
        _install_skill(
            ctx.workspace.workspace_dir,
            "real",
            {"name": "Real"},
            "body",
        )
        assert await _skill_fallback_handler("/ghost", ctx) is None

    async def test_disabled_skill_not_resolved(self, tmp_path):
        ctx = _workspace_ctx(tmp_path)
        workspace_dir = ctx.workspace.workspace_dir
        skills_dir = workspace_dir / "skills" / "off"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: Off\n---\nbody",
            encoding="utf-8",
        )
        manifest = {
            "schema_version": "workspace-skill-manifest.v1",
            "version": 1,
            "skills": {"off": {"enabled": False}},
        }
        (workspace_dir / "skill.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        assert await _skill_fallback_handler("/off", ctx) is None

    async def test_skill_dir_without_skill_md_returns_none(self, tmp_path):
        ctx = _workspace_ctx(tmp_path)
        workspace_dir = ctx.workspace.workspace_dir
        skills_dir = workspace_dir / "skills" / "bare"
        skills_dir.mkdir(parents=True)
        manifest = {
            "schema_version": "workspace-skill-manifest.v1",
            "version": 1,
            "skills": {"bare": {"enabled": True}},
        }
        (workspace_dir / "skill.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        assert await _skill_fallback_handler("/bare", ctx) is None


class TestSkillFallbackHandlerInfo:
    async def test_no_input_returns_info_message(self, tmp_path):
        ctx = _workspace_ctx(tmp_path)
        _install_skill(
            ctx.workspace.workspace_dir,
            "deploy",
            {"name": "Deploy Skill", "description": "Deploys things"},
            "body",
        )
        result = await _skill_fallback_handler("/deploy", ctx)
        assert result is not None
        text = result.content[0].text
        assert "deploy" in text
        assert "Deploy Skill" in text
        assert "Deploys things" in text
        assert "/deploy <input>" in text

    async def test_missing_description_shows_placeholder(self, tmp_path):
        ctx = _workspace_ctx(tmp_path)
        _install_skill(
            ctx.workspace.workspace_dir,
            "plain",
            {"name": "Plain"},
            "body",
        )
        result = await _skill_fallback_handler("/plain", ctx)
        assert result is not None
        assert "No description." in result.content[0].text

    async def test_case_insensitive_skill_lookup(self, tmp_path):
        ctx = _workspace_ctx(tmp_path)
        _install_skill(
            ctx.workspace.workspace_dir,
            "Deploy",
            {"name": "Deploy"},
            "body",
        )
        result = await _skill_fallback_handler("/deploy", ctx)
        assert result is not None


class TestSkillFallbackHandlerInjection:
    async def test_injects_into_existing_text_block(self, tmp_path):
        ctx = _workspace_ctx(
            tmp_path,
            content=[{"type": "text", "text": "/deploy run now"}],
        )
        _install_skill(
            ctx.workspace.workspace_dir,
            "deploy",
            {"name": "Deploy", "description": "D"},
            "skill body",
        )
        result = await _skill_fallback_handler("/deploy run now", ctx)
        assert result is None  # injection mutates the message in place
        merged = ctx.input_msgs[0].content[0].text
        assert merged.startswith("/deploy run now")
        assert "<skill>" in merged
        assert "skill body" in merged

    async def test_inserts_block_when_no_text_block(self, tmp_path):
        ctx = _workspace_ctx(
            tmp_path,
            content=[{"type": "image", "url": "http://x"}],
        )
        _install_skill(
            ctx.workspace.workspace_dir,
            "deploy",
            {"name": "Deploy", "description": "D"},
            "skill body",
        )
        result = await _skill_fallback_handler("/deploy run", ctx)
        assert result is None
        content = ctx.input_msgs[0].content
        assert len(content) == 2
        assert "<skill>" in content[0].text

    async def test_string_content_replaced(self, tmp_path):
        ctx = _workspace_ctx(tmp_path, content="/deploy run")
        _install_skill(
            ctx.workspace.workspace_dir,
            "deploy",
            {"name": "Deploy", "description": "D"},
            "skill body",
        )
        result = await _skill_fallback_handler("/deploy run", ctx)
        assert result is None
        assert "<skill>" in ctx.input_msgs[0].content

    async def test_no_input_msgs_returns_none(self, tmp_path):
        ctx = _workspace_ctx(tmp_path)
        _install_skill(
            ctx.workspace.workspace_dir,
            "deploy",
            {"name": "Deploy", "description": "D"},
            "skill body",
        )
        result = await _skill_fallback_handler("/deploy run", ctx)
        assert result is None
