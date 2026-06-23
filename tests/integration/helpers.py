# -*- coding: utf-8 -*-
"""Shared helpers for integration tests.

Extracted from individual test modules to eliminate duplication and
ensure fixes (e.g. TimeoutException handling) apply everywhere.
"""
from __future__ import annotations

import json
import shutil
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import httpx

PLUGIN_HTTP_TIMEOUT = 60.0
LOADER_READY_TIMEOUT = 20.0
AGENT_SCOPED_PREFIX = "/api/agents"
REPO_ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_PLUGINS_DIR = REPO_ROOT / "plugins"


# ------------------------------------------------------------------ #
# agent helpers
# ------------------------------------------------------------------ #


def scoped(agent_id: str, path: str) -> str:
    """Build an agent-scoped URL."""
    return f"{AGENT_SCOPED_PREFIX}/{agent_id}{path}"


def create_agent(app_server, agent_id: str) -> None:
    resp = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": f"Agent {agent_id}",
            "description": "",
        },
    )
    assert resp.status_code == 201, app_server.logs_tail()


def delete_agent_quietly(app_server, agent_id: str) -> None:
    try:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
        )
    except Exception:
        pass


def toggle_agent(app_server, agent_id: str, enabled: bool):
    """PATCH /api/agents/{id}/toggle and return response."""
    return app_server.api_request(
        "PATCH",
        f"/api/agents/{agent_id}/toggle",
        json={"enabled": enabled},
    )


# ------------------------------------------------------------------ #
# plugin helpers
# ------------------------------------------------------------------ #


def wait_until_plugin_loader_ready(
    app_server,
    *,
    timeout: float = LOADER_READY_TIMEOUT,
) -> None:
    """Poll a write endpoint until app.state.plugin_loader is set.

    install_plugin checks the loader BEFORE validating the source, so
    posting an invalid local path is a free readiness probe:
      * 503 ``Plugin loader is not ready yet`` -- not ready, keep polling
      * 400 ``Path not found``                 -- loader is up, return
    GET /api/plugins is NOT used because list_plugins falls back to
    on-disk scanning when the loader is absent and would mask the
    real readiness state.

    Per code review feedback, the readiness signal is now narrowed: we
    only accept the exact 400 + "Path not found" detail. Any other
    non-503 response (e.g. install_plugin code path changes that move
    the source check) is logged as ``unexpected`` and treated as
    fallback-ready (caller is the one that would then fail on the
    real install/upload), so this stays resilient to future router
    refactors without silently masking probe drift.
    """
    deadline = time.time() + timeout
    last_status = None
    last_detail = ""
    while time.time() < deadline:
        try:
            resp = app_server.api_request(
                "POST",
                "/api/plugins/install",
                json={
                    "source": "/tmp/integ-loader-readiness-probe",
                    "force": False,
                },
                timeout=5.0,
            )
        except httpx.TimeoutException:
            time.sleep(0.5)
            continue
        last_status = resp.status_code
        try:
            last_detail = resp.json().get("detail", "")
        except ValueError:
            last_detail = resp.text[:200]

        if resp.status_code == 400 and "Path not found" in last_detail:
            return
        if resp.status_code == 503:
            time.sleep(0.5)
            continue
        return
    raise AssertionError(
        f"plugin_loader not ready in {timeout}s, "
        f"last status={last_status} detail={last_detail!r}",
    )


def delete_plugin_quietly(
    app_server,
    plugin_id: str,
) -> None:
    """Best-effort plugin delete for finally blocks."""
    try:
        wait_until_plugin_loader_ready(app_server)
        app_server.api_request(
            "DELETE",
            f"/api/plugins/{plugin_id}",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
    except Exception:
        pass


# ------------------------------------------------------------------ #
# inbox helpers
# ------------------------------------------------------------------ #


def inbox_path(working_dir: Path) -> Path:
    return working_dir / "inbox_events.json"


def trace_dir(working_dir: Path) -> Path:
    return working_dir / "inbox_traces"


def seed_inbox_events(
    working_dir: Path,
    events: list[dict[str, Any]],
) -> None:
    """Write the events list to inbox_events.json."""
    path = inbox_path(working_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            events,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def seed_inbox_trace(
    working_dir: Path,
    run_id: str,
    payload: dict[str, Any],
) -> None:
    """Write one trace file under inbox_traces/<run_id>.json."""
    directory = trace_dir(working_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{run_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clean_inbox(working_dir: Path) -> None:
    """Remove inbox file + trace dir so the next test starts clean."""
    path = inbox_path(working_dir)
    if path.exists():
        path.unlink()
    directory = trace_dir(working_dir)
    if directory.exists():
        shutil.rmtree(directory)


def make_event(
    *,
    event_id: str,
    agent_id: str = "default",
    source_type: str = "cron",
    source_id: str = "",
    event_type: str = "cron_executed",
    status: str = "completed",
    severity: str = "info",
    title: str = "seeded event",
    body: str = "",
    payload: dict[str, Any] | None = None,
    read: bool = False,
    created_at: float | None = None,
) -> dict[str, Any]:
    """Mirror the shape produced by ``inbox_store.append_event``."""
    return {
        "id": event_id,
        "agent_id": agent_id,
        "source_type": source_type,
        "source_id": source_id,
        "event_type": event_type,
        "status": status,
        "severity": severity,
        "title": title,
        "body": body,
        "payload": payload or {},
        "read": read,
        "created_at": (created_at if created_at is not None else time.time()),
    }


# ------------------------------------------------------------------ #
# Mock LLM server
# ------------------------------------------------------------------ #

MOCK_LLM_RESPONSE = "Mock heartbeat response from integration test."
MOCK_LLM_PROVIDER_ID = "integ-mock-llm"
_HTTP_TIMEOUT = 15.0


class MockLLMHandler(BaseHTTPRequestHandler):
    """OpenAI-compatible streaming server with tool_call support.

    Behaviour matrix (checked in order):
      1. ``server.force_error`` is True  → 422
      2. Request has ``tools`` AND no ``role=tool`` message
         → stream a tool_call for ``get_current_time``
      3. Request has a ``role=tool`` message (round 2)
         → stream text summarising the tool result
      4. Otherwise → stream ``MOCK_LLM_RESPONSE``
    """

    def do_POST(self):  # noqa: N802
        if "/chat/completions" in self.path:
            self._stream_completion()
        else:
            self.send_error(404)

    def do_GET(self):  # noqa: N802
        if "/models" in self.path:
            self._list_models()
        else:
            self.send_error(404)

    # -- internals ---------------------------------------------------

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return {}

    def _stream_completion(self):
        body = self._read_body()

        # Track request count for fail-then-recover scenarios.
        count = getattr(self.server, "request_count", 0) + 1
        self.server.request_count = count

        delay = getattr(self.server, "response_delay", 0)
        if delay:
            time.sleep(delay)

        # force_status_code can be:
        #   - int: always return that status
        #   - list[int]: pop one per request (sequential failures)
        forced_codes = getattr(self.server, "force_status_code", None)
        if isinstance(forced_codes, list) and forced_codes:
            self._respond_error(forced_codes.pop(0))
            return
        if isinstance(forced_codes, int):
            self._respond_error(forced_codes)
            return

        if getattr(self.server, "force_error", False):
            self._respond_error(422)
            return

        messages = body.get("messages", [])
        tools = body.get("tools", [])
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        force_tc = getattr(self.server, "force_tool_call", False)

        if force_tc and tools and not has_tool_result:
            self._stream_tool_call()
        elif has_tool_result:
            tool_content = ""
            for m in messages:
                if m.get("role") == "tool":
                    tool_content = str(m.get("content", ""))
            text = (
                f"The current time is {tool_content}."
                if tool_content
                else MOCK_LLM_RESPONSE
            )
            self._stream_text(text)
        else:
            self._stream_text(MOCK_LLM_RESPONSE)

    def _respond_error(self, status_code: int = 422):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        err = {
            "error": {
                "message": f"forced status {status_code}",
                "type": "invalid_request_error",
            },
        }
        self.wfile.write(json.dumps(err).encode())

    def _stream_text(self, text: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        chunk = json.dumps(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": text,
                        },
                        "finish_reason": None,
                    },
                ],
                "usage": None,
            },
        )
        self.wfile.write(f"data: {chunk}\n\n".encode())
        self.wfile.flush()

        final = json.dumps(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    },
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )
        self.wfile.write(f"data: {final}\n\n".encode())
        self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _stream_tool_call(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        tool_name = getattr(
            self.server,
            "tool_call_name",
            "get_current_time",
        )
        tool_args = getattr(self.server, "tool_call_arguments", "{}")

        chunk1 = json.dumps(
            {
                "id": "chatcmpl-mock-tc",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_mock_tc",
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": "",
                                    },
                                },
                            ],
                        },
                        "finish_reason": None,
                    },
                ],
            },
        )
        self.wfile.write(f"data: {chunk1}\n\n".encode())
        self.wfile.flush()

        chunk2 = json.dumps(
            {
                "id": "chatcmpl-mock-tc",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {
                                        "arguments": tool_args,
                                    },
                                },
                            ],
                        },
                        "finish_reason": None,
                    },
                ],
            },
        )
        self.wfile.write(f"data: {chunk2}\n\n".encode())
        self.wfile.flush()

        chunk3 = json.dumps(
            {
                "id": "chatcmpl-mock-tc",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "tool_calls",
                    },
                ],
                "usage": {
                    "prompt_tokens": 15,
                    "completion_tokens": 10,
                    "total_tokens": 25,
                },
            },
        )
        self.wfile.write(f"data: {chunk3}\n\n".encode())
        self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _list_models(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {
                    "data": [
                        {"id": "mock-model", "object": "model"},
                    ],
                },
            ).encode(),
        )

    def log_message(self, fmt, *args):
        pass


# ------------------------------------------------------------------ #
# Mock LLM provider helpers
# ------------------------------------------------------------------ #


def register_mock_provider(app_server, mock_url: str) -> str:
    """Register + activate mock LLM provider. Returns provider id."""
    app_server.api_request(
        "POST",
        "/api/models/custom-providers",
        json={
            "id": MOCK_LLM_PROVIDER_ID,
            "name": "Integration Mock",
            "default_base_url": mock_url,
            "chat_model": "OpenAIChatModel",
            "models": [
                {"id": "mock-model", "name": "Mock Model"},
            ],
        },
        timeout=_HTTP_TIMEOUT,
    )
    app_server.api_request(
        "PUT",
        f"/api/models/{MOCK_LLM_PROVIDER_ID}/config",
        json={
            "api_key": "test-key-mock",
            "base_url": mock_url,
        },
        timeout=_HTTP_TIMEOUT,
    )
    app_server.api_request(
        "PUT",
        "/api/models/active",
        json={
            "provider_id": MOCK_LLM_PROVIDER_ID,
            "model": "mock-model",
            "scope": "global",
        },
        timeout=_HTTP_TIMEOUT,
    )
    return MOCK_LLM_PROVIDER_ID


def unregister_mock_provider(app_server, provider_id: str):
    """Best-effort cleanup of mock provider."""
    try:
        app_server.api_request(
            "DELETE",
            f"/api/models/custom-providers/{provider_id}",
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:
        pass
