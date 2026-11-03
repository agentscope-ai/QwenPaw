# -*- coding: utf-8 -*-
"""Provider-required output limits, never per-operation token budgets.

OpenAI-compatible and Gemini requests omit output limits entirely. Anthropic
Messages requires max_tokens: use the model's capability, not a small task
budget (or the SDK's 8192-token fallback).
"""

from functools import lru_cache
import re
from urllib.parse import quote

import httpx

from utils.exceptions import ModelError


@lru_cache(maxsize=1)
def _anthropic_model_limits() -> dict[str, int]:
    from agentscope.model import AnthropicChatModel

    return {
        card.name: card.output_size
        for card in AnthropicChatModel.list_models()
    }


def known_anthropic_output_limit(model_name: str) -> int | None:
    """Read installed model capabilities, including dated Claude aliases."""
    # MiniMax's Anthropic protocol documents a maximum of 204800 tokens:
    # https://platform.minimax.io/docs/api-reference/text-chat-anthropic
    if re.fullmatch(
        r"MiniMax-M2(?:\.[157])?(?:-highspeed)?",
        model_name,
        re.I,
    ):
        return 204800
    name = re.sub(r"-(?:\d{8}|latest)$", "", model_name)
    return _anthropic_model_limits().get(name)


async def anthropic_output_limit(
    model_name: str,
    *,
    base_url: str,
    api_key: str,
) -> int:
    """Resolve unknown models through the provider's read-only Models API."""
    known = known_anthropic_output_limit(model_name)
    if known is not None:
        return known
    base = base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    headers = {"anthropic-version": "2023-06-01"}
    if api_key:
        headers["x-api-key"] = api_key
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{base}/models/{quote(model_name, safe='')}",
                headers=headers,
            )
            response.raise_for_status()
            limit = response.json().get("max_tokens")
        if (
            isinstance(limit, int)
            and not isinstance(limit, bool)
            and limit > 0
        ):
            return limit
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise ModelError(
            f"无法读取 Anthropic 模型 {model_name} 的输出上限。"
            "此协议必须传入 max_tokens；请检查模型名称和 Models API，"
            "或使用该服务的 OpenAI 兼容协议。",
            model_name=model_name,
            retryable=False,
        ) from exc
    raise ModelError(
        f"Anthropic 模型 {model_name} 未提供有效的输出上限；"
        "请更新模型能力信息或使用该服务的 OpenAI 兼容协议。",
        model_name=model_name,
        retryable=False,
    )
