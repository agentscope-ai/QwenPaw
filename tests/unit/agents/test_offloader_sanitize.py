# -*- coding: utf-8 -*-
"""Unit tests for ``_sanitize_secrets`` in agents/offloader.py."""

from __future__ import annotations

from qwenpaw.agents.offloader import _sanitize_secrets


def test_redacts_sk_api_key():
    data = {"text": "api_key: sk-abc123def456ghi789jkl012mno345pqr"}
    result = _sanitize_secrets(data)
    assert "sk-xxxxxxxxxxxx" in result["text"]
    assert "sk-abc123" not in result["text"]


def test_redacts_ghp_token():
    data = {"text": "token: ghp_abcdef1234567890ghijklmnopqrstuv"}
    result = _sanitize_secrets(data)
    assert "ghp_xxxxxxxxxxxx" in result["text"]


def test_redacts_github_pat_fine_grained():
    data = {
        "text": (
            "github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuv"
        ),
    }
    result = _sanitize_secrets(data)
    assert "github_pat_xxxxxxxxxxxx" in result["text"]


def test_passes_through_safe_content():
    data = {"text": "hello world", "count": 42}
    result = _sanitize_secrets(data)
    assert result == {"text": "hello world", "count": 42}


def test_handles_nested_dicts_and_lists():
    data = {
        "messages": [
            {
                "role": "user",
                "content": "key: sk-abc123def456ghi789jkl012mno345pqr",
            },
            {"role": "assistant", "content": "normal reply"},
        ],
        "metadata": {"safe": True},
    }
    result = _sanitize_secrets(data)
    assert "sk-xxxxxxxxxxxx" in result["messages"][0]["content"]
    assert result["messages"][1]["content"] == "normal reply"


def test_handles_plain_string_input():
    result = _sanitize_secrets(
        "use token ghp_abc123def4567890ghijklmnopqrstuv here",
    )
    assert "ghp_xxxxxxxxxxxx" in result
    assert "ghp_abc123" not in result


def test_preserves_non_string_types():
    data = {"flag": True, "num": 3.14, "null_val": None}
    result = _sanitize_secrets(data)
    assert result == {"flag": True, "num": 3.14, "null_val": None}
