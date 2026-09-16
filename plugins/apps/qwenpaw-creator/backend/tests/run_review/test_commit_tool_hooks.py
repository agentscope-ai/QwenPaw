# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
"""Both agent commit tools must attach the sync review advisory."""

from __future__ import annotations

import json
import threading

import pytest

from models import text_model
from services.project_files.agent_tools import (
    AgentProjectToolContext,
    AgentProjectTools,
)
from services.project_files.models import Project
from services.project_files.store import ProjectStore
from services.run_review import admission

pytestmark = pytest.mark.unit

PROJECT_ID = "project-commit-tools"


def _advisory_response() -> str:
    scores = [
        {"row_key": k, "score": 8, "ok": True, "finding": "", "suggestion": ""}
        for k in ("concept", "contract", "rhythm")
    ]
    scores[0] |= {
        "score": 3,
        "ok": False,
        "finding": "/strategy/creative_brief 是流水账",
        "suggestion": "提炼一句话概念",
    }
    return json.dumps(
        {"scores": scores, "summary": "需要补概念"},
        ensure_ascii=False,
    )


def _boundary(tmp_path) -> AgentProjectTools:
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


def _patch(boundary: AgentProjectTools, value: str = "剪一剪加音乐") -> dict:
    return boundary.invoke(
        "patch_project",
        {
            "projectId": PROJECT_ID,
            "ops": [
                {
                    "op": "replace",
                    "path": "/strategy/creative_brief",
                    "value": value,
                },
            ],
        },
    )


@pytest.fixture()
def tools(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")

    async def fake_chat_completion(prompt, **kwargs):
        return _advisory_response()

    monkeypatch.setattr(text_model, "chat_completion", fake_chat_completion)
    return _boundary(tmp_path)


def test_both_commit_tools_attach_review_advisory(tools) -> None:
    """jq_project and patch_project share the commit pipeline.

    Regression: patch_project initially bypassed the sync-review
    attachment, silently losing the advisory for agent runs.
    """
    result = tools.invoke(
        "jq_project",
        {
            "projectId": PROJECT_ID,
            "program": '.strategy.creative_brief = "剪一剪加音乐"',
        },
    )
    advisory = result.get("reviewAdvisory")
    assert advisory["round"] == 1
    advisory = _patch(tools, "换个节奏再剪一版").get("reviewAdvisory")
    assert advisory["round"] == 2


def test_commit_tools_skip_review_when_off(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CREATOR_SYNC_REVIEW_ENABLED", raising=False)
    assert _patch(_boundary(tmp_path)).get("reviewAdvisory") is None


def test_parent_commit_registers_fence_until_inline_review_finishes(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CREATOR_SYNC_REVIEW_ENABLED", "1")
    started = threading.Event()
    release = threading.Event()

    async def blocked_review(_prompt, **_kwargs):
        started.set()
        assert release.wait(5)
        return _advisory_response()

    monkeypatch.setattr(text_model, "chat_completion", blocked_review)
    boundary = _boundary(tmp_path)
    outcome: dict[str, object] = {}

    def commit() -> None:
        outcome.update(
            boundary.invoke(
                "patch_project",
                {
                    "projectId": PROJECT_ID,
                    "ops": [
                        {
                            "op": "replace",
                            "path": "/strategy",
                            "value": {
                                "creative_brief": "纸船驶向晨雾",
                                "audience": "纪录片观众",
                                "creative_direction": "柔和电影感",
                                "constraints": "单镜头",
                                "success_criteria": "主体清晰",
                            },
                        },
                    ],
                },
            ),
        )

    worker = threading.Thread(target=commit, daemon=True)
    worker.start()
    assert started.wait(5)
    reports_root = (
        boundary.store.project_root(PROJECT_ID) / "runtime" / "run-review"
    )
    assert admission.active_sync_fences(reports_root)
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert outcome.get("reviewAdvisory") is not None
    # Strategy is reviewed inline but is not itself a generation input, so it
    # must not leave a cross-turn media blocker behind.
    assert not admission.active_sync_fences(reports_root)
