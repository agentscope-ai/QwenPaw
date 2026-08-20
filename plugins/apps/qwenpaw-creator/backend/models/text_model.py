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
from utils.exceptions import ModelError


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
    async with model_slot("text"):
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _openai_chat_url(),
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
    async with model_slot("text"):
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _anthropic_chat_url(),
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                json=body,
            )
    if response.status_code >= 400:
        raise ModelError(
            f"Text model HTTP {response.status_code}: {response.text[:500]}",
            model_name=model_name,
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
        raise ModelError(
            f"Text model HTTP {response.status_code}: {response.text[:500]}",
            model_name=model_name,
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
    if not api_key:
        raise ModelError(
            "Creator text model API key 未配置",
            model_name=model_name,
        )
    messages: list[dict[str, str]] = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt})
    try:
        protocol_lower = protocol.casefold()
        if "anthropic" in protocol_lower or "minimax" in protocol_lower:
            return await _call_anthropic(
                messages,
                api_key=api_key,
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        if "gemini" in protocol_lower or "google" in protocol_lower:
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
            f"Text model request failed: {type(exc).__name__}: {exc}",
            model_name=model_name,
        ) from exc


__all__ = ["chat_completion"]
