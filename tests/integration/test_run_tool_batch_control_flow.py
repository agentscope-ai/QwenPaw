# -*- coding: utf-8 -*-
"""run_tool_batch control flow driven through real agent turns.

Covers ``agents/tools/run_tool_batch.py`` beyond simple sequential
execution: the ``label``/``goto``/``set_var`` built-ins, arithmetic
expression evaluation, ``${steps.N}``/``${vars.N}`` reference
resolution, ``${args.name}`` substitution, ``maxstep`` guarding,
``last_only`` response shaping and the argument-validation branches.

Every loop/branch assertion is grounded on a real side effect: the
batch appends to a file in the agent workspace via the shell tool, so
the file content proves how many iterations actually ran and which
values were resolved.

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


def _fresh_target(app_server, name: str) -> Path:
    """Return a workspace path with any previous content removed."""
    target = _workspace_dir(app_server) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    return target


def _append_step(target: Path, text: str) -> dict:
    """A batch step that appends ``text`` to ``target`` via the shell.

    ``append_file`` is disabled in the default agent's builtin toolset,
    so the shell tool is used to produce the on-disk side effect.
    """
    return {
        "tool_name": "execute_shell_command",
        "args": {"command": f"printf '{text}\\n' >> {target}"},
    }


def _run_batch(app_server, *, user_id: str, prompt: str) -> dict:
    """Submit a chat task that triggers the forced batch; poll to end."""
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
        "batch task did not finish: " + app_server.logs_tail()[-2000:],
    )


def _wait_for_content(target: Path, predicate, timeout: float = 30.0) -> str:
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


# ======================= A. loops: set_var / goto / label ==================


@pytest.mark.integration
@pytest.mark.p1
def test_batch_loop_appends_three_iterations(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A set_var/goto/label loop runs exactly the requested iterations.

    Test purpose:
      - Cover the loop machinery in _run_steps: set_var assignment,
        arithmetic increment (``i=${vars.i}+1``), label registration
        via _build_label_map, and conditional goto evaluation through
        _evaluate_condition with a ``${vars.i}<3`` comparison.

    Test flow:
      1. Force a batch that initialises i=0, appends "tick" to a file,
         increments i, and jumps back while i<3.
      2. Assert the file contains exactly three ticks, proving the
         loop iterated the expected number of times (not once, not
         forever).
    """
    srv, mock_url = mock_llm
    target = _fresh_target(app_server, "integ-batch-loop.txt")
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {"tool_name": "set_var", "args": {"expr": "i=0"}},
                {"tool_name": "label", "args": {"name": "top"}},
                _append_step(target, "tick"),
                {
                    "tool_name": "set_var",
                    "args": {"expr": "i=${vars.i}+1"},
                },
                {
                    "tool_name": "goto",
                    "args": {"label": "top", "condition": "${vars.i}<3"},
                },
            ],
            "stop_on_error": True,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_batch(
            app_server,
            user_id="integ-batch-loop",
            prompt="run the loop batch",
        )
        assert final.get("status") == "finished", final
        text = _wait_for_content(target, lambda t: t.count("tick") >= 3)
        assert text.count("tick") == 3, (
            f"expected 3 loop iterations, got {text!r}; "
            f"logs={app_server.logs_tail()[-2000:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_batch_unconditional_goto_skips_step(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A goto without a condition jumps forward, skipping a step.

    Test purpose:
      - Cover the unconditional-jump branch of goto (condition None)
        plus forward jumping through _build_label_map.

    Test flow:
      1. Batch: goto end -> append "skipped" -> label end -> append
         "reached".
      2. Assert the file has "reached" but never "skipped".
    """
    srv, mock_url = mock_llm
    target = _fresh_target(app_server, "integ-batch-goto.txt")
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {"tool_name": "goto", "args": {"label": "end"}},
                _append_step(target, "skipped"),
                {"tool_name": "label", "args": {"name": "end"}},
                _append_step(target, "reached"),
            ],
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_batch(
            app_server,
            user_id="integ-batch-goto",
            prompt="run the goto batch",
        )
        assert final.get("status") == "finished", final
        text = _wait_for_content(target, lambda t: "reached" in t)
        assert "reached" in text, text
        assert "skipped" not in text, f"goto did not skip step: {text!r}"
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_batch_maxstep_halts_infinite_loop(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """maxstep caps execution of an otherwise endless loop.

    Test purpose:
      - Cover the execution-budget guard: an unconditional backwards
        goto would never terminate, so the batch must stop with the
        "Exceeded maximum execution steps" error and the turn must
        still complete.

    Test flow:
      1. Batch: label top -> append -> goto top (unconditional),
         maxstep=6.
      2. Assert the turn finished and the append ran at least once but
         far fewer times than an unbounded loop would produce.
    """
    srv, mock_url = mock_llm
    target = _fresh_target(app_server, "integ-batch-maxstep.txt")
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {"tool_name": "label", "args": {"name": "top"}},
                _append_step(target, "x"),
                {"tool_name": "goto", "args": {"label": "top"}},
            ],
            "maxstep": 6,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_batch(
            app_server,
            user_id="integ-batch-maxstep",
            prompt="run the capped batch",
        )
        assert final.get("status") == "finished", final
        text = _wait_for_content(target, lambda t: t.count("x") >= 1)
        count = text.count("x")
        assert 1 <= count <= 3, (
            f"maxstep=6 should allow ~2 appends, got {count}; "
            f"logs={app_server.logs_tail()[-2000:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


# ======================= B. reference resolution ===========================


@pytest.mark.integration
@pytest.mark.p1
def test_batch_step_ref_feeds_next_step(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A ${steps.N} reference carries one step's output into the next.

    Test purpose:
      - Cover resolve_step_refs / _lookup_step_ref: read a file in
        step 0, then write that text into another file in step 1 via
        ``${steps.0.text}``.

    Test flow:
      1. Seed a source file with a unique marker.
      2. Batch: read_file(source) -> write_file(dest,
         "${steps.0.text}").
      3. Assert the destination contains the marker, proving the
         reference resolved to the real step output.
    """
    srv, mock_url = mock_llm
    marker = "STEPREF-MARKER-7391"
    src_name = "integ-batch-ref-src.txt"
    dst_name = "integ-batch-ref-dst.txt"
    src = _workspace_dir(app_server) / src_name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(marker + "\n", encoding="utf-8")
    target = _fresh_target(app_server, dst_name)
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {
                    "tool_name": "read_file",
                    "args": {"file_path": src_name},
                },
                {
                    "tool_name": "write_file",
                    "args": {
                        "file_path": dst_name,
                        "content": "copied: ${steps.0.text}",
                    },
                },
            ],
            "stop_on_error": True,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_batch(
            app_server,
            user_id="integ-batch-stepref",
            prompt="run the step-ref batch",
        )
        assert final.get("status") == "finished", final
        text = _wait_for_content(target, lambda t: marker in t)
        assert marker in text, (
            f"step ref did not resolve: {text!r}; "
            f"logs={app_server.logs_tail()[-2000:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_batch_args_placeholder_from_file(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """${args.name} placeholders in a batch file are substituted.

    Test purpose:
      - Cover _load_actions_from_file plus _resolve_args: the batch
        file declares a ``${args.payload}`` placeholder and the caller
        supplies ``args`` alongside ``file_path``.

    Test flow:
      1. Write a batch JSON whose write_file content is a placeholder.
      2. Force run_tool_batch with file_path + args.
      3. Assert the substituted value landed on disk.
    """
    srv, mock_url = mock_llm
    payload = "ARGS-SUBST-4820"
    batch_name = "integ-batch-args.json"
    out_name = "integ-batch-args-out.txt"
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
                            "content": "value=${args.payload}",
                        },
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    target = _fresh_target(app_server, out_name)
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            # _load_batch_file requires an absolute path.
            "file_path": str(batch_path),
            "args": {"payload": payload},
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_batch(
            app_server,
            user_id="integ-batch-args",
            prompt="run the parameterised batch",
        )
        assert final.get("status") == "finished", final
        text = _wait_for_content(target, lambda t: payload in t)
        assert payload in text, (
            f"args placeholder unresolved: {text!r}; "
            f"logs={app_server.logs_tail()[-2000:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


# ======================= C. error / validation branches ====================


@pytest.mark.integration
@pytest.mark.p2
def test_batch_unknown_label_reports_error(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A goto to a missing label aborts the batch before later steps.

    Test purpose:
      - Cover the "Unknown label" branch: the batch must break, so a
        step placed after the bad goto never runs.
    """
    srv, mock_url = mock_llm
    target = _fresh_target(app_server, "integ-batch-badlabel.txt")
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {"tool_name": "goto", "args": {"label": "nowhere"}},
                _append_step(target, "ran"),
            ],
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_batch(
            app_server,
            user_id="integ-batch-badlabel",
            prompt="run the bad-label batch",
        )
        assert final.get("status") == "finished", final
        time.sleep(1.0)
        assert not target.exists(), (
            "batch continued past an unknown label: "
            f"{target.read_text(encoding='utf-8')!r}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_batch_recursive_call_is_rejected(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A nested run_tool_batch step is refused, halting the batch.

    Test purpose:
      - Cover the recursion guard ("Recursive run_tool_batch is not
        allowed"); the step after it must not execute.
    """
    srv, mock_url = mock_llm
    target = _fresh_target(app_server, "integ-batch-recursive.txt")
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {
                    "tool_name": "run_tool_batch",
                    "args": {
                        "actions": [
                            {"tool_name": "get_current_time", "args": {}},
                        ],
                    },
                },
                _append_step(target, "ran"),
            ],
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_batch(
            app_server,
            user_id="integ-batch-recursive",
            prompt="run the recursive batch",
        )
        assert final.get("status") == "finished", final
        time.sleep(1.0)
        assert not target.exists(), (
            "batch continued past the recursion guard: "
            f"{target.read_text(encoding='utf-8')!r}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_batch_continues_when_stop_on_error_disabled(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """With stop_on_error=False a failing step does not abort the batch.

    Test purpose:
      - Cover _append_error_and_should_stop's continue path: the first
        step fails (missing file) yet the following append still runs.
    """
    srv, mock_url = mock_llm
    target = _fresh_target(app_server, "integ-batch-continue.txt")
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {
                    "tool_name": "read_file",
                    "args": {"file_path": "integ-batch-no-such-file.txt"},
                },
                _append_step(target, "after-error"),
            ],
            "stop_on_error": False,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_batch(
            app_server,
            user_id="integ-batch-continue",
            prompt="run the resilient batch",
        )
        assert final.get("status") == "finished", final
        text = _wait_for_content(target, lambda t: "after-error" in t)
        assert "after-error" in text, (
            "batch stopped despite stop_on_error=False; "
            f"logs={app_server.logs_tail()[-2000:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_batch_rejects_actions_and_file_path_together(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Supplying both actions and file_path is a validation error.

    Test purpose:
      - Cover _prepare_batch_inputs' mutually-exclusive check; no step
        may run, so the would-be append must not appear.
    """
    srv, mock_url = mock_llm
    target = _fresh_target(app_server, "integ-batch-both.txt")
    # A real, loadable batch file: the rejection must come from the
    # mutual-exclusion check, not from a missing-file error.
    batch_path = _workspace_dir(app_server) / "integ-batch-both.json"
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(
        json.dumps(
            {"actions": [{"tool_name": "get_current_time", "args": {}}]},
        ),
        encoding="utf-8",
    )
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [_append_step(target, "ran")],
            "file_path": str(batch_path),
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_batch(
            app_server,
            user_id="integ-batch-both",
            prompt="run the conflicting batch",
        )
        assert final.get("status") == "finished", final
        time.sleep(1.0)
        assert not target.exists(), (
            "batch executed despite conflicting inputs: "
            f"{target.read_text(encoding='utf-8')!r}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_batch_last_only_still_applies_side_effects(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """last_only trims the response but every step still executes.

    Test purpose:
      - Cover _build_batch_response's last_only shaping together with
        _should_include_last_text_block, while proving the earlier
        step's side effect happened.
    """
    srv, mock_url = mock_llm
    name = "integ-batch-lastonly.txt"
    target = _fresh_target(app_server, name)
    srv.force_tool_call = True
    srv.tool_call_name = "run_tool_batch"
    srv.tool_call_arguments = json.dumps(
        {
            "actions": [
                {
                    "tool_name": "write_file",
                    "args": {"file_path": name, "content": "first step ran"},
                },
                {"tool_name": "get_current_time", "args": {}},
            ],
            "last_only": True,
        },
    )
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        final = _run_batch(
            app_server,
            user_id="integ-batch-lastonly",
            prompt="run the terse batch",
        )
        assert final.get("status") == "finished", final
        text = _wait_for_content(target, lambda t: "first step ran" in t)
        assert "first step ran" in text, (
            f"first step did not run under last_only: {text!r}; "
            f"logs={app_server.logs_tail()[-2000:]}"
        )
    finally:
        srv.force_tool_call = False
        unregister_mock_provider(app_server, provider_id)
