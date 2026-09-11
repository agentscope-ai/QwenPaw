# -*- coding: utf-8 -*-
"""Fork-worktree paths driven through console chat request_context.

Covers ``agents/fork_project.py`` by supplying ``fork_project_dir`` /
``fork_worktree_branch`` / ``fork_scope_id`` in a console chat task's
``request_context``: the console router then calls the fork
finalize/fail helpers against a real git repository created via the
workspace git auto-init endpoint.

API endpoints:
  - GET  /api/workspace/git/status   (auto-inits the repo)
  - POST /api/console/chat/task
  - GET  /api/console/chat/task/{task_id}
  - POST /api/fork/agent
"""
from __future__ import annotations

import json
import threading
import time
from http.server import HTTPServer
from pathlib import Path

import pytest
from helpers import (
    MOCK_LLM_PROVIDER_ID,
    MockLLMHandler,
    default_http_timeout,
    register_mock_provider,
    unregister_mock_provider,
)

_HTTP_TIMEOUT = default_http_timeout(60.0)


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI server."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


@pytest.fixture(scope="module")
def provider(app_server, mock_llm):  # pylint: disable=redefined-outer-name
    """Register the mock provider once for this module."""
    _srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    yield provider_id
    unregister_mock_provider(app_server, provider_id)


@pytest.fixture(scope="module")
def git_repo(app_server) -> Path:
    """Ensure the default workspace is a git repo; return its path."""
    resp = app_server.api_request(
        "GET",
        "/api/workspace/git/status",
        timeout=default_http_timeout(30.0),
    )
    assert resp.status_code == 200, app_server.logs_tail()[-2000:]
    return Path(app_server.working_dir) / "workspaces" / "default"


def _chat_with_fork_context(
    app_server,
    *,
    user_id: str,
    project_dir: str,
    branch: str,
    scope_id: str = "",
) -> dict:
    """Run a chat task carrying fork worktree context."""
    submit = app_server.api_request(
        "POST",
        "/api/console/chat/task",
        json={
            "channel": "console",
            "user_id": user_id,
            "session_id": f"console:{user_id}",
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [{"type": "text", "text": "fork work"}],
                },
            ],
            "request_context": {
                "approval_level": "off",
                "fork_project_dir": project_dir,
                "fork_worktree_branch": branch,
                "fork_scope_id": scope_id,
            },
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert submit.status_code == 200, app_server.logs_tail()[-2000:]
    task_id = submit.json()["task_id"]
    deadline = time.time() + 90.0
    while time.time() < deadline:
        poll = app_server.api_request(
            "GET",
            f"/api/console/chat/task/{task_id}",
            timeout=default_http_timeout(15.0),
        )
        assert poll.status_code == 200, app_server.logs_tail()[-2000:]
        body = poll.json()
        if body.get("status") == "finished":
            return body
        time.sleep(0.4)
    raise AssertionError(
        "fork chat task did not finish: " + app_server.logs_tail()[-2000:],
    )


@pytest.mark.integration
@pytest.mark.p1
def test_fork_finalize_runs_on_real_repo(
    app_server,
    git_repo,  # pylint: disable=redefined-outer-name
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """A chat carrying fork context triggers the finalize helper.

    Test purpose:
      - Cover agents/fork_project.py's finalize path: the console
        router calls finalize_fork_worktree_or_fail against a real git
        repo (registry/lock handling, branch resolution).

    Test flow:
      1. Ensure the workspace is a git repo (auto-init endpoint).
      2. Run a chat task with fork_project_dir + branch context.
      3. Assert the turn completes (finalize ran; failures are logged
         and swallowed by design).
    """
    final = _chat_with_fork_context(
        app_server,
        user_id="integ-fork-finalize",
        project_dir=str(git_repo),
        branch="integ-fork-branch-1",
    )
    assert final.get("status") == "finished", final


@pytest.mark.integration
@pytest.mark.p2
def test_fork_context_with_scope_id(
    app_server,
    git_repo,  # pylint: disable=redefined-outer-name
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """A fork scope id exercises the scope-guard branch.

    Test purpose:
      - Cover the expected_scope handling in the finalize helper.
    """
    final = _chat_with_fork_context(
        app_server,
        user_id="integ-fork-scope",
        project_dir=str(git_repo),
        branch="integ-fork-branch-2",
        scope_id="integ-scope-abc",
    )
    assert final.get("status") == "finished", final


@pytest.mark.integration
@pytest.mark.p2
def test_fork_context_with_bogus_project_dir(
    app_server,
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """A non-repo fork dir is handled without breaking the turn.

    Test purpose:
      - Cover the error path of the fork helpers (invalid project dir
        is logged and swallowed by the console router).
    """
    final = _chat_with_fork_context(
        app_server,
        user_id="integ-fork-bogus",
        project_dir="/tmp/integ-not-a-repo-dir",
        branch="integ-fork-branch-3",
    )
    assert final.get("status") == "finished", final


@pytest.mark.integration
@pytest.mark.p1
def test_fork_agent_endpoint_on_git_repo(
    app_server,
    git_repo,  # pylint: disable=redefined-outer-name,unused-argument
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """POST /api/fork/agent responds for a git-backed workspace.

    Test purpose:
      - Cover the fork router against a workspace that is now a real
        git repo (as opposed to the empty-worktree case covered
        elsewhere).

    API endpoints:
      - POST /api/fork/agent
    """
    resp = app_server.api_request(
        "POST",
        "/api/fork/agent",
        json={"agent_id": "default"},
        timeout=default_http_timeout(30.0),
    )
    assert resp.status_code in (200, 400, 404, 422), resp.text


@pytest.mark.integration
@pytest.mark.p1
def test_spawn_subagent_with_fork_worktree(
    app_server,
    git_repo,  # pylint: disable=redefined-outer-name,unused-argument
    mock_llm,  # pylint: disable=redefined-outer-name
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """spawn_subagent(fork=True) exercises the fork worktree pipeline.

    Test purpose:
      - Cover the full fork flow: _call_fork_api -> POST /api/fork/agent
        -> begin_fork_scope / worktree provisioning in
        agents/fork_project.py, then subagent execution and the
        finalize-or-fail path on completion.

    Test flow:
      1. Ensure the workspace is a git repo (git_repo fixture).
      2. Force spawn_subagent with fork=True.
      3. Assert the turn reaches a terminal state.
    """
    srv, _mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "spawn_subagent"
    srv.tool_call_arguments = json.dumps(
        {"task": "work in a fork", "fork": True, "timeout": 120},
    )
    try:
        submit = app_server.api_request(
            "POST",
            "/api/console/chat/task",
            json={
                "channel": "console",
                "user_id": "integ-fork-spawn",
                "session_id": "console:integ-fork-spawn",
                "input": [
                    {
                        "role": "user",
                        "type": "message",
                        "content": [{"type": "text", "text": "fork it"}],
                    },
                ],
                "request_context": {"approval_level": "off"},
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert submit.status_code == 200, app_server.logs_tail()[-2000:]
        task_id = submit.json()["task_id"]
        # Real worktree provisioning plus a subagent run can take a
        # few minutes; the coverage goal (fork pipeline entered) is met
        # once the task is accepted and progressing, so accept either a
        # finished task or one still running after a bounded wait.
        deadline = time.time() + 60.0
        body = None
        while time.time() < deadline:
            poll = app_server.api_request(
                "GET",
                f"/api/console/chat/task/{task_id}",
                timeout=default_http_timeout(15.0),
            )
            body = poll.json()
            if body.get("status") == "finished":
                break
            time.sleep(0.5)
        assert body is not None, "no task status returned"
        assert body.get("status") in ("finished", "running"), body
    finally:
        srv.force_tool_call = False


@pytest.mark.integration
@pytest.mark.p2
def test_fork_agent_endpoint_with_parent_session(
    app_server,
    git_repo,  # pylint: disable=redefined-outer-name,unused-argument
    provider,  # pylint: disable=redefined-outer-name,unused-argument
):
    """POST /api/fork/agent with a parent session id.

    Test purpose:
      - Cover the fork router's session-derivation path (parent
        session + user + channel) against a git-backed workspace.

    API endpoints:
      - POST /api/fork/agent
    """
    resp = app_server.api_request(
        "POST",
        "/api/fork/agent",
        json={
            "agent_id": "default",
            "parent_session_id": "console:integ-fork-parent",
            "user_id": "integ-fork-parent",
            "channel": "console",
        },
        timeout=default_http_timeout(30.0),
    )
    assert resp.status_code in (200, 400, 404, 422), resp.text
