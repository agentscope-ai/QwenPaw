# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,consider-using-from-import
"""Agent skills: loading resilience, catalog rendering and the viewer tool."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from models import config
import services.external_skills as external_skills
from services.external_skills import load_skills
from services.file_agent_runtime import (
    AgentModelTurn,
    AgentRunStatus,
    AgentToolCall,
    CallbackAgentChatClient,
    FileCreatorAgentRuntime,
)
from services.project_files.facade import CreatorFileServices
from services.project_files.models import Project

pytestmark = pytest.mark.unit

PROJECT_ID = "project-1"
SESSION_ID = "session-1"

_SKILL_MD = """---
name: demo-skill
description: Use when the user asks for a demo tutorial.
---

# Demo Skill

Domain knowledge body: structure scenes as motion_clip Elements.
"""


def _write_skill(root: Path, *, skill_md: str = _SKILL_MD) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return root


def _configure(tmp_path: Path, monkeypatch, entries: list[dict]) -> Path:
    data_root = tmp_path / "creator-data"
    (data_root / "config").mkdir(parents=True, exist_ok=True)
    (data_root / "config" / "skills_config.json").write_text(
        json.dumps({"skills": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(data_root))
    monkeypatch.delenv("CREATOR_SKILLS_CONFIG_PATH", raising=False)
    config._clear_skills_config_cache()
    external_skills._clear_load_cache()
    return data_root


@pytest.fixture(autouse=True)
def _reset_caches():
    yield
    config._clear_skills_config_cache()
    external_skills._clear_load_cache()


# ── Loading resilience ───────────────────────────────────────────────────────


def test_broken_entries_stay_isolated(tmp_path, monkeypatch) -> None:
    """Bad path / bad SKILL.md / invalid entry never raise, only mark."""

    good = _write_skill(tmp_path / "good")
    bad_md = tmp_path / "bad-md"
    bad_md.mkdir()
    (bad_md / "SKILL.md").write_text("no front matter", encoding="utf-8")
    _configure(
        tmp_path,
        monkeypatch,
        [
            {"name": "good", "path": str(good), "enabled": True},
            {"name": "ghost", "path": str(tmp_path / "nope"), "enabled": True},
            {"name": "bad-md", "path": str(bad_md), "enabled": True},
            {"name": "off", "path": str(good), "enabled": False},
            {"name": "Bad Entry ~~"},
        ],
    )
    loaded = {skill.entry.name: skill for skill in load_skills()}
    assert loaded["good"].available
    assert not loaded["ghost"].available and loaded["ghost"].reason
    assert not loaded["bad-md"].available
    assert "off" not in loaded  # disabled entries are skipped entirely
    invalid = next(s for s in loaded.values() if "invalid" in (s.reason or ""))
    assert not invalid.available


# ── Driver loop: progressive disclosure end to end ───────────────────────────


def _create_project(tmp_path, *, initial_goal: str):
    services = CreatorFileServices.create(tmp_path.resolve())

    def initialize(staged_root) -> None:
        services.sessions.initialize_staged_project(
            staged_root,
            PROJECT_ID,
            session_id=SESSION_ID,
            conversation_id="conversation-1",
            initial_goal=initial_goal,
            goal_id="goal-1",
            initial_message_id="message-initial",
            initial_client_message_id="client-initial",
        )

    snapshot = services.projects.create(
        Project.new(project_id=PROJECT_ID, name="Initial"),
        initialize_staged_project=initialize,
    )
    services.poller.note_commit(snapshot)
    return services


async def _wait_for(predicate, *, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition was not met in time")
        await asyncio.sleep(0.02)


def test_driver_progressive_disclosure(tmp_path, monkeypatch) -> None:
    """The prompt carries only the catalog; view_skill returns the body
    verbatim without requesting any execution authorization."""

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    skill_root = _write_skill(tmp_path / "demo-src")
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "skills_config.json").write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "name": "demo-skill",
                        "path": str(skill_root),
                        "enabled": True,
                    },
                    {"name": "broken entry ~~ not valid"},
                ],
            },
        ),
        encoding="utf-8",
    )
    config._clear_skills_config_cache()
    external_skills._clear_load_cache()
    turn = 0

    async def callback(messages, tools):
        nonlocal turn
        names = {item["function"]["name"] for item in tools}
        assert "view_skill" in names
        assert "<name>demo-skill</name>" in messages[0]["content"]
        # Progressive disclosure: the SKILL.md body never rides the prompt,
        # and the broken config entry is invisible to the model.
        assert "# Demo Skill" not in messages[0]["content"]
        assert "broken entry" not in messages[0]["content"]
        turn += 1
        if turn == 1:
            return AgentModelTurn(
                tool_calls=(
                    AgentToolCall(
                        call_id="view-1",
                        name="view_skill",
                        arguments={"skill": "demo-skill"},
                    ),
                ),
            )
        return AgentModelTurn(content="已阅读 skill 说明。")

    async def scenario():
        services = _create_project(tmp_path, initial_goal="查看 demo skill")
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        messages = services.sessions.list_messages(PROJECT_ID, SESSION_ID)
        runs = driver.runs.list(PROJECT_ID)
        authorizations = driver.executions.list_execution_authorizations(
            PROJECT_ID,
        )
        await driver.stop()
        return messages, runs, authorizations

    messages, runs, authorizations = asyncio.run(scenario())
    assert runs[0].status is AgentRunStatus.SUCCEEDED
    tool_results = [item for item in messages if item.role == "tool"]
    payload = json.loads(tool_results[0].content_parts[0].text or "{}")
    assert payload["ok"] is True
    assert payload["content"] == _SKILL_MD
    # Viewing domain knowledge is read-only: no authorization records.
    assert authorizations == []


def test_skill_loading_runs_off_the_event_loop(tmp_path, monkeypatch) -> None:
    """Skill discovery scans disk and may probe node; never on the loop.

    The review's case: a slow requirement probe inside
    ``load_external_skills()`` froze every coroutine in the process for up
    to 10 seconds because the model loop called it synchronously.
    """

    import threading

    from services.file_agent_runtime import driver as driver_module

    monkeypatch.setenv("CREATOR_DATA_ROOT", str(tmp_path))
    config._clear_skills_config_cache()
    external_skills._clear_load_cache()

    real_load = driver_module.load_external_skills
    load_threads: list[int] = []

    def recording_load():
        load_threads.append(threading.get_ident())
        return real_load()

    monkeypatch.setattr(
        driver_module,
        "load_external_skills",
        recording_load,
    )

    async def callback(_messages, _tools):
        return AgentModelTurn(content="好的。")

    async def scenario() -> int:
        services = _create_project(tmp_path, initial_goal="问候")
        driver = FileCreatorAgentRuntime(
            services,
            model_client=CallbackAgentChatClient(callback),
            poll_interval_seconds=0.01,
        )
        await driver.start()
        driver.notify(PROJECT_ID)
        await _wait_for(
            lambda: (
                services.sessions.get_project_session(
                    PROJECT_ID,
                ).last_consumed_message_seq
                == 1
            ),
        )
        await driver.wait_until_idle(PROJECT_ID)
        await driver.stop()
        return threading.get_ident()

    loop_thread = asyncio.run(scenario())

    assert load_threads, "the model loop must have loaded external skills"
    assert all(thread != loop_thread for thread in load_threads)
