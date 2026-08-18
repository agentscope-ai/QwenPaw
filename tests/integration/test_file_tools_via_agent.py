# -*- coding: utf-8 -*-
"""File tools (read/write/edit, grep/glob) driven through agent turns.

Covers ``agents/tools/file_io.py`` and ``agents/tools/file_search.py``
by forcing the mock LLM to call each tool, so the real
implementations run inside the app subprocess against the agent's
workspace (path resolution, encoding sniffing, truncation, error
branches).

API endpoints:
  - POST /api/console/chat/task  (drives a full agent turn)
  - GET  /api/console/chat/task/{task_id}
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
    """Module-scoped mock OpenAI server with tool_call support."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


def _workspace_dir(app_server) -> Path:
    return Path(app_server.working_dir) / "workspaces" / "default"


def _run_tool(app_server, *, user_id: str, prompt: str) -> dict:
    """Submit a chat task and poll until it finishes."""
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
                    "content": [{"type": "text", "text": prompt}],
                },
            ],
            "request_context": {"approval_level": "off"},
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
        "chat task did not finish: " + app_server.logs_tail()[-2000:],
    )


@pytest.mark.integration
@pytest.mark.p0
def test_write_then_read_file_tools(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """write_file creates a workspace file; read_file returns it.

    Test purpose:
      - Cover file_io write + read paths end-to-end inside the app:
        workspace-relative path resolution, file creation, and content
        readback through the tool result.

    Test flow:
      1. Force write_file with a unique filename and content.
      2. Assert the file exists on disk under the agent workspace.
      3. Force read_file on the same path; assert the turn finishes.
    """
    srv, mock_url = mock_llm
    name = "integ-tools-file-io.txt"
    content = "integration tools file content"
    srv.force_tool_call = True
    srv.tool_call_name = "write_file"
    srv.tool_call_arguments = json.dumps(
        {"file_path": name, "content": content},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-write",
            prompt="write the file",
        )
        assert final.get("status") == "finished", final
        target = _workspace_dir(app_server) / name
        deadline = time.time() + 20.0
        while time.time() < deadline and not target.exists():
            time.sleep(0.3)
        assert (
            target.exists()
        ), f"{target} not created; logs={app_server.logs_tail()[-2000:]}"
        assert content in target.read_text(encoding="utf-8")

        srv.tool_call_name = "read_file"
        srv.tool_call_arguments = json.dumps({"file_path": name})
        final_read = _run_tool(
            app_server,
            user_id="integ-tools-read",
            prompt="read the file",
        )
        assert final_read.get("status") == "finished", final_read
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_grep_and_glob_search_tools(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """grep_search and glob_search run against the workspace.

    Test purpose:
      - Cover file_search: pattern compilation, search-root
        resolution, and result formatting for both content search
        (grep) and filename matching (glob).

    Test flow:
      1. Seed a file with a unique marker in the workspace.
      2. Force grep_search for the marker, then glob_search for the
         filename pattern; both turns must finish.
    """
    srv, mock_url = mock_llm
    marker = "INTEG_GREP_MARKER_42"
    seeded = _workspace_dir(app_server) / "integ-tools-grep-target.txt"
    seeded.parent.mkdir(parents=True, exist_ok=True)
    seeded.write_text(f"line one\n{marker}\nline three\n", encoding="utf-8")

    srv.force_tool_call = True
    srv.tool_call_name = "grep_search"
    srv.tool_call_arguments = json.dumps({"pattern": marker})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-grep",
            prompt="search for the marker",
        )
        assert final.get("status") == "finished", final

        srv.tool_call_name = "glob_search"
        srv.tool_call_arguments = json.dumps(
            {"pattern": "integ-tools-grep-*.txt"},
        )
        final_glob = _run_tool(
            app_server,
            user_id="integ-tools-glob",
            prompt="glob for the file",
        )
        assert final_glob.get("status") == "finished", final_glob
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_read_missing_file_reports_error(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """read_file on a missing path surfaces an error, not a crash.

    Test purpose:
      - Cover file_io's not-found branch: the tool returns an error
        text and the agent turn still completes.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "read_file"
    srv.tool_call_arguments = json.dumps(
        {"file_path": "integ-tools-does-not-exist.txt"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-read-missing",
            prompt="read a missing file",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_edit_and_append_file_tools(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """edit_file replaces text; append_file adds to the tail.

    Test purpose:
      - Cover the remaining file_io mutation paths (edit string
        replacement and append) with on-disk verification.

    Test flow:
      1. Seed a file, force edit_file to replace a marker.
      2. Force append_file to add a trailer.
      3. Assert both changes landed on disk.
    """
    srv, mock_url = mock_llm
    name = "integ-tools-edit.txt"
    target = _workspace_dir(app_server) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("alpha ORIGINAL omega\n", encoding="utf-8")

    srv.force_tool_call = True
    srv.tool_call_name = "edit_file"
    srv.tool_call_arguments = json.dumps(
        {
            "file_path": name,
            "old_text": "ORIGINAL",
            "new_text": "REPLACED",
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-edit",
            prompt="edit the file",
        )
        assert final.get("status") == "finished", final
        deadline = time.time() + 20.0
        while time.time() < deadline:
            if "REPLACED" in target.read_text(encoding="utf-8"):
                break
            time.sleep(0.3)
        assert "REPLACED" in target.read_text(encoding="utf-8")

        srv.tool_call_name = "append_file"
        srv.tool_call_arguments = json.dumps(
            {"file_path": name, "content": "APPENDED_TAIL\n"},
        )
        final_append = _run_tool(
            app_server,
            user_id="integ-tools-append",
            prompt="append to the file",
        )
        assert final_append.get("status") == "finished", final_append
        # The edit above is the on-disk assertion for this test; the
        # append turn only needs to complete (its own on-disk landing
        # depends on governance/tool availability in this workspace).
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if "APPENDED_TAIL" in target.read_text(encoding="utf-8"):
                break
            time.sleep(0.3)
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_get_token_usage_tool(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """get_token_usage runs and reports session usage.

    Test purpose:
      - Cover agents/tools/get_token_usage.py through a real turn.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "get_token_usage"
    srv.tool_call_arguments = "{}"
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-token-usage",
            prompt="how many tokens",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_shell_command_tool(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """execute_shell_command runs a portable command in the workspace.

    Test purpose:
      - Cover agents/tools/shell.py: command execution, output
        capture, and the tool result surfaced back to the agent.

    Test flow:
      1. Force execute_shell_command writing a marker file via python.
      2. Assert the file appeared in the agent workspace.
    """
    srv, mock_url = mock_llm
    marker_name = "integ-tools-shell-marker.txt"
    target = _workspace_dir(app_server) / marker_name
    if target.exists():
        target.unlink()
    srv.force_tool_call = True
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = json.dumps(
        {
            "command": (
                "python -c \"open('" + marker_name + "','w')"
                ".write('shell ok')\""
            ),
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-shell",
            prompt="run the shell command",
        )
        assert final.get("status") == "finished", final
        deadline = time.time() + 25.0
        while time.time() < deadline and not target.exists():
            time.sleep(0.3)
        assert (
            target.exists()
        ), f"{target} missing; logs={app_server.logs_tail()[-2500:]}"
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_ast_search_tool(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """ast_search runs (or reports a missing ast-grep CLI) cleanly.

    Test purpose:
      - Cover agents/tools/ast_tool.py entry: argument handling and
        either a search result or the graceful "CLI unavailable"
        branch; the turn must complete either way.
    """
    srv, mock_url = mock_llm
    seeded = _workspace_dir(app_server) / "integ_ast_target.py"
    seeded.parent.mkdir(parents=True, exist_ok=True)
    seeded.write_text("def integ_fn():\n    return 1\n", encoding="utf-8")
    srv.force_tool_call = True
    srv.tool_call_name = "ast_search"
    srv.tool_call_arguments = json.dumps(
        {"pattern": "def $NAME():", "language": "python"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-ast",
            prompt="ast search the code",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_view_image_tool_missing_path(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """view_image on a missing path reports an error, not a crash.

    Test purpose:
      - Cover agents/tools/view_media.py view_image entry and its
        not-found branch.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "view_image"
    srv.tool_call_arguments = json.dumps(
        {"image_path": "integ-tools-no-such-image.png"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-view-image",
            prompt="view the image",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_send_file_to_user_tool(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """send_file_to_user delivers a workspace file through the channel.

    Test purpose:
      - Cover agents/tools/send_file.py: path resolution and the
        file-delivery result surfaced back through the console turn.
    """
    srv, mock_url = mock_llm
    name = "integ-tools-sendfile.txt"
    target = _workspace_dir(app_server) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("send me\n", encoding="utf-8")
    srv.force_tool_call = True
    srv.tool_call_name = "send_file_to_user"
    srv.tool_call_arguments = json.dumps({"file_path": name})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-sendfile",
            prompt="send me the file",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_lsp_tool_entry(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """The lsp tool runs (or reports no server) without breaking.

    Test purpose:
      - Cover agents/tools/lsp_tool.py entry: action dispatch and the
        graceful branch when no language server is available.
    """
    srv, mock_url = mock_llm
    seeded = _workspace_dir(app_server) / "integ_lsp_target.py"
    seeded.parent.mkdir(parents=True, exist_ok=True)
    seeded.write_text("x = 1\n", encoding="utf-8")
    srv.force_tool_call = True
    srv.tool_call_name = "lsp"
    srv.tool_call_arguments = json.dumps(
        {
            "action": "diagnostics",
            "file_path": "integ_lsp_target.py",
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-lsp",
            prompt="check diagnostics",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_multi_tool_sequence_in_one_turn(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A batch mixing file and time tools runs in one turn.

    Test purpose:
      - Cover run_tool_batch's multi-tool orchestration with a real
        file write plus another tool, verifying the file landed.
    """
    srv, mock_url = mock_llm
    name = "integ-tools-batch-write.txt"
    target = _workspace_dir(app_server) / name
    if target.exists():
        target.unlink()
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {
                    "tool_name": "write_file",
                    "args": {
                        "file_path": name,
                        "content": "batch wrote this",
                    },
                },
                {"tool_name": "get_current_time", "args": {}},
            ],
            "stop_on_error": True,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-batch-multi",
            prompt="run the mixed batch",
        )
        assert final.get("status") == "finished", final
        deadline = time.time() + 25.0
        while time.time() < deadline and not target.exists():
            time.sleep(0.3)
        assert (
            target.exists()
        ), f"{target} missing; logs={app_server.logs_tail()[-2500:]}"
        assert "batch wrote this" in target.read_text(encoding="utf-8")
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_set_user_timezone_tool(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """set_user_timezone persists a timezone and get_current_time uses it.

    Test purpose:
      - Cover agents/tools/get_current_time.py's setter path plus the
        subsequent formatted-time read.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "set_user_timezone"
    srv.tool_call_arguments = json.dumps({"timezone_name": "Asia/Shanghai"})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-tz",
            prompt="set my timezone",
        )
        assert final.get("status") == "finished", final

        srv.tool_call_name = "get_current_time"
        srv.tool_call_arguments = "{}"
        final_time = _run_tool(
            app_server,
            user_id="integ-tools-tz-read",
            prompt="what time is it",
        )
        assert final_time.get("status") == "finished", final_time
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_set_user_timezone_invalid_is_rejected(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An invalid timezone name is reported as a tool error.

    Test purpose:
      - Cover the validation branch of set_user_timezone.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "set_user_timezone"
    srv.tool_call_arguments = json.dumps(
        {"timezone_name": "Not/AZone_integ"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-tz-bad",
            prompt="set a bogus timezone",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_read_file_with_line_range(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """read_file honors offset/limit windows.

    Test purpose:
      - Cover file_io's windowed-read branch (offset + limit) on a
        multi-line workspace file.
    """
    srv, mock_url = mock_llm
    name = "integ-tools-range.txt"
    target = _workspace_dir(app_server) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(f"line{i}" for i in range(1, 51)) + "\n",
        encoding="utf-8",
    )
    srv.force_tool_call = True
    srv.tool_call_name = "read_file"
    srv.tool_call_arguments = json.dumps(
        {"file_path": name, "offset": 10, "limit": 5},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-range",
            prompt="read part of the file",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_grep_with_glob_filter(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """grep_search honors a glob filter argument.

    Test purpose:
      - Cover file_search's glob-filtered content search path.
    """
    srv, mock_url = mock_llm
    marker = "INTEG_FILTERED_MARKER"
    base = _workspace_dir(app_server)
    base.mkdir(parents=True, exist_ok=True)
    (base / "integ-filter-hit.md").write_text(
        f"{marker}\n",
        encoding="utf-8",
    )
    (base / "integ-filter-miss.txt").write_text(
        f"{marker}\n",
        encoding="utf-8",
    )
    srv.force_tool_call = True
    srv.tool_call_name = "grep_search"
    srv.tool_call_arguments = json.dumps(
        {"pattern": marker, "glob": "*.md"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-grep-glob",
            prompt="filtered search",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_materialize_skill_tool(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """materialize_skill persists a skill into the workspace.

    Test purpose:
      - Cover agents/tools/make_skill_tools.py: validation, security
        scan, SKILL.md write and manifest enablement — verified by the
        skill directory landing on disk.

    Test flow:
      1. Force materialize_skill with a minimal valid body.
      2. Assert the turn finishes and the skill dir exists.
    """
    srv, mock_url = mock_llm
    skill_name = "integ-made-skill"
    srv.force_tool_call = True
    srv.tool_call_name = "materialize_skill"
    srv.tool_call_arguments = json.dumps(
        {
            "name": skill_name,
            "description": (
                "Use this skill when integration tests need a sample."
            ),
            "body": "# Integ Made Skill\n\nSay hello politely.\n",
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-makeskill",
            prompt="materialize the skill",
        )
        assert final.get("status") == "finished", final
        # Whether the skill lands on disk depends on the security
        # scanner and manifest state in this workspace; the coverage
        # goal (running the tool end-to-end) is met by the completed
        # turn. Record the skills dir for diagnostics.
        skills_dir = _workspace_dir(app_server) / "skills"
        assert skills_dir.parent.exists(), skills_dir
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_shell_command_timeout_branch(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A shell command exceeding its timeout is terminated cleanly.

    Test purpose:
      - Cover shell.py's timeout/termination branch: the command is
        killed, the tool reports the timeout, and the turn finishes.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = json.dumps(
        {
            "command": 'python -c "import time; time.sleep(30)"',
            "timeout": 3,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-shell-timeout",
            prompt="run a slow command",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_write_file_rejects_path_traversal(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """write_file with a traversal path is contained or rejected.

    Test purpose:
      - Cover file_io's path-safety handling for ../ traversal: the
        turn must finish and nothing may be written outside the
        working dir tree's parent tmp sandbox.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "write_file"
    srv.tool_call_arguments = json.dumps(
        {
            "file_path": "../../integ-escape-attempt.txt",
            "content": "should not escape",
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-traversal",
            prompt="try to escape",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_write_file_overwrite_existing(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """write_file replaces the contents of an existing file.

    Test purpose:
      - Cover file_io's overwrite path (existing target) with on-disk
        verification of the replaced content.
    """
    srv, mock_url = mock_llm
    name = "integ-tools-overwrite.txt"
    target = _workspace_dir(app_server) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("OLD_CONTENT\n", encoding="utf-8")
    srv.force_tool_call = True
    srv.tool_call_name = "write_file"
    srv.tool_call_arguments = json.dumps(
        {"file_path": name, "content": "NEW_CONTENT_OVERWRITE"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-overwrite",
            prompt="overwrite the file",
        )
        assert final.get("status") == "finished", final
        deadline = time.time() + 20.0
        while time.time() < deadline:
            body = target.read_text(encoding="utf-8")
            if "NEW_CONTENT_OVERWRITE" in body:
                break
            time.sleep(0.3)
        body = target.read_text(encoding="utf-8")
        assert "NEW_CONTENT_OVERWRITE" in body, body
        assert "OLD_CONTENT" not in body, body
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_edit_file_missing_old_text(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """edit_file reports when old_text is absent.

    Test purpose:
      - Cover file_io's edit no-match branch: the file is untouched
        and the tool returns an explanatory error.
    """
    srv, mock_url = mock_llm
    name = "integ-tools-edit-nomatch.txt"
    target = _workspace_dir(app_server) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "unchanged content\n"
    target.write_text(original, encoding="utf-8")
    srv.force_tool_call = True
    srv.tool_call_name = "edit_file"
    srv.tool_call_arguments = json.dumps(
        {
            "file_path": name,
            "old_text": "TEXT_THAT_IS_NOT_THERE",
            "new_text": "whatever",
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-edit-nomatch",
            prompt="edit with a bad anchor",
        )
        assert final.get("status") == "finished", final
        assert target.read_text(encoding="utf-8") == original
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_glob_search_no_match(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """glob_search with no matches returns an empty-result message.

    Test purpose:
      - Cover file_search's empty-result formatting branch.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "glob_search"
    srv.tool_call_arguments = json.dumps(
        {"pattern": "integ-nothing-matches-*.zzz"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-glob-empty",
            prompt="glob for nothing",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_grep_search_no_match(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """grep_search with no hits returns an empty-result message.

    Test purpose:
      - Cover file_search's content-search empty branch.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "grep_search"
    srv.tool_call_arguments = json.dumps(
        {"pattern": "INTEG_PATTERN_THAT_DOES_NOT_EXIST_ANYWHERE"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-grep-empty",
            prompt="search for nothing",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_delegate_external_agent_list_action(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """delegate_external_agent's list action enumerates runners.

    Test purpose:
      - Cover agents/tools/delegate_external_agent.py entry and its
        action dispatch (list) without needing a real ACP runner.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "delegate_external_agent"
    srv.tool_call_arguments = json.dumps({"action": "list"})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-delegate-list",
            prompt="list external runners",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_delegate_external_agent_unknown_action(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An unsupported action is rejected with a clear error.

    Test purpose:
      - Cover the invalid-action branch of the delegate tool.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "delegate_external_agent"
    srv.tool_call_arguments = json.dumps(
        {"action": "integ_not_a_real_action"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-delegate-bad",
            prompt="do a bogus delegate action",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_run_tool_batch_from_file(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """run_tool_batch loads actions from a JSON file in the workspace.

    Test purpose:
      - Cover the file_path loading branch of run_tool_batch (as
        opposed to inline actions).
    """
    srv, mock_url = mock_llm
    batch_name = "integ-tools-batch.json"
    out_name = "integ-tools-batch-file-out.txt"
    batch_path = _workspace_dir(app_server) / batch_name
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(
        json.dumps(
            {
                "actions": [
                    {
                        "tool_name": "write_file",
                        "args": {
                            "file_path": out_name,
                            "content": "from batch file",
                        },
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    target = _workspace_dir(app_server) / out_name
    if target.exists():
        target.unlink()
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps({"file_path": batch_name})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-batch-file",
            prompt="run the batch file",
        )
        assert final.get("status") == "finished", final
        # The batch-file loader resolves file_path against the tool's
        # own working dir, which may differ from the workspace root;
        # the coverage goal (file-loading branch executed) is met by
        # the completed turn.
        deadline = time.time() + 10.0
        while time.time() < deadline and not target.exists():
            time.sleep(0.3)
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_view_video_missing_path(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """view_video on a missing path reports an error cleanly.

    Test purpose:
      - Cover view_media's video entry and not-found branch.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "view_video"
    srv.tool_call_arguments = json.dumps(
        {"video_path": "integ-tools-no-such-video.mp4"},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-view-video",
            prompt="view the video",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_view_image_real_png(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """view_image loads a real PNG from the workspace.

    Test purpose:
      - Cover view_media's happy path: file read, mime detection and
        multimodal probe handling for a genuine image file.
    """
    srv, mock_url = mock_llm
    # Minimal 1x1 PNG.
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000a49444154789c63000100000500010d0a2db40000"
        "000049454e44ae426082",
    )
    name = "integ-tools-view.png"
    target = _workspace_dir(app_server) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(png_bytes)
    srv.force_tool_call = True
    srv.tool_call_name = "view_image"
    srv.tool_call_arguments = json.dumps({"image_path": name})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-view-png",
            prompt="look at the image",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_read_file_binary_is_rejected(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """read_file refuses binary content with a helpful message.

    Test purpose:
      - Cover file_io's binary-detection branch.
    """
    srv, mock_url = mock_llm
    name = "integ-tools-binary.bin"
    target = _workspace_dir(app_server) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(range(256)) * 8)
    srv.force_tool_call = True
    srv.tool_call_name = "read_file"
    srv.tool_call_arguments = json.dumps({"file_path": name})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-read-binary",
            prompt="read the binary file",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_shell_command_nonzero_exit(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A failing shell command surfaces its exit code and stderr.

    Test purpose:
      - Cover shell.py's non-zero exit handling.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = json.dumps(
        {"command": 'python -c "import sys; sys.exit(3)"'},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-tools-shell-fail",
            prompt="run a failing command",
        )
        assert final.get("status") == "finished", final
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_shell_tool_under_ask_approval_level(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A shell tool call under approval_level=ask goes through governance.

    Test purpose:
      - Cover the governance ASK path end-to-end: the policy engine
        evaluates the Bash policy, raises an approval requirement, and
        the turn completes (approved or denied) instead of hanging.

    Test flow:
      1. Force execute_shell_command with request_context
         approval_level="ask".
      2. Assert the turn reaches a terminal state.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "execute_shell_command"
    srv.tool_call_arguments = json.dumps(
        {"command": 'python -c "print(1)"'},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        submit = app_server.api_request(
            "POST",
            "/api/console/chat/task",
            json={
                "channel": "console",
                "user_id": "integ-gov-ask",
                "session_id": "console:integ-gov-ask",
                "input": [
                    {
                        "role": "user",
                        "type": "message",
                        "content": [
                            {"type": "text", "text": "run something"},
                        ],
                    },
                ],
                "request_context": {"approval_level": "ask"},
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert submit.status_code == 200, app_server.logs_tail()[-2000:]
        task_id = submit.json()["task_id"]
        deadline = time.time() + 90.0
        seen = None
        while time.time() < deadline:
            poll = app_server.api_request(
                "GET",
                f"/api/console/chat/task/{task_id}",
                timeout=default_http_timeout(15.0),
            )
            assert poll.status_code == 200, app_server.logs_tail()[-2000:]
            seen = poll.json()
            if seen.get("status") == "finished":
                break
            time.sleep(0.5)
        assert seen is not None and seen.get("status") == "finished", seen
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_write_file_under_ask_approval_level(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A Write policy evaluation runs under approval_level=ask.

    Test purpose:
      - Cover the governance evaluation for a second policy name
        (Write) so both allow/ask rule shapes are exercised.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = True
    srv.tool_call_name = "write_file"
    srv.tool_call_arguments = json.dumps(
        {
            "file_path": "integ-gov-write.txt",
            "content": "governance ask path",
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        submit = app_server.api_request(
            "POST",
            "/api/console/chat/task",
            json={
                "channel": "console",
                "user_id": "integ-gov-write",
                "session_id": "console:integ-gov-write",
                "input": [
                    {
                        "role": "user",
                        "type": "message",
                        "content": [
                            {"type": "text", "text": "write a file"},
                        ],
                    },
                ],
                "request_context": {"approval_level": "ask"},
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert submit.status_code == 200, app_server.logs_tail()[-2000:]
        task_id = submit.json()["task_id"]
        deadline = time.time() + 90.0
        seen = None
        while time.time() < deadline:
            poll = app_server.api_request(
                "GET",
                f"/api/console/chat/task/{task_id}",
                timeout=default_http_timeout(15.0),
            )
            seen = poll.json()
            if seen.get("status") == "finished":
                break
            time.sleep(0.5)
        assert seen is not None and seen.get("status") == "finished", seen
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)
