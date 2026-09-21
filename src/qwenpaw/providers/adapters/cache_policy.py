# -*- coding: utf-8 -*-
"""Wire-level cache controls, independent of catalog and billing."""

from copy import deepcopy
from typing import Any


# Keep the supported protocol cases together for review.
# pylint: disable-next=too-many-branches
def cache_request(
    kwargs: dict[str, Any],
    protocol: str,
    modes: frozenset[str],
) -> dict[str, Any]:
    """Validate opt-in controls and use the pinned SDK's extra body."""
    result = deepcopy(kwargs)
    if result.get(f"extra_body") is None:
        result.pop(f"extra_body", None)
    extra = result.get(f"extra_body", {})
    if not isinstance(extra, dict):
        raise ValueError(f"extra_body must be an object")
    for name in (
        f"prompt_cache_options",
        f"cache_control",
        f"prompt_cache_key",
        f"prompt_cache_retention",
        f"enable_prompt_cache_breakpoint",
    ):
        if name in extra:
            if name in result:
                raise ValueError(f"Duplicate cache control: {name}")
            result[name] = extra.pop(name)
    enabled = result.pop(f"enable_prompt_cache_breakpoint", False)
    if type(enabled) is not bool:
        raise ValueError(f"Cache breakpoint flag must be boolean")
    if enabled and not (
        protocol == f"responses"
        and f"openai_explicit" in modes
        or protocol in {f"chat", f"anthropic"}
        and f"anthropic" in modes
    ):
        raise ValueError(f"Explicit caching is unsupported for this model")
    options = result.pop(f"prompt_cache_options", None)
    if options is not None:
        if protocol != f"responses" or f"openai_explicit" not in modes:
            raise ValueError(f"Explicit Responses caching is unsupported")
        if not isinstance(options, dict) or set(options) - {f"mode", f"ttl"}:
            raise ValueError(f"Invalid prompt_cache_options")
        if options.get(f"ttl", f"30m") != f"30m":
            raise ValueError(f"Explicit cache TTL must be 30m")
        if options.get(f"mode", f"implicit") not in {f"implicit", f"explicit"}:
            raise ValueError(f"Invalid prompt cache mode")
        result.setdefault(f"extra_body", {})[f"prompt_cache_options"] = options
    if f"cache_control" in result and f"anthropic" not in modes:
        raise ValueError(f"This provider does not support cache_control")
    control = result.get(f"cache_control")
    if control is not None:
        if (
            not isinstance(control, dict)
            or set(control) - {f"type", f"ttl"}
            or control.get(f"type") != f"ephemeral"
            or control.get(f"ttl", f"5m") not in {f"5m", f"1h"}
        ):
            raise ValueError(f"Invalid cache_control")
        if protocol == f"chat":
            result.pop(f"cache_control")
            result.setdefault(f"extra_body", {})[f"cache_control"] = control
    for name in (f"prompt_cache_key", f"prompt_cache_retention"):
        if name in result and not modes.intersection(
            {
                f"openai",
                f"openai_explicit",
            },
        ):
            raise ValueError(f"Unsupported cache control: {name}")
    return result


def mark_stable_prefix(messages: list[dict], *, responses: bool) -> list:
    """Mark only the last text block of the leading instruction prefix."""
    result = deepcopy(messages)
    last = None
    for message in result:
        if message.get(f"role") not in {f"system", f"developer"}:
            break
        content = message.get(f"content")
        if isinstance(content, str):
            content = [
                {
                    f"type": f"input_text" if responses else f"text",
                    f"text": content,
                },
            ]
            message[f"content"] = content
        for block in content or []:
            if isinstance(block, dict) and block.get(f"type") in {
                f"input_text",
                f"text",
            }:
                last = block
    if last is not None:
        key = f"prompt_cache_breakpoint" if responses else f"cache_control"
        value = (
            {f"mode": f"explicit"}
            if responses
            else {
                f"type": f"ephemeral",
            }
        )
        last.setdefault(key, value)
    return result
