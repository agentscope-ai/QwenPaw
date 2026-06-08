# -*- coding: utf-8 -*-
"""Unit tests for MCP client key validation."""

from qwenpaw.app.mcp.client_key import validate_mcp_client_key


def test_valid_keys():
    assert validate_mcp_client_key("jenkins") is None
    assert validate_mcp_client_key("My_MCP-01") is None
    assert validate_mcp_client_key("a" * 100) is None


def test_empty_key():
    assert validate_mcp_client_key("") is not None
    assert validate_mcp_client_key("   ") is not None


def test_too_long():
    assert validate_mcp_client_key("a" * 101) is not None


def test_invalid_characters():
    assert validate_mcp_client_key("中文") is not None
    assert validate_mcp_client_key("has space") is not None
    assert validate_mcp_client_key("dot.name") is not None


def test_reserved_prefix():
    assert validate_mcp_client_key("tools/foo") is not None
    assert validate_mcp_client_key("oauth") is not None
    assert validate_mcp_client_key("reconnect/x") is not None
