# -*- coding: utf-8 -*-
"""Decode JSON and server-sent events from OpenAI-compatible chat endpoints."""

from __future__ import annotations

import json
from typing import Any

import httpx

from utils.exceptions import ModelError

_EVENT_DONE = "[DONE]"
# A gateway that is not serving the API at all answers with the frontend
# shell (200 + SPA HTML) or with an nginx error page; both are caught here so
# the caller sees "wrong endpoint" instead of a JSON decode error or an empty
# completion.
_HTML_MARKERS = ("<!doctype", "<html", "<head", "<body")
_MAX_BODY_ECHO = 300


def is_event_stream(content_type: str) -> bool:
    """True when the response body is an SSE stream."""
    return "text/event-stream" in (content_type or "").casefold()


def _looks_like_html(text: str) -> bool:
    stripped = text.lstrip()[:400].casefold()
    return any(stripped.startswith(marker) for marker in _HTML_MARKERS)


def parse_sse_frames(text: str) -> list[dict]:
    """Split an SSE body into decoded data frames.

    Handles ``data:`` with or without the optional leading space (the proxy
    sends no space), multi-line data events, comments and ``id:``/``event:``
    fields, and stops collecting at the ``[DONE]`` sentinel.
    """
    frames: list[dict] = []
    unparsable = 0
    for raw_event in (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .split(
            "\n\n",
        )
    ):
        data_lines: list[str] = []
        for line in raw_event.split("\n"):
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                # id: / event: / retry: carry no payload for this consumer.
                continue
            value = line[len("data:") :]
            if value.startswith(" "):
                value = value[1:]
            data_lines.append(value)
        if not data_lines:
            continue
        payload = "\n".join(data_lines).strip()
        if not payload:
            continue
        if payload == _EVENT_DONE:
            break
        try:
            parsed = json.loads(payload)
        except ValueError:
            unparsable += 1
            continue
        if isinstance(parsed, dict):
            frames.append(parsed)
    if not frames and text.strip():
        raise ModelError(
            "gateway returned an unreadable SSE body "
            f"({unparsable} data frame(s) failed to parse): "
            f"{text[:_MAX_BODY_ECHO]}",
        )
    return frames


def sse_stream_terminated(text: str) -> bool:
    """Whether the stream carried the closing ``[DONE]`` sentinel.

    :func:`parse_sse_frames` consumes the sentinel and stops there, so the
    aggregator cannot tell a politely-ended stream from one the gateway severed
    mid-flight. This reads the raw body for it, which is what makes a
    truncation claim safe rather than a guess.
    """

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        if line[len("data:") :].strip() == _EVENT_DONE:
            return True
    return False


def _fold_tool_calls(
    accumulated: list[dict],
    streamed: list[dict],
) -> None:
    """Merge streamed ``tool_calls`` deltas by their ``index``."""
    for fragment in streamed:
        if not isinstance(fragment, dict):
            continue
        try:
            index = int(fragment.get("index", len(accumulated)))
        except (TypeError, ValueError):
            index = len(accumulated)
        while len(accumulated) <= index:
            accumulated.append(
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )
        slot = accumulated[index]
        if fragment.get("id"):
            slot["id"] = str(fragment["id"])
        if fragment.get("type"):
            slot["type"] = str(fragment["type"])
        function = fragment.get("function")
        if not isinstance(function, dict):
            continue
        if function.get("name"):
            slot["function"]["name"] += str(function["name"])
        if function.get("arguments"):
            slot["function"]["arguments"] += str(function["arguments"])


def _delta_payload(choice: dict) -> dict:
    """The streamed delta, or the whole message when a server sends one."""
    for key in ("delta", "message"):
        payload = choice.get(key)
        if isinstance(payload, dict):
            return payload
    return {}


def _fold_choice(choice: dict, state: dict) -> None:
    """Apply one streamed choice onto the accumulating completion state."""
    payload = _delta_payload(choice)
    text = payload.get("content")
    if isinstance(text, str) and text:
        state["content_parts"].append(text)
    # ``reasoning_content`` is the thinking trace of a reasoning model;
    # folding it into the answer would leak chain-of-thought into the
    # assistant text every downstream consumer reads.
    if payload.get("reasoning_content"):
        state["reasoning_seen"] = True
    streamed_calls = payload.get("tool_calls")
    if isinstance(streamed_calls, list):
        _fold_tool_calls(state["tool_calls"], streamed_calls)
    if choice.get("finish_reason"):
        state["finish_reason"] = str(choice["finish_reason"])


def aggregate_stream_to_completion(
    frames: list[dict],
    *,
    terminated: bool = True,
) -> dict:
    """Fold streamed chunks into one non-streaming ``chat.completion`` dict."""
    state: dict[str, Any] = {
        "content_parts": [],
        "tool_calls": [],
        "reasoning_seen": False,
        "finish_reason": "",
        "usage": {},
        "envelope": {},
    }

    envelope: dict = state["envelope"]
    for frame in frames:
        for key in ("id", "model", "created", "system_fingerprint"):
            if key in envelope or frame.get(key) in (None, ""):
                continue
            envelope[key] = frame[key]
        if isinstance(frame.get("usage"), dict):
            state["usage"] = frame["usage"]
        for choice in frame.get("choices") or []:
            if isinstance(choice, dict):
                _fold_choice(choice, state)

    content_parts: list[str] = state["content_parts"]
    tool_calls: list[dict] = state["tool_calls"]
    reasoning_seen: bool = state["reasoning_seen"]
    finish_reason: str = state["finish_reason"]
    usage: dict = state["usage"]

    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content_parts),
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    completion: dict[str, Any] = {
        "choices": [
            {
                "message": message,
                "finish_reason": finish_reason or "stop",
            },
        ],
    }
    if usage:
        completion["usage"] = usage
    completion.update(envelope)
    # Side channel for a reply that carries no text: the folded
    # ``finish_reason`` keeps its "stop" default so every existing parser
    # still sees the shape it expects, while these keys record that the
    # upstream never said how it ended, and how many frames were seen.
    completion["_frame_count"] = len(frames)
    if not finish_reason:
        completion["_finish_reason_missing"] = True
    # Neither an ending reason nor a closing sentinel means the gateway stopped
    # talking mid-answer: what was folded is a prefix. Providers that end
    # politely without ever reporting a finish_reason stay out of this branch.
    if not finish_reason and not terminated:
        completion["_stream_truncated"] = True
    if reasoning_seen:
        completion["_reasoning_content_dropped"] = True
    return completion


def _raise_for_streamed_error(frames: list[dict]) -> None:
    """Surface an error frame carried inside an otherwise 200 stream."""
    for frame in frames:
        error = frame.get("error")
        if not isinstance(error, dict):
            continue
        code = str(error.get("code") or "")
        request_id = str(frame.get("request_id") or "")
        raise ModelError(
            "gateway returned an error inside the SSE stream: "
            f"{code or 'unknown'} {str(error.get('message') or '')[:200]}"
            + (f" (request_id={request_id})" if request_id else ""),
            retryable=False,
        )


def decode_chat_response(
    *,
    status_code: int,
    text: str,
    content_type: str,
    model_name: str,
    url: str = "",
) -> dict:
    """Return a ``chat.completion``-shaped dict from a chat response body.

    Accepts a plain JSON body and the forced-SSE body alike; rejects an HTML
    answer, which means the configured base URL is not serving the API.
    """
    location = f" endpoint={url}" if url else ""
    if is_event_stream(content_type) or text.lstrip().startswith("data:"):
        frames = parse_sse_frames(text)
        if not frames:
            raise ModelError(
                f"gateway returned an empty SSE stream{location}",
                model_name=model_name,
            )
        _raise_for_streamed_error(frames)
        return aggregate_stream_to_completion(
            frames,
            terminated=sse_stream_terminated(text),
        )
    if _looks_like_html(text):
        raise ModelError(
            f"HTTP {status_code} returned an HTML page instead of a chat "
            f"completion{location} - the base URL is not the model API: "
            f"{text[:_MAX_BODY_ECHO]}",
            model_name=model_name,
        )
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ModelError(
            f"unreadable chat response (HTTP {status_code}){location}: "
            f"{text[:_MAX_BODY_ECHO]}",
            model_name=model_name,
        ) from exc
    if not isinstance(payload, dict):
        raise ModelError(
            f"unexpected chat response type {type(payload).__name__}"
            f"{location}",
            model_name=model_name,
        )
    return payload


def read_chat_response(
    response: httpx.Response, *, gateway: bool, model_name: str, url: str
) -> dict:
    """Read the native JSON response or a provider's streamed completion."""
    if not gateway:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except ValueError:
            # An endpoint may serve SSE even when the client requested JSON.
            pass
    return decode_chat_response(
        status_code=response.status_code,
        content_type=response.headers.get("content-type", ""),
        text=response.text,
        model_name=model_name,
        url=url,
    )
