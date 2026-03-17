# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Tests for MCP config ${VAR} environment variable expansion.

Verifies that MCPClientManager correctly expands ${VAR_NAME} placeholders
in all config fields before passing them to the underlying MCP clients.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from copaw.app.mcp.manager import MCPClientManager, _ENV_VAR_RE
from copaw.config.config import MCPClientConfig


# ---------------------------------------------------------------------------
# _expand_env_vars
# ---------------------------------------------------------------------------


class TestExpandEnvVars:
    """Unit tests for MCPClientManager._expand_env_vars."""

    def test_single_var(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MY_TOKEN", "secret123")
        result = MCPClientManager._expand_env_vars("Bearer ${MY_TOKEN}")
        assert result == "Bearer secret123"

    def test_multiple_vars(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HOST", "example.com")
        monkeypatch.setenv("PORT", "8080")
        result = MCPClientManager._expand_env_vars("${HOST}:${PORT}")
        assert result == "example.com:8080"

    def test_no_placeholders(self):
        result = MCPClientManager._expand_env_vars("plain-value")
        assert result == "plain-value"

    def test_empty_string(self):
        result = MCPClientManager._expand_env_vars("")
        assert result == ""

    def test_unset_var_kept_as_is(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        result = MCPClientManager._expand_env_vars("${NONEXISTENT_VAR}")
        assert result == "${NONEXISTENT_VAR}"

    def test_partial_expansion(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("KNOWN", "resolved")
        monkeypatch.delenv("UNKNOWN", raising=False)
        result = MCPClientManager._expand_env_vars("${KNOWN}-${UNKNOWN}")
        assert result == "resolved-${UNKNOWN}"

    def test_dollar_without_braces_ignored(self):
        result = MCPClientManager._expand_env_vars("$NOT_A_VAR")
        assert result == "$NOT_A_VAR"


# ---------------------------------------------------------------------------
# _expand_config_strings
# ---------------------------------------------------------------------------


class TestExpandConfigStrings:
    """Tests for MCPClientManager._expand_config_strings."""

    def test_http_headers_expanded(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GH_TOKEN", "ghp_abc123")
        cfg = MCPClientConfig(
            name="github",
            transport="streamable_http",
            url="https://api.github.com/mcp/",
            headers={"Authorization": "Bearer ${GH_TOKEN}"},
        )
        resolved = MCPClientManager._expand_config_strings(cfg)
        assert resolved["headers"]["Authorization"] == "Bearer ghp_abc123"

    def test_url_expanded(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MCP_HOST", "myserver.com")
        cfg = MCPClientConfig(
            name="custom",
            transport="sse",
            url="https://${MCP_HOST}/sse",
        )
        resolved = MCPClientManager._expand_config_strings(cfg)
        assert resolved["url"] == "https://myserver.com/sse"

    def test_stdio_fields_expanded(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TOOL_PATH", "/usr/local/bin/tool")
        monkeypatch.setenv("API_KEY", "key123")
        cfg = MCPClientConfig(
            name="local",
            transport="stdio",
            command="${TOOL_PATH}",
            args=["--key", "${API_KEY}"],
            env={"MY_KEY": "${API_KEY}"},
        )
        resolved = MCPClientManager._expand_config_strings(cfg)
        assert resolved["command"] == "/usr/local/bin/tool"
        assert resolved["args"] == ["--key", "key123"]
        assert resolved["env"]["MY_KEY"] == "key123"

    def test_original_config_not_mutated(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("TOKEN", "val")
        cfg = MCPClientConfig(
            name="test",
            transport="streamable_http",
            url="https://host/mcp",
            headers={"Auth": "Bearer ${TOKEN}"},
        )
        MCPClientManager._expand_config_strings(cfg)
        # Original config must still contain the placeholder
        assert cfg.headers["Auth"] == "Bearer ${TOKEN}"


# ---------------------------------------------------------------------------
# _build_client (integration-level)
# ---------------------------------------------------------------------------


class TestBuildClientExpansion:
    """Tests that _build_client passes expanded values to the client."""

    @patch("copaw.app.mcp.manager.HttpStatefulClient")
    def test_http_client_receives_expanded_headers(
        self,
        mock_http_cls: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("MY_SECRET", "s3cret")
        cfg = MCPClientConfig(
            name="test-http",
            transport="streamable_http",
            url="https://example.com/mcp",
            headers={"Authorization": "Bearer ${MY_SECRET}"},
        )
        MCPClientManager._build_client(cfg)
        mock_http_cls.assert_called_once_with(
            name="test-http",
            transport="streamable_http",
            url="https://example.com/mcp",
            headers={"Authorization": "Bearer s3cret"},
        )

    @patch("copaw.app.mcp.manager.StdIOStatefulClient")
    def test_stdio_client_receives_expanded_env(
        self,
        mock_stdio_cls: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("KEY_VAL", "realkey")
        cfg = MCPClientConfig(
            name="test-stdio",
            transport="stdio",
            command="npx",
            args=["-y", "some-mcp@latest"],
            env={"API_KEY": "${KEY_VAL}"},
        )
        MCPClientManager._build_client(cfg)
        call_kwargs = mock_stdio_cls.call_args.kwargs
        assert call_kwargs["env"]["API_KEY"] == "realkey"

    @patch("copaw.app.mcp.manager.HttpStatefulClient")
    def test_rebuild_info_stores_raw_template(
        self,
        mock_http_cls: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("TOK", "expanded")
        cfg = MCPClientConfig(
            name="test",
            transport="streamable_http",
            url="https://x.com/mcp",
            headers={"H": "Bearer ${TOK}"},
        )
        client = MCPClientManager._build_client(cfg)
        info = client._copaw_rebuild_info
        # rebuild_info must keep the raw placeholder for watcher comparison
        assert info["headers"]["H"] == "Bearer ${TOK}"


# ---------------------------------------------------------------------------
# Regex sanity
# ---------------------------------------------------------------------------


class TestEnvVarRegex:
    """Sanity checks for the _ENV_VAR_RE pattern."""

    @pytest.mark.parametrize(
        "text,expected_vars",
        [
            ("${FOO}", ["FOO"]),
            ("${FOO_BAR}", ["FOO_BAR"]),
            ("a${X}b${Y}c", ["X", "Y"]),
            ("no-vars-here", []),
            ("$NOT ${YES}", ["YES"]),
            ("${A1_B2_C3}", ["A1_B2_C3"]),
        ],
    )
    def test_pattern_extraction(self, text: str, expected_vars: list):
        found = _ENV_VAR_RE.findall(text)
        assert found == expected_vars
