# -*- coding: utf-8 -*-
"""MQTT Channel for IoT devices and robots"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional, Union

import paho.mqtt.client as mqtt
from paho.mqtt import MQTTException

from agentscope_runtime.engine.schemas.agent_schemas import (
    TextContent,
    ContentType,
)

from ....config.config import MQTTConfig as MQTTChannelConfig
from ..base import (
    BaseChannel,
    OnReplySent,
    ProcessHandler,
    OutgoingContentPart,
)

logger = logging.getLogger(__name__)


class MQTTChannel(BaseChannel):
    """MQTT Channel for IoT devices and robots"""

    channel = "mqtt"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        host: str,
        port: str,
        transport: str,
        username: str,
        password: str,
        subscribe_topic: str,
        publish_topic: str,
        bot_prefix: str,
        tls_enabled: bool = False,
        tls_ca_certs: Optional[str] = None,
        tls_certfile: Optional[str] = None,
        tls_keyfile: Optional[str] = None,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
        )

        self.transport = transport
        self.tls_enabled = tls_enabled
        self.enabled = enabled
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.subscribe_topic = subscribe_topic
        self.publish_topic = publish_topic
        self.bot_prefix = bot_prefix
        self.tls_ca_certs = tls_ca_certs
        self.tls_certfile = tls_certfile
        self.tls_keyfile = tls_keyfile
        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self._thread: Optional[threading.Thread] = None

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "MQTTChannel":
        import os

        return cls(
            process=process,
            enabled=os.getenv("MQTT_CHANNEL_ENABLED", "0") == "1",
            host=os.getenv("MQTT_HOST", ""),
            port=os.getenv("MQTT_PORT", "1883"),
            username=os.getenv("MQTT_USERNAME", ""),
            password=os.getenv("MQTT_PASSWORD", ""),
            subscribe_topic=os.getenv("MQTT_SUBSCRIBE_TOPIC", ""),
            publish_topic=os.getenv("MQTT_PUBLISH_TOPIC", ""),
            bot_prefix=os.getenv("MQTT_BOT_PREFIX", ""),
            tls_enabled=os.getenv("MQTT_TLS_ENABLED", "0") == "1",
            tls_ca_certs=os.getenv("MQTT_TLS_CA_CERTS"),
            tls_certfile=os.getenv("MQTT_TLS_CERTFILE"),
            tls_keyfile=os.getenv("MQTT_TLS_KEYFILE"),
            transport=os.getenv("MQTT_TRANSPORT", "mqtt"),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Union[MQTTChannelConfig, dict],
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
    ) -> "MQTTChannel":
        if isinstance(config, dict):
            return cls(
                process=process,
                enabled=bool(config.get("enabled", False)),
                host=(config.get("host") or "").strip(),
                port=(config.get("port") or "1883").strip(),
                username=(config.get("username") or "").strip(),
                password=(config.get("password") or "").strip(),
                subscribe_topic=(config.get("subscribe_topic") or "").strip(),
                publish_topic=(config.get("publish_topic") or "").strip(),
                bot_prefix=(config.get("bot_prefix") or "").strip(),
                tls_enabled=bool(config.get("tls_enabled", False)),
                tls_ca_certs=config.get("tls_ca_certs"),
                tls_certfile=config.get("tls_certfile"),
                tls_keyfile=config.get("tls_keyfile"),
                transport=config.get("transport", "tcp"),
                on_reply_sent=on_reply_sent,
                show_tool_details=show_tool_details,
            )
        return cls(
            process=process,
            enabled=config.enabled,
            host=config.host or "",
            port=config.port or "1883",
            username=config.username or "",
            password=config.password or "",
            subscribe_topic=config.subscribe_topic or "",
            publish_topic=config.publish_topic or "",
            bot_prefix=config.bot_prefix or "",
            transport=getattr(config, "transport", ""),
            tls_enabled=getattr(config, "tls_enabled", False),
            tls_ca_certs=getattr(config, "tls_ca_certs", None),
            tls_certfile=getattr(config, "tls_certfile", None),
            tls_keyfile=getattr(config, "tls_keyfile", None),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
        )

    def _validate_config(self):
        """Validate required MQTT config"""
        if not self.host:
            raise ValueError("MQTT host is required")

        if not self.subscribe_topic:
            raise ValueError("MQTT subscribe_topic is required")

        if not self.publish_topic:
            raise ValueError("MQTT publish_topic is required")

    def _on_connect(
        self,
        client,
        _userdata,
        _flags,
        reason_code,
        _properties=None,
    ):
        if reason_code == 0:
            self.connected = True
            logger.info("MQTT connected")
            client.subscribe(self.subscribe_topic, qos=0)
            logger.info(f"Subscribed to {self.subscribe_topic}")
        else:
            logger.error(f"MQTT connect failed, return code {reason_code}")

    def _on_disconnect(
        self,
        _client,
        _userdata,
        _flags,
        _reason,
        _properties=None,
    ):
        self.connected = False
        # Use reason code for logging
        if _reason != 0:
            logger.warning(f"MQTT disconnected unexpectedly, code={_reason}")

    def _on_message(self, _client, _userdata, msg):
        try:
            payload = msg.payload.decode("utf-8").strip()

            # Auto parse JSON or plain text
            data = {}
            content = ""
            try:
                data = json.loads(payload)
                content = data.get("text", "")
            except json.JSONDecodeError:
                content = payload

            if not content:
                return

            # Extract device_id from multiple sources
            device_id = ""

            # First try from topic structure
            parts = msg.topic.split("/")
            if len(parts) >= 2:
                # Try different positions for device_id
                for i in range(len(parts)):
                    # Look for common patterns in topic structure
                    if parts[i] not in [
                        "server",
                        "device",
                        "up",
                        "down",
                        "message",
                    ]:
                        device_id = parts[i]
                        break

            # If no device_id from topic, try from payload
            if not device_id:
                device_id = (
                    data.get("device_id")
                    or data.get("deviceId")
                    or data.get("client_id")
                )

            # If still no device_id, use a default
            if not device_id:
                device_id = "unknown-device"
                logger.warning(
                    f"MQTT: No device_id found in topic or payload: {msg.topic}",
                )

            logger.info(f"MQTT [{device_id}] >> {content}")

            # Build content parts
            content_parts = [TextContent(type=ContentType.TEXT, text=content)]

            # Create native payload
            native = {
                "channel_id": self.channel,
                "sender_id": device_id,
                "content_parts": content_parts,
                "meta": {
                    "topic": msg.topic,
                    "device_id": device_id,
                    "raw_payload": payload,
                },
            }

            # Enqueue the message
            if self._enqueue is not None:
                self._enqueue(native)
            else:
                logger.warning("MQTT: _enqueue not set, message dropped")

        except Exception as e:
            logger.error(
                f"Error processing MQTT message: {str(e)}",
                exc_info=True,
            )

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("MQTT: start() skipped (enabled=false)")
            return

        try:
            self._validate_config()
        except ValueError as e:
            logger.error(f"MQTT config validation failed: {str(e)}")
            return

        logger.info("Starting MQTT channel...")

        import uuid

        client_id = f"copaw-mqtt-{uuid.uuid4()}"
        self.client = mqtt.Client(
            client_id=client_id,
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            transport=self.transport,
        )

        # Username / password auth (only if provided)
        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)

        # Enable TLS if configured
        if self.tls_enabled:
            logger.info("MQTT: Enabling TLS")
            self.client.tls_set(
                ca_certs=self.tls_ca_certs,
                certfile=self.tls_certfile,
                keyfile=self.tls_keyfile,
            )

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        try:
            port = int(self.port) if self.port else 1883
            self.client.connect(self.host, port, keepalive=60)
            logger.info(
                f"MQTT connecting to {self.host}:{port} {'(TLS enabled)' if self.tls_enabled else ''} (transport: {self.transport})",
            )
        except MQTTException as e:
            logger.error(f"MQTT connect failed: {str(e)}")
            return

        # Run MQTT loop in background thread
        self._thread = threading.Thread(
            target=self.client.loop_forever,
            daemon=True,
        )
        self._thread.start()

        logger.info("MQTT channel started")
        logger.info(f"Subscribing to: {self.subscribe_topic}")
        logger.info(f"Publishing to: {self.publish_topic}")
        logger.info(f"Using transport: {self.transport}")

    async def stop(self) -> None:
        logger.info("Stopping MQTT channel...")
        if self.client:
            self.client.disconnect()
            self.client = None
        self.connected = False
        logger.info("MQTT channel stopped")

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[dict] = None,
    ) -> None:
        """Send text to device (to_handle is device_id)"""
        if not self.enabled or not self.client or not self.connected:
            return

        try:
            device_id = to_handle
            if meta and "device_id" in meta:
                device_id = meta["device_id"]

            if not device_id:
                logger.warning("MQTT send: no device_id in to_handle or meta")
                return

            # Format topic with device_id
            send_topic = self.publish_topic.format(device_id=device_id)
            self.client.publish(send_topic, text, qos=0)

            logger.info(f"MQTT [{device_id}] << {text}")

        except Exception as e:
            logger.error(f"Failed to send MQTT message: {str(e)}")

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[dict] = None,
    ) -> None:
        """Send media to device"""
        if not self.enabled or not self.client or not self.connected:
            return

        try:
            device_id = to_handle
            if meta and "device_id" in meta:
                device_id = meta["device_id"]

            if not device_id:
                logger.warning(
                    "MQTT send_media: no device_id in to_handle or meta",
                )
                return

            # Format topic with device_id
            send_topic = self.publish_topic.format(device_id=device_id)

            # Convert media part to text representation
            part_type = getattr(part, "type", None)
            if part_type == ContentType.IMAGE:
                image_url = getattr(part, "image_url", None)
                if image_url:
                    self.client.publish(
                        send_topic,
                        f"[Image: {image_url}]",
                        qos=0,
                    )
            elif part_type == ContentType.VIDEO:
                video_url = getattr(part, "video_url", None)
                if video_url:
                    self.client.publish(
                        send_topic,
                        f"[Video: {video_url}]",
                        qos=0,
                    )
            elif part_type == ContentType.AUDIO:
                self.client.publish(send_topic, "[Audio]", qos=0)
            elif part_type == ContentType.FILE:
                file_url = getattr(part, "file_url", None)
                file_id = getattr(part, "file_id", None)
                if file_url or file_id:
                    self.client.publish(
                        send_topic,
                        f"[File: {file_url or file_id}]",
                        qos=0,
                    )

        except Exception as e:
            logger.error(f"Failed to send MQTT media: {str(e)}")

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[dict] = None,
    ) -> str:
        """Session by device_id"""
        return f"mqtt:{sender_id}"

    def get_to_handle_from_request(self, request: Any) -> str:
        """Send target is device_id"""
        meta = getattr(request, "channel_meta", None) or {}
        device_id = meta.get("device_id")
        if device_id:
            return str(device_id)
        sid = getattr(request, "session_id", "")
        if sid.startswith("mqtt:"):
            return sid.split(":", 1)[-1]
        return getattr(request, "user_id", "") or ""

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """Build AgentRequest from MQTT native dict"""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        user_id = str(meta.get("device_id") or sender_id)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.user_id = user_id
        request.channel_meta = meta
        return request

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        """Cron dispatch: use session_id suffix as device_id"""
        if session_id.startswith("mqtt:"):
            return session_id.split(":", 1)[-1]
        return user_id
