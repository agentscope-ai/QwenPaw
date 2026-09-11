# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for default MCP client configuration (anysearch)."""

from __future__ import annotations

from qwenpaw.config.config import MCPConfig


def test_default_mcp_config_contains_anysearch() -> None:
    """Test purpose:
    - Verify the default MCP config ships an anysearch client template.

    Test flow:
    1. Build MCPConfig() with default factory.
    2. Assert the anysearch client entry exists with the agreed shape.

    API endpoints:
    - none (pure config model).
    """
    cfg = MCPConfig()
    assert "anysearch" in cfg.clients
    client = cfg.clients["anysearch"]

    assert client.enabled is False
    assert client.transport == "streamable_http"
    assert client.url == "https://api.anysearch.com/mcp"
    assert client.headers == {"Authorization": "Bearer ${ANYSEARCH_API_KEY}"}
    assert client.name == "anysearch_mcp"


def test_default_mcp_config_has_no_tavily() -> None:
    """Test purpose:
    - Verify the tavily template is gone (replaced by anysearch).

    Test flow:
    1. Build MCPConfig() with default factory.
    2. Assert no tavily_search entry remains.

    API endpoints:
    - none (pure config model).
    """
    cfg = MCPConfig()
    assert "tavily_search" not in cfg.clients


def test_default_mcp_config_migration_version_is_zero() -> None:
    """Test purpose:
    - Verify the migration watermark stays at 0 for a fresh config so the
      v0->v1 migration picks up the default client on first start.

    Test flow:
    1. Build MCPConfig() with default factory.
    2. Assert migration_version is 0.

    API endpoints:
    - none (pure config model).
    """
    cfg = MCPConfig()
    assert cfg.migration_version == 0
