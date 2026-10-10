# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Text-model client for semantic media planning.

Supports three API protocols:

* OpenAI-compatible (``/chat/completions``) — the default for most providers.
* Anthropic Messages (``/v1/messages``) — used by Anthropic Claude and MiniMax.
* Google Gemini (``/v1beta/models/{model}:generateContent``).

The protocol is read from the persisted ``llm`` section of
``model_config.json`` (or the request-scoped tool config) via
``model_config.get_text_protocol()``.
"""

from __future__ import annotations

import httpx

from models import config as model_config
from models.concurrency import model_slot
from utils.exceptions import ModelError, redact_url, upstream_status_hint


def _openai_chat_url() -> str:
    base = model_config.get_text_base_url().rstrip("/")
    return (
        base
        if base.endswith("/chat/completions")
        else f"{base}/chat/completions"
    )


def _anthropic_chat_url() -> str:
    base = model_config.get_text_base_url().rstrip("/")
    return f"{base}/v1/messages"


def _gemini_chat_url(model_name: str) -> str:
    base = model_config.get_text_base_url().rstrip("/")
    return f"{base}/v1beta/models/{model_name}:generateContent"


def _http_error(
    response: httpx.Response,
    *,
    protocol: str,
    model_name: str,
    url: str,
) -> ModelError:
    """Build a ModelError carrying enough context to diagnose a failure.

    User reports that only say "model call failed" are not actionable, so
    the message names the protocol, model, endpoint, upstream status, and
    the upstream response excerpt plus a status-specific hint.
    """
    hint = upstream_status_hint(response.status_code)
    detail = f"上游响应: {response.text[:500]}" if response.text else "上游未返回响应体"
    message = (
        f"Text model 请求失败 [protocol={protocol} model={model_name} "
        f"endpoint={redact_url(url)}] "
        f"HTTP {response.status_code}: {detail}"
    )
    if hint:
        message = f"{message}。{hint}"
    # Upstream 4xx client errors are permanent: retrying will not help.
    return ModelError(
        message,
        model_name=model_name,
        retryable=response.status_code >= 500,
    )


async def _call_openai(
    messages: list[dict],
    *,
    api_key: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> str:
    body = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # Free-tier gateways (e.g. OpenCode Zen ``*-free``) accept requests
    # without an Authorization header; an empty Bearer value would be
    # rejected as an invalid key.
    url = _openai_chat_url()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with model_slot("text"):
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers=headers,
                json=body,
            )
    if response.status_code >= 400:
        raise _http_error(
            response,
            protocol="OpenAI-compatible",
            model_name=model_name,
            url=url,
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


async def _call_anthropic(
    messages: list[dict],
    *,
    api_key: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> str:
    # Anthropic does not support a ``system`` role in ``messages``; it uses
    # a top-level ``system`` field instead.
    system_text = ""
    filtered: list[dict] = []
    for msg in messages:
        if msg.get("role") == "system":
            system_text = msg.get("content", "")
        else:
            filtered.append(msg)
    body: dict = {
        "model": model_name,
        "max_tokens": max_tokens,
        "messages": filtered,
    }
    if system_text.strip():
        body["system"] = system_text.strip()
    if temperature > 0:
        body["temperature"] = temperature
    headers: dict = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key
    url = _anthropic_chat_url()
    async with model_slot("text"):
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers=headers,
                json=body,
            )
    if response.status_code >= 400:
        raise _http_error(
            response,
            protocol="Anthropic Messages",
            model_name=model_name,
            url=url,
        )
    payload = response.json()
    content_blocks = payload.get("content") or []
    text_parts = [
        block.get("text", "")
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    content = "\n".join(text_parts)
    if not content.strip():
        raise ModelError("Text model 返回空内容", model_name=model_name)
    return content.strip()


async def _call_gemini(
    messages: list[dict],
    *,
    api_key: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> str:
    # Gemini uses a ``contents`` array with ``parts``; system instructions
    # go into a separate ``systemInstruction`` field.
    system_text = ""
    contents: list[dict] = []
    for msg in messages:
        role = msg.get("role", "")
        text = msg.get("content", "")
        if role == "system":
            system_text = text
        elif role == "user":
            contents.append({"role": "user", "parts": [{"text": text}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": text}]})
    body: dict = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system_text.strip():
        body["systemInstruction"] = {"parts": [{"text": system_text.strip()}]}
    if temperature > 0:
        body["generationConfig"]["temperature"] = temperature
    url = _gemini_chat_url(model_name)
    if api_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={api_key}"
    async with model_slot("text"):
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json=body,
            )
    if response.status_code >= 400:
        raise _http_error(
            response,
            protocol="Google Gemini",
            model_name=model_name,
            url=url,
        )
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        raise ModelError("Text model 返回空内容", model_name=model_name)
    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    content_obj = candidate.get("content") or {}
    parts = content_obj.get("parts") or []
    text_parts = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    content = "\n".join(text_parts)
    if not content.strip():
        raise ModelError("Text model 返回空内容", model_name=model_name)
    return content.strip()


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
    protocol = model_config.get_text_protocol()
    # Anthropic and Gemini gateways always authenticate; OpenAI-compatible
    # gateways may serve free keyless models (e.g. OpenCode Zen), so an
    # empty key is only an error for protocols that require one.
    if not api_key and model_config.protocol_requires_api_key(protocol):
        raise ModelError(
            "Creator text model API key 未配置：协议 "
            f"'{protocol}' 必须提供 API Key（模型: '{model_name or '未配置'}'，"
            f"Base URL: '{model_config.get_text_base_url() or '未配置'}'）。"
            "请在 Creator 模型配置弹窗或环境变量中填写 API Key；"
            "若使用免 Key 的免费模型（如 OpenCode Zen *-free），"
            "请选择 OpenAI 兼容协议。",
            model_name=model_name,
            retryable=False,
        )
    messages: list[dict[str, str]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt})
    try:
        if model_config.is_anthropic_protocol(protocol):
            return await _call_anthropic(
                messages,
                api_key=api_key,
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        if model_config.is_gemini_protocol(protocol):
            return await _call_gemini(
                messages,
                api_key=api_key,
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        return await _call_openai(
            messages,
            api_key=api_key,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    except ModelError:
        raise
    except Exception as exc:
        raise ModelError(
            f"Text model request failed [protocol={protocol} "
            f"model={model_name} base_url="
            f"{model_config.get_text_base_url()}] "
            f"{type(exc).__name__}: {exc}",
            model_name=model_name,
        ) from exc


__all__ = ["chat_completion"]
