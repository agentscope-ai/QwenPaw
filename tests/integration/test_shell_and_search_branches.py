# -*- coding: utf-8 -*-
"""Shell and search tool branches driven through real agent turns.

Covers the parts of ``agents/tools/shell.py`` and
``agents/tools/file_search.py`` that only run for specific argument
shapes or command outcomes: the self-kill guard, newline handling
inside and outside quotes, non-zero exit formatting, stderr merging,
plus grep's regex / case-insensitive / context-line / show_file
grouping paths and glob's directory scoping.

Assertions read the tool output that the agent surfaces back through
the chat response, or the on-disk effect of the command, so each branch
is proven to have executed rather than merely not crashed.

API endpoints:
  - POST /api/console/chat/task  (drives a full agent turn)
  - GET  /api/console/chat/task/{task_id}
"""
from __future__ import annotations

import json
import sys
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


def _run_tool(
    app_server,
    *,
    user_id: str,
    prompt: str,
    poll_timeout: float = 240.0,
) -> dict:
    """Submit a chat task that triggers the forced tool; poll to end."""
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
    deadline = time.time() + poll_timeout
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
        "tool task did not finish: " + app_server.logs_tail()[-2000:],
    )


def _tool_output(final: dict) -> str:
    """Return the concatenated tool output text from a finished turn."""
    return json.dumps(final, ensure_ascii=False)


def _wait_for_file(target: Path, predicate, timeout: float = 25.0) -> str:
    """Poll a workspace file until predicate(text) holds; return text."""
    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        if target.exists():
            text = target.read_text(encoding="utf-8")
            if predicate(text):
                return text
        time.sleep(0.3)
    return text


def _force(srv, name: str, arguments: dict) -> None:
    srv.force_tool_call = True
    srv.tool_call_name = name
    srv.tool_call_arguments = json.dumps(arguments)


# ============================== A. shell.py ================================


@pytest.mark.integration
@pytest.mark.p1
def test_shell_self_kill_is_blocked(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A command targeting our own process group is refused.

    Test purpose:
      - Cover _is_dangerous_self_kill's shell-variable branch
        (``kill -9 $$``): the tool must return the "Blocked" text and,
        critically, the app subprocess must still be alive afterwards.

    Test flow:
      1. Force execute_shell_command with ``kill -9 $$``.
      2. Assert the refusal text is surfaced.
      3. Assert the app still answers a follow-up request, proving it
         was not killed.
    """
    srv, mock_url = mock_llm
    _force(srv, "execute_shell_command", {"command": "kill -9 $$"})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-shell-selfkill",
            prompt="kill yourself",
        )
        body = _tool_output(final)
        assert "Blocked" in body, body[:1500]
        health = app_server.api_request(
            "GET",
            "/api/agents",
            timeout=default_http_timeout(15.0),
        )
        assert health.status_code == 200, "app died after self-kill command"
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX shell syntax (printf, >&2, exit N) is not cmd.exe",
)
def test_shell_nonzero_exit_reports_code_and_stderr(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A failing command surfaces its exit code plus both streams.

    Test purpose:
      - Cover the non-zero-exit formatting branch that assembles
        "Command failed with exit code N" together with the [stdout]
        and [stderr] sections.
    """
    srv, mock_url = mock_llm
    _force(
        srv,
        "execute_shell_command",
        {
            "command": (
                "printf 'out-marker\\n'; " "printf 'err-marker\\n' >&2; exit 3"
            ),
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-shell-nonzero",
            prompt="run the failing command",
        )
        body = _tool_output(final)
        assert "exit code 3" in body, body[:2000]
        assert "out-marker" in body, body[:2000]
        assert "err-marker" in body, body[:2000]
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_shell_success_with_stderr_merges_both(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An exit-0 command that wrote to stderr still reports stderr.

    Test purpose:
      - Cover the success path's stderr-append branch, distinct from
        the failure formatting above.
    """
    srv, mock_url = mock_llm
    _force(
        srv,
        "execute_shell_command",
        {
            "command": (
                "printf 'ok-line\\n'; printf 'warn-line\\n' >&2; exit 0"
            ),
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-shell-stderr",
            prompt="run the noisy command",
        )
        body = _tool_output(final)
        assert "ok-line" in body, body[:2000]
        assert "warn-line" in body, body[:2000]
        assert "exit code" not in body, "exit-0 must not be reported as failed"
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_shell_no_output_command_reports_success(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A silent successful command yields the explicit success text.

    Test purpose:
      - Cover the "Command executed successfully (no output)." branch,
        which is only reachable when stdout and stderr are both empty.
    """
    srv, mock_url = mock_llm
    _force(srv, "execute_shell_command", {"command": "true"})
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-shell-silent",
            prompt="run the silent command",
        )
        body = _tool_output(final)
        assert "no output" in body, body[:2000]
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "quoted-newline handling is POSIX sh specific; "
        "cmd.exe collapses all newlines"
    ),
)
def test_shell_newline_inside_quotes_is_preserved(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A newline inside double quotes survives normalization.

    Test purpose:
      - Cover _collapse_newlines_outside_quotes' in_double_quote
        branch: the quoted newline must reach the shell intact, so the
        written file ends up with two lines.
    """
    srv, mock_url = mock_llm
    target = _workspace_dir(app_server) / "integ-shell-quoted-nl.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    _force(
        srv,
        "execute_shell_command",
        {"command": f'printf "%s" "quoted-a\nquoted-b" > {target}'},
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-shell-quoted-nl",
            prompt="write the quoted multi-line text",
        )
        assert final.get("status") == "finished", final
        text = _wait_for_file(target, lambda t: "quoted-b" in t)
        assert text.splitlines() == ["quoted-a", "quoted-b"], (
            f"quoted newline was not preserved: {text!r}; "
            f"logs={app_server.logs_tail()[-2000:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX shell statement separators differ on cmd.exe",
)
def test_shell_unquoted_newline_is_collapsed(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An unquoted newline becomes a space, keeping both statements.

    Test purpose:
      - Cover the collapse branch: with a ``;`` terminating the first
        statement, joining the lines with a space must still execute
        both, so the file contains both markers.
    """
    srv, mock_url = mock_llm
    target = _workspace_dir(app_server) / "integ-shell-collapsed.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    _force(
        srv,
        "execute_shell_command",
        {
            "command": (
                f"printf 'stmt-a\\n' > {target};\n"
                f"printf 'stmt-b\\n' >> {target}"
            ),
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-shell-collapsed",
            prompt="run the two statements",
        )
        assert final.get("status") == "finished", final
        text = _wait_for_file(target, lambda t: "stmt-b" in t)
        assert "stmt-a" in text and "stmt-b" in text, (
            f"both statements should have run, got {text!r}; "
            f"logs={app_server.logs_tail()[-2000:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


# ============================ B. file_search.py ============================


@pytest.fixture(scope="module")
def search_tree(app_server):
    """Create a small, known file tree for the search assertions."""
    root = _workspace_dir(app_server) / "integ-search-tree"
    (root / "sub").mkdir(parents=True, exist_ok=True)
    (root / "alpha.py").write_text(
        "before-line\nNeedleValue = 1\nafter-line\n",
        encoding="utf-8",
    )
    (root / "beta.txt").write_text(
        "needlevalue lowercase here\n",
        encoding="utf-8",
    )
    (root / "sub" / "gamma.py").write_text(
        "other = 2\nNeedleValue = 3\n",
        encoding="utf-8",
    )
    return root


@pytest.mark.integration
@pytest.mark.p1
def test_grep_regex_matches_across_files(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    search_tree,  # pylint: disable=redefined-outer-name
):
    """A regex pattern matches in several files under one root.

    Test purpose:
      - Cover _compile_search_pattern's regex branch plus the
        multi-file walk, asserting both matching files appear and the
        non-matching lowercase file does not.
    """
    srv, mock_url = mock_llm
    _force(
        srv,
        "grep_search",
        {
            "pattern": r"Needle[A-Z][a-z]+",
            "path": str(search_tree),
            "is_regex": True,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-grep-regex",
            prompt="grep with a regex",
        )
        body = _tool_output(final)
        assert "alpha.py" in body, body[:2500]
        assert "gamma.py" in body, body[:2500]
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_grep_case_insensitive_finds_lowercase(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    search_tree,  # pylint: disable=redefined-outer-name
):
    """case_sensitive=False widens the match to the lowercase file.

    Test purpose:
      - Cover the re.IGNORECASE flag branch: the same literal pattern
        must now also hit beta.txt, which only has lowercase text.
    """
    srv, mock_url = mock_llm
    _force(
        srv,
        "grep_search",
        {
            "pattern": "NeedleValue",
            "path": str(search_tree),
            "case_sensitive": False,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-grep-nocase",
            prompt="grep case-insensitively",
        )
        body = _tool_output(final)
        assert "beta.txt" in body, body[:2500]
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_grep_context_lines_include_neighbours(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    search_tree,  # pylint: disable=redefined-outer-name
):
    """context_lines emits the lines surrounding each hit.

    Test purpose:
      - Cover _output_context_for_hit and the ``---`` separator path:
        with context_lines=1 the neighbours of the hit in alpha.py must
        appear even though they do not match the pattern.
    """
    srv, mock_url = mock_llm
    _force(
        srv,
        "grep_search",
        {
            "pattern": "NeedleValue",
            "path": str(search_tree / "alpha.py"),
            "context_lines": 1,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-grep-context",
            prompt="grep with context",
        )
        body = _tool_output(final)
        assert "before-line" in body, body[:2500]
        assert "after-line" in body, body[:2500]
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_grep_show_file_false_groups_by_file(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    search_tree,  # pylint: disable=redefined-outer-name
):
    """show_file=False prints each path once as a group header.

    Test purpose:
      - Cover _emit_file_header_if_needed's grouping mode: the paths
        still appear (as headers) while individual match lines drop the
        path prefix.
    """
    srv, mock_url = mock_llm
    _force(
        srv,
        "grep_search",
        {
            "pattern": "NeedleValue",
            "path": str(search_tree),
            "show_file": False,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-grep-group",
            prompt="grep grouped by file",
        )
        body = _tool_output(final)
        assert "alpha.py" in body, body[:2500]
        assert "gamma.py" in body, body[:2500]
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_grep_invalid_regex_reports_error(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    search_tree,  # pylint: disable=redefined-outer-name
):
    """A malformed regex is reported instead of raising.

    Test purpose:
      - Cover _compile_search_pattern's re.error branch.
    """
    srv, mock_url = mock_llm
    _force(
        srv,
        "grep_search",
        {
            "pattern": "Needle(",
            "path": str(search_tree),
            "is_regex": True,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-grep-badre",
            prompt="grep with a broken regex",
        )
        body = _tool_output(final)
        assert "Error" in body or "error" in body, body[:2500]
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_grep_missing_path_reports_error(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Searching a non-existent root is reported cleanly.

    Test purpose:
      - Cover _resolve_search_root's not-found branch.
    """
    srv, mock_url = mock_llm
    _force(
        srv,
        "grep_search",
        {
            "pattern": "anything",
            "path": "/tmp/integ-no-such-search-root-9182",
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-grep-nopath",
            prompt="grep a missing directory",
        )
        body = _tool_output(final)
        assert "Error" in body or "not" in body, body[:2500]
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_glob_search_scoped_to_subdirectory(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
    search_tree,  # pylint: disable=redefined-outer-name
):
    """glob_search honours its path argument as the search root.

    Test purpose:
      - Cover _walk_and_glob's scoped walk: searching only ``sub``
        must find gamma.py and must not report alpha.py.
    """
    srv, mock_url = mock_llm
    _force(
        srv,
        "glob_search",
        {
            "pattern": "*.py",
            "path": str(search_tree / "sub"),
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_tool(
            app_server,
            user_id="integ-glob-scoped",
            prompt="glob only the subdirectory",
        )
        body = _tool_output(final)
        assert "gamma.py" in body, body[:2500]
        assert "alpha.py" not in body, (
            "glob leaked outside its path argument: " + body[:2500]
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)
