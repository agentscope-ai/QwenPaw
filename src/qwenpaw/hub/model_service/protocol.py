# -*- coding: utf-8 -*-
"""Allowlisted OpenAI wire fields and normalized authoritative usage."""

from fastapi import HTTPException

_ALLOWED = {
    "model",
    "messages",
    "stream",
    "stream_options",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "temperature",
    "top_p",
    "stop",
    "seed",
    "response_format",
    "frequency_penalty",
    "presence_penalty",
    "max_tokens",
    "max_completion_tokens",
    "n",
}


def usage_tokens(payload: dict) -> int | None:
    """Accept complete nonnegative upstream usage without double counting."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    values = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
    if any(type(value) is not int or value < 0 for value in values):
        return None
    return sum(int(value) for value in values if value is not None)


def safe_payload(payload: dict, model_id: str) -> dict:
    """Expose only protocol output fields and the managed model alias."""
    if "error" in payload:
        raise ValueError("Upstream stream error")
    return {
        **{
            k: payload[k]
            for k in (
                "id",
                "object",
                "created",
                "choices",
                "usage",
            )
            if k in payload
        },
        "model": model_id,
    }


def validate_request(body):
    """Reject connection overrides and unbounded output parameters."""
    if not isinstance(body, dict) or set(body) - _ALLOWED:
        raise HTTPException(422, "Unsupported model request fields")
    if (
        not isinstance(body.get("model"), str)
        or not isinstance(body.get("messages"), list)
        or body.get("n", 1) != 1
        or type(body.get("stream", False)) is not bool
    ):
        raise HTTPException(422, "Invalid Chat Completions request")
    limits = [
        body[k]
        for k in ("max_tokens", "max_completion_tokens")
        if body.get(k) is not None
    ]
    if any(type(value) is not int or value <= 0 for value in limits):
        raise HTTPException(422, "Output limit must be a positive integer")
    return min(limits) if limits else None


def upstream_payload(body, model, cap):
    """Replace model routing and output bounds with server-owned values."""
    payload = {
        k: v
        for k, v in body.items()
        if k
        not in {
            "max_tokens",
            "max_completion_tokens",
            "stream_options",
        }
    }
    payload.update(
        {
            "model": model["upstream_model"],
            model["output_limit_field"]: cap,
        },
    )
    if body.get("stream", False):
        payload["stream_options"] = {"include_usage": True}
    return payload
