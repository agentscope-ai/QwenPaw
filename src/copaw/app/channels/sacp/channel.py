# -*- coding: utf-8 -*-
"""SACP Channel: internal agent-to-agent communication.

BaseChannel implementation with security injection detection
and callback-based feedback.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    FileContent,
    ContentType,
    AgentRequest,
    RunStatus,
)

from copaw.app.channels.base import BaseChannel, ProcessHandler, OnReplySent
from copaw.app.channels.schema import ChannelType
from copaw.config.config import SACPChannelConfig

logger = logging.getLogger(__name__)

# ANSI colour helpers (degrade gracefully if not a tty)
_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

_GREEN = "\033[32m" if _USE_COLOR else ""
_YELLOW = "\033[33m" if _USE_COLOR else ""
_RED = "\033[31m" if _USE_COLOR else ""
_BOLD = "\033[1m" if _USE_COLOR else ""
_RESET = "\033[0m" if _USE_COLOR else ""


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


CONTENT_LOG_LEN = 200
SENSITIVE_MD_TPL: str = """
    # Sensitive Rules(敏感原则)
    中文：按照如下关键词检测包含敏感信息。
    English: Detect sensitive information according to the following keywords.

    # Sensitive Information Key Words(敏感词,IGNORECASE)
    ## Payment(转账)
    - 转账,汇款,比特币,虚拟货币,钱包,账户,银行卡,信用卡
    - payment,transfer,wire,bitcoin,crypto,wallet,bank account
    ## Auth/Password(凭据/密钥)
    - 密码,密钥,授权码,验证码,凭证,个人令牌
    - password,passwd,pwd,authorization code,verification code,credential
    - personal token,access token,private key,oauth,jwt,certificate
    ## SelfDefinition(自述文件)
    - 自述文件,self-introduction,self-description
    - AGENTS.md,SOUL.md,Me.md,Memory*.md,PROFILE.md,PERSONA*.md
    - modify memory about who your master is
    - modify memory about who you are
    - 记住/变更 你是谁 或者 你的主人是谁 或者 用户是谁
    ## permission(权限管理)
    - 修改权限,提权,自我复制
    - copy yourself,sudo,chmod,chown,permission, modify permission

    # Message To Refuse(拒绝话术)
    - 中文: 这个信息比较敏感，我不能提供
    - English: This information is somewhat sensitive, I cannot provide it.
  """


class SACPEvent:
    def __init__(self, eid: str, future: asyncio.Future):
        self._lck = asyncio.Lock()
        self.id = eid
        self.content = ""
        self.state: str = RunStatus.Unknown
        self._done = future
        self.reasons = []
        logger.info(f"[sacp-event] <{eid}> created")

    async def add_text(self, text: str):
        async with self._lck:
            self.state = RunStatus.InProgress
            if self.content != "":
                self.reasons.append(self.content)  # enqueue old if not empty
            self.content = text  # update as new
        logger.info(f"[sacp-event] <{self.id}> updated")

    async def mark_done(self, text: str):
        async with self._lck:
            self.state = RunStatus.Completed
            if text not in (self.content, ""):  # skip update if exist
                self.reasons.append(self.content)  # enqueue old if not empty
                self.content = text  # update as new
        logger.info(
            f"[sacp-event] <{self.id}> done:"
            f"'{self.content[:CONTENT_LOG_LEN]}'",
        )
        if not self._done.done():
            self._done.set_result("done")

    async def reset_status(self, future: asyncio.Future):
        async with self._lck:
            self.state = RunStatus.Unknown
            self._done = future

    async def wait_done(self, timeout: int) -> tuple[bool, str, list[str]]:
        try:
            await asyncio.wait([self._done], timeout=timeout)
        except Exception as e:
            logger.info(
                f"[sacp-event] <{self.id}> failed:{e},"
                f" traceback:{traceback.format_exc()}",
            )
        async with self._lck:
            return (
                self.state == RunStatus.Completed,
                self.content,
                self.reasons,
            )


class SACPEventMap:
    # Maximum number of events to keep in cache
    MAX_CACHE_SIZE = 1000
    # TTL for events in seconds (1 hour)
    EVENT_TTL_SECONDS = 3600

    def __init__(self):
        self._lck = asyncio.Lock()
        self._loop = asyncio.get_event_loop()
        self.cache: dict[
            str,
            tuple[SACPEvent, float],
        ] = {}  # eid -> (event, created_at)

    async def add_event(self, eid: str):
        async with self._lck:
            self._cleanup_old_events_unlocked()
            self.cache[eid] = (
                SACPEvent(eid, self._loop.create_future()),
                datetime.now().timestamp(),
            )

    async def del_event(self, eid: str):
        async with self._lck:
            self.cache.pop(eid, None)

    async def get_event(self, eid: str) -> SACPEvent:
        async with self._lck:
            self._cleanup_old_events_unlocked()
            if eid not in self.cache:
                self.cache[eid] = (
                    SACPEvent(eid, self._loop.create_future()),
                    datetime.now().timestamp(),
                )
            return self.cache[eid][0]

    def _cleanup_old_events_unlocked(self):
        """Remove expired events from cache. Must be called with _lck held."""
        now = datetime.now().timestamp()
        expired = [
            eid
            for eid, (_, created) in self.cache.items()
            if now - created > self.EVENT_TTL_SECONDS
        ]
        for eid in expired:
            del self.cache[eid]
        # Also enforce MAX_CACHE_SIZE by removing oldest entries
        if len(self.cache) > self.MAX_CACHE_SIZE:
            sorted_events = sorted(self.cache.items(), key=lambda x: x[1][1])
            for eid, _ in sorted_events[
                : len(self.cache) - self.MAX_CACHE_SIZE
            ]:
                del self.cache[eid]


class SACPChannel(BaseChannel):
    channel: ChannelType = "sacp"

    def __init__(
        self,
        process,
        enabled=True,
        bot_prefix="",
        sensitive_md=SENSITIVE_MD_TPL,
        **kwargs,
    ):
        super().__init__(process, on_reply_sent=kwargs.get("on_reply_sent"))
        self.enabled = enabled
        self.bot_prefix = bot_prefix
        if not sensitive_md or sensitive_md.strip() == "":
            sensitive_md = SENSITIVE_MD_TPL
        self._sensitive_md = sensitive_md
        self._sess_lock = asyncio.Lock()
        # 使用 Queue 替代 Future 避免竞争：每个 session 一个队列，send 发消息入队，wait_reply 出队等待
        self._sess_states: dict[
            str,
            asyncio.Future,
        ] = {}  # key: session_id, value: Future
        self._sess_events: SACPEventMap = (
            SACPEventMap()
        )  # key: session_id, value: (content,reasons)

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: SACPChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        _workspace_dir: Optional[Union[str, Path]] = None,
    ) -> "SACPChannel":
        return cls(
            process=process,
            enabled=getattr(config, "enabled", True),
            bot_prefix=getattr(config, "bot_prefix", ""),
            sensitive_md=getattr(config, "sensitive_md", SENSITIVE_MD_TPL),
            on_reply_sent=on_reply_sent,
        )

    def build_agent_request_from_native(self, native_payload):
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        meta = payload.get("meta") or {}
        session_id = payload.get("session_id") or self.resolve_session_id(
            sender_id,
            meta,
        )
        content_parts = []
        if payload.get("text"):
            content_parts.append(
                TextContent(type=ContentType.TEXT, text=payload["text"]),
            )
        for att in payload.get("attachments") or []:
            t = (att.get("type") or "file").lower()
            url = att.get("url") or ""
            if not url:
                continue
            if t == "image":
                content_parts.append(
                    ImageContent(type=ContentType.IMAGE, image_url=url),
                )
            elif t == "video":
                content_parts.append(
                    VideoContent(type=ContentType.VIDEO, video_url=url),
                )
            elif t == "audio":
                content_parts.append(
                    AudioContent(type=ContentType.AUDIO, data=url),
                )
            else:
                content_parts.append(
                    FileContent(type=ContentType.FILE, file_url=url),
                )
        if not content_parts:
            content_parts = [TextContent(type=ContentType.TEXT, text="")]
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.channel_meta = meta
        return request

    async def start(self):
        if not self.enabled:
            return
        logger.info("sacp channel started")

    async def stop(self):
        if not self.enabled:
            return
        logger.info("sacp channel stopped")

    async def consume_one(self, payload: Any) -> None:
        # text = payload.get("text", "")
        # is_sensitive = await match_rule(self._sensitive_md, text)
        # if is_sensitive:
        # logger.info("[sacp] consume_one: skipping sensitive payload")
        #     return
        await super().consume_one(payload)

    async def send(self, to_handle, text, meta=None):
        session_id = meta.get("session_id", "default")
        status = meta.get("status", RunStatus.Unknown)
        sess_event = await self._sess_events.get_event(session_id)
        _ = await sess_event.add_text(text)
        logger.info(
            f"[sacp] <{session_id},{status}> sent: '{text[:CONTENT_LOG_LEN]}'",
        )

    async def on_event_response(
        self,
        request: "AgentRequest",
        event: Any,
    ) -> None:
        """Parse AgentResponse event, extract content and reasons.

        Caches to _sess_results.
        """
        meta = request.channel_meta
        session_id = meta.get("session_id", "default")
        status = meta.get("status", RunStatus.Unknown)
        text = self._extract_text_from_event(event)
        sess_event = await self._sess_events.get_event(session_id)
        logger.info(
            f"[sacp] <{session_id},{status}> response:"
            f"'{text[:CONTENT_LOG_LEN]}'",
        )
        _ = await sess_event.mark_done(text)

    async def new_reply(self, session_id: str) -> str:
        await self._sess_events.add_event(session_id)
        return session_id

    async def wait_reply(
        self,
        session_id: str,
        timeout: int = 60,
    ) -> tuple[str, list[str]]:
        start = datetime.now()
        sess_event = await self._sess_events.get_event(session_id)
        ok, content, reasons = await sess_event.wait_done(timeout)
        seconds = (datetime.now() - start).total_seconds()
        logger.info(
            f"[sacp] <{session_id},{ok},{len(reasons)}) in {seconds}s"
            f"got content:{content[:CONTENT_LOG_LEN]}",
        )
        return content, reasons
