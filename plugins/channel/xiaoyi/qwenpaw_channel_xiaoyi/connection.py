# -*- coding: utf-8 -*-
"""One instance-owned authenticated XiaoYi WebSocket and its two readers."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import re
import time
from urllib.parse import urlparse

import aiohttp

from .auth import generate_auth_headers
from .constants import CONNECTION_TIMEOUT, HEARTBEAT_INTERVAL
from .errors import XiaoYiDeliveryError

logger = logging.getLogger(__name__)
_IP_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def _is_ip_address(host):
    return bool(_IP_RE.match(host)) and all(
        0 <= int(part) <= 255 for part in host.split(".")
    )


def _get_ssl_for_url(url):
    # Preserve the existing IP-direct certificate policy.
    return False if _is_ip_address(urlparse(url).hostname or "") else None


class XiaoYiConnection:
    def __init__(
        self,
        server_name,
        ws_url,
        ak,
        sk,
        agent_id,
        on_message,
        on_disconnect,
    ):
        self.server_name, self.ws_url = server_name, ws_url
        self.ak, self.sk, self.agent_id = ak, sk, agent_id
        self.on_message, self.on_disconnect = on_message, on_disconnect
        self._ssl = _get_ssl_for_url(ws_url)
        self._ws = self._session = None
        self._heartbeat_task = self._receive_task = None
        self._generation = 0
        self._stopping = False
        self.connected = False

    async def connect(self):
        await self.disconnect()
        self._stopping = False
        generation = self._generation
        self._session = aiohttp.ClientSession()
        # ClientWSTimeout was introduced after the declared aiohttp>=3.9 floor.
        timeout = (
            aiohttp.ClientWSTimeout(ws_close=CONNECTION_TIMEOUT)
            if hasattr(aiohttp, "ClientWSTimeout")
            else float(CONNECTION_TIMEOUT)
        )
        kwargs = {
            "headers": generate_auth_headers(self.ak, self.sk, self.agent_id),
            "timeout": timeout,
        }
        if self._ssl is not None:
            kwargs["ssl"] = self._ssl
        try:
            self._ws = await asyncio.wait_for(
                self._session.ws_connect(self.ws_url, **kwargs),
                CONNECTION_TIMEOUT,
            )
            self.connected = True
            await self._send_init_message()
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(generation),
            )
            self._receive_task = asyncio.create_task(
                self._receive_loop(generation),
            )
            return True
        except asyncio.CancelledError:
            self.connected = False
            await self._cleanup()
            raise
        except Exception:
            logger.warning("xiaoyi [%s]: connection failed", self.server_name)
            self.connected = False
            await self._cleanup()
            return False

    async def disconnect(self):
        self._stopping = True
        self.connected = False
        self._generation += 1
        current = asyncio.current_task()
        tasks = [
            task
            for task in (self._heartbeat_task, self._receive_task)
            if task is not None and task is not current
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Keep each resource reference if closing that resource fails.
        await self._cleanup()
        self._heartbeat_task = self._receive_task = None

    async def _cleanup(self):
        failures = []
        for name in ("_ws", "_session"):
            resource = getattr(self, name)
            if resource is not None:
                try:
                    await resource.close()
                except Exception as exc:
                    failures.append(exc)
                else:
                    setattr(self, name, None)
        if failures:
            raise RuntimeError("XIAOYI_CONNECTION_CLOSE_FAILED") from failures[
                0
            ]

    def _current(self, generation):
        return (
            not self._stopping
            and generation == self._generation
            and self.connected
        )

    async def send_json(self, data):
        if not self.connected or self._ws is None or self._ws.closed:
            return False
        try:
            await self._ws.send_json(data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A write exception does not prove that the remote missed it.
            raise XiaoYiDeliveryError(
                "PLATFORM_RESULT_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        return True

    async def _send_init_message(self):
        await self._ws.send_json(
            {
                "msgType": "clawd_bot_init",
                "agentId": self.agent_id,
                "msgDetail": json.dumps(
                    {"agentId": self.agent_id, "hostname": platform.node()},
                ),
            },
        )

    async def _heartbeat_loop(self, generation):
        try:
            while self._current(generation):
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if not self._current(generation):
                    return
                if not await self.send_json(
                    {
                        "msgType": "heartbeat",
                        "agentId": self.agent_id,
                        "msgDetail": json.dumps(
                            {"timestamp": int(time.time() * 1000)},
                        ),
                    },
                ):
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("xiaoyi [%s]: heartbeat failed", self.server_name)
        if self._current(generation) and self._ws is not None:
            # Closing wakes the receive loop and its single disconnect notice.
            await self._ws.close()

    async def _handle_text(self, data):
        try:
            value = json.loads(data)
        except (ValueError, TypeError):
            logger.warning(
                "xiaoyi [%s]: invalid JSON ignored",
                self.server_name,
            )
            return
        if isinstance(value, dict):
            await self.on_message(value, self.server_name)

    async def _receive_loop(self, generation):
        try:
            async for message in self._ws:
                if not self._current(generation):
                    return
                if message.type == aiohttp.WSMsgType.TEXT:
                    try:
                        await self._handle_text(message.data)
                    except Exception:
                        logger.exception(
                            "xiaoyi [%s]: message rejected",
                            self.server_name,
                        )
                elif message.type in {
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.CLOSE,
                }:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("xiaoyi [%s]: receive failed", self.server_name)
        finally:
            if generation == self._generation:
                self.connected = False
                if not self._stopping:
                    await self.on_disconnect(self.server_name)
