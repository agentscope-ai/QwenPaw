# -*- coding: utf-8 -*-
"""Translate the Hub's bounded Chat contract into native model protocols."""

from __future__ import annotations

import json
from copy import deepcopy


def anthropic_base_url(base_url: str) -> str:
    """Give the SDK a root; it appends its own /v1 resource prefix."""
    return base_url.rstrip(f"/").removesuffix(f"/v1")


def protocol_url(base_url: str, protocol: str) -> str:
    """Build the same resource URL used by the native protocol SDK."""
    if protocol == f"anthropic":
        return f"{anthropic_base_url(base_url)}/v1/messages"
    paths = {f"chat": f"chat/completions", f"responses": f"responses"}
    if protocol not in paths:
        raise ValueError(f"Unsupported model protocol: {protocol}")
    return f"{base_url.rstrip('/')}/{paths[protocol]}"


class WireProtocol:
    """Keep streaming conversion state private to one admitted request."""

    def __init__(self, protocol: str):
        if protocol not in {f"chat", f"responses", f"anthropic"}:
            raise ValueError(f"Unsupported gateway protocol: {protocol}")
        self.protocol = protocol
        self.input_usage: dict = {}
        self.tools: dict[int, int] = {}
        self.done = False

    @property
    def path(self) -> str:
        return {
            f"chat": f"chat/completions",
            f"responses": f"responses",
            f"anthropic": f"messages",
        }[self.protocol]

    # Keep the supported protocol cases together for review.
    # pylint: disable-next=too-many-branches
    def request(self, payload: dict) -> dict:
        """Reject unsupported controls instead of silently dropping them."""
        if self.protocol == f"chat":
            return deepcopy(payload)
        extra = set(payload) - {
            f"model",
            f"messages",
            f"stream",
            f"stream_options",
            f"max_tokens",
            f"max_completion_tokens",
            f"temperature",
            f"top_p",
            f"tools",
            f"tool_choice",
            f"stop",
            f"prompt_cache_key",
            f"prompt_cache_options",
            f"cache_control",
            f"reasoning",
            f"thinking",
            f"output_config",
        }
        if extra:
            raise ValueError(f"Unsupported {self.protocol} controls: {extra}")
        result = {
            k: deepcopy(v)
            for k, v in payload.items()
            if k
            in {
                f"model",
                f"stream",
                f"temperature",
                f"top_p",
            }
        }
        cap = payload.get(f"max_completion_tokens", payload.get(f"max_tokens"))
        if self.protocol == f"responses":
            if f"thinking" in payload or f"output_config" in payload:
                raise ValueError(f"Anthropic controls on Responses route")
            if f"reasoning" in payload:
                result[f"reasoning"] = deepcopy(payload[f"reasoning"])
            result[f"max_output_tokens"] = cap
            result[f"input"] = self._responses_input(payload[f"messages"])
            if payload.get(f"stop"):
                raise ValueError(f"Responses does not support stop sequences")
            for key in (f"prompt_cache_key", f"prompt_cache_options"):
                if key in payload:
                    result[key] = payload[key]
            if payload.get(f"tools"):
                result[f"tools"] = [
                    {f"type": f"function", **t[f"function"]}
                    for t in payload[f"tools"]
                ]
            choice = payload.get(f"tool_choice")
            if choice is not None:
                result[f"tool_choice"] = (
                    {f"type": f"function", **choice[f"function"]}
                    if isinstance(choice, dict)
                    else choice
                )
            return result
        if f"reasoning" in payload:
            raise ValueError(f"Responses reasoning on Anthropic route")
        for field in (f"thinking", f"output_config"):
            if field in payload:
                result[field] = deepcopy(payload[field])
        result[f"max_tokens"] = cap
        system, messages = self._anthropic_input(payload[f"messages"])
        if system:
            result[f"system"] = system
        result[f"messages"] = messages
        if f"stop" in payload:
            stop = payload[f"stop"]
            result[f"stop_sequences"] = (
                [stop] if isinstance(stop, str) else stop
            )
        if f"cache_control" in payload:
            result[f"cache_control"] = payload[f"cache_control"]
        if payload.get(f"tools"):
            result[f"tools"] = [
                {
                    f"name": t[f"function"][f"name"],
                    f"description": t[f"function"].get(f"description", f""),
                    f"input_schema": t[f"function"].get(f"parameters", {}),
                }
                for t in payload[f"tools"]
            ]
        choice = payload.get(f"tool_choice")
        if isinstance(choice, dict):
            result[f"tool_choice"] = {
                f"type": f"tool",
                f"name": choice[f"function"][f"name"],
            }
        elif choice:
            result[f"tool_choice"] = {
                f"type": f"any" if choice == f"required" else choice,
            }
        return result

    @staticmethod
    def _responses_input(messages: list[dict]) -> list:
        result = []
        for message in messages:
            role = message[f"role"]
            if role == f"tool":
                result.append(
                    {
                        f"type": f"function_call_output",
                        f"call_id": message[f"tool_call_id"],
                        f"output": message.get(f"content", f""),
                    },
                )
                continue
            content = message.get(f"content")
            if content:
                if isinstance(content, list):
                    blocks = []
                    for block in content:
                        if block[f"type"] == f"text":
                            blocks.append(
                                {
                                    **block,
                                    f"type": (
                                        f"output_text"
                                        if role == f"assistant"
                                        else f"input_text"
                                    ),
                                },
                            )
                        elif block[f"type"] == f"image_url":
                            blocks.append(
                                {
                                    f"type": f"input_image",
                                    **block[f"image_url"],
                                    f"image_url": block[f"image_url"][f"url"],
                                },
                            )
                            blocks[-1].pop(f"url", None)
                        else:
                            raise ValueError(f"Unsupported Responses content")
                    content = blocks
                result.append({f"role": role, f"content": content})
            for call in message.get(f"tool_calls", []):
                result.append(
                    {
                        f"type": f"function_call",
                        f"call_id": call[f"id"],
                        **call[f"function"],
                    },
                )
        return result

    @staticmethod
    # Keep the supported protocol cases together for review.
    # pylint: disable-next=too-many-branches
    def _anthropic_input(messages: list[dict]) -> tuple[list, list]:
        system, result = [], []
        for message in messages:
            role = message[f"role"]
            content = message.get(f"content") or []
            if isinstance(content, str):
                content = [{f"type": f"text", f"text": content}]
            content = deepcopy(content)
            for block in content:
                if block[f"type"] == f"image_url":
                    url = block[f"image_url"][f"url"]
                    if url.startswith(f"data:"):
                        mime, data = url[5:].split(f";base64,", 1)
                        source = {
                            f"type": f"base64",
                            f"media_type": mime,
                            f"data": data,
                        }
                    else:
                        source = {f"type": f"url", f"url": url}
                    block.clear()
                    block.update({f"type": f"image", f"source": source})
                elif block[f"type"] != f"text":
                    raise ValueError(f"Unsupported Anthropic content")
            if role in {f"system", f"developer"}:
                if result:
                    raise ValueError(f"System messages must be a prefix")
                system.extend(content)
                continue
            if role == f"tool":
                role = f"user"
                content = [
                    {
                        f"type": f"tool_result",
                        f"tool_use_id": message[f"tool_call_id"],
                        f"content": content,
                    },
                ]
            for call in message.get(f"tool_calls", []):
                content.append(
                    {
                        f"type": f"tool_use",
                        f"id": call[f"id"],
                        f"name": call[f"function"][f"name"],
                        f"input": json.loads(call[f"function"][f"arguments"]),
                    },
                )
            if result and result[-1][f"role"] == role:
                result[-1][f"content"].extend(content)
            else:
                result.append({f"role": role, f"content": content})
        return system, result

    def usage(self, usage: dict) -> dict:
        """Normalize complete native token accounting for Hub settlement."""
        if self.protocol == f"chat":
            return usage
        prompt = usage.get(f"input_tokens")
        output = usage.get(f"output_tokens")
        if type(prompt) is not int or type(output) is not int:
            return {}
        read = usage.get(f"cache_read_input_tokens", 0)
        write = usage.get(f"cache_creation_input_tokens", 0)
        if self.protocol == f"anthropic":
            prompt += read + write
        else:
            details = usage.get(f"input_tokens_details") or {}
            read = details.get(f"cached_tokens", 0)
            write = details.get(f"cache_write_tokens", 0)
        return {
            f"prompt_tokens": prompt,
            f"completion_tokens": output,
            f"total_tokens": prompt + output,
            f"prompt_tokens_details": {
                f"cached_tokens": read,
                f"cache_write_tokens": write,
            },
        }

    def response(self, payload: dict) -> dict:
        """Translate a complete response, preserving tool call identities."""
        if self.protocol == f"chat":
            return payload
        if payload.get(f"error"):
            raise ValueError(f"Upstream response error")
        if self.protocol == f"responses" and payload.get(f"status") in {
            f"failed",
            f"cancelled",
            f"queued",
            f"in_progress",
        }:
            raise ValueError(f"Upstream response incomplete")
        text, tools = [], []
        blocks = (
            payload.get(f"content", [])
            if self.protocol == f"anthropic"
            else payload.get(f"output", [])
        )
        for block in blocks:
            kind = block.get(f"type")
            if kind == f"message":
                text.extend(
                    b[f"text"]
                    for b in block.get(f"content", [])
                    if b.get(f"type") == f"output_text"
                )
            elif kind == f"text":
                text.append(block[f"text"])
            elif kind in {f"tool_use", f"function_call"}:
                tools.append(
                    {
                        f"id": block.get(f"call_id", block.get(f"id")),
                        f"type": f"function",
                        f"function": {
                            f"name": block[f"name"],
                            f"arguments": block.get(f"arguments")
                            or json.dumps(block.get(f"input", {})),
                        },
                    },
                )
        message = {f"role": f"assistant", f"content": f"".join(text)}
        if tools:
            message[f"tool_calls"] = tools
        reason = f"tool_calls" if tools else f"stop"
        if (
            payload.get(f"stop_reason") == f"max_tokens"
            or payload.get(f"status") == f"incomplete"
        ):
            reason = f"length"
        elif payload.get(f"stop_reason") == f"refusal":
            reason = f"content_filter"
        return {
            f"id": payload.get(f"id"),
            f"object": f"chat.completion",
            f"choices": [
                {f"index": 0, f"message": message, f"finish_reason": reason},
            ],
            f"usage": self.usage(payload.get(f"usage") or {}),
        }

    # Keep the supported protocol cases together for review.
    # pylint: disable-next=too-many-branches
    def event(self, payload: dict) -> dict | None:
        """Convert native stream events into bounded Chat deltas."""
        if self.protocol == f"chat":
            return payload
        kind = payload.get(f"type", f"")
        delta, usage, finish = {}, None, None
        if kind in {f"error", f"response.failed", f"response.incomplete"}:
            raise ValueError(f"Upstream stream incomplete")
        if kind == f"message_start":
            self.input_usage = payload[f"message"].get(f"usage", {})
        elif kind == f"message_delta":
            self.input_usage.update(payload.get(f"usage", {}))
            usage = self.usage(self.input_usage)
            reason = payload.get(f"delta", {}).get(f"stop_reason")
            finish = {
                f"tool_use": f"tool_calls",
                f"max_tokens": f"length",
            }.get(reason, f"stop")
        elif kind == f"message_stop":
            self.done = True
        elif kind == f"response.completed":
            usage = self.usage(payload[f"response"].get(f"usage", {}))
            finish = f"tool_calls" if self.tools else f"stop"
            self.done = True
        elif kind in {f"content_block_start", f"response.output_item.added"}:
            block = payload.get(f"content_block", payload.get(f"item", {}))
            if block.get(f"type") in {f"tool_use", f"function_call"}:
                index = payload.get(f"index", payload.get(f"output_index", 0))
                self.tools[index] = len(self.tools)
                delta[f"tool_calls"] = [
                    {
                        f"index": self.tools[index],
                        f"type": f"function",
                        f"id": block.get(f"call_id", block.get(f"id")),
                        f"function": {
                            f"name": block[f"name"],
                            f"arguments": f"",
                        },
                    },
                ]
        elif kind == f"response.output_text.delta":
            delta[f"content"] = payload[f"delta"]
        elif kind == f"response.function_call_arguments.delta":
            delta[f"tool_calls"] = [
                {
                    f"index": self.tools[payload[f"output_index"]],
                    f"function": {f"arguments": payload[f"delta"]},
                },
            ]
        elif kind == f"content_block_delta":
            block = payload[f"delta"]
            if block[f"type"] == f"text_delta":
                delta[f"content"] = block[f"text"]
            elif block[f"type"] == f"input_json_delta":
                delta[f"tool_calls"] = [
                    {
                        f"index": self.tools[payload[f"index"]],
                        f"function": {f"arguments": block[f"partial_json"]},
                    },
                ]
        if not delta and usage is None and finish is None:
            return None
        result = {
            f"object": f"chat.completion.chunk",
            f"choices": [
                {f"index": 0, f"delta": delta, f"finish_reason": finish},
            ],
        }
        if usage is not None:
            result[f"usage"] = usage
        return result
