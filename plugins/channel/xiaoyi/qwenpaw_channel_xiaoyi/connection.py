# -*- coding: utf-8 -*-
"""One authenticated XiaoYi WebSocket with receive and heartbeat tasks."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import re
import secrets
import time
from urllib.parse import urlparse

import aiohttp

from .auth import generate_auth_headers
from .constants import CONNECTION_TIMEOUT, HEARTBEAT_INTERVAL, PONG_TIMEOUT
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
    ):
        self.server_name, self.ws_url = server_name, ws_url
        self.ak, self.sk, self.agent_id = ak, sk, agent_id
        self.on_message = on_message
        self._ssl = _get_ssl_for_url(ws_url)
        self._ws = self._session = None
        self._heartbeat_task = self._receive_task = None
        self._pong = asyncio.Event()
        self._ping_token = None
        self._dispatching_text = False
        self.connected = False

    async def connect(self):
        await self.disconnect()
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
            f"autoping": False,
        }
        if self._ssl is not None:
            kwargs["ssl"] = self._ssl
        phase = f"handshake"
        try:
            async with asyncio.timeout(CONNECTION_TIMEOUT):
                self._ws = await self._session.ws_connect(
                    self.ws_url,
                    **kwargs,
                )
                logger.info(f"XiaoYi {self.server_name} WebSocket connected")
                phase = f"init"
                await self._send_init_message()
                logger.debug(f"XiaoYi {self.server_name} init frame sent")
            self.connected = True
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(),
            )
            self._receive_task = asyncio.create_task(self._receive_loop())
            return True
        except asyncio.CancelledError:
            await self._cleanup()
            raise
        except Exception as exc:
            status = (
                exc.status
                if isinstance(exc, aiohttp.ClientResponseError)
                else None
            )
            logger.warning(
                f"XiaoYi {self.server_name} connection failed: "
                f"phase={phase} http_status={status} "
                f"({type(exc).__name__})",
            )
            await self._cleanup()
            return False

    async def wait_disconnected(self, timeout=None):
        finished, _ = await asyncio.wait(
            (self._heartbeat_task, self._receive_task),
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if finished:
            self.connected = False
        return bool(finished)

    async def disconnect(self):
        has_resources = self._ws is not None or self._session is not None
        self.connected = False
        tasks = [
            task
            for task in (self._heartbeat_task, self._receive_task)
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Keep each resource reference if closing that resource fails.
        await self._cleanup()
        self._heartbeat_task = self._receive_task = None
        if has_resources:
            logger.debug(f"XiaoYi {self.server_name} connection released")

    async def _cleanup(self):
        failures = []
        for name in ("_ws", "_session"):
            resource = getattr(self, name)
            if resource is not None:
                try:
                    await resource.close()
                except Exception as exc:
                    logger.warning(
                        f"XiaoYi {self.server_name} resource close failed: "
                        f"resource={name} ({type(exc).__name__})",
                    )
                    failures.append(exc)
                else:
                    setattr(self, name, None)
        if failures:
            raise RuntimeError("XIAOYI_CONNECTION_CLOSE_FAILED") from failures[
                0
            ]

    async def send_json(self, data):
        if not self.connected or self._ws is None or self._ws.closed:
            return False
        try:
            await self._ws.send_json(data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A write exception does not prove that the remote missed it.
            logger.warning(
                f"XiaoYi {self.server_name} WebSocket write result unknown "
                f"({type(exc).__name__})",
            )
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

    async def _heartbeat_loop(self):
        try:
            while self.connected:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if not self.connected:
                    return
                async with asyncio.timeout(PONG_TIMEOUT):
                    if not await self.send_json(
                        {
                            f"msgType": f"heartbeat",
                            f"agentId": self.agent_id,
                            f"msgDetail": json.dumps(
                                {f"timestamp": int(time.time() * 1000)},
                            ),
                        },
                    ):
                        return
                    self._pong.clear()
                    self._ping_token = secrets.token_bytes(8)
                    await self._ws.ping(self._ping_token)
                    logger.debug(
                        f"XiaoYi {self.server_name} heartbeat written",
                    )
                try:
                    await asyncio.wait_for(self._pong.wait(), PONG_TIMEOUT)
                except TimeoutError:
                    # The reader may be paused or receive Pong at the deadline.
                    if self._dispatching_text or self._pong.is_set():
                        continue
                    logger.warning(
                        f"XiaoYi {self.server_name} Pong timeout",
                    )
                    return
        except Exception as exc:
            logger.warning(
                f"XiaoYi {self.server_name} heartbeat failed "
                f"({type(exc).__name__})",
            )
        finally:
            self.connected = False

    async def _handle_text(self, data):
        try:
            value = json.loads(data)
        except (ValueError, TypeError) as exc:
            logger.warning(
                f"XiaoYi {self.server_name} invalid JSON ignored "
                f"({type(exc).__name__})",
            )
            return
        if isinstance(value, dict):
            await self.on_message(value, self.server_name)
        else:
            logger.debug(f"XiaoYi {self.server_name} ignored non-object JSON")

    async def _receive_loop(self):
        close_code = reason = None
        try:
            while self.connected:
                message = await self._ws.receive()
                if message.type == aiohttp.WSMsgType.TEXT:
                    self._dispatching_text = True
                    try:
                        await self._handle_text(message.data)
                    except Exception as exc:
                        logger.error(
                            f"XiaoYi {self.server_name} message handling "
                            f"failed ({type(exc).__name__})",
                        )
                    finally:
                        self._dispatching_text = False
                elif message.type == aiohttp.WSMsgType.PING:
                    await self._ws.pong(message.data)
                elif message.type == aiohttp.WSMsgType.PONG:
                    if message.data == self._ping_token:
                        self._pong.set()
                elif message.type == aiohttp.WSMsgType.CLOSE:
                    close_code = message.data
                    reason = str(message.extra)[:160]
                    break
                elif message.type == aiohttp.WSMsgType.ERROR:
                    reason = type(message.data).__name__
                    break
                elif message.type in {
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                }:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = type(exc).__name__
        finally:
            self.connected = False
        logger.warning(
            f"xiaoyi [%s]: disconnected (code=%s, reason=%r)",
            self.server_name,
            close_code or self._ws.close_code,
            reason,
        )
