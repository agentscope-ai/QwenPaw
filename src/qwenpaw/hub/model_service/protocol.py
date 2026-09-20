# -*- coding: utf-8 -*-
"""Allowlisted OpenAI wire fields and normalized authoritative usage."""

from fastapi import HTTPException
from pydantic import ValidationError

from ...providers.thinking import ThinkingPreference

from .provider_setup import model_provider

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
    "hub_thinking_level",
    "hub_thinking_budget",
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
    try:
        ThinkingPreference(
            level=body.get(f"hub_thinking_level", f"inherit"),
            budget_tokens=body.get(f"hub_thinking_budget"),
        )
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid Hub thinking setting") from exc
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


def upstream_payload(body, model, cap, connection):
    """Replace model routing and output bounds with server-owned values."""
    payload = {
        k: v
        for k, v in body.items()
        if k
        not in {
            "max_tokens",
            "max_completion_tokens",
            "stream_options",
            "hub_thinking_level",
            "hub_thinking_budget",
        }
    }
    payload["model"] = model["upstream_model"]
    if cap is not None:
        payload[model["output_limit_field"]] = cap
    level = body.get("hub_thinking_level", "inherit")
    if level != "inherit":
        provider = model_provider(model, connection)
        if not provider.supports_agent_thinking(model["upstream_model"]):
            raise HTTPException(422, "Model does not support thinking control")
        controls = provider.get_agent_thinking_kwargs(
            model["upstream_model"],
            level,
            body.get(f"hub_thinking_budget"),
        )
        protocol = provider.model_protocol(model[f"upstream_model"])
        if protocol == f"anthropic":
            enabled = controls.pop(f"thinking_enable", None)
            budget = controls.pop(f"thinking_budget", None)
            if f"thinking" not in controls and enabled is not None:
                controls[f"thinking"] = (
                    {f"type": f"enabled", f"budget_tokens": budget}
                    if enabled
                    else {f"type": f"disabled"}
                )
            thinking = controls.get(f"thinking", {})
            if thinking.get(f"type") == f"enabled":
                if cap <= 1024:
                    raise HTTPException(422, f"Output cap is below budget")
                thinking[f"budget_tokens"] = min(
                    thinking[f"budget_tokens"],
                    cap - 1,
                )
        payload.update(controls.pop("extra_body", {}))
        if controls.pop("disable_thinking", False):
            payload.update(
                enable_thinking=False,
                thinking={"type": "disabled"},
            )
        if "thinking_enable" in controls:
            controls["enable_thinking"] = controls.pop("thinking_enable")
        if "thinking_budget" in controls and cap is not None:
            controls["thinking_budget"] = min(controls["thinking_budget"], cap)
        payload.update(controls)
    if body.get("stream", False):
        payload["stream_options"] = {"include_usage": True}
    return payload
