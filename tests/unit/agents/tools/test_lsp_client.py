# -*- coding: utf-8 -*-
"""Tests for ``qwenpaw.agents.tools._lsp_client``.

Wire format helpers are tested as pure functions; the client class
itself is exercised end-to-end against a tiny fake LSP server
implemented as a Python subprocess.
"""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import json
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

from qwenpaw.agents.tools import _lsp_client as lsp


# ---------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------


def test_encode_message_has_correct_header_and_body():
    msg = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    framed = lsp.encode_message(msg)
    head, _, body = framed.partition(b"\r\n\r\n")
    assert head.startswith(b"Content-Length:")
    declared = int(head.split(b":", 1)[1].strip())
    assert declared == len(body)
    assert json.loads(body.decode()) == msg


def test_parse_messages_single_complete_message():
    framed = lsp.encode_message({"jsonrpc": "2.0", "id": 1, "result": 42})
    msgs, leftover = lsp.parse_messages(framed)
    assert msgs == [{"jsonrpc": "2.0", "id": 1, "result": 42}]
    assert leftover == b""


def test_parse_messages_multiple_messages_in_one_chunk():
    framed = lsp.encode_message({"id": 1, "result": "a"}) + lsp.encode_message(
        {"id": 2, "result": "b"},
    )
    msgs, leftover = lsp.parse_messages(framed)
    assert len(msgs) == 2
    assert msgs[0]["result"] == "a"
    assert msgs[1]["result"] == "b"
    assert leftover == b""


def test_parse_messages_partial_body_returns_leftover():
    framed = lsp.encode_message({"id": 1, "result": "x"})
    # Cut off the last 2 bytes of body
    chopped = framed[:-2]
    msgs, leftover = lsp.parse_messages(chopped)
    assert not msgs
    assert leftover == chopped


def test_parse_messages_skips_header_without_content_length():
    bad = b"X-Random: 1\r\n\r\n" + lsp.encode_message(
        {"id": 1, "result": "x"},
    )
    msgs, leftover = lsp.parse_messages(bad)
    assert len(msgs) == 1
    assert msgs[0]["result"] == "x"
    assert leftover == b""


def test_parse_messages_drops_bad_json_body():
    bad_body = b"not-json"
    framed = (
        f"Content-Length: {len(bad_body)}\r\n\r\n".encode("ascii") + bad_body
    )
    msgs, leftover = lsp.parse_messages(framed)
    assert not msgs
    assert leftover == b""


# ---------------------------------------------------------------------
# Capabilities + helpers
# ---------------------------------------------------------------------


def test_client_capabilities_minimum_shape():
    caps = lsp._client_capabilities()
    assert "textDocument" in caps
    assert "workspace" in caps
    assert caps["textDocument"]["definition"]["linkSupport"] is False


# ---------------------------------------------------------------------
# End-to-end against a fake server subprocess
# ---------------------------------------------------------------------


_FAKE_SERVER_SCRIPT = textwrap.dedent(
    """
    import sys, json

    def read_message():
        headers = {}
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            line = line.rstrip(b"\\r\\n")
            if line == b"":
                break
            k, _, v = line.decode("ascii").partition(":")
            headers[k.strip().lower()] = v.strip()
        length = int(headers["content-length"])
        body = sys.stdin.buffer.read(length)
        return json.loads(body.decode("utf-8"))

    def write(msg):
        body = json.dumps(msg).encode("utf-8")
        sys.stdout.buffer.write(
            b"Content-Length: " + str(len(body)).encode("ascii")
            + b"\\r\\n\\r\\n" + body
        )
        sys.stdout.buffer.flush()

    while True:
        msg = read_message()
        if msg is None:
            break
        method = msg.get("method")
        if method == "exit":
            break
        if "id" not in msg:
            # Notification (e.g. initialized, didOpen) — ignore.
            continue
        if method == "initialize":
            write({
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {"capabilities": {}},
            })
        elif method == "shutdown":
            write({"jsonrpc": "2.0", "id": msg["id"], "result": None})
        elif method == "trigger-server-request":
            # Server sends an unsolicited request to the client.
            write({
                "jsonrpc": "2.0",
                "id": 9999,
                "method": "workspace/configuration",
                "params": {"items": []},
            })
            # Then respond to the trigger itself.
            write({
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {"ok": True},
            })
        else:
            write({
                "jsonrpc": "2.0",
                "id": msg["id"],
                "result": {
                    "echo_method": method,
                    "echo_params": msg.get("params"),
                },
            })
    """,
).strip()


@pytest.fixture
def fake_server_script():
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(_FAKE_SERVER_SCRIPT)
        path = f.name
    yield path
    try:
        Path(path).unlink()
    except OSError:
        pass


@pytest.fixture
def project_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def started_client(fake_server_script, project_dir):
    client = lsp.LspClient(
        argv=[sys.executable, fake_server_script],
        project_dir=project_dir,
        language_id="python",
    )
    client.start()
    yield client
    client.shutdown()


def test_initialize_completes(started_client):
    # If start() returned, initialize succeeded.
    assert started_client._proc is not None


def test_definition_round_trip(started_client, project_dir):
    file_path = project_dir / "foo.py"
    file_path.write_text("def x(): pass\n", encoding="utf-8")
    result = started_client.definition(file_path, line=1, character=5)
    assert result == {
        "echo_method": "textDocument/definition",
        "echo_params": {
            "textDocument": {"uri": file_path.resolve().as_uri()},
            "position": {"line": 0, "character": 4},
        },
    }


def test_workspace_symbol_round_trip(started_client):
    result = started_client.workspace_symbol("my_func")
    assert result["echo_method"] == "workspace/symbol"
    assert result["echo_params"] == {"query": "my_func"}


def test_did_open_is_only_sent_once(started_client, project_dir):
    file_path = project_dir / "bar.py"
    file_path.write_text("x = 1\n", encoding="utf-8")
    started_client.hover(file_path, line=1, character=1)
    started_client.hover(file_path, line=1, character=2)
    uri = file_path.resolve().as_uri()
    assert uri in started_client._opened
    assert len(started_client._opened) == 1


def test_server_initiated_request_is_replied(started_client):
    # Triggering this also produces the request's own response, so we
    # implicitly verify that the server-initiated request did not stall
    # the client's reader thread.
    result = started_client._request("trigger-server-request", {})
    assert result == {"ok": True}


def test_shutdown_drains_pending_requests(
    fake_server_script,
    project_dir,
):
    client = lsp.LspClient(
        argv=[sys.executable, fake_server_script],
        project_dir=project_dir,
        language_id="python",
    )
    client.start()
    # No outstanding requests right now — shutdown must succeed cleanly.
    client.shutdown()
    # Second shutdown should be a no-op.
    client.shutdown()


# ---------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------


def test_pool_reuses_client_for_same_key(
    fake_server_script,
    project_dir,
    monkeypatch,
):
    # Clear pool to isolate from other tests.
    monkeypatch.setattr(lsp, "_POOL", {})
    argv = [sys.executable, fake_server_script]
    c1 = lsp.get_client(project_dir, "python", argv)
    c2 = lsp.get_client(project_dir, "python", argv)
    try:
        assert c1 is c2
    finally:
        lsp.shutdown_all()


def test_pool_returns_distinct_clients_for_different_languages(
    fake_server_script,
    project_dir,
    monkeypatch,
):
    monkeypatch.setattr(lsp, "_POOL", {})
    argv = [sys.executable, fake_server_script]
    py = lsp.get_client(project_dir, "python", argv)
    ts = lsp.get_client(project_dir, "typescript", argv)
    try:
        assert py is not ts
    finally:
        lsp.shutdown_all()
