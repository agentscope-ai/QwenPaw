# -*- coding: utf-8 -*-
"""Agent-management tools driven through a real agent turn.

Covers ``agents/tools/agent_management.py`` by forcing the mock LLM to
emit tool calls for the internal agent-management tools, so the real
tool implementations run inside the app subprocess and hit the local
API (list_agents) or the agent-to-agent path (chat_with_agent).

Coverage targets:
  list_agents / list_agents_data / resolve_agent_api_base_url /
  create_agent_api_client / _tool_text_response / _json_text and the
  chat_with_agent argument-validation branches.

API endpoints:
  - POST /api/console/chat  (drives a full agent turn)
  - GET  /api/agents
"""
from __future__ import annotations

import json
import threading
import time
from http.server import HTTPServer

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
    """Module-scoped mock OpenAI server with tool_call support."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


def _chat_once(app_server, user_id: str, text: str):
    """Run one console chat task to completion; return final payload."""
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
                    "content": [{"type": "text", "text": text}],
                },
            ],
            "request_context": {"approval_level": "off"},
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert submit.status_code == 200, app_server.logs_tail()[-2000:]
    task_id = submit.json()["task_id"]
    deadline = time.time() + 240.0
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
        "chat task did not finish: " + app_server.logs_tail()[-2000:],
    )


@pytest.mark.integration
@pytest.mark.p1
def test_list_agents_tool_runs_against_local_api(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """The list_agents tool executes and returns the agent roster.

    Test purpose:
      - Run the real list_agents tool inside the app: it resolves the
        local API base URL, calls GET /api/agents through the internal
        client, and returns JSON text containing the default agent.

    Test flow:
      1. Force the mock LLM to call list_agents.
      2. Assert the turn completes and the agent id appears in the
         tool result surfaced back through the chat response.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "list_agents"
    srv.tool_call_arguments = "{}"
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _chat_once(
            app_server,
            "integ-tools-list-agents",
            "list the agents",
        )
        body = json.dumps(final, ensure_ascii=False)
        assert "default" in body, body[:1500]
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_chat_with_agent_unknown_target_is_handled(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """chat_with_agent against an unknown agent returns an error text.

    Test purpose:
      - Cover the agent-to-agent path's failure branch: the tool runs,
        resolves ids, calls the local API, and surfaces the 404 as a
        tool error instead of crashing the turn.

    Test flow:
      1. Force a chat_with_agent tool call with a bogus to_agent.
      2. Assert the turn still completes (200).
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "chat_with_agent"
    srv.tool_call_arguments = json.dumps(
        {
            "to_agent": "integ-nonexistent-agent",
            "message": "ping",
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _chat_once(
            app_server,
            "integ-tools-chat-agent",
            "talk to the other agent",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_run_tool_batch_inline_actions(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """run_tool_batch executes inline actions sequentially.

    Test purpose:
      - Cover agents/tools/run_tool_batch.py: inline ``actions``
        parsing, sequential execution of a registered tool, and the
        aggregated tool result.

    Test flow:
      1. Force a run_tool_batch call with two get_current_time steps.
      2. Assert the turn finishes (batch executed without error).
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {"tool_name": "get_current_time", "args": {}},
                {"tool_name": "get_current_time", "args": {}},
            ],
            "stop_on_error": True,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _chat_once(
            app_server,
            "integ-tools-batch",
            "run the batch",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_run_tool_batch_unknown_tool_reports_error(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An unknown tool_name in the batch is reported, not fatal.

    Test purpose:
      - Cover the batch error branch: unknown tool resolution fails,
        stop_on_error halts the batch, and the turn still completes.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {"tool_name": "integ_no_such_tool", "args": {}},
            ],
            "stop_on_error": True,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _chat_once(
            app_server,
            "integ-tools-batch-err",
            "run the bad batch",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_spawn_subagent_tool(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """spawn_subagent runs an ephemeral subagent in the workspace.

    Test purpose:
      - Cover the spawn path in agent_management: argument coercion,
        subagent construction and result aggregation.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "spawn_subagent"
    srv.tool_call_arguments = json.dumps(
        {"task": "say hello", "timeout": 60},
    )
    # The spawned subagent's own turn also reaches the mock LLM; without
    # this gate it would be forced to spawn again and recurse until the
    # request times out. Only the parent prompt carries the marker.
    marker = "INTEG-SPAWN-PARENT"
    srv.force_tool_call_user_marker = marker
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _chat_once(
            app_server,
            "integ-tools-spawn",
            f"{marker} spawn a subagent",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        srv.force_tool_call_user_marker = None
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_submit_to_agent_unknown_target(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """submit_to_agent against an unknown agent reports the failure.

    Test purpose:
      - Cover the background-submit path and its 404 branch.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "submit_to_agent"
    srv.tool_call_arguments = json.dumps(
        {"to_agent": "integ-nonexistent-agent", "text": "ping"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _chat_once(
            app_server,
            "integ-tools-submit",
            "submit to the other agent",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_check_agent_task_unknown_id(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """check_agent_task with an unknown task id returns not-found.

    Test purpose:
      - Cover the task-status lookup path and its missing-task branch.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "check_agent_task"
    srv.tool_call_arguments = json.dumps(
        {"task_id": "integ-no-such-task-id"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _chat_once(
            app_server,
            "integ-tools-checktask",
            "check the task",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_spawn_subagent_batch(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """spawn_subagent batch mode dispatches several subagents.

    Test purpose:
      - Cover _spawn_batch: spec normalization, parallel dispatch and
        aggregated reporting.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "spawn_subagent"
    srv.tool_call_arguments = json.dumps(
        {
            "task": "batch parent",
            "batch": [
                {"task": "sub one"},
                {"task": "sub two"},
            ],
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _chat_once(
            app_server,
            "integ-tools-spawn-batch",
            "spawn a batch",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_subagent_empty_batch_rejected(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An empty batch list is rejected with a clear error.

    Test purpose:
      - Cover _spawn_batch's validation branch.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "spawn_subagent"
    srv.tool_call_arguments = json.dumps(
        {"task": "parent", "batch": []},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _chat_once(
            app_server,
            "integ-tools-spawn-empty",
            "spawn an empty batch",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_spawn_subagent_with_allowed_tools(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """spawn_subagent honors an allowed_tools restriction list.

    Test purpose:
      - Cover the tool-allowlist coercion path in spawn_subagent.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "spawn_subagent"
    srv.tool_call_arguments = json.dumps(
        {
            "task": "restricted work",
            "allowed_tools": ["get_current_time"],
            "timeout": 60,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _chat_once(
            app_server,
            "integ-tools-spawn-allowed",
            "spawn with restricted tools",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)
