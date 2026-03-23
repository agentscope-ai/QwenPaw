# -*- coding: utf-8 -*-
"""Codex provider backed by local Codex CLI credentials."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator, Literal, Type

from agentscope.message import TextBlock, ThinkingBlock, ToolUseBlock
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel

from copaw.providers.provider import ModelInfo, Provider

logger = logging.getLogger(__name__)

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_DEFAULT_INSTRUCTIONS = "You are a helpful assistant."
CODEX_DEFAULT_MODELS = [
    ModelInfo(id="gpt-5.4", name="GPT-5.4"),
    ModelInfo(id="gpt-5.4-mini", name="GPT-5.4 Mini"),
]


@dataclass(eq=True)
class CodexCliCredential:
    """Credential loaded from a local Codex CLI auth file."""

    access_token: str
    account_id: str = ""
    source: str = ""


def _build_codex_client(
    *,
    access_token: str,
    account_id: str,
    timeout: float | None = 30,
) -> AsyncOpenAI:
    headers = {"originator": "codex_cli_rs"}
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    return AsyncOpenAI(
        api_key=access_token,
        base_url=CODEX_BASE_URL,
        default_headers=headers,
        timeout=timeout,
    )


async def _collect_response_payload(response_or_stream: Any) -> dict[str, Any]:
    if hasattr(response_or_stream, "__aiter__"):
        completed_response: Any = None
        try:
            async for event in response_or_stream:
                if getattr(event, "type", None) == "response.completed":
                    completed_response = getattr(event, "response", None)
        finally:
            close = getattr(response_or_stream, "close", None)
            if close is not None:
                await close()

        if completed_response is None:
            raise RuntimeError(
                "Codex API stream ended without response.completed event",
            )
        response_or_stream = completed_response

    if hasattr(response_or_stream, "model_dump"):
        return response_or_stream.model_dump()
    return response_or_stream


def _resolve_credential_path() -> Path:
    override = os.getenv("CODEX_AUTH_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codex" / "auth.json"


def load_codex_cli_credential() -> CodexCliCredential | None:
    """Load Codex CLI auth from ~/.codex/auth.json or CODEX_AUTH_PATH."""
    auth_path = _resolve_credential_path()
    if not auth_path.exists() or auth_path.is_dir():
        return None

    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read Codex auth file: %s", auth_path)
        return None

    tokens = data.get("tokens", {})
    if not isinstance(tokens, dict):
        tokens = {}

    access_token = (
        data.get("access_token")
        or data.get("token")
        or tokens.get("access_token")
        or ""
    )
    account_id = data.get("account_id") or tokens.get("account_id") or ""

    if not isinstance(access_token, str) or not access_token.strip():
        return None

    return CodexCliCredential(
        access_token=access_token.strip(),
        account_id=str(account_id or "").strip(),
        source="codex-cli",
    )


class CodexChatModel(ChatModelBase):
    """ChatModelBase adapter for Codex Responses API."""

    def __init__(
        self,
        *,
        model_name: str,
        access_token: str,
        account_id: str,
        stream: bool = False,
        reasoning_effort: str = "medium",
        generate_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(model_name=model_name, stream=stream)
        self._access_token = access_token
        self._account_id = account_id
        self._reasoning_effort = reasoning_effort
        self._generate_kwargs = generate_kwargs or {}

    @staticmethod
    def _normalize_content_dict(content: dict[str, Any]) -> str:
        block_type = content.get("type")
        if block_type == "text":
            value = content.get("text", "")
        elif block_type == "thinking":
            value = content.get("thinking", "")
        elif block_type == "tool_result":
            value = content.get("output", "")
        elif isinstance(content.get("text"), str):
            value = content["text"]
        elif "content" in content:
            value = content["content"]
        else:
            try:
                return json.dumps(content, ensure_ascii=False)
            except TypeError:
                return str(content)
        return CodexChatModel._normalize_content(value)

    @staticmethod
    def _normalize_content(content: Any) -> str:
        normalized = content
        if isinstance(content, str):
            return normalized
        if isinstance(content, list):
            parts = [
                CodexChatModel._normalize_content(item)
                for item in content
            ]
            normalized = "\n".join(part for part in parts if part).strip()
        elif isinstance(content, dict):
            normalized = CodexChatModel._normalize_content_dict(content)
        else:
            normalized = str(content)
        return normalized

    def _convert_messages(
        self,
        messages: list[dict],
    ) -> tuple[str, list[dict]]:
        instructions_parts: list[str] = []
        input_items: list[dict] = []

        for message in messages:
            role = message.get("role")
            content = self._normalize_content(message.get("content", ""))

            if role == "system":
                if content:
                    instructions_parts.append(content)
                continue

            if role in {"user", "assistant"} and content:
                input_items.append({"role": role, "content": content})

            if role == "assistant":
                for tool_call in message.get("tool_calls") or []:
                    function = tool_call.get("function") or {}
                    arguments = function.get("arguments", "{}")
                    input_items.append(
                        {
                            "type": "function_call",
                            "name": function.get("name", ""),
                            "arguments": arguments,
                            "call_id": tool_call.get("id", ""),
                        },
                    )
            elif role == "tool":
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.get("tool_call_id", ""),
                        "output": content,
                    },
                )

        instructions = "\n\n".join(part for part in instructions_parts if part)
        return instructions, input_items

    @staticmethod
    def _convert_tools(tools: list[dict] | None) -> list[dict]:
        responses_tools: list[dict] = []
        for tool in tools or []:
            if tool.get("type") == "function" and "function" in tool:
                function = tool["function"]
                responses_tools.append(
                    {
                        "type": "function",
                        "name": function["name"],
                        "description": function.get("description", ""),
                        "parameters": function.get("parameters", {}),
                    },
                )
        return responses_tools

    @staticmethod
    def _convert_tool_choice(
        tool_choice: Literal["auto", "none", "required"] | str | None,
    ) -> str | dict | None:
        if tool_choice in {None, "auto", "none", "required"}:
            return tool_choice
        return {"type": "function", "name": tool_choice}

    @staticmethod
    def _collect_reasoning_parts(output_item: dict[str, Any]) -> list[str]:
        reasoning_parts: list[str] = []
        for summary_item in output_item.get("summary", []):
            if not isinstance(summary_item, dict):
                continue
            if summary_item.get("type") != "summary_text":
                continue
            text = summary_item.get("text", "")
            if isinstance(text, str) and text:
                reasoning_parts.append(text)
        return reasoning_parts

    @staticmethod
    def _collect_text_parts(output_item: dict[str, Any]) -> list[str]:
        text_parts: list[str] = []
        for part in output_item.get("content", []):
            if part.get("type") != "output_text":
                continue
            text = part.get("text", "")
            if isinstance(text, str) and text:
                text_parts.append(text)
        return text_parts

    @staticmethod
    def _parse_tool_use_block(output_item: dict[str, Any]) -> ToolUseBlock:
        raw_arguments = output_item.get("arguments", "{}")
        if isinstance(raw_arguments, dict):
            parsed_arguments = raw_arguments
            raw_input = json.dumps(raw_arguments)
        else:
            try:
                parsed_arguments = json.loads(raw_arguments or "{}")
            except (TypeError, json.JSONDecodeError):
                parsed_arguments = {}
            raw_input = raw_arguments

        return ToolUseBlock(
            type="tool_use",
            id=output_item.get("call_id", ""),
            name=output_item.get("name", ""),
            input=parsed_arguments,
            raw_input=raw_input,
        )

    def _parse_response(self, response: dict[str, Any]) -> ChatResponse:
        content_blocks: list = []
        reasoning_parts: list[str] = []
        text_parts: list[str] = []
        tool_blocks: list[ToolUseBlock] = []

        for output_item in response.get("output", []):
            item_type = output_item.get("type")
            if item_type == "reasoning":
                reasoning_parts.extend(
                    self._collect_reasoning_parts(output_item),
                )
                continue
            if item_type == "message":
                text_parts.extend(self._collect_text_parts(output_item))
                continue
            if item_type == "function_call":
                tool_blocks.append(
                    self._parse_tool_use_block(output_item),
                )

        if reasoning_parts:
            content_blocks.append(
                ThinkingBlock(
                    type="thinking",
                    thinking="\n".join(reasoning_parts),
                ),
            )
        if text_parts:
            content_blocks.append(
                TextBlock(
                    type="text",
                    text="".join(text_parts),
                ),
            )
        content_blocks.extend(tool_blocks)

        usage_raw = response.get("usage") or {}
        usage = ChatUsage(
            input_tokens=usage_raw.get("input_tokens", 0),
            output_tokens=usage_raw.get("output_tokens", 0),
            time=0.0,
        )
        return ChatResponse(content=content_blocks, usage=usage)

    async def _collect_response_payload(
        self,
        response_or_stream: Any,
    ) -> dict[str, Any]:
        return await _collect_response_payload(response_or_stream)

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        del structured_model
        merged_kwargs = {**self._generate_kwargs, **kwargs}
        reasoning_effort = merged_kwargs.pop(
            "reasoning_effort",
            self._reasoning_effort,
        )
        merged_kwargs.pop("max_output_tokens", None)
        merged_kwargs.pop("max_tokens", None)

        instructions, input_items = self._convert_messages(messages)
        create_kwargs: dict[str, Any] = {
            "model": self.model_name,
            "input": input_items,
            "store": False,
            "stream": True,
            "reasoning": {
                "effort": reasoning_effort,
            },
        }
        create_kwargs["instructions"] = (
            instructions or CODEX_DEFAULT_INSTRUCTIONS
        )
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            create_kwargs["tools"] = converted_tools
        converted_tool_choice = self._convert_tool_choice(tool_choice)
        if converted_tool_choice is not None:
            create_kwargs["tool_choice"] = converted_tool_choice

        client = _build_codex_client(
            access_token=self._access_token,
            account_id=self._account_id,
            timeout=merged_kwargs.pop("timeout", 30),
        )
        response = await client.responses.create(
            **create_kwargs,
        )
        payload = await _collect_response_payload(response)
        return self._parse_response(payload)


class CodexProvider(Provider):
    """Built-in provider that reuses local Codex CLI auth."""

    def _load_credential(self) -> CodexCliCredential | None:
        return load_codex_cli_credential()

    def _client(self, timeout: float = 5) -> AsyncOpenAI:
        credential = self._load_credential()
        if credential is None:
            raise RuntimeError(
                "Codex CLI credential not found. Expected ~/.codex/auth.json "
                "or CODEX_AUTH_PATH.",
            )
        return _build_codex_client(
            access_token=credential.access_token,
            account_id=credential.account_id,
            timeout=timeout,
        )

    def _get_client_and_credential(
        self,
        timeout: float = 5,
    ) -> tuple[AsyncOpenAI, CodexCliCredential] | tuple[None, None]:
        credential = self._load_credential()
        if credential is None:
            return None, None
        return (
            self._client(timeout=timeout),
            credential,
        )

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        client, _credential = self._get_client_and_credential(
            timeout=timeout,
        )
        if client is None:
            return False, "Codex CLI credential not found"
        model_id = self.models[0].id if self.models else "gpt-5.4"
        try:
            response = await client.responses.create(
                model=model_id,
                instructions=CODEX_DEFAULT_INSTRUCTIONS,
                input=[{"role": "user", "content": "ping"}],
                reasoning={"effort": "none"},
                store=False,
                stream=True,
                timeout=timeout,
            )
            await _collect_response_payload(response)
            return True, ""
        except APIError:
            return False, "API error when connecting to Codex"
        except Exception as exc:
            return False, f"Unknown exception when connecting to Codex: {exc}"

    async def fetch_models(self, timeout: float = 5) -> list[ModelInfo]:
        del timeout
        return list(self.models)

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        client, _credential = self._get_client_and_credential(timeout=timeout)
        if client is None:
            return False, "Codex CLI credential not found"
        try:
            response = await client.responses.create(
                model=model_id,
                instructions=CODEX_DEFAULT_INSTRUCTIONS,
                input=[{"role": "user", "content": "ping"}],
                reasoning={"effort": "none"},
                store=False,
                stream=True,
                timeout=timeout,
            )
            await _collect_response_payload(response)
            return True, ""
        except APIError:
            return False, f"API error when connecting to model '{model_id}'"
        except Exception as exc:
            return False, (
                "Unknown exception when connecting to model "
                f"'{model_id}': {exc}"
            )

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        credential = self._load_credential()
        if credential is None:
            raise ValueError(
                "Codex CLI credential not found. Run codex login first.",
            )

        reasoning_effort = str(
            self.generate_kwargs.get("reasoning_effort", "medium"),
        )
        return CodexChatModel(
            model_name=model_id,
            access_token=credential.access_token,
            account_id=credential.account_id,
            stream=False,
            reasoning_effort=reasoning_effort,
            generate_kwargs=self.generate_kwargs,
        )
