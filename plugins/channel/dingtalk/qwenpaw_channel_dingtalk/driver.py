# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""DingTalk child Driver; policy and Agent execution belong to the host."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
import time
import uuid

from qwenpaw.channel_protocol.response_policy import ResponsePolicy
from qwenpaw.channel_protocol.targets import decode_reply_target
from qwenpaw.channel_protocol.errors import RPC_LIFECYCLE_ERROR, RpcError
from qwenpaw.channel_protocol.models import (
    InboundEvent,
    ResponseOutcome,
)
from qwenpaw.channel_protocol.response_lifecycle import ResponseResourceRef
from qwenpaw.channel_protocol.shared_response_driver import (
    SharedResponseDriver,
)
from qwenpaw.exceptions import ChannelError
from qwenpaw.schemas import Message

from .constants import AI_CARD_RECOVERY_FINAL_TEXT
from .content_utils import (
    shared_group_session_id_from_conversation_id,
    short_session_id_from_conversation_id,
)
from .transport import DingTalkTransport


class DingTalkDeliveryError(RuntimeError):
    """Safe determinate/uncertain platform result."""

    def __init__(self, reason_code, *, side_effect_possible, retryable=False):
        self.reason_code = reason_code
        self.side_effect_possible = side_effect_possible
        self.retryable = retryable
        super().__init__(reason_code)


class DingTalkDriver(SharedResponseDriver):
    """Own the SDK/Stream/Webhook/media resources and durable reply routes."""

    @staticmethod
    async def manage(request):
        from .management import manage

        return await manage(request)

    def __init__(self):
        super().__init__(
            "dingtalk",
            "dingtalk.shared.responses",
            DingTalkDeliveryError,
        )
        self._supervisor = None
        self._ingress = set()

    async def _store_ref(self, snapshot, ref, *, previous=None, route=False):
        field = "route_refs" if route else "resource_refs"
        rows = [
            old
            for old in getattr(snapshot, field)
            if (old.kind, old.resource_id)
            not in {(ref.kind, ref.resource_id), previous}
        ]
        updated = replace(
            snapshot,
            version=snapshot.version + 1,
            **{field: tuple(sorted([*rows, ref]))},
        )
        self._routes.restore(updated)
        try:
            await self._checkpoint()
        except ValueError as exc:
            if str(exc) == "RESPONSE_STATE_CAPACITY":
                self._routes.restore(
                    replace(snapshot, version=updated.version + 1),
                )
            raise
        return updated

    @staticmethod
    def _feedback_fingerprint(delivery_id):
        return hashlib.sha256(
            ("dingtalk.feedback:" + delivery_id).encode(),
        ).hexdigest()

    async def _feedback(self, snapshot, meta, label, *, recall=False):
        if not meta.get("message_id") or not meta.get("conversation_id"):
            return snapshot
        delivery_id = (
            snapshot.response_handle + ":" + ("recall" if recall else label)
        )
        if any(
            ref.resource_id == delivery_id for ref in snapshot.resource_refs
        ):
            return snapshot
        attrs = {
            "fingerprint": self._feedback_fingerprint(delivery_id),
            "operation": "reaction",
            "state": "unknown",
            "reason_code": "PLATFORM_RESULT_UNKNOWN",
        }
        ref = ResponseResourceRef.create(
            "dingtalk.attempt",
            delivery_id,
            attrs,
        )
        try:
            snapshot = await self._store_ref(snapshot, ref)
        except Exception:
            await self._diagnostic("REACTION_CHECKPOINT_FAILED")
            return self._routes.snapshot(snapshot.response_handle)
        try:
            await self._require_connected()._send_emotion(
                meta["message_id"],
                meta["conversation_id"],
                label,
                recall=recall,
                strict=True,
            )
        except Exception:
            await self._diagnostic("REACTION_RESULT_UNKNOWN")
            return snapshot
        attrs.update(state="acknowledged", reason_code="")
        try:
            return await self._store_ref(
                snapshot,
                ResponseResourceRef.create(
                    "dingtalk.attempt",
                    delivery_id,
                    attrs,
                ),
            )
        except Exception:
            await self._diagnostic("REACTION_CHECKPOINT_FAILED")
            return self._routes.snapshot(snapshot.response_handle)

    async def _before_cleanup_complete(self, snapshot):
        if not snapshot.route_refs:
            return snapshot
        meta = json.loads(
            dict(snapshot.route_refs[0].attributes)["session_ctx"],
        )
        prepared = any(
            ref.kind == "dingtalk.delivery"
            and dict(ref.attributes).get("prepare") == "true"
            for ref in snapshot.resource_refs
        )
        if prepared:
            snapshot = await self._feedback(
                snapshot,
                meta,
                "🤔Thinking",
                recall=True,
            )
            label = (
                "🥳Done"
                if snapshot.outcome is ResponseOutcome.COMPLETED
                else "☹️Error"
            )
            snapshot = await self._feedback(snapshot, meta, label)
        return snapshot

    async def _card_created(self, params, resource, text, **extra):
        self._routes.record_delivery(
            params.to_handle,
            [
                ResponseResourceRef.create(
                    "dingtalk.delivery",
                    params.delivery_id,
                    {
                        **resource,
                        "sequence": "0",
                        "text": text,
                        "final": "false",
                        **extra,
                    },
                ),
            ],
        )
        await self._checkpoint()

    async def _perform_prepare(self, params):
        platform = self._require_connected()
        meta = json.loads(self._route_attrs(params.to_handle)["session_ctx"])
        await self._feedback(
            self._routes.snapshot(params.to_handle),
            meta,
            "🤔Thinking",
        )
        resource = {"prepare": "true", "prepared": "true"}
        await self._store_ref(
            self._routes.snapshot(params.to_handle),
            ResponseResourceRef.create(
                "dingtalk.delivery",
                params.delivery_id,
                resource,
            ),
        )
        if platform._ai_card_enabled() and meta.get("conversation_id"):
            text = platform._build_ai_card_initial_text()
            partial = []

            async def created(card_ref):
                partial.append(card_ref)
                await self._card_created(params, card_ref, text, **resource)

            try:
                card = await platform._create_ai_card(
                    meta["conversation_id"],
                    meta=meta,
                    on_created=created,
                )
                if card is not None:
                    resource.update(
                        card_id=card.card_instance_id,
                        conversation_id=card.conversation_id,
                        sequence="0",
                        text=text,
                        final="false",
                        unsettled="false",
                    )
            except ChannelError as exc:
                raise DingTalkDeliveryError(
                    "PLATFORM_SEND_FAILED",
                    side_effect_possible=bool(partial),
                ) from exc
        return ResponseResourceRef.create(
            "dingtalk.delivery",
            params.delivery_id,
            resource,
        )

    def _prepared_card(self, handle):
        return next(
            (
                ref
                for ref in self._routes.snapshot(handle).resource_refs
                if ref.kind == "dingtalk.delivery"
                and dict(ref.attributes).get("card_id")
                and dict(ref.attributes).get("prepared") == "true"
                and dict(ref.attributes).get("final") != "true"
            ),
            None,
        )

    def _card_at_prefix(self, handle, meta):
        platform = self._require_connected()
        first = not any(
            dict(ref.attributes).get("consumed") == "true"
            for ref in self._routes.snapshot(handle).resource_refs
            if ref.kind == "dingtalk.delivery"
        )
        if (
            first
            and platform.at_sender_on_reply
            and meta.get("is_group")
            and meta.get("sender_staff_id")
        ):
            staff = meta["sender_staff_id"]
            return f"<a atId={staff}>{meta.get('user_name') or staff}</a>\n"
        return ""

    async def _mention_meta(self, handle, meta):
        if not self._platform.at_sender_on_reply or not meta.get("is_group"):
            return meta
        snapshot = self._routes.snapshot(handle)
        route = snapshot.route_refs[0]
        attrs = dict(route.attributes)
        if attrs.get("at_sent") == "true":
            return {**meta, "sender_staff_id": "", "sender_dingtalk_id": ""}
        attrs["at_sent"] = "true"
        await self._store_ref(
            snapshot,
            ResponseResourceRef.create(route.kind, route.resource_id, attrs),
            route=True,
        )
        return meta

    async def start(self, config):
        self._config = dict(config)
        self._stopping = False
        self._connection_generation += 1
        self._platform = DingTalkTransport()
        self._platform.initialize(config)
        self._platform._journal_owner = True
        self._platform._admit_callback = self._message
        try:
            await self._restore_responses()
            await self._context.set_platform_state("connecting")
            await self._platform.start()
            self._supervisor = asyncio.create_task(self._supervise())
        except BaseException:
            await self._context.set_platform_state("failed")
            raise
        finally:
            self._config.pop("client_secret", None)

    async def _supervise(self):
        try:
            recovering = True
            while not self._stopping:
                self._platform._update_connection_state()
                connected = self._platform._state == "running"
                if connected != self._connected:
                    self._connected = connected
                    if not connected:
                        await self._context.set_platform_state("disconnected")
                    elif not recovering:
                        await self._context.set_platform_state("connected")
                if connected and recovering:
                    recovering = False
                    await self._recover_legacy_cards()
                    for snapshot in self._routes.pending_cleanups():
                        async with self._lock(snapshot.response_handle):
                            try:
                                await self._cleanup(snapshot)
                            except Exception:
                                await self._diagnostic(
                                    "RESPONSE_FINISH_FAILED",
                                )
                    await self._context.set_platform_state("connected")
                await asyncio.sleep(0.1)
        except Exception:
            self._connected = False
            await self._context.set_platform_state("failed")

    async def stop(self):
        self._stopping = True
        self._connection_generation += 1
        if self._supervisor is not None:
            self._supervisor.cancel()
            await asyncio.gather(self._supervisor, return_exceptions=True)
            self._supervisor = None
        for task in tuple(self._ingress):
            task.cancel()
        if self._ingress:
            await asyncio.gather(*self._ingress, return_exceptions=True)
        # Active journals and original card IDs survive process restart.
        await self._checkpoint()
        self._connected = False
        if self._platform is not None:
            await self._platform.stop()
            self._platform = None
        await self._context.set_platform_state("disconnected")

    def _require_connected(self):
        if not self._connected or self._platform is None:
            raise ValueError("NOT_CONNECTED")
        return self._platform

    def response_policy(self, response_handle: str) -> ResponsePolicy:
        meta = json.loads(self._route_attrs(response_handle)["session_ctx"])
        return ResponsePolicy(
            streaming=bool(self._config.get("streaming_enabled"))
            and str(self._config.get("message_type") or "markdown").lower()
            == "card",
            prepare=bool(
                meta.get("message_id") and meta.get("conversation_id"),
            ),
        )

    def _session(self, sender, meta):
        cid = str(meta.get("conversation_id") or "")
        if cid:
            if meta.get("is_group") and self._config.get(
                "share_session_in_group",
            ):
                return shared_group_session_id_from_conversation_id(cid)
            return short_session_id_from_conversation_id(cid)
        return "dingtalk:" + sender

    async def _target(self, handle, meta):
        platform = self._require_connected()
        neutral = decode_reply_target(str(handle))
        if neutral is not None:
            handle = (
                "dingtalk:sw:"
                + (neutral["user_id"] + "_" if neutral["user_id"] else "")
                + neutral["session_id"]
            )
        route = platform._route_from_handle(handle)
        entry = (
            await platform._load_session_webhook_entry(
                route.get("webhook_key", ""),
            )
            or {}
        )
        target = {**entry, **meta}
        target["session_webhook"] = (
            meta.get("session_webhook")
            or meta.get("sessionWebhook")
            or route.get("session_webhook")
            or entry.get("webhook")
            or ""
        )
        expires = target.get("session_webhook_expired_time") or target.get(
            "expired_time",
        )
        if expires and int(expires) <= int(time.time() * 1000):
            target["session_webhook"] = ""
        target.setdefault(
            "is_group",
            target.get("conversation_type") == "group",
        )
        if not target["session_webhook"] and not target.get("conversation_id"):
            raise ValueError("OUTBOUND_TARGET_UNKNOWN")
        return {
            "to_handle": str(handle),
            "session_ctx": json.dumps(target),
            "bot_prefix": str(
                meta.get("bot_prefix") or self._config.get("bot_prefix") or "",
            ),
        }

    async def _open(self, params, request):
        self._identity(params)
        self._require_connected()
        if set(params) - {
            *self._context.identity.to_mapping(),
            "to_handle",
            "meta",
            "session_id",
        }:
            raise ValueError("SCHEMA_MISMATCH")
        meta = dict(params.get("meta") or {})
        if params.get("session_id"):
            meta["session_id"] = params["session_id"]
        handle = "dingtalk:reply:" + uuid.uuid4().hex
        try:
            target = await self._target(params["to_handle"], meta)
        except ValueError as exc:
            raise RpcError(
                RPC_LIFECYCLE_ERROR,
                "outbound target unavailable",
                data={
                    "reason_code": "OUTBOUND_TARGET_UNKNOWN",
                    "retryable": False,
                },
            ) from exc
        await self._persist_route(handle, target)
        return {"response_handle": handle}

    async def _message(self, native):
        task = asyncio.current_task()
        if len(self._ingress) >= 128:
            raise RuntimeError("INBOUND_CAPACITY")
        self._ingress.add(task)
        try:
            self._require_connected()
            meta = dict(native.get("meta") or {})
            actor = str(native.get("acl_sender_id") or "")
            sender = str(native.get("sender_id") or "")
            event_id = str(
                native.get("message_id") or meta.get("message_id") or "",
            )
            if not actor or not sender or not event_id:
                raise ValueError("EVENT_INVALID")
            meta.update(
                session_id=self._session(sender, meta),
                user_id=(
                    "group"
                    if meta.get("is_group")
                    and self._config.get("share_session_in_group")
                    else sender
                ),
            )
            meta["debounce_key"] = meta["session_id"] + (
                ""
                if meta.get("is_group")
                and self._config.get("share_session_in_group")
                else ":" + sender
            )
            key = (
                "dingtalk:sw:"
                + (meta["user_id"] + "_" if not meta.get("is_group") else "")
                + meta["session_id"]
            )
            platform = self._require_connected()
            webhook = meta.get("session_webhook") or native.get(
                "session_webhook",
            )
            if webhook:
                await platform._save_session_webhook(
                    key,
                    webhook,
                    meta.get("conversation_id"),
                    meta.get("conversation_type"),
                    meta.get("sender_staff_id"),
                )
                platform._session_webhook_store[key][
                    "session_webhook_expired_time"
                ] = meta.get("session_webhook_expired_time")
                platform._save_session_webhook_store_to_disk()
            handle = (
                "dingtalk:reply:"
                + hashlib.sha256(
                    (
                        self._context.identity.instance_id + ":" + event_id
                    ).encode(),
                ).hexdigest()
            )
            snapshot = self._routes.snapshot(handle)
            created = snapshot is None
            if snapshot is None or snapshot.kind.value != "terminal":
                await self._persist_route(
                    handle,
                    await self._target(key, meta),
                )
            event = InboundEvent(
                **self._context.identity.to_mapping(),
                event_id=event_id,
                event_kind="message",
                sender_name=str(meta.get("user_name") or ""),
                sender_id=sender,
                acl_sender_id=actor,
                conversation={
                    "id": meta["session_id"],
                    "type": "group" if meta.get("is_group") else "dm",
                },
                content_parts=tuple(
                    (
                        part.model_dump(
                            mode="json",
                            exclude_none=True,
                            exclude={
                                "delta",
                                "index",
                                "status",
                                "object",
                                "msg_id",
                            },
                        )
                        if hasattr(part, "model_dump")
                        else part
                    )
                    for part in native.get("content_parts", [])
                ),
                metadata=meta,
                response_handle=handle,
            )
            admission = await self._admit_event(event, created)
            if admission is None:
                return
            ack, uncertain = admission
        finally:
            self._ingress.discard(task)

    async def _recover_legacy_cards(self):
        platform = self._require_connected()
        known = {
            dict(ref.attributes).get("card_id")
            for row in self._routes.snapshots()
            for ref in row.resource_refs
        }
        uncertain = any(
            ref.kind == "dingtalk.attempt"
            and dict(ref.attributes).get("state") == "unknown"
            for row in self._routes.snapshots()
            for ref in row.resource_refs
        )
        for record in platform._card_store.load():
            card_id = str(record.get("card_instance_id") or "")
            if (
                not card_id
                or card_id in known
                or uncertain
                or str(record.get("state")) in {"3", "5"}
            ):
                continue
            conversation_id = str(record.get("conversation_id") or "")
            if not conversation_id:
                continue
            handle = (
                "dingtalk:reply:legacy-"
                + hashlib.sha256(card_id.encode()).hexdigest()
            )
            await self._persist_route(
                handle,
                {"to_handle": "", "session_ctx": "{}", "bot_prefix": ""},
            )
            self._routes.record_delivery(
                handle,
                [
                    ResponseResourceRef.create(
                        "dingtalk.delivery",
                        card_id,
                        {
                            "card_id": card_id,
                            "conversation_id": conversation_id,
                            "text": AI_CARD_RECOVERY_FINAL_TEXT,
                            "sequence": "0",
                            "final": "false",
                        },
                    ),
                ],
            )
            self._routes.begin_finish(handle, ResponseOutcome.CANCELLED)
            await self._checkpoint()

    async def _update_nonstream_card(
        self,
        params,
        prepared,
        parts,
        meta,
        body,
    ):
        platform = self._require_connected()
        resource = dict(prepared.attributes)
        first = resource.get("consumed") != "true"
        at_prefix = (
            self._card_at_prefix(params.to_handle, meta)
            if first
            else resource.get("at_prefix", "")
        )
        previous = "" if first else resource.get("body", "")
        body = previous + "\n" + body.strip() if previous else body.strip()
        sequence = int(resource.get("sequence", "0")) + 1
        text = at_prefix + body
        resource["unsettled"] = "true"
        await self._store_ref(
            self._routes.snapshot(params.to_handle),
            ResponseResourceRef.create(
                "dingtalk.delivery",
                prepared.resource_id,
                resource,
            ),
        )
        if not await platform.update_stream(
            resource,
            text,
            sequence,
            final=False,
        ):
            raise DingTalkDeliveryError(
                "PLATFORM_SEND_FAILED",
                side_effect_possible=True,
            )
        resource.update(
            body=body,
            text=text,
            sequence=str(sequence),
            consumed="true",
            at_prefix=at_prefix,
            unsettled="false",
        )
        self._routes.record_delivery(
            params.to_handle,
            [
                ResponseResourceRef.create(
                    "dingtalk.delivery",
                    prepared.resource_id,
                    resource,
                ),
            ],
        )
        await self._checkpoint()
        media = [
            p
            for p in parts
            if getattr(p, "type", "") not in {"text", "refusal"}
        ]
        if media:
            await platform.send_parts(
                self._route_attrs(params.to_handle)["to_handle"],
                media,
                meta,
            )
        return ResponseResourceRef.create(
            "dingtalk.delivery",
            prepared.resource_id,
            resource,
        )

    async def _start_stream_card(self, params, meta, created, partial):
        platform = self._require_connected()
        prepared = self._prepared_card(params.to_handle)
        at_prefix = self._card_at_prefix(params.to_handle, meta)
        text = at_prefix + (params.accumulated_text or "...")
        if prepared:
            resource = dict(prepared.attributes)
            resource.update(
                prepared="false",
                consumed="true",
                at_prefix=at_prefix,
                unsettled="true",
            )
            # Transfer the original card before its segment update.
            # Exactly one resource ref owns its cleanup at every point.
            await self._store_ref(
                self._routes.snapshot(params.to_handle),
                ResponseResourceRef.create(
                    "dingtalk.delivery",
                    params.delivery_id,
                    resource,
                ),
                previous=(prepared.kind, prepared.resource_id),
            )
            partial.append(resource)
            if not await platform.update_stream(
                resource,
                text,
                0,
                final=False,
            ):
                raise DingTalkDeliveryError(
                    "PLATFORM_SEND_FAILED",
                    side_effect_possible=True,
                )
        else:
            resource = await platform.start_stream(
                meta,
                text,
                on_created=created,
            )
        resource.update(
            sequence="0",
            text=text,
            final="false",
            consumed="true",
            at_prefix=at_prefix,
            unsettled="false",
        )
        return resource

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
            raise DingTalkDeliveryError(
                "STREAM_CLEANUP_FAILED",
                side_effect_possible=False,
            )

    async def _perform_send(self, params):
        platform = self._require_connected()
        attrs = self._route_attrs(params.to_handle)
        meta = json.loads(attrs["session_ctx"])
        operation = params.operation.value
        partial = []

        async def created(resource):
            partial.append(resource)
            await self._card_created(
                params,
                resource,
                params.accumulated_text or "...",
            )

        try:
            if operation == "stream.start" and any(
                ref.kind == "dingtalk.attempt"
                and ref.resource_id != params.delivery_id
                and dict(ref.attributes).get("state") == "unknown"
                and dict(ref.attributes).get("operation") == "stream.start"
                for ref in self._routes.snapshot(
                    params.to_handle,
                ).resource_refs
            ):
                raise DingTalkDeliveryError(
                    "PLATFORM_RESULT_UNKNOWN",
                    side_effect_possible=True,
                )
            if operation == "message.create":
                parts = Message(content=list(params.content_parts)).content
                prepared = self._prepared_card(params.to_handle)
                body = platform._parts_to_single_text(parts)
                if prepared and body.strip() and not params.approval:
                    partial.append(dict(prepared.attributes))
                    return await self._update_nonstream_card(
                        params,
                        prepared,
                        parts,
                        meta,
                        body,
                    )
                meta = await self._mention_meta(params.to_handle, meta)
                await platform.send_parts(
                    attrs["to_handle"],
                    parts,
                    {**meta, "bot_prefix": ""},
                    approval=params.approval,
                    on_created=created,
                )
                resource = {
                    "message_id": str(meta.get("message_id") or ""),
                    "conversation_id": str(meta.get("conversation_id") or ""),
                }
            elif operation == "stream.start":
                resource = await self._start_stream_card(
                    params,
                    meta,
                    created,
                    partial,
                )
            elif operation in {"stream.delta", "stream.end"}:
                ref = self._delivery_resource(
                    params.to_handle,
                    params.target_delivery_id,
                )
                if ref is None:
                    raise DingTalkDeliveryError(
                        "OUTBOUND_TARGET_UNKNOWN",
                        side_effect_possible=False,
                    )
                resource = dict(ref.attributes)
                if params.sequence <= int(resource.get("sequence", "0")):
                    raise DingTalkDeliveryError(
                        "STREAM_SEQUENCE_STALE",
                        side_effect_possible=False,
                    )
                final = operation == "stream.end"
                text = resource.get("at_prefix", "") + (
                    params.accumulated_text or "..."
                )
                if not await platform.update_stream(
                    resource,
                    text,
                    params.sequence,
                    final=final,
                ):
                    raise DingTalkDeliveryError(
                        "PLATFORM_SEND_FAILED",
                        side_effect_possible=False,
                    )
                resource.update(
                    sequence=str(params.sequence),
                    text=text,
                    final="true" if final else "false",
                )
                return ResponseResourceRef.create(
                    "dingtalk.delivery",
                    params.target_delivery_id,
                    resource,
                )
            else:
                raise DingTalkDeliveryError(
                    "OPERATION_UNSUPPORTED",
                    side_effect_possible=False,
                )
        except ChannelError as exc:
            raise DingTalkDeliveryError(
                "PLATFORM_SEND_FAILED",
                side_effect_possible=bool(partial),
            ) from exc
        return ResponseResourceRef.create(
            "dingtalk.delivery",
            params.delivery_id,
            resource,
        )

    async def _perform_reaction(self, params):
        meta = json.loads(self._route_attrs(params.to_handle)["session_ctx"])
        if meta.get("message_id") and meta.get("conversation_id"):
            await self._require_connected()._send_emotion(
                meta["message_id"],
                meta["conversation_id"],
                "✅Completed",
            )
