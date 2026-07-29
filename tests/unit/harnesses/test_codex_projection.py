# -*- coding: utf-8 -*-
"""Tests for QwenPaw capability projection into Codex."""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.harnesses.capabilities import (
    HarnessMCPServerDefinition,
    HarnessRuntimeCapabilities,
    HarnessSkillDefinition,
)
from qwenpaw.harnesses.codex.projection import project_runtime


def test_projects_skills_and_http_mcp_without_secret_argv(
    tmp_path: Path,
) -> None:
    capabilities = HarnessRuntimeCapabilities(
        skills=[
            HarnessSkillDefinition(
                name="review",
                directory=tmp_path / "skills" / "review",
            ),
        ],
        mcp_servers=[
            HarnessMCPServerDefinition(
                name="docs",
                display_name="Docs",
                transport="streamable_http",
                url="https://mcp.example.test",
                headers={"Authorization": "Bearer secret-value"},
                tools=["read", "write"],
                tool_policies={"read": "allow", "write": "deny"},
                default_policy="ask",
            ),
        ],
    )

    projection = project_runtime(capabilities)

    assert projection.skill_roots == (str(tmp_path / "skills" / "review"),)
    assert set(projection.environment.values()) == {"Bearer secret-value"}
    arguments = "\n".join(projection.config_overrides)
    assert "secret-value" not in arguments
    assert "mcp_servers.docs.url=" in arguments
    assert 'mcp_servers.docs.enabled_tools=["read"]' in arguments
    assert 'default_tools_approval_mode="prompt"' in arguments


def test_rejects_conflicting_stdio_environment() -> None:
    capabilities = HarnessRuntimeCapabilities(
        mcp_servers=[
            HarnessMCPServerDefinition(
                name="first",
                display_name="First",
                transport="stdio",
                command="first-server",
                env={"API_KEY": "first"},
            ),
            HarnessMCPServerDefinition(
                name="second",
                display_name="Second",
                transport="stdio",
                command="second-server",
                env={"API_KEY": "second"},
            ),
        ],
    )

    with pytest.raises(ValueError, match="conflicting values"):
        project_runtime(capabilities)
