# -*- coding: utf-8 -*-
"""Unit tests for the ``get_token_usage`` agent tool."""

from __future__ import annotations

import json
from datetime import date

import pytest

from qwenpaw.agents.tools.get_token_usage import get_token_usage
from qwenpaw.token_usage.manager import TokenUsageManager

TODAY = date.today().isoformat()

DATA = {
    TODAY: {
        "openai:gpt-4": {
            "provider_id": "openai",
            "model_name": "gpt-4",
            "prompt_tokens": 120,
            "completion_tokens": 60,
            "call_count": 2,
            "by_user": {
                "alice": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "call_count": 1,
                },
                "bob": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "call_count": 1,
                },
            },
        },
    },
}


@pytest.fixture(autouse=True)
def _usage_file(tmp_path, monkeypatch):
    """Back the token usage singleton with a temp file holding DATA."""
    monkeypatch.setattr("qwenpaw.token_usage.manager.WORKING_DIR", tmp_path)
    monkeypatch.setattr(
        "qwenpaw.token_usage.manager.TOKEN_USAGE_FILE",
        "test_token_usage.json",
    )
    (tmp_path / "test_token_usage.json").write_text(
        json.dumps(DATA),
        encoding="utf-8",
    )
    # pylint: disable=protected-access
    TokenUsageManager._instance = None
    yield
    TokenUsageManager._instance = None


def _text(chunk) -> str:
    return "".join(block.text for block in chunk.content)


@pytest.mark.asyncio
async def test_reports_usage_per_user():
    """The default report breaks usage down per caller."""
    text = _text(await get_token_usage(days=1))

    assert "By user:" in text
    assert "alice" in text
    assert "bob" in text


@pytest.mark.asyncio
async def test_filters_by_user():
    """``user_id`` restricts the report to one caller."""
    text = _text(await get_token_usage(days=1, user_id="alice"))

    assert "user=alice" in text
    assert "- Prompt tokens: 100" in text
    assert "bob" not in text
