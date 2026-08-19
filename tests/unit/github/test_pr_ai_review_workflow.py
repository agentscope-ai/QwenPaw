# -*- coding: utf-8 -*-
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "pr-ai-review.yml"


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_ai_reviewer_and_publisher_have_separate_permissions() -> None:
    workflow = _load_workflow()
    jobs = workflow["jobs"]

    assert workflow["permissions"] == {}
    assert jobs["review-gate"]["permissions"] == {}
    assert jobs["ai-review"]["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    assert jobs["publish-review"]["permissions"] == {
        "actions": "read",
        "pull-requests": "write",
    }


def test_ai_reviewer_and_publisher_capabilities_are_isolated() -> None:
    jobs = _load_workflow()["jobs"]

    analysis_steps = str(jobs["ai-review"]["steps"])
    assert "createComment" not in analysis_steps
    assert "addLabels" not in analysis_steps
    assert "removeLabel" not in analysis_steps

    publisher = jobs["publish-review"]
    publisher_steps = str(publisher["steps"])
    assert all("run" not in step for step in publisher["steps"])
    assert "review_runner.py" not in publisher_steps
    assert "Start QwenPaw server" not in publisher_steps


def test_publisher_rejects_a_stale_review_before_writing() -> None:
    publisher_steps = _load_workflow()["jobs"]["publish-review"]["steps"]
    publish_step = next(
        step
        for step in publisher_steps
        if step["name"] == "Post review comment and manage labels"
    )
    publish_script = publish_step["with"]["script"]

    assert "context.payload.pull_request.head.sha" in publish_script
    assert "pulls.get" in publish_script
    assert "currentPull.data.head.sha" in publish_script
    assert publish_step["env"]["REVIEW_VERDICT"] == (
        "${{ needs.ai-review.outputs.verdict }}"
    )
    assert "needs.ai-review.outputs.verdict" not in publish_script
