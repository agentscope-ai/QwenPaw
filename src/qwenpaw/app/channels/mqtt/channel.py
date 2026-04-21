# -*- coding: utf-8 -*-
"""MQTT Channel for IoT devices and robots"""
from __future__ import annotations

import json
import uuid
import logging
import threading
from typing import Any, Dict, Optional, Union

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
        port: int,
        transport: str,
        username: str,
        password: str,
        subscribe_topic: str,
        publish_topic: str,
        bot_prefix: str,
        clean_session: bool = True,
        qos: int = 2,
        tls_enabled: bool = False,
        tls_ca_certs: Optional[str] = None,
        tls_certfile: Optional[str] = None,
        tls_keyfile: Optional[str] = None,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ):
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )

        self.enabled = enabled
        self.host = host
        self.port = port
        self.transport = transport
        self.username = username
        self.password = password
        self.subscribe_topic = subscribe_topic
        self.publish_topic = publish_topic
        self.bot_prefix = bot_prefix
        self.tls_enabled = tls_enabled
        self.tls_ca_certs = tls_ca_certs
        self.tls_certfile = tls_certfile
        self.tls_keyfile = tls_keyfile
        self.clean_session = clean_session
        self.qos = qos
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

        port_str = os.getenv("MQTT_PORT", "1883")
        port = int(port_str) if port_str.isdigit() else 1883

        clean_session = os.getenv("MQTT_CLEAN_SESSION", "1") == "1"
        qos_str = os.getenv("MQTT_QOS", "2")
        qos = int(qos_str) if qos_str.isdigit() else 0

        return cls(
            process=process,
            enabled=os.getenv("MQTT_CHANNEL_ENABLED", "0") == "1",
            host=os.getenv("MQTT_HOST", ""),
            port=port,
            transport=os.getenv("MQTT_TRANSPORT", "mqtt"),
            username=os.getenv("MQTT_USERNAME", ""),
            password=os.getenv("MQTT_PASSWORD", ""),
            subscribe_topic=os.getenv("MQTT_SUBSCRIBE_TOPIC", ""),
            publish_topic=os.getenv("MQTT_PUBLISH_TOPIC", ""),
            bot_prefix=os.getenv("MQTT_BOT_PREFIX", ""),
            clean_session=clean_session,
            qos=qos,
            tls_enabled=os.getenv("MQTT_TLS_ENABLED", "0") == "1",
            tls_ca_certs=os.getenv("MQTT_TLS_CA_CERTS"),
            tls_certfile=os.getenv("MQTT_TLS_CERTFILE"),
            tls_keyfile=os.getenv("MQTT_TLS_KEYFILE"),
            on_reply_sent=on_reply_sent,
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Union[MQTTChannelConfig, dict],
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "MQTTChannel":
        if isinstance(config, dict):
            port_val = config.get("port", 1883)
            port = (
                int(port_val)
                if isinstance(port_val, (str, int)) and str(port_val).isdigit()
                else 1883
            )

            clean_session = bool(config.get("clean_session", True))
            qos_val = config.get("qos", 2)
            qos = (
                int(qos_val)
                if isinstance(qos_val, (str, int)) and str(qos_val).isdigit()
                else 0
            )

            return cls(
                process=process,
                enabled=bool(config.get("enabled", False)),
                host=(config.get("host") or "").strip(),
                port=port,
                username=(config.get("username") or "").strip(),
                password=(config.get("password") or "").strip(),
                subscribe_topic=(config.get("subscribe_topic") or "").strip(),
                publish_topic=(config.get("publish_topic") or "").strip(),
                bot_prefix=(config.get("bot_prefix") or "").strip(),
                clean_session=clean_session,
                qos=qos,
                tls_enabled=bool(config.get("tls_enabled", False)),
                tls_ca_certs=config.get("tls_ca_certs"),
                tls_certfile=config.get("tls_certfile"),
                tls_keyfile=config.get("tls_keyfile"),
                transport=config.get("transport", "tcp"),
                on_reply_sent=on_reply_sent,
                show_tool_details=show_tool_details,
                filter_tool_messages=filter_tool_messages,
                filter_thinking=filter_thinking,
            )
        port = int(config.port) if config.port else 1883

        clean_session = getattr(config, "clean_session", True)
        qos = getattr(config, "qos", 2)

        return cls(
            process=process,
            enabled=config.enabled,
            host=config.host or "",
            port=port,
            username=config.username or "",
            password=config.password or "",
            subscribe_topic=config.subscribe_topic or "",
            publish_topic=config.publish_topic or "",
            bot_prefix=config.bot_prefix or "",
            clean_session=clean_session,
            qos=qos,
            transport=getattr(config, "transport", ""),
            tls_enabled=getattr(config, "tls_enabled", False),
            tls_ca_certs=getattr(config, "tls_ca_certs", None),
            tls_certfile=getattr(config, "tls_certfile", None),
            tls_keyfile=getattr(config, "tls_keyfile", None),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
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
            client.subscribe(self.subscribe_topic, qos=self.qos)
            logger.info(
                f"Subscribed to {self.subscribe_topic} with QoS={self.qos}",
            )
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
        if _reason != 0:
            logger.warning(f"MQTT disconnected unexpectedly, code={_reason}")

    def _on_message(self, _client, _userdata, msg):
        try:
            payload = msg.payload.decode("utf-8").strip()
            data = {}
            try:
                data = json.loads(payload)
                content = data.get("text", "")
            except json.JSONDecodeError:
                content = payload

            if not content:
                logger.error(f"Error MQTT message: {msg.topic} - {payload}")
                return

            client_id = data.get("redirect_client_id")
            if not client_id:
                parts = msg.topic.split("/")
                if len(parts) >= 2:
                    client_id = parts[1]
            if not client_id:
                client_id = "unknown-client"
                logger.warning(
                    f"MQTT: No client_id found in topic or payload: "
                    f"{msg.topic}",
                )

            logger.info(f"MQTT [{client_id}] >> {content}")

            content_parts = [TextContent(type=ContentType.TEXT, text=content)]
            native = {
                "channel_id": self.channel,
                "sender_id": client_id,
                "content_parts": content_parts,
                "meta": {
                    "topic": msg.topic,
                    "client_id": client_id,
                    "raw_payload": payload,
                },
            }

            if self._enqueue is not None:
                self._enqueue(native)
            else:
                logger.warning("MQTT: _enqueue not set, message dropped")

        except Exception as e:
            logger.error(
                f"Error processing MQTT message: {str(e)}",
                exc_info=True,
            )

    async def health_check(self) -> Dict[str, Any]:
        """Check MQTT broker connection status."""
        if not self.enabled:
            return {
                "channel": self.channel,
                "status": "disabled",
                "detail": "MQTT channel is disabled.",
            }
        if self.client is None:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "MQTT client not initialized.",
            }
        if not self.connected:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "MQTT client is not connected to broker.",
            }
        return {
            "channel": self.channel,
            "status": "healthy",
            "detail": f"MQTT connected to {self.host}:{self.port}.",
        }

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

        client_id = f"mqtt-{uuid.uuid4()}"
        self.client = mqtt.Client(
            client_id=client_id,
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            transport=self.transport,
            clean_session=self.clean_session,
        )

        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)

        if self.tls_enabled:
            logger.info("MQTT: Enabling TLS")
            self.client.tls_set(
                ca_certs=self.tls_ca_certs,
                certfile=self.tls_certfile,
                keyfile=self.tls_keyfile,
            )

        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        try:
            self.client.connect(self.host, self.port, keepalive=60)
            logger.info(
                f"MQTT connecting to {self.host}:{self.port} "
                f"{'(TLS enabled)' if self.tls_enabled else ''} "
                f"(transport: {self.transport})",
            )
        except MQTTException as e:
            logger.error(f"MQTT connect failed: {str(e)}")
            return

        self.client.loop_start()

        logger.info("MQTT channel started")
        logger.info(f"Subscribing to: {self.subscribe_topic}")
        logger.info(f"Publishing to: {self.publish_topic}")
        logger.info(f"Using transport: {self.transport}")
        logger.info(f"Clean session: {self.clean_session}")
        logger.info(f"QoS level: {self.qos}")

    async def stop(self) -> None:
        logger.info("Stopping MQTT channel...")
        if self.client:
            self.client.loop_stop()
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
        if not self.enabled or not self.client or not self.connected:
            return

        try:
            client_id = to_handle
            if meta and "client_id" in meta:
                client_id = meta["client_id"]

            if not client_id:
                logger.warning("MQTT send: no client_id")
                return

            send_topic = self.publish_topic.format(client_id=client_id)
            self.client.publish(send_topic, text, qos=self.qos)
            logger.info(f"MQTT [{client_id}] << {text} (QoS={self.qos})")

        except Exception as e:
            logger.error(f"Failed to send MQTT message: {str(e)}")

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[dict] = None,
    ) -> None:
        if not self.enabled or not self.client or not self.connected:
            return

        try:
            client_id = to_handle
            if meta and "client_id" in meta:
                client_id = meta["client_id"]

            if not client_id:
                logger.warning("MQTT send_media: no client_id")
                return

            send_topic = self.publish_topic.format(client_id=client_id)
            part_type = getattr(part, "type", None)

            if part_type == ContentType.IMAGE:
                img_url = getattr(part, "image_url", "")
                self.client.publish(
                    send_topic,
                    f"[Image] {img_url}",
                    qos=self.qos,
                )
            elif part_type == ContentType.VIDEO:
                vid_url = getattr(part, "video_url", "")
                self.client.publish(
                    send_topic,
                    f"[Video] {vid_url}",
                    qos=self.qos,
                )
            elif part_type == ContentType.AUDIO:
                self.client.publish(send_topic, "[Audio]", qos=self.qos)
            elif part_type == ContentType.FILE:
                file_url = getattr(part, "file_url", "") or getattr(
                    part,
                    "file_id",
                    "",
                )
                self.client.publish(
                    send_topic,
                    f"[File] {file_url}",
                    qos=self.qos,
                )

        except Exception as e:
            logger.error(f"Failed to send MQTT media: {str(e)}")

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[dict] = None,
    ) -> str:
        return f"mqtt:{sender_id}"

    def get_to_handle_from_request(self, request: Any) -> str:
        meta = getattr(request, "channel_meta", None) or {}
        client_id = meta.get("client_id")
        if client_id:
            return str(client_id)
        sid = getattr(request, "session_id", "")
        if sid.startswith("mqtt:"):
            return sid.split(":", 1)[-1]
        return getattr(request, "user_id", "") or ""

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        user_id = str(meta.get("client_id") or sender_id)
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
        if session_id.startswith("mqtt:"):
            return session_id.split(":", 1)[-1]
        return user_id
