# -*- coding: utf-8 -*-
"""Account-scoped ChatGPT plan models on the public Responses endpoint."""

from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
from agentscope.credential import OpenAICredential
from agentscope.message import Msg, TextBlock
from agentscope.model import OpenAIResponseModel
from agentscope.tool import ToolChoice
from openai import AsyncOpenAI

from .adapters.chatgpt import ChatGPTStream
from .oauth.chatgpt import RESOURCE, chatgpt_accounts
from .openai_response_provider import OpenAIResponseModelCompat
from .provider import ModelInfo, Provider, ProviderInfo
from .thinking import ThinkingControl


class ChatGPTModel(OpenAIResponseModelCompat):
    """Reuse native history and response parsing with plan-only requests."""

    def __init__(
        self,
        model_id: str,
        context_size: int = 200000,
        extra_generate_kwargs: dict | None = None,
    ):
        super().__init__(
            credential=OpenAICredential(api_key=f"oauth-per-request"),
            model=model_id,
            context_size=context_size,
            parameters=OpenAIResponseModel.Parameters(),
            max_retries=0,
            extra_generate_kwargs=extra_generate_kwargs,
        )

    async def _call_api(
        self,
        model_name: str,
        messages: list[Msg],
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        **generate_kwargs,
    ):
        items = await self.formatter.format(messages)
        for item in items:
            if item.get(f"role") == f"system":
                item[f"role"] = f"developer"
            if item.get(f"type") == f"function_call":
                item[f"namespace"] = f"qwenpaw"
        functions, choice = self._format_tools(tools, tool_choice)
        payload = {
            f"model": model_name,
            f"input": items,
            f"store": False,
            f"stream": True,
            f"include": [f"reasoning.encrypted_content"],
        }
        if functions:
            payload[f"tools"] = [
                {
                    f"type": f"namespace",
                    f"name": f"qwenpaw",
                    f"description": f"Tools executed by the QwenPaw agent.",
                    f"tools": functions,
                },
            ]
            if isinstance(choice, dict):
                name = choice[f"name"]
                payload[f"tools"][0][f"tools"] = [
                    tool for tool in functions if tool[f"name"] == name
                ]
                choice = f"required"
            if choice:
                payload[f"tool_choice"] = choice
        generate_kwargs = {**self._extra_generate_kwargs, **generate_kwargs}
        if generate_kwargs.get(f"reasoning"):
            payload[f"reasoning"] = generate_kwargs[f"reasoning"]
        # Sampling, token limits, and server-side history are not supported.
        structured = generate_kwargs.get(f"structured_model")
        if structured:
            payload[f"text"] = {
                f"format": {
                    f"type": f"json_schema",
                    f"name": structured.__name__,
                    f"schema": structured.model_json_schema(),
                    f"strict": False,
                },
            }
        token = await asyncio.to_thread(chatgpt_accounts.access_token)
        stream = self._plan_stream(payload, token, structured)
        if self.stream:
            return stream
        async for chunk in stream:
            result = chunk
        return result

    async def _plan_stream(self, payload: dict, token: str, structured):
        started = datetime.now()
        async with AsyncOpenAI(
            api_key=token,
            base_url=RESOURCE,
            max_retries=0,
            timeout=120,
        ) as client:
            stream = await client.responses.create(**payload)

            plan_stream = ChatGPTStream(stream)
            async for chunk in self._parse_stream_response(
                started,
                plan_stream,
            ):
                yield chunk
            result = self._parse_completion_response(
                started,
                plan_stream.completed,
            )
            if structured:
                text = f"".join(
                    b.text for b in result.content if b.type == f"text"
                )
                result.metadata = structured.model_validate_json(
                    text,
                ).model_dump()
            yield result


class ChatGPTProvider(Provider):
    """Keep subscription credentials and models outside API-key catalogs."""

    wire_protocol = f"responses"

    def discovery_candidates(self) -> list[ModelInfo]:
        return [
            m
            for m in self.discovered_models
            if m.id not in self.hidden_model_ids
        ]

    async def get_info(
        self,
        mock_secret: bool = True,
        *,
        include_candidates: bool = True,
    ) -> ProviderInfo:
        del mock_secret
        info = ProviderInfo.model_validate(self.model_dump())
        info.name = f"ChatGPT Subscription"
        info.api_key = f""
        info.discovered_models = (
            self.discovery_candidates() if include_candidates else []
        )
        session = await asyncio.to_thread(chatgpt_accounts.status)
        info.oauth_connected = session[f"sharing"]
        info.meta = {**info.meta, f"chatgpt_session": session}
        info.model_count = len(self.discovered_models)
        info.models = [self.model_capabilities(m) for m in info.models]
        info.extra_models = [
            self.model_capabilities(m) for m in info.extra_models
        ]
        if not session[f"sharing"]:
            info.models = []
            info.extra_models = []
            info.discovered_models = []
            info.model_count = 0
        return info

    def model_capabilities(self, model: ModelInfo) -> ModelInfo:
        """Use account discovery without importing API-key catalog limits."""
        discovered = self.get_discovered_model_info(model.id)
        if not discovered:
            return model
        fields = {
            f"name",
            f"supports_image",
            f"supports_multimodal",
            f"supports_video",
            f"supports_audio",
            f"supports_tool_calling",
            f"thinking_control",
            f"reasoning_effort",
            f"max_input_length",
            f"max_input_length_auto_detected",
            f"effective_max_input_length",
            f"automatic_max_input_length",
            f"context_length_source",
            f"capability_provenance",
        }
        return model.model_copy(
            update={field: getattr(discovered, field) for field in fields},
        )

    def resolve_model_info(self, model_id: str) -> ModelInfo:
        """Keep agent context and picker capabilities account-scoped."""
        return self.model_capabilities(
            self.get_model_info(model_id)
            or self.get_discovered_model_info(model_id)
            or ModelInfo(id=model_id, name=model_id),
        )

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 60,
    ) -> tuple[bool, str]:
        async def check():
            model = self.get_chat_model_instance(model_id)
            stream = await model(
                [
                    Msg(
                        name=f"user",
                        role=f"user",
                        content=[TextBlock(text=f"Say OK.")],
                    ),
                ],
            )
            async for _ in stream:
                pass

        try:
            await asyncio.wait_for(check(), timeout)
            return True, f""
        except Exception:
            return (
                False,
                f"Check ChatGPT sign-in, model access and plan usage.",
            )

    async def fetch_model_pricing(
        self,
        models: list[ModelInfo] | None = None,
        timeout: float = 5,
    ) -> dict:
        """Plan allowances are not Platform API prices."""
        return {}

    async def fetch_models(self, timeout: float = 20) -> list[ModelInfo]:
        token = await asyncio.to_thread(chatgpt_accounts.access_token)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{RESOURCE}/models",
                headers={f"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
        models = []
        for row in response.json()[f"models"]:
            if row.get(f"visibility") != f"list":
                continue
            modalities = row.get(f"input_modalities")
            image = f"image" in modalities if modalities is not None else None
            context = row.get(f"context_window")
            efforts = [
                level[f"effort"]
                for level in row.get(f"supported_reasoning_levels", [])
                if level.get(f"effort")
                in {
                    f"minimal",
                    f"low",
                    f"medium",
                    f"high",
                    f"xhigh",
                    f"max",
                }
            ]
            maximum = row.get(f"max_context_window") or context
            limits = {}
            if isinstance(context, int) and context >= 1000:
                limits = {
                    f"max_input_length": context,
                    f"effective_max_input_length": context,
                    f"automatic_max_input_length": context,
                    f"context_length_source": f"api",
                    f"max_input_length_auto_detected": maximum,
                    f"capability_provenance": {
                        f"context_window": {
                            f"source": f"{RESOURCE}/models",
                            f"default": context,
                            f"maximum": maximum,
                        },
                    },
                }
            models.append(
                ModelInfo(
                    id=row[f"slug"],
                    name=row[f"display_name"],
                    supports_image=image,
                    supports_multimodal=image,
                    supports_video=False,
                    supports_audio=False,
                    supports_tool_calling=True,
                    thinking_control=(
                        ThinkingControl(kind=f"effort", efforts=efforts)
                        if efforts
                        else None
                    ),
                    reasoning_effort=row.get(f"default_reasoning_level"),
                    source=f"discovered",
                    discovery_origin=f"api",
                    **limits,
                ),
            )
        return models

    async def check_connection(self, timeout: float = 20) -> tuple[bool, str]:
        try:
            await self.fetch_models(timeout)
            return True, f""
        except (ValueError, httpx.HTTPError):
            return False, f"Check ChatGPT sign-in and plan permissions."

    def get_chat_model_instance(self, model_id: str) -> ChatGPTModel:
        model = self.resolve_model_info(model_id)
        return ChatGPTModel(
            model_id,
            context_size=model.max_input_length,
            extra_generate_kwargs=self.get_effective_generate_kwargs(model_id),
        )
