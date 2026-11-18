# -*- coding: utf-8 -*-
"""One worker-owned paho client, callback tasks and publish confirmations."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTDeliveryError(Exception):
    def __init__(
        self,
        reason_code,
        *,
        side_effect_possible=False,
        retryable=False,
    ):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        self.retryable = retryable


class MQTTPlatform:
    def __init__(self, config, on_event, on_state):
        self.config, self.on_event, self.on_state = config, on_event, on_state
        self.client = None
        self._client_id = "mqtt-" + uuid.uuid4().hex
        self._last_mid = 0
        self._loop = None
        self._tasks = set()
        self._publishes = set()
        self._stopping = False
        self._epoch = 0
        self._ready = asyncio.Event()
        self._reconnect_pending = None
        self.connected = False

    def _owns(self, client, epoch=None):
        return (
            not self._stopping
            and client is self.client
            and (epoch is None or epoch == self._epoch)
        )

    def _schedule(self, factory, client, epoch):
        # Executed on paho's thread. Recheck ownership on the worker loop.
        if not self._stopping and self._loop is not None:
            self._loop.call_soon_threadsafe(
                self._spawn,
                factory,
                client,
                epoch,
            )

    def _spawn(self, factory, client, epoch):
        if not self._owns(client, epoch):
            if self._reconnect_pending == (client, epoch):
                self._reconnect_pending = None
            return
        if len(self._tasks) >= 500:
            logger.warning("MQTT event capacity exceeded")
            return
        task = asyncio.create_task(factory())
        self._tasks.add(task)
        task.add_done_callback(self._done)

    def _done(self, task):
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            logger.warning("MQTT callback failed: %s", task.exception())

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties=None,
    ):
        if not self._owns(client):
            return
        if reason_code != 0:
            self._schedule(
                lambda: self._connection_failed(client, self._epoch),
                client,
                self._epoch,
            )
            return
        rc, _mid = client.subscribe(
            self.config["subscribe_topic"],
            qos=self.config.get("qos", 2),
        )
        if not self._owns(client):
            return
        if rc != mqtt.MQTT_ERR_SUCCESS:
            self._schedule(
                lambda: self._connection_failed(client, self._epoch),
                client,
                self._epoch,
            )
            return
        self._epoch += 1
        epoch = self._epoch
        self.connected = True
        self._schedule(lambda: self._connected(client, epoch), client, epoch)

    async def _connection_failed(self, client, epoch):
        if not self._owns(client, epoch):
            return
        await self.on_state("failed")
        if self._owns(client, epoch):
            self._ready.set()

    async def _connected(self, client, epoch):
        if not self._owns(client, epoch):
            return
        await self.on_state("connected")
        if self._owns(client, epoch):
            self._ready.set()

    def _on_disconnect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties=None,
    ):
        if not self._owns(client):
            return
        if (
            self._reconnect_pending is not None
            and self._reconnect_pending[0] is client
        ):
            return
        self.connected = False
        self._epoch += 1
        epoch = self._epoch
        if self._reconnect_pending is not None:
            # Release a failed replacement's connection wait; the one existing
            # reconnect owner will close it and retry without overlapping.
            self._schedule(
                lambda: self._connection_failed(client, epoch),
                client,
                epoch,
            )
            return
        self._reconnect_pending = (client, epoch)
        self._schedule(lambda: self._reconnect(client, epoch), client, epoch)

    async def _reconnect(self, client, epoch):
        token = (client, epoch)
        try:
            if not self._owns(client, epoch):
                return
            await self.on_state("disconnected")
            if not self._owns(client, epoch):
                return
            # paho implicitly republishes unknown outbound messages. Replace
            # its object, retaining the worker identity and MID cursor.
            self._last_mid = client._last_mid
            rc = await asyncio.to_thread(client.loop_stop)
            if (
                rc != mqtt.MQTT_ERR_SUCCESS
                and getattr(client, "_thread", None) is not None
            ):
                raise RuntimeError("MQTT_LOOP_STOP_FAILED")
            if not self._owns(client, epoch):
                return
            self.client = None
            delay = 1
            while not self._stopping and self._reconnect_pending == token:
                await asyncio.sleep(delay)
                if self.client is not None:
                    return
                try:
                    self._ready.clear()
                    await self.start()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    if self.client is not None:
                        failed = self.client
                        failed.disconnect()
                        rc = await asyncio.to_thread(failed.loop_stop)
                        if (
                            rc != mqtt.MQTT_ERR_SUCCESS
                            and getattr(failed, "_thread", None) is not None
                        ):
                            raise RuntimeError("MQTT_LOOP_STOP_FAILED")
                        if self.client is failed:
                            self.client = None
                    delay = min(delay * 2, 10)
        finally:
            if self._reconnect_pending == token:
                self._reconnect_pending = None

    def _on_message(self, client, userdata, msg):
        if not self._owns(client) or not self.connected:
            return
        epoch = self._epoch
        try:
            payload = msg.payload.decode("utf-8").strip()
            data = {}
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                text = payload
            else:
                if not isinstance(data, dict):
                    return
                text = data.get("text", "")
            if not isinstance(text, str) or not text:
                return
            sender = data.get("redirect_client_id")
            if not sender:
                fields = msg.topic.split("/")
                sender = fields[1] if len(fields) >= 2 else "unknown-client"
            sender = str(sender or "unknown-client")
        except (UnicodeError, ValueError, TypeError):
            return
        value = {
            "sender": sender,
            "text": text,
            "topic": msg.topic,
            "payload": payload,
            "event_id": uuid.uuid4().hex,
        }

        async def receive():
            if not self._owns(client, epoch) or not self.connected:
                return
            await self.on_event(value)

        self._schedule(receive, client, epoch)

    async def start(self):
        for key in ("host", "subscribe_topic", "publish_topic"):
            if not self.config.get(key):
                raise ValueError("MQTT " + key + " is required")
        self._loop = asyncio.get_running_loop()
        self.client = mqtt.Client(
            client_id=self._client_id,
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            transport=(
                "tcp"
                if self.config.get("transport") in {None, "", "mqtt"}
                else self.config["transport"]
            ),
            clean_session=self.config.get("clean_session", True),
            reconnect_on_failure=False,
        )
        c = self.client
        # Keep packet IDs progressing across replacement clients, including
        # durable broker sessions. Never alias a still-unknown old publish.
        c._last_mid = self._last_mid
        if self.config.get("username") and self.config.get("password"):
            c.username_pw_set(self.config["username"], self.config["password"])
        if self.config.get("tls_enabled"):
            c.tls_set(
                ca_certs=self.config.get("tls_ca_certs"),
                certfile=self.config.get("tls_certfile"),
                keyfile=self.config.get("tls_keyfile"),
            )
        c.reconnect_delay_set(min_delay=1, max_delay=10)
        c.on_connect, c.on_disconnect, c.on_message = (
            self._on_connect,
            self._on_disconnect,
            self._on_message,
        )
        await asyncio.to_thread(
            c.connect,
            self.config["host"],
            self.config.get("port") or 1883,
            60,
        )
        if c.loop_start() != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError("MQTT_LOOP_START_FAILED")
        await self._ready.wait()
        if not self._owns(c) or not self.connected:
            raise RuntimeError("MQTT_CONNECT_FAILED")

    async def publish_parts(self, sender, parts):
        current = asyncio.current_task()
        self._publishes.add(current)
        published = []
        try:
            for part in parts:
                kind = part["type"]
                if kind in {"text", "refusal"}:
                    text = part.get("text") or part.get("refusal") or ""
                elif kind == "audio":
                    text = "[Audio]"
                elif kind in {"image", "video", "file"}:
                    value = (
                        part.get(kind + "_url") or part.get("file_id") or ""
                    )
                    text = f"[{kind.title()}] {value}"
                else:
                    continue
                if not self.connected or self._stopping:
                    raise MQTTDeliveryError(
                        "NOT_CONNECTED",
                        side_effect_possible=bool(published),
                    )
                info = self.client.publish(
                    self.config["publish_topic"].format(client_id=sender),
                    text,
                    qos=self.config.get("qos", 2),
                )
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    raise MQTTDeliveryError(
                        "MQTT_PUBLISH_REJECTED",
                        side_effect_possible=bool(published),
                        retryable=not published,
                    )
                try:
                    await asyncio.to_thread(info.wait_for_publish, 3.0)
                    confirmed = info.is_published()
                except Exception as exc:
                    raise MQTTDeliveryError(
                        "MQTT_CONFIRMATION_UNKNOWN",
                        side_effect_possible=True,
                    ) from exc
                if not confirmed:
                    raise MQTTDeliveryError(
                        "MQTT_CONFIRMATION_UNKNOWN",
                        side_effect_possible=True,
                    )
                published.append(str(info.mid))
            return {"message_id": ",".join(published)}
        finally:
            self._publishes.discard(current)

    async def stop(self):
        self._stopping = True
        self._epoch += 1
        # Fence callbacks before awaiting any external shutdown.
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        if self._publishes:
            await asyncio.gather(
                *tuple(self._publishes),
                return_exceptions=True,
            )
        if self.client is not None:
            c = self.client
            c.disconnect()
            rc = await asyncio.to_thread(c.loop_stop)
            if (
                rc != mqtt.MQTT_ERR_SUCCESS
                and getattr(c, "_thread", None) is not None
            ):
                raise RuntimeError("MQTT_LOOP_STOP_FAILED")
            thread = getattr(c, "_thread", None)
            if thread is not None and thread.is_alive():
                raise RuntimeError("MQTT_LOOP_STILL_RUNNING")
            self.client = None
        self.connected = False
