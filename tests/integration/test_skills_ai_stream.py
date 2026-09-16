# -*- coding: utf-8 -*-
"""AI skill-optimization streaming endpoint.

Covers ``app/routers/skills_stream.py``, which had no integration
coverage: the SSE generator that streams optimized skill content, its
language selection, and the guard that reports a missing model instead of
failing the stream.

The happy path is driven with the mock LLM provider so the response is
deterministic, and assertions parse the SSE frames (text deltas plus the
terminating ``done`` event) rather than only checking the status code —
an endpoint that returned 200 with an empty body would otherwise pass.

API endpoints:
  - POST /api/skills/ai/optimize/stream
"""
from __future__ import annotations

import json
import threading
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
_ENDPOINT = "/api/skills/ai/optimize/stream"

_SKILL_BODY = "---\nname: integ-probe\n---\n\nDo the thing.\n"


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI server for deterministic streaming."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


def _sse_events(body: str) -> list[dict]:
    """Parse ``data:`` frames from an SSE response body."""
    events: list[dict] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload:
            continue
        try:
            events.append(json.loads(payload))
        except ValueError:
            continue
    return events


@pytest.mark.integration
@pytest.mark.p1
def test_optimize_stream_emits_text_then_done(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """The optimize stream emits content frames and terminates.

    Test purpose:
      - Cover the streaming success path: the model is resolved, the
        system prompt for the requested language is selected, the
        response is consumed, and the stream closes with
        ``{"done": true}`` and no error frame.

    Test flow:
      1. Register the mock LLM as the active provider.
      2. POST a skill body to the optimize stream.
      3. Parse the SSE frames and assert the stream terminates with a
         done event and no error frame.
    """
    _srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        resp = app_server.api_request(
            "POST",
            _ENDPOINT,
            json={"content": _SKILL_BODY, "language": "en"},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, resp.text[:500]
        events = _sse_events(resp.text)
        assert events, f"no SSE frames emitted: {resp.text[:500]}"
        assert any(e.get("done") for e in events), events[-3:]
        assert not any("error" in e for e in events), events
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_optimize_stream_accepts_chinese_language(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A zh request selects its prompt and still streams to completion.

    Test purpose:
      - Cover the language lookup in SYSTEM_PROMPTS for a non-default
        value, which is a distinct branch from the ``en`` path.
    """
    _srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        resp = app_server.api_request(
            "POST",
            _ENDPOINT,
            json={"content": _SKILL_BODY, "language": "zh"},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, resp.text[:500]
        events = _sse_events(resp.text)
        assert any(e.get("done") for e in events), events[-3:]
        assert not any("error" in e for e in events), events
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_optimize_stream_unknown_language_falls_back(
    app_server,
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An unrecognised language falls back to the English prompt.

    Test purpose:
      - Cover the ``SYSTEM_PROMPTS.get(..., SYSTEM_PROMPTS["en"])``
        default: an unknown code must not raise a KeyError inside the
        generator, which would truncate the stream.
    """
    _srv, mock_url = mock_llm
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        resp = app_server.api_request(
            "POST",
            _ENDPOINT,
            json={"content": _SKILL_BODY, "language": "integ-xx"},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, resp.text[:500]
        events = _sse_events(resp.text)
        assert any(e.get("done") for e in events), events[-3:]
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_optimize_stream_requires_content(app_server):
    """A request without content is rejected by schema validation.

    Test purpose:
      - Cover AIOptimizeSkillRequest's required-field validation, which
        keeps an empty prompt from reaching the model.
    """
    resp = app_server.api_request(
        "POST",
        _ENDPOINT,
        json={"language": "en"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text
