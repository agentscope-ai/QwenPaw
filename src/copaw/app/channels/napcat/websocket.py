# -*- coding: utf-8 -*-
"""NapCat WebSocket client."""

import json
import logging
import threading
import time
from typing import Any, Callable, Dict

import websocket

from .constants import (
    RECONNECT_DELAYS,
    MAX_RECONNECT_ATTEMPTS,
    QUICK_DISCONNECT_THRESHOLD,
    MAX_QUICK_DISCONNECT_COUNT,
)

logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client for NapCat."""

    def __init__(
        self,
        host: str,
        ws_port: int,
        access_token: str,
        stop_event: threading.Event,
        message_handler: Callable[[Dict[str, Any]], None],
    ):
        self.host = host
        self.ws_port = ws_port
        self.access_token = access_token
        self._stop_event = stop_event
        self._message_handler = message_handler

    def run_forever(self) -> None:
        """Run WebSocket client to receive events."""
        reconnect_attempts = 0
        last_connect_time = 0.0
        quick_disconnect_count = 0

        def connect() -> bool:
            # pylint: disable=invalid-name
            nonlocal reconnect_attempts
            nonlocal last_connect_time, quick_disconnect_count
            if self._stop_event.is_set():
                return False

            ws_url = f"ws://{self.host}:{self.ws_port}/ws"
            headers = {}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"

            logger.info(f"napcat connecting to {ws_url}")

            try:
                ws = websocket.create_connection(
                    ws_url,
                    header=headers,
                    timeout=30,
                )
            except Exception as e:
                logger.warning(f"napcat ws connect failed: {e}")
                return True

            current_ws = ws

            try:
                while not self._stop_event.is_set():
                    try:
                        raw = current_ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    except websocket.WebSocketConnectionClosedException:
                        break

                    if not raw:
                        break

                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning(f"napcat invalid JSON: {raw[:200]}")
                        continue

                    # Handle OneBot 11 event
                    self._message_handler(payload)

            except Exception as e:
                logger.exception(f"napcat ws loop: {e}")
            finally:
                try:
                    current_ws.close()
                except Exception:
                    pass

            # Calculate reconnect delay
            if (
                last_connect_time
                and (time.time() - last_connect_time)
                < QUICK_DISCONNECT_THRESHOLD
            ):
                quick_disconnect_count += 1
                if quick_disconnect_count >= MAX_QUICK_DISCONNECT_COUNT:
                    quick_disconnect_count = 0
                    delay = 60  # Rate limit
                else:
                    delay = RECONNECT_DELAYS[
                        min(reconnect_attempts, len(RECONNECT_DELAYS) - 1)
                    ]
            else:
                quick_disconnect_count = 0
                delay = RECONNECT_DELAYS[
                    min(reconnect_attempts, len(RECONNECT_DELAYS) - 1)
                ]

            reconnect_attempts += 1
            if reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
                logger.error("napcat max reconnect attempts reached")
                return False

            logger.info(
                f"napcat reconnecting in {delay}s "
                f"(attempt {reconnect_attempts})",
            )
            self._stop_event.wait(timeout=delay)
            return not self._stop_event.is_set()

        while connect():
            pass
        self._stop_event.set()
        logger.info("napcat ws thread stopped")
