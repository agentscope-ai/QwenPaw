# -*- coding: utf-8 -*-
# pylint: disable=unused-argument,too-many-return-statements
"""Feishu child transport; the host owns policy and Agent execution."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import uuid

from qwenpaw.channel_protocol.errors import RPC_LIFECYCLE_ERROR, RpcError
from qwenpaw.channel_protocol.response_policy import ResponsePolicy
from qwenpaw.channel_protocol.targets import decode_reply_target
from qwenpaw.channel_protocol.models import InboundEvent
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from .errors import FeishuDeliveryError
from .utils import sender_display_string, short_session_id_from_full_id

_STATE_KEY = "feishu.shared.responses"
_RECEIVE_KEY = "feishu.shared.receive_ids"
_MAX_ROUTES = 128


class FeishuDriver(SharedResponseDriver):
    """Own one SDK connection and durable reply resources."""

    @staticmethod
    async def manage(request):
        from .management import manage

        return await manage(request)

    def __init__(self):
        super().__init__("feishu", _STATE_KEY, FeishuDeliveryError)
        self._receive_ids = OrderedDict()
        self._supervisor = None

    async def start(self, config):
        self._config = dict(config)
        self._stopping = False
        secret = {
            key: self._config.pop(key, "")
            for key in ("app_secret", "encrypt_key", "verification_token")
        }
        try:
            from .platform import LarkOapiPlatform

            self._platform = LarkOapiPlatform()
            media = self._config.get("media_dir")
            if not media:
                workspace = self._config.get("workspace_dir")
                if workspace:
                    media = str(Path(workspace) / "media")
                else:
                    from qwenpaw.constant import DEFAULT_MEDIA_DIR

                    media = str(DEFAULT_MEDIA_DIR)
            await self._platform.prepare(
                {**self._config, "bot_prefix": ""},
                secret,
                Path(media).expanduser(),
            )
            await self._restore_responses()
            targets = (await self._state("get", _RECEIVE_KEY))["value"] or {}
            if not isinstance(targets, dict) or len(targets) > 256:
                raise ValueError("RECEIVE_STATE_INVALID")
            self._receive_ids.update(targets)
            self._load_legacy_targets()
            await self._connect()
            for snapshot in self._routes.pending_cleanups():
                async with self._lock(snapshot.response_handle):
                    try:
                        await self._cleanup(snapshot)
                    except Exception:
                        await self._diagnostic("RESPONSE_FINISH_FAILED")
            self._supervisor = asyncio.create_task(self._supervise())
        except BaseException:
            self._connected = False
            await self._context.set_platform_state("failed")
            raise
        finally:
            secret.clear()

    async def _connect(self):
        self._connection_generation += 1
        generation = self._connection_generation
        ready = asyncio.Event()

        async def message(value):
            await ready.wait()
            self._check_connection(generation)
            await self._message(value)

        async def card(value):
            await ready.wait()
            self._check_connection(generation)
            await self._card(value)

        await self._context.set_platform_state("connecting")
        try:
            await self._platform.connect(message, card)
            self._connected = True
            await self._context.set_platform_state("connected")
        finally:
            ready.set()

    async def _supervise(self):
        delay = 1.0
        try:
            while not self._stopping:
                await self._platform.wait_disconnected()
                self._connected = False
                self._connection_generation += 1
                await self._context.set_platform_state("disconnected")
                await self._platform.disconnect()
                while not self._stopping:
                    await asyncio.sleep(delay)
                    try:
                        await self._connect()
                    except Exception:
                        await self._platform.disconnect()
                        delay = min(30.0, delay * 2)
                    else:
                        delay = 1.0
                        break
        except Exception:
            self._connected = False
            await self._context.set_platform_state("failed")

    async def stop(self):
        self._stopping = True
        self._connected = False
        self._connection_generation += 1
        if self._supervisor is not None:
            self._supervisor.cancel()
            await asyncio.gather(self._supervisor, return_exceptions=True)
            self._supervisor = None
        if self._platform is not None:
            await self._platform.close()
            self._platform = None
        await self._context.set_platform_state("disconnected")

    def _require_connected(self):
        if not self._connected or self._stopping or self._platform is None:
            raise ValueError("NOT_CONNECTED")
        return self._platform

    def response_policy(self, response_handle: str) -> ResponsePolicy:
        attrs = self._route_attrs(response_handle)
        return ResponsePolicy(
            streaming=bool(self._config.get("streaming_enabled"))
            and not bool(json.loads(attrs["session_ctx"]).get("thread_id")),
            completion_reaction=True,
        )

    def _session(self, sender, meta):
        chat = str(meta.get("feishu_chat_id") or "")
        if meta.get("feishu_chat_type") == "group" and chat:
            return (
                str(self._config.get("app_id") or "")[-4:]
                + "_"
                + short_session_id_from_full_id(chat)
            )
        return short_session_id_from_full_id(sender or chat)

    def _target(self, handle, meta):
        neutral = decode_reply_target(str(handle))
        if meta.get("feishu_receive_id"):
            return [
                meta.get("feishu_receive_id_type") or "open_id",
                meta["feishu_receive_id"],
            ]
        if neutral is not None:
            session = neutral["session_id"]
            if session:
                return self._receive_ids.get(session)
            return (
                ["open_id", neutral["user_id"]] if neutral["user_id"] else None
            )
        value = str(handle).strip()
        if value.startswith("feishu:sw:"):
            key = value[len("feishu:sw:") :]
            if key in self._receive_ids:
                return self._receive_ids[key]
            if key.startswith("feishu:open_id:"):
                return ["open_id", key[len("feishu:open_id:") :]]
            suffix = key.split("#", 1)[-1] if "#" in key else ""
            if len(suffix) >= 4:
                return next(
                    (
                        pair
                        for pair in self._receive_ids.values()
                        if pair[1].endswith(suffix)
                    ),
                    None,
                )
            return None
        for kind in ("open_id", "chat_id"):
            if value.startswith("feishu:" + kind + ":"):
                return [kind, value[len("feishu:" + kind + ":") :]]
        return (
            ["chat_id" if value.startswith("oc_") else "open_id", value]
            if value
            else None
        )

    def _load_legacy_targets(self):
        workspace = self._config.get("workspace_dir")
        if workspace:
            path = Path(workspace) / "feishu_receive_ids.json"
        else:
            from qwenpaw.config.utils import get_config_path

            path = get_config_path().parent / "feishu_receive_ids.json"
        if not path.is_file():
            return
        try:
            if path.stat().st_size > 256 * 1024:
                raise ValueError("RECEIVE_STATE_CAPACITY")
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, pair in data.items():
                if isinstance(pair, list) and len(pair) >= 2:
                    first, second = map(str, pair[:2])
                    if second in {"open_id", "chat_id"}:
                        first, second = second, first
                    if first in {"open_id", "chat_id"} and second:
                        self._receive_ids[key] = [first, second]
            while len(self._receive_ids) > 256:
                self._receive_ids.popitem(last=False)
        except (OSError, ValueError, AttributeError):
            return

    async def _open_route(self, handle, target, meta):
        attrs = {
            "receive_id_type": str(target[0]),
            "receive_id": str(target[1]),
            "reply_message_id": (
                str(meta.get("feishu_message_id") or "")
                if meta.get("feishu_thread_id")
                else ""
            ),
            "session_ctx": json.dumps(
                {
                    **{
                        key.removeprefix("feishu_"): value
                        for key, value in meta.items()
                        if key.startswith("feishu_")
                    },
                    "session_id": meta.get("session_id", ""),
                    "is_group": bool(meta.get("is_group")),
                },
            ),
            "bot_prefix": str(
                meta.get("bot_prefix") or self._config.get("bot_prefix") or "",
            ),
        }
        return await self._persist_route(handle, attrs)

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        if set(params) - {
            "channel_key",
            "instance_id",
            "generation",
            "to_handle",
            "meta",
            "session_id",
        }:
            raise ValueError("SCHEMA_MISMATCH")
        meta = dict(params.get("meta") or {})
        if params.get("session_id"):
            meta["session_id"] = params["session_id"]
        target = self._target(params["to_handle"], meta)
        if not target:
            raise RpcError(
                RPC_LIFECYCLE_ERROR,
                "outbound target unavailable",
                data={
                    "reason_code": "OUTBOUND_TARGET_UNKNOWN",
                    "retryable": False,
                },
            )
        handle = "feishu:reply:" + uuid.uuid4().hex
        await self._open_route(handle, target, meta)
        return {"response_handle": handle}

    async def _message(self, value):
        if not isinstance(value, dict):
            raise ValueError("EVENT_INVALID")
        sender = str(value.get("sender_open_id") or "")
        chat = str(value.get("chat_id") or "")
        message_id = str(value.get("message_id") or "")
        event_id = str(value.get("event_id") or message_id)
        parts = value.get("content_parts") or []
        if not sender or not chat or not event_id or not parts:
            raise ValueError("EVENT_INVALID")
        group = value.get("chat_type") == "group"
        thread = str(value.get("thread_id") or "")
        meta = {
            "feishu_message_id": message_id,
            "feishu_chat_id": chat,
            "feishu_chat_type": "group" if group else "p2p",
            "feishu_sender_id": sender,
            "feishu_receive_id": chat if group else sender,
            "feishu_receive_id_type": "chat_id" if group else "open_id",
            "is_group": group,
            "user_name": str(value.get("sender_name") or ""),
            "bot_mentioned": bool(value.get("bot_mentioned")),
        }
        if thread:
            meta.update(
                feishu_thread_id=thread,
                feishu_sender_id="thread:"
                + short_session_id_from_full_id(thread),
            )
        elif group and self._config.get("share_session_in_group"):
            meta["feishu_sender_id"] = "group"
        meta.update(
            session_id=self._session(sender, meta),
            user_id=meta["feishu_sender_id"],
        )
        if (
            group
            and self._config.get("require_mention")
            and not meta["bot_mentioned"]
        ) or self._config.get("group_disabled" if group else "dm_disabled"):
            return
        await self._emit(
            event_id,
            "message",
            sender_display_string(meta["user_name"], sender),
            sender,
            parts,
            meta,
        )

    async def _card(self, value):
        action = str(value.get("action") or "")
        operator = str(value.get("operator_open_id") or "")
        request_id = str(value.get("request_id") or "")
        if action not in {"approve", "deny"} or not operator or not request_id:
            return
        ctx = dict(value.get("session_ctx") or {})
        meta = {
            "feishu_" + key: ctx.get(key, "")
            for key in (
                "chat_id",
                "chat_type",
                "receive_id",
                "receive_id_type",
                "thread_id",
                "message_id",
            )
        }
        meta.update(
            feishu_sender_id=operator,
            is_group=bool(ctx.get("is_group")),
            from_card_action=True,
            has_bot_command=True,
            user_id=operator,
            session_id=ctx.get("session_id")
            or self._session(str(ctx.get("sender_id") or operator), meta),
        )
        event_id = str(
            value.get("event_id") or f"card-{request_id}-{operator}-{action}",
        )
        await self._emit(
            event_id,
            "approval_action",
            operator,
            operator,
            [{"type": "text", "text": f"/approval {action} {request_id}"}],
            meta,
        )

    async def _emit(self, event_id, kind, sender, actor, parts, meta):
        meta = dict(meta)
        meta["debounce_key"] = meta["session_id"] + (
            ":" + meta["user_id"]
            if meta.get("is_group") and meta["user_id"] != "group"
            else ""
        )
        handle = (
            "feishu:reply:"
            + hashlib.sha256(
                (self._context.identity.instance_id + ":" + event_id).encode(),
            ).hexdigest()
        )
        target = self._target(actor, meta)
        snapshot = self._routes.snapshot(handle)
        created = snapshot is None
        if snapshot is not None and snapshot.kind.value == "terminal":
            # The host classifies duplicates without reopening a closed reply.
            pass
        else:
            await self._open_route(handle, target, meta)
        event = InboundEvent(
            **self._context.identity.to_mapping(),
            event_id=event_id,
            event_kind=kind,
            conversation={
                "id": meta["feishu_chat_id"] or actor,
                "type": "group" if meta["is_group"] else "dm",
                "thread_id": meta.get("feishu_thread_id") or None,
            },
            sender_id=sender,
            acl_sender_id=actor,
            sender_name=meta.get("user_name", ""),
            content_parts=tuple(parts),
            metadata=meta,
            response_handle=handle,
        )
        admission = await self._admit_event(event, created)
        if admission is None:
            return
        ack, uncertain = admission
        for alias in (meta["session_id"], actor, meta["feishu_chat_id"]):
            if alias:
                self._receive_ids[alias] = target
        while len(self._receive_ids) > 256:
            self._receive_ids.popitem(last=False)
        await self._state("put", _RECEIVE_KEY, dict(self._receive_ids))
        if event_id in ack.accepted_event_ids and kind == "message":
            await self._platform.add_reaction(
                meta["feishu_message_id"],
                "Typing",
            )

    @staticmethod
    def _text(params):
        return params.accumulated_text or ""

    def _needs_stream_cleanup(self, ref):
        return bool(dict(ref.attributes).get("card_id"))

    async def _perform_stream_cleanup(self, ref, resource, sequence):
        try:
            platform = self._require_connected()
        except ValueError as exc:
            if str(exc) != "NOT_CONNECTED":
                raise
            raise self.delivery_error(
                "NOT_CONNECTED",
                side_effect_possible=False,
            ) from exc
        if not await platform.update_stream(
            resource,
            resource.get("text", ""),
            sequence,
            final=True,
        ):
            raise FeishuDeliveryError(
                "STREAM_CLEANUP_FAILED",
                side_effect_possible=False,
            )

    async def _perform_send(self, params):  # pylint: disable=too-many-branches
        platform = self._require_connected()
        attrs = self._route_attrs(params.to_handle)
        target = attrs["receive_id_type"], attrs["receive_id"]
        operation = params.operation.value
        if operation == "message.create":
            texts, media = [], []
            for part in params.content_parts:
                if part["type"] in {"text", "refusal"}:
                    text = part.get("text") or part.get("refusal")
                    if text:
                        texts.append(text)
                elif part["type"] in {"image", "file", "audio", "video"}:
                    media.append(part)
            body = "\n".join(texts).strip()
            if params.approval:
                message_id = await platform.send_approval(
                    *target,
                    params.approval.to_mapping(),
                    body,
                    session_ctx=json.loads(attrs["session_ctx"]),
                )
            else:
                message_id = await platform.send_message(
                    *target,
                    tuple(
                        ([{"type": "text", "text": body}] if body else [])
                        + media,
                    ),
                    reply_message_id=attrs["reply_message_id"],
                )
            resource = {"message_id": message_id}
        elif operation == "stream.start":
            if attrs["reply_message_id"]:
                raise FeishuDeliveryError(
                    "THREAD_STREAM_UNSUPPORTED",
                    side_effect_possible=False,
                )
            resource = await platform.start_stream(
                *target,
                self._text(params),
                collapsible=params.stream_type.value == "reasoning",
            )
            resource.update(
                sequence="0",
                text=self._text(params),
                final="false",
                stream_type=params.stream_type.value,
            )
        elif operation in {"stream.delta", "stream.end"}:
            ref = self._delivery_resource(
                params.to_handle,
                params.target_delivery_id,
            )
            if ref is None or ref.kind != "feishu.delivery":
                raise FeishuDeliveryError(
                    "OUTBOUND_TARGET_UNKNOWN",
                    side_effect_possible=False,
                )
            resource = dict(ref.attributes)
            if params.sequence <= int(resource.get("sequence", "0")):
                raise FeishuDeliveryError(
                    "STREAM_SEQUENCE_STALE",
                    side_effect_possible=False,
                )
            final = operation == "stream.end"
            text = self._text(params)
            if not await platform.update_stream(
                resource,
                text,
                params.sequence,
                final=final,
            ):
                raise FeishuDeliveryError(
                    "PLATFORM_SEND_FAILED",
                    side_effect_possible=False,
                )
            resource.update(
                sequence=str(params.sequence),
                text=text,
                final="true" if final else "false",
            )
            if (
                final
                and params.stream_type.value == "reasoning"
                and self._config.get("auto_collapse_thinking")
            ):
                await platform.collapse_reasoning_panel(
                    resource["card_id"],
                    params.sequence + 2,
                )
            return ResponseResourceRef.create(
                "feishu.delivery",
                params.target_delivery_id,
                resource,
            )
        else:
            raise FeishuDeliveryError(
                "OPERATION_UNSUPPORTED",
                side_effect_possible=False,
            )
        return ResponseResourceRef.create(
            "feishu.delivery",
            params.delivery_id,
            resource,
        )

    async def _perform_reaction(self, params):
        ref = self._delivery_resource(
            params.to_handle,
            params.target_delivery_id,
        )
        if ref is None or not dict(ref.attributes).get("message_id"):
            raise FeishuDeliveryError(
                "OUTBOUND_TARGET_UNKNOWN",
                side_effect_possible=False,
            )
        if not await self._require_connected().add_reaction(
            dict(ref.attributes)["message_id"],
            "DONE",
        ):
            raise FeishuDeliveryError(
                "PLATFORM_SEND_FAILED",
                side_effect_possible=False,
            )
