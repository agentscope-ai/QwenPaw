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
    access_token: str
    account_id: str = ""
    source: str = ""


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

    def _client(self, timeout: float | None = 30) -> AsyncOpenAI:
        headers = {"originator": "codex_cli_rs"}
        if self._account_id:
            headers["ChatGPT-Account-ID"] = self._account_id
        return AsyncOpenAI(
            api_key=self._access_token,
            base_url=CODEX_BASE_URL,
            default_headers=headers,
            timeout=timeout,
        )

    @staticmethod
    def _normalize_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [CodexChatModel._normalize_content(item) for item in content]
            return "\n".join(part for part in parts if part).strip()
        if isinstance(content, dict):
            block_type = content.get("type")
            if block_type == "text":
                text = content.get("text")
                return text if isinstance(text, str) else ""
            if block_type == "thinking":
                thinking = content.get("thinking")
                return thinking if isinstance(thinking, str) else ""
            if block_type == "tool_result":
                result = content.get("output")
                return CodexChatModel._normalize_content(result)
            if "text" in content and isinstance(content["text"], str):
                return content["text"]
            if "content" in content:
                return CodexChatModel._normalize_content(content["content"])
            try:
                return json.dumps(content, ensure_ascii=False)
            except TypeError:
                return str(content)
        return str(content)

    def _convert_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
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

    def _parse_response(self, response: dict[str, Any]) -> ChatResponse:
        content_blocks: list = []
        reasoning_parts: list[str] = []
        text_parts: list[str] = []
        tool_blocks: list[ToolUseBlock] = []

        for output_item in response.get("output", []):
            item_type = output_item.get("type")
            if item_type == "reasoning":
                for summary_item in output_item.get("summary", []):
                    if (
                        isinstance(summary_item, dict)
                        and summary_item.get("type") == "summary_text"
                    ):
                        text = summary_item.get("text", "")
                        if isinstance(text, str) and text:
                            reasoning_parts.append(text)
            elif item_type == "message":
                for part in output_item.get("content", []):
                    if part.get("type") == "output_text":
                        text = part.get("text", "")
                        if isinstance(text, str) and text:
                            text_parts.append(text)
            elif item_type == "function_call":
                raw_arguments = output_item.get("arguments", "{}")
                parsed_arguments: dict[str, Any]
                if isinstance(raw_arguments, dict):
                    parsed_arguments = raw_arguments
                else:
                    try:
                        parsed_arguments = json.loads(raw_arguments or "{}")
                    except (TypeError, json.JSONDecodeError):
                        parsed_arguments = {}

                tool_blocks.append(
                    ToolUseBlock(
                        type="tool_use",
                        id=output_item.get("call_id", ""),
                        name=output_item.get("name", ""),
                        input=parsed_arguments,
                        raw_input=raw_arguments if isinstance(raw_arguments, str) else json.dumps(raw_arguments),
                    ),
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

    async def _collect_response_payload(self, response_or_stream: Any) -> dict[str, Any]:
        if hasattr(response_or_stream, "__aiter__"):
            completed_response: Any = None
            try:
                async for event in response_or_stream:
                    event_type = getattr(event, "type", None)
                    if event_type == "response.completed":
                        completed_response = getattr(event, "response", None)
            finally:
                close = getattr(response_or_stream, "close", None)
                if close is not None:
                    await close()

            if completed_response is None:
                raise RuntimeError(
                    "Codex API stream ended without response.completed event",
                )
            if hasattr(completed_response, "model_dump"):
                return completed_response.model_dump()
            return completed_response

        if hasattr(response_or_stream, "model_dump"):
            return response_or_stream.model_dump()
        return response_or_stream

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
        create_kwargs["instructions"] = instructions or CODEX_DEFAULT_INSTRUCTIONS
        converted_tools = self._convert_tools(tools)
        if converted_tools:
            create_kwargs["tools"] = converted_tools
        converted_tool_choice = self._convert_tool_choice(tool_choice)
        if converted_tool_choice is not None:
            create_kwargs["tool_choice"] = converted_tool_choice

        response = await self._client(timeout=merged_kwargs.pop("timeout", 30)).responses.create(
            **create_kwargs,
        )
        payload = await self._collect_response_payload(response)
        return self._parse_response(payload)


class CodexProvider(Provider):
    """Built-in provider that reuses local Codex CLI auth."""

    def _load_credential(self) -> CodexCliCredential | None:
        return load_codex_cli_credential()

    def _client(self, timeout: float = 5) -> AsyncOpenAI:
        credential = self._load_credential()
        if credential is None:
            raise RuntimeError(
                "Codex CLI credential not found. Expected ~/.codex/auth.json or CODEX_AUTH_PATH.",
            )
        return CodexChatModel(
            model_name=self.models[0].id if self.models else "gpt-5.4",
            access_token=credential.access_token,
            account_id=credential.account_id,
            stream=False,
        )._client(timeout=timeout)

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        credential = self._load_credential()
        if credential is None:
            return False, "Codex CLI credential not found"

        model_id = self.models[0].id if self.models else "gpt-5.4"
        client = self._client(timeout=timeout)
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
            await CodexChatModel(
                model_name=model_id,
                access_token=credential.access_token,
                account_id=credential.account_id,
            )._collect_response_payload(response)
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
        credential = self._load_credential()
        if credential is None:
            return False, "Codex CLI credential not found"

        client = self._client(timeout=timeout)
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
            await CodexChatModel(
                model_name=model_id,
                access_token=credential.access_token,
                account_id=credential.account_id,
            )._collect_response_payload(response)
            return True, ""
        except APIError:
            return False, f"API error when connecting to model '{model_id}'"
        except Exception as exc:
            return False, (
                f"Unknown exception when connecting to model '{model_id}': {exc}"
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
