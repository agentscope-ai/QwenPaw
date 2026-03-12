# -*- coding: utf-8 -*-
"""企业微信 AI Bot 频道 - 基于 wecom-aibot-sdk

使用官方 wecom-aibot-sdk 实现企业微信 AI Bot 集成：
- 接收文本/图片/混合/语音/文件消息
- 流式消息回复（打字机效果）
- 进入会话时发送欢迎消息
- 自动心跳保活和重连
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from wecom_aibot_sdk import WSClient
from wecom_aibot_sdk.types import WsFrame

from ..base import (
    BaseChannel,
    ImageContent,
    OnReplySent,
    ProcessHandler,
)
from ....config.config import WecomConfig as WecomChannelConfig
from . import handlers, stream
from .utils import save_image_to_dir

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

logger = logging.getLogger(__name__)


class WecomChannel(BaseChannel):
    """企业微信 AI Bot 频道"""

    channel = "wecom"

    def __init__(
        self,
        config: WecomChannelConfig,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ):
        """初始化企业微信频道

        Args:
            config: 企业微信配置
            process: 消息处理函数
            on_reply_sent: 回复发送回调
        """
        super().__init__(
            process=process,
            on_reply_sent=on_reply_sent,
            show_tool_details=True,
            filter_tool_messages=config.filter_tool_messages,
            filter_thinking=config.filter_thinking,
            dm_policy=config.dm_policy,
            group_policy=config.group_policy,
            allow_from=config.allow_from,
            deny_message=config.deny_message,
        )
        self.config = config
        self.bot_id = config.bot_id
        self.secret = config.secret
        self.media_dir = Path(config.media_dir).expanduser()
        self.media_dir.mkdir(parents=True, exist_ok=True)

        # SDK 客户端（连接时创建）
        self.client: Optional[WSClient] = None
        self.running = False
        self.active_tasks: set[asyncio.Task] = set()

        # 会话锁，用于消息排队（session_id -> lock）
        # 保证同一会话的消息按顺序处理，不同会话可以并发
        self._session_locks: Dict[str, asyncio.Lock] = {}
        # 记录锁的最后使用时间，用于清理
        self._lock_last_used: Dict[str, float] = {}

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: WecomChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,  # noqa: ARG003
        filter_tool_messages: bool = False,  # noqa: ARG003
        filter_thinking: bool = False,  # noqa: ARG003
    ) -> "WecomChannel":
        """从配置创建频道实例"""
        return cls(
            config=config,
            process=process,
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "WecomChannel":
        """从环境变量创建频道实例"""
        config = WecomChannelConfig(
            enabled=True,
            bot_id=os.getenv("WECOM_BOT_ID", ""),
            secret=os.getenv("WECOM_SECRET", ""),
            media_dir=os.getenv("WECOM_MEDIA_DIR", "~/.copaw/media"),
        )
        return cls(
            config=config,
            process=process,
            on_reply_sent=on_reply_sent,
        )

    # -- 生命周期 -------------------------------------------------------

    async def start(self) -> None:
        """启动频道并建立 WebSocket 连接"""
        if self.running:
            logger.warning("WecomChannel is already running")
            return

        if not self.bot_id or not self.secret:
            raise ValueError(
                "WeCom config incomplete: bot_id and secret are required",
            )

        self._validate_credentials()
        self.running = True
        logger.info(
            "Starting WeCom Channel, Bot ID: %s... (masked)",
            self.bot_id[:8],
        )

        # 创建 SDK WSClient - 处理 WebSocket、心跳、重连
        self.client = WSClient(bot_id=self.bot_id, secret=self.secret)
        self._register_handlers()

        try:
            await self.client.connect()
        except Exception as exc:
            logger.error("Failed to start WebSocket client: %s", exc)
            self.running = False
            raise

    def _validate_credentials(self) -> None:
        """验证凭证长度是否合理"""
        if len(self.bot_id) < 10:
            logger.warning(
                "bot_id length looks suspicious (%d chars), check config",
                len(self.bot_id),
            )
        if len(self.secret) < 20:
            logger.warning(
                "secret length looks suspicious (%d chars), check config",
                len(self.secret),
            )

    async def stop(self) -> None:
        """停止频道并关闭 WebSocket 连接"""
        if not self.running:
            return

        logger.info("Stopping WeCom Channel")
        self.running = False

        # 清理会话锁
        self._session_locks.clear()
        self._lock_last_used.clear()

        # 取消并等待活跃任务
        if self.active_tasks:
            for task in self.active_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self.active_tasks, return_exceptions=True)
            self.active_tasks.clear()

        if self.client:
            await self.client.disconnect()
            self.client = None

        logger.info("WeCom Channel stopped")

    # -- SDK 事件注册 ------------------------------------------

    def _register_handlers(self) -> None:
        """注册所有 SDK 事件处理器"""
        if not self.client:
            return

        # 连接状态事件
        self.client.on(
            "connected",
            lambda: logger.info("[WeCom] WebSocket connected"),
        )
        self.client.on(
            "authenticated",
            lambda: logger.info("[WeCom] Authenticated"),
        )
        self.client.on(
            "disconnected",
            lambda reason: logger.warning(
                "[WeCom] Disconnected: %s", reason,
            ),
        )
        self.client.on(
            "reconnecting",
            lambda attempt: logger.info(
                "[WeCom] Reconnecting, attempt %d", attempt,
            ),
        )
        self.client.on(
            "error",
            lambda err: logger.error("[WeCom] Error: %s", err),
        )

        # 消息事件
        self.client.on("message.text", self._on_text)
        self.client.on("message.image", self._on_image)
        self.client.on("message.mixed", self._on_mixed)
        self.client.on("message.voice", self._on_voice)
        self.client.on("message.file", self._on_file)

        # 事件回调
        self.client.on("event.enter_chat", self._on_enter_chat)
        self.client.on(
            "event.template_card_event",
            self._on_template_card_event,
        )
        self.client.on("event.feedback_event", self._on_feedback_event)

    # -- 消息事件回调（同步，委托给异步处理器） ------

    def _on_text(self, frame: WsFrame) -> None:
        """文本消息回调"""
        self._spawn(handlers.handle_text(self, frame))

    def _on_image(self, frame: WsFrame) -> None:
        """图片消息回调"""
        self._spawn(handlers.handle_image(self, frame))

    def _on_mixed(self, frame: WsFrame) -> None:
        """混合消息回调"""
        self._spawn(handlers.handle_mixed(self, frame))

    def _on_voice(self, frame: WsFrame) -> None:
        """语音消息回调"""
        self._spawn(handlers.handle_voice(self, frame))

    def _on_file(self, frame: WsFrame) -> None:
        """文件消息回调"""
        self._spawn(handlers.handle_file(self, frame))

    def _on_enter_chat(self, frame: WsFrame) -> None:
        """进入会话事件，发送欢迎���息"""
        self._spawn(handlers.send_welcome(self, frame))

    def _on_template_card_event(self, frame: WsFrame) -> None:
        """模板卡片交互事件"""
        body = frame.get("body", {})
        event = body.get("event", {})
        logger.info(
            "[WeCom] Template card event: %s",
            event.get("eventtype"),
        )

    def _on_feedback_event(self, frame: WsFrame) -> None:
        """用户反馈事件"""
        body = frame.get("body", {})
        event = body.get("event", {})
        logger.info(
            "[WeCom] User feedback event: %s",
            event.get("eventtype"),
        )

    # -- 异步任务管理 -------------------------------------------

    def _spawn(self, coro: Any) -> None:
        """创建异步任务并跟踪（非阻塞）"""
        task = asyncio.create_task(coro)
        self.active_tasks.add(task)
        task.add_done_callback(self.active_tasks.discard)

    # -- 消息分发 ------------------------------------------------

    async def dispatch_message(
        self,
        frame: WsFrame,
        content_parts: list,
    ) -> None:
        """构建 AgentRequest 并使用会话锁处理消息

        使用每个会话独立的锁来保证同一用户的消息按顺序处理，
        同时允许不同用户的消息并发处理。这种方式在保证消息
        顺序的同时，保留了流式输出的上下文。

        Args:
            frame: SDK 原始 WsFrame
            content_parts: 内容部分列表（文本/图片）
        """
        headers = frame.get("headers", {})
        req_id = headers.get("req_id", "")
        body = frame.get("body", {})

        from_user = body.get("from", {})
        user_id = from_user.get("userid", "")
        chatid = body.get("chatid") or user_id
        session_id = f"{self.channel}:{chatid}"

        # 获取或创建该会话的锁
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        lock = self._session_locks[session_id]

        try:
            # 使用锁保证消息按顺序处理
            async with lock:
                # 更新最后使用时间
                self._lock_last_used[session_id] = time.time()

                request = self.build_agent_request_from_user_content(
                    channel_id=self.channel,
                    sender_id=user_id,
                    session_id=session_id,
                    content_parts=content_parts,
                )

                await stream.dispatch_with_timeout(self, request, frame, req_id)

                # 定期清理旧锁（超过 100 个时）
                if len(self._session_locks) > 100:
                    self._cleanup_old_locks()

        except Exception as exc:
            logger.error(
                "[WeCom] Error processing message from %s: %s",
                user_id,
                exc,
                exc_info=True,
            )
            raise

    def _cleanup_old_locks(self) -> None:
        """清理 1 小时未使用的会话锁"""
        now = time.time()
        cutoff = now - 3600  # 1 小时
        to_remove = [
            sid
            for sid, last_used in self._lock_last_used.items()
            if last_used < cutoff
        ]
        for sid in to_remove:
            self._session_locks.pop(sid, None)
            self._lock_last_used.pop(sid, None)
        if to_remove:
            logger.debug(
                "[WeCom] Cleaned up %d old session locks",
                len(to_remove),
            )

    # -- 图片下载 --------------------------------------------------

    async def download_image(
        self,
        url: str,
        aes_key: str,
    ) -> Optional[ImageContent]:
        """使用 SDK 下载并解密图片，保存到本地

        Args:
            url: 图片下载 URL
            aes_key: AES 解密密钥

        Returns:
            包含本地文件路径的 ImageContent，失败返回 None
        """
        if not self.client:
            logger.error(
                "[WeCom] Client not initialized, cannot download image",
            )
            return None

        try:
            # SDK 处理下载 + AES-256-CBC 解密
            result = await self.client.download_file(url, aes_key)
            data: bytes = result["buffer"]
            return save_image_to_dir(data, self.media_dir)
        except Exception as exc:
            logger.error(
                "[WeCom] Image download/decrypt failed: %s",
                exc,
                exc_info=True,
            )
            return None

    # -- 主动消息发送 ---------------------------------------

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,  # noqa: ARG002
    ) -> None:
        """主动发送 Markdown 消息到指定会话

        Args:
            to_handle: 会话标识符（userid 或 chatid）
            text: 消息文本（支持 Markdown）
            meta: 元数据（暂未使用）
        """
        if not self.client:
            logger.warning(
                "[WeCom] Client not initialized, cannot send message",
            )
            return

        try:
            await self.client.send_message(
                to_handle,
                {"msgtype": "markdown", "markdown": {"content": text}},
            )
            logger.info("[WeCom] Proactive message sent to %s", to_handle)
        except Exception as exc:
            logger.error(
                "[WeCom] Failed to send proactive message: %s",
                exc,
                exc_info=True,
            )

    # -- BaseChannel 抽象方法 -------------------------------------

    async def consume_one(self, payload: Any) -> None:  # noqa: ARG002
        """未使用 - WeCom 在 handler 中直接处理消息"""
