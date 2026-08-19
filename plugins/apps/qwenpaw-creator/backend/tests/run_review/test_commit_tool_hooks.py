# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Both agent commit tools must attach the sync review advisory."""

from __future__ import annotations

import json

import pytest

from services.project_files.agent_tools import (
    AgentProjectToolContext,
    AgentProjectTools,
)
from services.project_files.models import Project
from services.project_files.store import ProjectStore

pytestmark = pytest.mark.unit

PROJECT_ID = "project-commit-tools"


def _advisory_response() -> str:
    return json.dumps(
        {
            "scores": [
                {
                    "row_key": "concept",
                    "score": 3,
                    "ok": False,
                    "finding": "/strategy/creative_brief 是流水账",
                    "suggestion": "提炼一句话概念",
                },
                {
                    "row_key": "contract",
                    "score": 8,
                    "ok": True,
                    "finding": "",
                    "suggestion": "",
                },
                {
                    "row_key": "rhythm",
                    "score": 8,
                    "ok": True,
                    "finding": "",
                    "suggestion": "",
                },
            ],
            "summary": "需要补概念",
        },
        ensure_ascii=False,
    )


@pytest.fixture()
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")

    async def fake_chat_completion(prompt, **kwargs):
        del prompt, kwargs
        return _advisory_response()

    from models import text_model

    monkeypatch.setattr(text_model, "chat_completion", fake_chat_completion)
    store = ProjectStore(tmp_path.resolve())
    store.create(Project.new(project_id=PROJECT_ID, name="Initial"))
    boundary = AgentProjectTools(
        store,
        context=AgentProjectToolContext(
            origin="runtime_task",
            caused_by_request_id="request-1",
            caused_by_message_seq=1,
            round_id="agent-round-run-1",
        ),
    )
    boundary.invoke("read_project", {"projectId": PROJECT_ID})
    return boundary


def test_jq_project_attaches_review_advisory(tools) -> None:
    result = tools.invoke(
        "jq_project",
        {
            "projectId": PROJECT_ID,
            "program": '.strategy.creative_brief = "剪一剪加音乐"',
        },
    )
    advisory = result.get("reviewAdvisory")
    assert advisory is not None
    assert advisory["pointer_group"] == "strategy"


def test_patch_project_attaches_review_advisory(tools) -> None:
    """patch_project shares the commit pipeline and must review too.

    Regression: the dev/creator patch_project tool (agent reliability
    batch) initially bypassed the sync-review attachment, so agent runs
    that never call jq_project silently lost the whole advisory bypass.
    """
    result = tools.invoke(
        "patch_project",
        {
            "projectId": PROJECT_ID,
            "ops": [
                {
                    "op": "replace",
                    "path": "/strategy/creative_brief",
                    "value": "剪一剪加音乐",
                },
            ],
        },
    )
    advisory = result.get("reviewAdvisory")
    assert advisory is not None
    assert advisory["pointer_group"] == "strategy"
    assert advisory["round"] == 1


def test_commit_tools_skip_review_when_off(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CREATOR_SYNC_REVIEW_ENABLED", raising=False)
    store = ProjectStore(tmp_path.resolve())
    store.create(Project.new(project_id=PROJECT_ID, name="Initial"))
    boundary = AgentProjectTools(
        store,
        context=AgentProjectToolContext(
            origin="runtime_task",
            caused_by_request_id="request-1",
            caused_by_message_seq=1,
            round_id="agent-round-run-1",
        ),
    )
    boundary.invoke("read_project", {"projectId": PROJECT_ID})
    result = boundary.invoke(
        "patch_project",
        {
            "projectId": PROJECT_ID,
            "ops": [
                {
                    "op": "replace",
                    "path": "/strategy/creative_brief",
                    "value": "剪一剪加音乐",
                },
            ],
        },
    )
    assert result.get("reviewAdvisory") is None
