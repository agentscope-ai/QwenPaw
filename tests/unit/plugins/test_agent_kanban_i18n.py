# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Regression tests for Agent Kanban language handling."""

import copy
import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException


_BACKEND_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "apps"
    / "agent-kanban"
    / "backend"
    / "main.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "test_agent_kanban_backend_i18n",
    _BACKEND_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
_BACKEND = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BACKEND)


@pytest.mark.parametrize("status", ["todo", "in_progress"])
def test_legacy_queued_issue_keeps_chinese_prompt(status: str) -> None:
    """Tasks saved before the language field existed retain Chinese."""
    issue = {
        "id": "legacy-issue",
        "title": "旧任务",
        "description": "兼容升级前保存的数据",
        "status": status,
        "assignee": "agent-1",
    }

    prompt = _BACKEND._build_issue_prompt(issue)

    assert "请完成该任务" in prompt
    assert "concisely in English" not in prompt


def test_explicit_unsupported_language_falls_back_to_english() -> None:
    """An explicit unsupported locale follows the English fallback rule."""
    issue = {
        "id": "unsupported-language",
        "title": "Task",
        "language": "ja",
    }

    prompt = _BACKEND._build_issue_prompt(issue)

    assert "concisely in English" in prompt


class _NoopTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


@pytest.mark.asyncio
async def test_rejected_run_does_not_mutate_issue(monkeypatch) -> None:
    """A run rejected for missing assignee leaves cached state untouched."""
    issue = {
        "id": "unassigned",
        "title": "No owner",
        "description": "",
        "status": "backlog",
        "assignee": "",
        "language": "en",
        "updated_at": 1,
    }
    before = copy.deepcopy(issue)

    def read_issues():
        return [issue]

    def transaction():
        return _NoopTransaction()

    monkeypatch.setattr(_BACKEND, "_txn", transaction)
    monkeypatch.setattr(_BACKEND, "_read_all", read_issues)

    with pytest.raises(HTTPException) as exc_info:
        await _BACKEND.run_issue(
            "unassigned",
            language="zh",
            ctx=object(),
        )

    assert exc_info.value.status_code == 400
    assert issue == before
