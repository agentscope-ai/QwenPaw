# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Small OpenAI-compatible text-model client for semantic media planning."""

from __future__ import annotations

import httpx

from models import config as model_config
from models.concurrency import model_slot
from utils.exceptions import ModelError


def _chat_url() -> str:
    base = model_config.get_text_base_url().rstrip("/")
    return (
        base
        if base.endswith("/chat/completions")
        else f"{base}/chat/completions"
    )


async def chat_completion(
    prompt: str,
    *,
    system_prompt: str = "",
    temperature: float = 0.2,
    max_tokens: int = 6000,
    timeout: float = 180.0,
) -> str:
    """Call the configured text model without accepting any media content parts."""

    api_key = model_config.get_text_api_key()
    model_name = model_config.get_text_model_name()
    if not api_key:
        raise ModelError(
            "Creator text model API key 未配置",
            model_name=model_name,
        )
    messages: list[dict[str, str]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt})
    body = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with model_slot("text"):
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    _chat_url(),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        if response.status_code >= 400:
            raise ModelError(
                f"Text model HTTP {response.status_code}: {response.text[:500]}",
                model_name=model_name,
            )
        payload = response.json()
        choices = payload.get("choices") or []
        content = (
            choices[0].get("message", {}).get("content")
            if choices and isinstance(choices[0], dict)
            else None
        )
        if not isinstance(content, str) or not content.strip():
            raise ModelError("Text model 返回空内容", model_name=model_name)
        return content.strip()
    except ModelError:
        raise
    except Exception as exc:
        # ``str(exc)`` is empty for httpx timeout classes; keep the type
        # name so operators can tell a timeout from a broken endpoint.
        raise ModelError(
            f"Text model request failed: {type(exc).__name__}: {exc}",
            model_name=model_name,
        ) from exc


__all__ = ["chat_completion"]
