# -*- coding: utf-8 -*-
"""Tests for the LSP client wire-format helpers and client pool.

Covers encode_message, parse_messages (framing, partial buffers,
malformed headers/bodies), _client_capabilities shape, and the
pool-keyed get_client/shutdown_all lifecycle with the subprocess
spawning stubbed out.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import json

import pytest

from qwenpaw.agents.tools import _lsp_client as lsp


def _frame(payload: dict) -> bytes:
    return lsp.encode_message(payload)


# ---------------------------------------------------------------------------
# encode_message
# ---------------------------------------------------------------------------


class TestEncodeMessage:
    def test_header_and_body(self):
        result = lsp.encode_message({"jsonrpc": "2.0", "id": 1})
        assert result.startswith(b"Content-Length: ")
        header, body = result.split(b"\r\n\r\n", 1)
        declared = int(header.split(b":", 1)[1].strip())
        assert declared == len(body)
        assert json.loads(body) == {"jsonrpc": "2.0", "id": 1}

    def test_utf8_body_length_is_bytes(self):
        result = lsp.encode_message({"text": "中文"})
        header, body = result.split(b"\r\n\r\n", 1)
        declared = int(header.split(b":", 1)[1].strip())
        assert declared == len(body)  # byte length, not char count

    def test_round_trip(self):
        payload = {"method": "hover", "params": {"x": [1, 2]}}
        messages, leftover = lsp.parse_messages(_frame(payload))
        assert messages == [payload]
        assert leftover == b""


# ---------------------------------------------------------------------------
# parse_messages
# ---------------------------------------------------------------------------


class TestParseMessages:
    def test_empty_buffer(self):
        messages, leftover = lsp.parse_messages(b"")
        assert messages == []
        assert leftover == b""

    def test_single_message(self):
        payload = {"id": 1, "result": {"ok": True}}
        messages, leftover = lsp.parse_messages(_frame(payload))
        assert messages == [payload]
        assert leftover == b""

    def test_multiple_messages(self):
        buffer = _frame({"id": 1}) + _frame({"id": 2}) + _frame({"id": 3})
        messages, leftover = lsp.parse_messages(buffer)
        assert [m["id"] for m in messages] == [1, 2, 3]
        assert leftover == b""

    def test_partial_body_kept_as_leftover(self):
        complete = _frame({"id": 1})
        partial = _frame({"id": 2})[:10]
        messages, leftover = lsp.parse_messages(complete + partial)
        assert len(messages) == 1
        assert leftover == partial

    def test_partial_header_kept_as_leftover(self):
        incomplete = b"Content-Length: 5\r\n"  # no \r\n\r\n yet
        messages, leftover = lsp.parse_messages(incomplete)
        assert messages == []
        assert leftover == incomplete

    def test_malformed_header_length_skipped(self):
        bad = b"Content-Length: abc\r\n\r\n"
        good = _frame({"id": 9})
        messages, leftover = lsp.parse_messages(bad + good)
        assert messages == [{"id": 9}]
        assert leftover == b""

    def test_missing_content_length_header_skipped(self):
        bad = b"X-Custom: 1\r\n\r\n"
        good = _frame({"id": 7})
        messages, leftover = lsp.parse_messages(bad + good)
        assert messages == [{"id": 7}]
        assert leftover == b""

    def test_invalid_json_body_dropped(self):
        header = b"Content-Length: 12\r\n\r\n"
        buffer = header + b"not json at " + _frame({"id": 5})
        messages, leftover = lsp.parse_messages(buffer)
        assert messages == [{"id": 5}]
        assert leftover == b""

    def test_invalid_utf8_body_dropped(self):
        header = b"Content-Length: 4\r\n\r\n"
        buffer = header + b"\xff\xfe\xfd\xfc"
        messages, leftover = lsp.parse_messages(buffer)
        assert messages == []
        assert leftover == b""

    def test_header_case_insensitive(self):
        payload = {"id": 3}
        body = json.dumps(payload).encode()
        buffer = f"content-length: {len(body)}\r\n\r\n".encode() + body
        messages, leftover = lsp.parse_messages(buffer)
        assert messages == [payload]
        # The buffer was consumed exactly, so nothing is left over.
        assert leftover == b""


# ---------------------------------------------------------------------------
# _client_capabilities
# ---------------------------------------------------------------------------


class TestClientCapabilities:
    def test_shape(self):
        caps = lsp._client_capabilities()
        assert "textDocument" in caps
        assert "workspace" in caps
        td = caps["textDocument"]
        assert "definition" in td
        assert "references" in td
        assert "hover" in td
        assert td["synchronization"]["didSave"] is False

    def test_fresh_dict_each_call(self):
        assert lsp._client_capabilities() is not lsp._client_capabilities()


# ---------------------------------------------------------------------------
# pool: get_client / shutdown_all
# ---------------------------------------------------------------------------


class TestClientPool:
    @pytest.fixture(autouse=True)
    def _clear_pool(self):
        lsp._POOL.clear()
        yield
        lsp._POOL.clear()

    def test_get_client_reuses_same_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lsp.LspClient, "start", lambda self: None)
        first = lsp.get_client(tmp_path, "python", ["pyright"])
        second = lsp.get_client(tmp_path, "python", ["pyright"])
        assert first is second
        assert len(lsp._POOL) == 1

    def test_different_language_gets_new_client(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lsp.LspClient, "start", lambda self: None)
        py = lsp.get_client(tmp_path, "python", ["pyright"])
        ts = lsp.get_client(tmp_path, "typescript", ["ts-ls"])
        assert py is not ts
        assert len(lsp._POOL) == 2

    def test_pool_key_uses_resolved_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(lsp.LspClient, "start", lambda self: None)
        link = tmp_path / "link"
        link.symlink_to(tmp_path)
        direct = lsp.get_client(tmp_path, "python", ["pyright"])
        via_link = lsp.get_client(link, "python", ["pyright"])
        assert direct is via_link

    def test_shutdown_all_clears_pool(self, monkeypatch):
        shutdowns = []

        class FakeClient:
            def shutdown(self):
                shutdowns.append(self)

        lsp._POOL[("a", "py")] = FakeClient()
        lsp._POOL[("b", "py")] = FakeClient()
        lsp.shutdown_all()
        assert lsp._POOL == {}
        assert len(shutdowns) == 2

    def test_shutdown_all_empty_pool_safe(self):
        lsp.shutdown_all()  # must not raise
        assert lsp._POOL == {}
