# -*- coding: utf-8 -*-
"""WeCom self-built app channel (callback + proactive send)."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Dict, Optional

import aiohttp

from ....config.config import WeComAppConfig
from ..base import OnReplySent, ProcessHandler
from ..wecom.channel import WeComChannel

logger = logging.getLogger(__name__)


class WeComAppChannel(WeComChannel):
    """WeCom self-built app channel.

    Compared with ``WeComChannel``, this channel supports proactive text send
    via ``/cgi-bin/message/send``.
    """

    channel = "wecom_app"
    display_name = "WeCom App"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        token: str,
        encoding_aes_key: str,
        bot_prefix: str,
        corp_id: str,
        corp_secret: str,
        agent_id: int,
        api_base_url: str = "https://qyapi.weixin.qq.com",
        receive_id: str = "",
        webhook_path: str = "/wecom-app",
        reply_timeout_sec: float = 4.5,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
    ):
        super().__init__(
            process=process,
            enabled=enabled,
            token=token,
            encoding_aes_key=encoding_aes_key,
            bot_prefix=bot_prefix,
            receive_id=receive_id or corp_id,
            webhook_path=webhook_path,
            reply_timeout_sec=reply_timeout_sec,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
        )
        self.corp_id = corp_id or ""
        self.corp_secret = corp_secret or ""
        self.agent_id = int(agent_id or 0)
        self.api_base_url = (
            (api_base_url or "https://qyapi.weixin.qq.com").strip().rstrip("/")
        )

        self._token_lock = asyncio.Lock()
        self._access_token: Optional[str] = None
        self._access_token_expire_at: float = 0.0

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "WeComAppChannel":
        return cls(
            process=process,
            enabled=os.getenv("WECOM_APP_CHANNEL_ENABLED", "0") == "1",
            token=os.getenv("WECOM_APP_TOKEN", ""),
            encoding_aes_key=os.getenv("WECOM_APP_ENCODING_AES_KEY", ""),
            bot_prefix=os.getenv("WECOM_APP_BOT_PREFIX", "[BOT] "),
            corp_id=os.getenv("WECOM_APP_CORP_ID", ""),
            corp_secret=os.getenv("WECOM_APP_CORP_SECRET", ""),
            agent_id=int(os.getenv("WECOM_APP_AGENT_ID", "0") or 0),
            api_base_url=os.getenv(
                "WECOM_APP_API_BASE_URL",
                "https://qyapi.weixin.qq.com",
            ),
            receive_id=os.getenv("WECOM_APP_RECEIVE_ID", ""),
            webhook_path=os.getenv("WECOM_APP_WEBHOOK_PATH", "/wecom-app"),
            reply_timeout_sec=float(
                os.getenv("WECOM_APP_REPLY_TIMEOUT_SEC", "4.5"),
            ),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: WeComAppConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
    ) -> "WeComAppChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            token=config.token or "",
            encoding_aes_key=config.encoding_aes_key or "",
            bot_prefix=config.bot_prefix or "[BOT] ",
            corp_id=config.corp_id or "",
            corp_secret=config.corp_secret or "",
            agent_id=config.agent_id or 0,
            api_base_url=config.api_base_url or "https://qyapi.weixin.qq.com",
            receive_id=config.receive_id or "",
            webhook_path=config.webhook_path or "/wecom-app",
            reply_timeout_sec=config.reply_timeout_sec or 4.5,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
        )

    async def stop(self) -> None:
        if self._http and not self._http.closed:
            await self._http.close()
            self._http = None

    def _supports_stream_protocol(self) -> bool:
        return True

    def _route_from_handle(self, to_handle: str) -> Dict[str, str]:
        s = (to_handle or "").strip()
        if s.startswith("wecom_app:user:"):
            return {"touser": s.replace("wecom_app:user:", "", 1)}
        if s.startswith("wecom:user:"):
            return {"touser": s.replace("wecom:user:", "", 1)}
        if s.startswith("wecom_app:chat:"):
            return {"chatid": s.replace("wecom_app:chat:", "", 1)}
        if s.startswith("chatid:"):
            return {"chatid": s.replace("chatid:", "", 1)}
        if s.startswith("chat:"):
            return {"chatid": s.replace("chat:", "", 1)}
        return {"touser": s}

    @staticmethod
    def _split_text_by_bytes(text: str, max_bytes: int = 2048) -> list[str]:
        if not text:
            return [""]
        chunks: list[str] = []
        cur = ""
        cur_bytes = 0
        for ch in text:
            b = len(ch.encode("utf-8"))
            if cur and cur_bytes + b > max_bytes:
                chunks.append(cur)
                cur = ch
                cur_bytes = b
            else:
                cur += ch
                cur_bytes += b
        if cur:
            chunks.append(cur)
        return chunks or [text]

    async def _ensure_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    async def _get_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._access_token_expire_at - 60:
            return self._access_token

        async with self._token_lock:
            now = time.time()
            if self._access_token and now < self._access_token_expire_at - 60:
                return self._access_token

            if not (self.corp_id and self.corp_secret):
                raise RuntimeError("wecom_app missing corp_id/corp_secret")

            http = await self._ensure_http()
            url = f"{self.api_base_url}/cgi-bin/gettoken"
            params = {
                "corpid": self.corp_id,
                "corpsecret": self.corp_secret,
            }
            async with http.get(url, params=params, timeout=15) as resp:
                data = await resp.json(content_type=None)

            if int(data.get("errcode", -1)) != 0:
                raise RuntimeError(
                    f"wecom_app gettoken failed: {data.get('errcode')} {data.get('errmsg')}",
                )

            token = str(data.get("access_token") or "")
            expires_in = int(data.get("expires_in") or 7200)
            if not token:
                raise RuntimeError("wecom_app gettoken returned empty access_token")

            self._access_token = token
            self._access_token_expire_at = time.time() + expires_in
            return token

    async def _send_text_once(
        self,
        *,
        touser: str = "",
        chatid: str = "",
        content: str,
    ) -> None:
        token = await self._get_access_token()
        http = await self._ensure_http()
        url = f"{self.api_base_url}/cgi-bin/message/send"
        payload = {
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {"content": content},
            "safe": 0,
        }
        if chatid:
            payload["chatid"] = chatid
        else:
            payload["touser"] = touser

        async with http.post(
            url,
            params={"access_token": token},
            json=payload,
            timeout=20,
        ) as resp:
            data = await resp.json(content_type=None)

        if int(data.get("errcode", -1)) != 0:
            raise RuntimeError(
                f"wecom_app send failed: {data.get('errcode')} {data.get('errmsg')}",
            )

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, str]] = None,
    ) -> None:
        del meta
        if not self.enabled:
            logger.debug("wecom_app send skipped: disabled")
            return

        if not self.agent_id:
            logger.warning("wecom_app send skipped: agent_id is empty")
            return

        route = self._route_from_handle(to_handle)
        touser = (route.get("touser") or "").strip()
        chatid = (route.get("chatid") or "").strip()
        if not touser and not chatid:
            logger.warning("wecom_app send skipped: target empty")
            return

        body = (text or "").strip()
        if not body:
            return

        chunks = self._split_text_by_bytes(body, max_bytes=2048)
        for chunk in chunks:
            await self._send_text_once(
                touser=touser,
                chatid=chatid,
                content=chunk,
            )
