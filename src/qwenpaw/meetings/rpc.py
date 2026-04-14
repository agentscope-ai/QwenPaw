# -*- coding: utf-8 -*-
"""SACP RPC Client for calling Agent services."""

import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class SACPClient:
    """SACP RPC 客户端."""

    def __init__(
        self,
        timeout: int = 300,
        _internal_base_url: Optional[str] = None,
    ):
        """初始化 SACP 客户端.

        Args:
            timeout: 超时时间(秒)
            internal_base_url: 内部 agent 的基础 URL (默认从配置读取 CLI 指定的 host/port)
        """
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _resolve_url(self, url: str) -> str:
        """Resolve Agent URL, internal agent or external agent.
        Args:
            url: Agent URL
        Returns:
            full Agent URL
        """
        if url.startswith("/agents/") or url.startswith("agents/"):
            # internal URL format:
            # /agents/{agent_id} -> http://127.0.0.1:8088/api/sacp
            internal_base_url = self._get_internal_base_url()
            return internal_base_url.rstrip("/") + "/sacp"
        return url

    @staticmethod
    def _get_internal_base_url() -> str:
        """Get the base URL for internal agents from config.

        Reads the last used host/port from config (set by CLI --host/--port).

        Returns:
            Base URL for internal agents (e.g., http://127.0.0.1:8088/api)
        """
        try:
            from qwenpaw.config.utils import read_last_api

            result = read_last_api()
            if result:
                host, port = result
                return f"http://{host}:{port}/api"
        except Exception as e:
            logger.debug(f"Failed to read last_api config: {e}")

        # Fallback to default
        return "http://127.0.0.1:8088/api"

    async def close(self) -> None:
        """关闭客户端."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        url: str,
        auth_key: str,
        message: str,
        session_id: str = None,
        ask_agent_id: str = None,
        reply_agent_id: str = None,
        stream: bool = False,
    ) -> dict:
        """发送聊天请求.

        Args:
            url: Agent 服务地址
            auth_key: 认证密钥
            message: 消息内容
            session_id: 会话 ID
            stream: 是否流式响应
            ask_agent_id: 请求者的 agent ID (主持人)
            reply_agent_id: 回复目标 agent ID

        Returns:
            响应结果 (流式模式下返回完整文本内容)
        """

        # Resolve URL (handle internal agents with relative paths)
        resolved_url = self._resolve_url(url)

        headers = {
            "Content-Type": "application/json",
            "X-Auth-Key": auth_key,
            "X-Agent-Id": reply_agent_id,
        }

        payload = {
            "session_id": session_id or "",
            "reply_agent_id": reply_agent_id or "",
            "ask_agent_id": ask_agent_id or "",
            "message": message,
            "stream": stream,
        }

        try:
            client = await self._get_client()
            if stream:
                # 流式响应：读取 SSE 流并拼接完整内容
                full_content = await self._collect_stream(
                    client,
                    resolved_url,
                    payload,
                    headers,
                )
                return {"type": "text", "content": full_content}
            else:
                response = await client.post(
                    f"{resolved_url}/chat",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"[meetings] rpc: request failed, err: {e}")
            raise

    @staticmethod
    async def _collect_stream(
        client: httpx.AsyncClient,
        url: str,
        payload: dict,
        headers: dict,
    ) -> str:
        """处理 SSE 流式响应.

        Args:
            client: HTTP 客户端
            url: Agent 服务地址 (已解析)
            payload: 请求 payload
            headers: 请求头

        Returns:
            完整的文本内容
        """
        async with client.stream(
            "POST",
            f"{url}/chat",
            json=payload,
            headers=headers,
        ) as response:
            response.raise_for_status()
            full_content = ""
            async for line in response.aiter_lines():
                # SSE 格式: "data: {\"type\": \"text\", \"content\": \"...\"}"
                if line.startswith("data: "):
                    data = line[6:]  # 去掉 "data: " 前缀
                    if data in ("[DONE]", "done"):
                        break
                    try:
                        msg = json.loads(data)
                        if msg.get("type") == "text":
                            full_content += msg.get("content", "")
                        elif msg.get("type") == "done":
                            break
                    except json.JSONDecodeError:
                        # 如果不是 JSON，可能是纯文本
                        logger.warning(
                            "[meetings] rpc: JSON decode error in stream, "
                            "treating as plain text: %s",
                            data[:100],
                        )
                        full_content += data
                elif line.strip():
                    # 非 data: 行，可能是纯文本
                    full_content += line
            return full_content

    async def health_check(
        self,
        url: str,
        auth_key: str,
        agent_id: Optional[str] = None,
    ) -> dict:
        """健康检查.

        Args:
            url: Agent 服务地址
            auth_key: 认证密钥
            agent_id: 目标 agent ID (用于内部 agent)

        Returns:
            健康状态
        """
        client = await self._get_client()

        # Resolve URL (handle internal agents with relative paths)
        resolved_url = self._resolve_url(url)

        headers = {
            "Content-Type": "application/json",
            "X-Auth-Key": auth_key,
            "X-Agent-Id": agent_id,
        }

        try:
            response = await client.get(
                f"{resolved_url}/health",
                headers=headers,
            )
            response.raise_for_status()
            logger.info(
                f"[meetings] rpc: health check success for {resolved_url}",
            )
            return response.json()
        except Exception as e:
            logger.error(f"[meetings] rpc: health check failed, err: {e}")
            return {"status": "unhealthy", "error": str(e)}
