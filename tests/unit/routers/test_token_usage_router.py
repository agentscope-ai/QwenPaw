# -*- coding: utf-8 -*-
"""Unit tests for the per-user surface of the token usage router."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.token_usage import router
from qwenpaw.token_usage.manager import TokenUsageManager

DAY = "2026-07-23"

DATA = {
    DAY: {
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


@pytest.fixture(name="client")
def _client(tmp_path, monkeypatch):
    """Serve the router against a temp token usage file."""
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

    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)

    TokenUsageManager._instance = None


def test_summary_includes_by_user(client):
    """The summary breaks totals down per caller."""
    resp = client.get(
        f"/token-usage?start_date={DAY}&end_date={DAY}",
    )

    assert resp.status_code == 200
    by_user = resp.json()["by_user"]
    assert by_user["alice"]["prompt_tokens"] == 100
    assert by_user["bob"]["completion_tokens"] == 10


def test_summary_filters_by_user(client):
    """``user`` narrows the summary to a single caller."""
    resp = client.get(
        f"/token-usage?start_date={DAY}&end_date={DAY}&user=bob",
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_prompt_tokens"] == 20
    assert list(body["by_user"]) == ["bob"]


def test_details_carry_user_id(client):
    """Raw records expose which caller they belong to."""
    resp = client.get(
        f"/token-usage/details?start_date={DAY}&end_date={DAY}",
    )

    assert resp.status_code == 200
    users = {r["user_id"] for r in resp.json()}
    assert users == {"alice", "bob"}


def test_details_filters_by_user(client):
    """``user`` narrows the raw records to a single caller."""
    resp = client.get(
        f"/token-usage/details?start_date={DAY}&end_date={DAY}&user=alice",
    )

    assert resp.status_code == 200
    records = resp.json()
    assert [r["user_id"] for r in records] == ["alice"]
    assert records[0]["prompt_tokens"] == 100
