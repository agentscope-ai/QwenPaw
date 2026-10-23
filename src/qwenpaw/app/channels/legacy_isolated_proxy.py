# -*- coding: utf-8 -*-
"""Frozen compatibility for released official Channel contracts only."""

import hashlib
from qwenpaw.schemas import Message
from qwenpaw.channel_protocol.response_policy import ResponsePolicy
from .base import BaseChannel
from .isolated_proxy import IsolatedChannelProxy


def legacy_proxy_class(channel_key):
    if channel_key not in {"feishu", "dingtalk"}:
        raise ValueError("CHANNEL_CONTRACT_UNSUPPORTED")
    return LegacyIsolatedChannelProxy


class LegacyIsolatedChannelProxy(IsolatedChannelProxy):
    """Small legacy translations; lifecycle and ownership stay in the base."""

    def _configure_response(self, config):
        if self.channel == "dingtalk":
            config["streaming_enabled"] = bool(
                config.get("streaming_enabled")
                and str(config.get("message_type") or "markdown").lower()
                == "card",
            )

    def _normalize_event(self, event):
        meta = dict(event.metadata)
        meta["response_handle"] = event.response_handle
        payload = {
            "channel_id": self.channel,
            "sender_id": event.sender_id,
            "acl_sender_id": event.acl_sender_id,
            "user_id": meta.get("user_id")
            or meta.get("feishu_sender_id")
            or event.acl_sender_id,
            "session_id": meta.get("session_id") or event.conversation["id"],
            "content_parts": Message(
                content=list(event.content_parts),
            ).content,
            "meta": meta,
        }
        if self.channel == "dingtalk":
            payload["message_id"] = str(
                meta.get("message_id") or event.event_id,
            )
            if meta.get("session_webhook"):
                payload["session_webhook"] = meta["session_webhook"]
        return payload

    async def _response_policy(self, to_handle, meta):
        return ResponsePolicy(
            streaming=self.streaming_enabled
            and not bool(meta.get("feishu_thread_id")),
            prepare=self.channel == "dingtalk"
            and bool(meta.get("message_id") and meta.get("conversation_id")),
            completion_reaction=self.channel == "feishu",
        )

    def resolve_session_id(self, sender_id, channel_meta=None):
        meta = channel_meta or {}
        if meta.get("session_id"):
            return meta["session_id"]
        if self.channel == "dingtalk":
            cid = str(meta.get("conversation_id") or "")
            if cid:
                return (
                    hashlib.sha256(cid.encode()).hexdigest()[:16]
                    if meta.get("is_group")
                    and self._launch_spec.config.get("share_session_in_group")
                    else cid[-8:]
                )
            return f"dingtalk:{sender_id}"
        if self.channel == "feishu":
            chat = str(meta.get("feishu_chat_id") or "")
            if meta.get("feishu_chat_type") == "group" and chat:
                app_suffix = str(self._launch_spec.config.get("app_id") or "")[
                    -4:
                ]
                return f"{app_suffix}_{chat[-8:]}"
            return (
                str(sender_id or chat)[-8:]
                if sender_id or chat
                else f"{self.channel}:{sender_id}"
            )
        return super().resolve_session_id(sender_id, meta)

    def get_debounce_key(self, payload):
        key = BaseChannel.get_debounce_key(self, payload)
        if self.channel == "dingtalk" and isinstance(payload, dict):
            meta = payload.get("meta") or {}
            if not (
                meta.get("is_group")
                and self._launch_spec.config.get("share_session_in_group")
            ) and payload.get("sender_id"):
                return key + ":" + payload["sender_id"]
        return key

    def to_handle_from_target(self, *, user_id, session_id):
        if self.channel == "dingtalk":
            return (
                f"dingtalk:sw:{user_id}_{session_id}"
                if user_id
                else f"dingtalk:sw:{session_id}"
            )
        return (
            f"{self.channel}:sw:{session_id}"
            if session_id
            else f"{self.channel}:open_id:{user_id}"
        )
