# -*- coding: utf-8 -*-

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from collections import OrderedDict
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.message import Msg, TextBlock, ThinkingBlock

from copaw.providers.provider import ModelInfo, Provider

MAX_SESSION_CACHE_SIZE = 1000


def _build_headers(api_key: str) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        credentials = base64.b64encode(
            f"opencode:{api_key}".encode(),
        ).decode()
        headers["Authorization"] = f"Basic {credentials}"
    return headers


def _get_session_fingerprint(messages: List[Dict[str, Any]]) -> str:
    first_user_msg = next(
        (msg for msg in messages if msg.get("role") == "user"),
        None,
    )

    if first_user_msg is None:
        return "default"

    content = first_user_msg.get("content", "")
    if isinstance(content, list):
        content = str(content)

    return hashlib.md5(content[:100].encode()).hexdigest()[:16]


class OpenCodeChatModel(ChatModelBase):
    def __init__(
        self,
        model_name: str,
        base_url: str,
        api_key: str = "",
        stream: bool = True,
        generate_kwargs: Optional[Dict[str, Any]] = None,
        provider: Optional["OpenCodeProvider"] = None,
    ):
        super().__init__(model_name=model_name, stream=stream)
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.stream = stream
        self.generate_kwargs = generate_kwargs or {}
        self.headers = _build_headers(api_key)
        self._provider = provider

    def _client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=timeout,
        )

    async def _get_or_create_session(  # pylint: disable=protected-access
        self,
        messages: List[Dict[str, Any]],
    ) -> str:
        fingerprint = _get_session_fingerprint(messages)

        if self._provider is not None:
            opencode_session = self._provider._get_cached_session(fingerprint)
            if opencode_session is not None:
                return opencode_session

            opencode_session = await self._create_new_session()
            self._provider._cache_session(fingerprint, opencode_session)
            return opencode_session

        return await self._create_new_session()

    async def _create_new_session(self) -> str:
        try:
            async with self._client(timeout=30.0) as client:
                response = await client.post(
                    "/session",
                    json={"title": f"CoPaw {uuid.uuid4().hex[:8]}"},
                )
                response.raise_for_status()
                return response.json().get("id") or str(uuid.uuid4())
        except Exception:
            return str(uuid.uuid4())

    @staticmethod
    def _extract_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        return str(content)

    @classmethod
    def _extract_last_user_message(cls, messages: List[Dict[str, Any]]) -> str:
        msg = next(
            (m for m in reversed(messages) if m.get("role") == "user"),
            None,
        )
        return cls._extract_content(msg.get("content", "")) if msg else ""

    def _parse_model_name(self) -> tuple[str, str]:
        if "/" in self.model_name:
            parts = self.model_name.split("/", 1)
            return parts[0], parts[1]
        return self.model_name, self.model_name

    async def _send_message_async(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
    ) -> None:
        provider_id, model_id = self._parse_model_name()
        payload = {
            **self.generate_kwargs,
            "model": {
                "providerID": provider_id,
                "modelID": model_id,
            },
            "parts": [
                {
                    "type": "text",
                    "text": self._extract_last_user_message(messages),
                },
            ],
        }

        async with self._client(timeout=120.0) as client:
            response = await client.post(
                f"/session/{session_id}/prompt_async",
                json=payload,
            )
            response.raise_for_status()

    async def _stream_events(
        self,
        session_id: str,
    ) -> AsyncGenerator[ChatResponse, None]:
        part_contents: Dict[str, Dict[str, Any]] = {}

        async with self._client(timeout=300.0) as client:
            async with client.stream(
                "GET",
                "/event",
                headers={
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-cache",
                },
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type", "")
                    props = event.get("properties", {})

                    if props.get("sessionID") != session_id:
                        continue

                    if event_type == "message.part.updated":
                        part = props.get("part", {})
                        part_id = part.get("id", "")
                        part_type = part.get("type", "")
                        part_text = part.get("text", "")

                        if part_id not in part_contents:
                            part_contents[part_id] = {
                                "type": part_type,
                                "text": part_text,
                            }
                        else:
                            part_contents[part_id]["text"] = part_text

                        if part_type in ("reasoning", "text"):
                            yield self._build_response(part_contents)

                    elif event_type == "message.part.delta":
                        part_id = props.get("partID", "")
                        field = props.get("field", "")
                        delta = props.get("delta", "")

                        if part_id in part_contents and field == "text":
                            part_contents[part_id]["text"] += delta
                            part_type = part_contents[part_id].get("type", "")
                            if part_type in ("reasoning", "text"):
                                yield self._build_response(part_contents)

                    elif event_type == "session.status":
                        status = props.get("status", {})
                        if status.get("type") == "idle":
                            break

    def _build_response(
        self,
        part_contents: Dict[str, Dict[str, Any]],
    ) -> ChatResponse:
        thinking_text = ""
        response_text = ""

        for part_data in part_contents.values():
            part_type = part_data.get("type", "")
            part_text = part_data.get("text", "")
            if part_type == "reasoning":
                thinking_text = part_text
            elif part_type == "text":
                response_text = part_text

        contents: List[ThinkingBlock | TextBlock] = []
        if thinking_text:
            contents.append(
                ThinkingBlock(type="thinking", thinking=thinking_text),
            )
        if response_text:
            contents.append(TextBlock(type="text", text=response_text))

        return ChatResponse(content=contents)

    async def _stream_response(
        self,
        messages: List[Dict[str, Any]],
    ) -> AsyncGenerator[ChatResponse, None]:
        session_id = await self._get_or_create_session(messages)
        await self._send_message_async(session_id, messages)
        async for response in self._stream_events(session_id):
            yield response

    async def __call__(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        if self.stream:
            return self._stream_response(messages)

        responses = [r async for r in self._stream_response(messages)]
        if not responses:
            return ChatResponse(content=[TextBlock(type="text", text="")])

        return responses[-1]

    def format(
        self,
        *args: Any,
        **_kwargs: Any,
    ) -> List[Dict[str, Any]]:
        if not args or not isinstance(args[0], list):
            return []

        return [
            {"role": msg.role, "content": msg.content}
            if isinstance(msg, Msg)
            else msg
            if isinstance(msg, dict)
            else {"role": "user", "content": str(msg)}
            for msg in args[0]
        ]


class OpenCodeProvider(Provider):
    def __init__(self, **data: Any):
        super().__init__(**data)
        self._session_map: OrderedDict[str, str] = OrderedDict()
        self._session_last_used: Dict[str, float] = {}

    def _get_cached_session(self, fingerprint: str) -> Optional[str]:
        if fingerprint not in self._session_map:
            return None
        self._session_map.move_to_end(fingerprint)
        self._session_last_used[fingerprint] = time.time()
        return self._session_map[fingerprint]

    def _cache_session(self, fingerprint: str, session_id: str) -> None:
        if len(self._session_map) >= MAX_SESSION_CACHE_SIZE:
            oldest_key = next(iter(self._session_map))
            del self._session_map[oldest_key]
            del self._session_last_used[oldest_key]

        self._session_map[fingerprint] = session_id
        self._session_last_used[fingerprint] = time.time()

    def _client(self, timeout: float = 5.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=_build_headers(self.api_key),
            timeout=timeout,
        )

    async def check_connection(self, timeout: float = 5) -> tuple[bool, str]:
        try:
            async with self._client(timeout=timeout) as client:
                response = await client.get("/global/health")
                return self._parse_health_response(response)
        except httpx.ConnectError:
            return False, f"Cannot connect to {self.base_url}"
        except httpx.TimeoutException:
            return False, "Connection timeout"
        except Exception as e:
            return False, str(e)

    def _parse_health_response(
        self,
        response: httpx.Response,
    ) -> tuple[bool, str]:
        if response.status_code == 200:
            data = response.json()
            if data.get("healthy"):
                return True, f"OpenCode v{data.get('version', 'unknown')}"
            return False, "Server unhealthy"
        if response.status_code == 401:
            return False, "Authentication failed"
        return False, f"HTTP {response.status_code}"

    @staticmethod
    def _normalize_models(
        providers_data: List[Dict[str, Any]],
    ) -> List[ModelInfo]:
        models: List[ModelInfo] = []
        seen: set[str] = set()

        for provider in providers_data:
            provider_id = provider.get("id", "")
            provider_name = provider.get("name", provider_id)
            provider_models = provider.get("models", {})

            for model_id, model_data in provider_models.items():
                if not isinstance(model_data, dict):
                    continue

                model_name = model_data.get("name", model_id)
                display_name = f"{model_name} ({provider_name})"
                full_id = f"{provider_id}/{model_id}"

                if full_id in seen:
                    continue
                seen.add(full_id)

                models.append(
                    ModelInfo(
                        id=full_id,
                        name=display_name,
                    ),
                )

        return models

    async def fetch_models(self, timeout: float = 5) -> List[ModelInfo]:
        try:
            async with self._client(timeout=timeout) as client:
                response = await client.get("/config/providers")
                if response.status_code != 200:
                    return []

                data = response.json()
                return self._normalize_models(
                    data.get("providers", []),
                )
        except Exception:
            return []

    async def check_model_connection(
        self,
        model_id: str,
        timeout: float = 5,
    ) -> tuple[bool, str]:
        del model_id
        try:
            async with self._client(timeout=timeout) as client:
                create_resp = await client.post(
                    "/session",
                    json={"title": "Test"},
                )
                if create_resp.status_code != 200:
                    return False, "Session creation failed"

                session_id = create_resp.json().get("id")
                if not session_id:
                    return False, "No session ID returned"

                test_resp = await client.post(
                    f"/session/{session_id}/message",
                    json={"parts": [{"type": "text", "text": "Hi"}]},
                )

                if test_resp.status_code == 200:
                    return True, ""
                if test_resp.status_code == 401:
                    return False, "Authentication failed"
                return False, f"Test failed: {test_resp.status_code}"
        except Exception as e:
            return False, str(e)

    def get_chat_model_instance(self, model_id: str) -> ChatModelBase:
        return OpenCodeChatModel(
            model_name=model_id,
            base_url=self.base_url,
            api_key=self.api_key,
            stream=True,
            generate_kwargs=self.generate_kwargs,
            provider=self,
        )
