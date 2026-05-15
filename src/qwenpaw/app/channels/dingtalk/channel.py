# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements,too-many-branches
# pylint: disable=too-many-return-statements
"""DingTalk Channel.

The handler ACKs the DingTalk Stream callback immediately. All actual
replies are delivered asynchronously via sessionWebhook, AI Card streaming
updates, or Open API. The base class event loop drives processing through
hooks (on_streaming_start/delta/end, on_event_message_completed, etc.).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import os
import threading
import time
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
)
from uuid import uuid4
from urllib.parse import urlparse

import aiohttp
import dingtalk_stream
from dingtalk_stream import ChatbotMessage
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dingtalk.oauth2_1_0 import (
    client as dingtalk_oauth_client,
    models as dingtalk_oauth_models,
)
from alibabacloud_dingtalk.robot_1_0 import (
    client as dingtalk_robot_client,
    models as dingtalk_robot_models,
)
from alibabacloud_dingtalk.card_1_0 import (
    client as dingtalk_card_client,
    models as dingtalk_card_models,
)
from alibabacloud_tea_util import models as tea_util_models
from Tea.exceptions import TeaException

from ..utils import file_url_to_local_path
from ....config.config import DingTalkConfig as DingTalkChannelConfig
from ....config.utils import get_config_path
from ....constant import DEFAULT_MEDIA_DIR
from ....exceptions import ChannelError

from ..base import (
    BaseChannel,
    ContentType,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)

from .constants import (
    AI_CARD_PROCESSING_TEXT,
    AI_CARD_RECOVERY_FINAL_TEXT,
    AI_CARD_STREAM_MIN_INTERVAL_SECONDS,
    AI_CARD_TOKEN_PREEMPTIVE_REFRESH_SECONDS,
    DINGTALK_TOKEN_TTL_SECONDS,
)
from .content_utils import (
    parse_data_url,
    session_param_from_webhook_url,
    short_session_id_from_conversation_id,
)
from .handler import DingTalkChannelHandler
from . import markdown as dingtalk_markdown
from .ai_card import (
    FAILED,
    FINISHED,
    INPUTING,
    PROCESSING,
    AICardPendingStore,
    ActiveAICard,
)
from .utils import guess_suffix_from_file_content

if TYPE_CHECKING:
    from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

# Short aliases for long SDK model names (≤79 chars)
_GroupDeliverModel = (
    dingtalk_card_models.DeliverCardRequestImGroupOpenDeliverModel
)
_RobotDeliverModel = (
    dingtalk_card_models.DeliverCardRequestImRobotOpenDeliverModel
)

logger = logging.getLogger(__name__)


class DingTalkChannel(BaseChannel):
    """DingTalk Channel: DingTalk Stream -> Incoming -> to_agent_request ->
    process -> send_response -> DingTalk reply.

    Proactive send (stored sessionWebhook):
    - We store sessionWebhook from incoming messages in memory; send() uses it.
    - Key uses short suffix of conversation_id so request and cron stay short.
    - to_handle "dingtalk:sw:<session_id>" (session_id = last N of conv id).
    - Note: sessionWebhook has an expiry (sessionWebhookExpiredTime);
      push only works for users who have chatted recently. For cron to
      users who may not
      have spoken, consider Open API (corp_id + batchSend) instead.
    """

    channel = "dingtalk"

    _NON_SERIALIZABLE_META_KEYS = ()

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        client_id: str,
        client_secret: str,
        bot_prefix: str,
        message_type: str = "markdown",
        cron_message_type: str = "markdown",
        card_template_id: str = "",
        card_template_key: str = "content",
        robot_code: str = "",
        media_dir: str = "",
        workspace_dir: Path | None = None,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[List[str]] = None,
        deny_message: str = "",
        filter_thinking: bool = False,
        require_mention: bool = False,
        card_auto_layout: bool = False,
        at_sender_on_reply: bool = False,
        streaming_enabled: bool = False,
    ):
        # Streaming only makes sense for card mode (AI Card streaming updates).
        # For markdown mode, force streaming_enabled=False so base class
        # does not dispatch to streaming hooks (which would swallow events).
        effective_streaming = (
            streaming_enabled
            and (message_type or "markdown").strip().lower() == "card"
        )
        logger.info(
            "dingtalk init: streaming_enabled=%s message_type=%s "
            "effective_streaming=%s",
            streaming_enabled,
            message_type,
            effective_streaming,
        )
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=dm_policy,
            group_policy=group_policy,
            allow_from=allow_from,
            deny_message=deny_message,
            require_mention=require_mention,
            streaming_enabled=effective_streaming,
        )
        self.enabled = enabled
        self.client_id = client_id
        self.client_secret = client_secret
        self.bot_prefix = bot_prefix
        self.message_type = (message_type or "markdown").strip().lower()
        self.cron_message_type = (
            (cron_message_type or "markdown").strip().lower()
        )
        self.card_template_id = card_template_id or ""
        self.card_template_key = card_template_key or "content"
        self.robot_code = robot_code or self.client_id
        self.card_auto_layout = card_auto_layout
        self.at_sender_on_reply = at_sender_on_reply
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )
        self._active_cards: Dict[str, ActiveAICard] = {}
        self._active_cards_lock = asyncio.Lock()
        cards_dir = self._workspace_dir or get_config_path().parent
        self._card_store = AICardPendingStore(
            cards_dir / "dingtalk-active-cards.json",
        )
        # Use workspace-specific media dir if workspace_dir is provided
        if not media_dir and self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        elif media_dir:
            self._media_dir = Path(media_dir).expanduser()
        else:
            self._media_dir = DEFAULT_MEDIA_DIR
        self._media_dir.mkdir(parents=True, exist_ok=True)

        self._client: Optional[dingtalk_stream.DingTalkStreamClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._http: Optional[aiohttp.ClientSession] = None

        # DingTalk OpenAPI SDK clients
        self._oauth_sdk: Optional[dingtalk_oauth_client.Client] = None
        self._robot_sdk: Optional[dingtalk_robot_client.Client] = None
        self._card_sdk: Optional[dingtalk_card_client.Client] = None

        # Store sessionWebhook for proactive send (in-memory).
        # Key is a handle string, e.g. "dingtalk:sw:<sender>"
        # Value is a dict: {"webhook": str, "conversation_id": str, ...}
        self._session_webhook_store: Dict[str, Any] = {}
        self._session_webhook_lock = asyncio.Lock()

        # Time debounce disabled: manager drains same-session from queue
        # and merges before calling us.
        self._debounce_seconds = 0.0

        # Token cache (instance-level for multi-instance / tests)
        self._token_lock = asyncio.Lock()
        self._token_value: Optional[str] = None
        self._token_expires_at: float = 0.0

        # Dedup: in-flight message_ids only (message_id is sufficient).
        self._processing_message_ids: set = set()
        self._processing_message_ids_lock = threading.Lock()

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "DingTalkChannel":
        allow_from_env = os.getenv("DINGTALK_ALLOW_FROM", "")
        allow_from = (
            [s.strip() for s in allow_from_env.split(",") if s.strip()]
            if allow_from_env
            else []
        )
        return cls(
            process=process,
            enabled=os.getenv("DINGTALK_CHANNEL_ENABLED", "1") == "1",
            client_id=os.getenv("DINGTALK_CLIENT_ID", ""),
            client_secret=os.getenv("DINGTALK_CLIENT_SECRET", ""),
            bot_prefix=os.getenv("DINGTALK_BOT_PREFIX", ""),
            message_type=os.getenv("DINGTALK_MESSAGE_TYPE", "markdown"),
            cron_message_type=os.getenv(
                "DINGTALK_CRON_MESSAGE_TYPE",
                "markdown",
            ),
            card_template_id=os.getenv("DINGTALK_CARD_TEMPLATE_ID", ""),
            card_template_key=os.getenv(
                "DINGTALK_CARD_TEMPLATE_KEY",
                "content",
            ),
            robot_code=os.getenv("DINGTALK_ROBOT_CODE", "")
            or os.getenv("DINGTALK_CLIENT_ID", ""),
            media_dir=os.getenv("DINGTALK_MEDIA_DIR", ""),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("DINGTALK_DM_POLICY", "open"),
            group_policy=os.getenv("DINGTALK_GROUP_POLICY", "open"),
            allow_from=allow_from,
            deny_message=os.getenv("DINGTALK_DENY_MESSAGE", ""),
            require_mention=os.getenv("DINGTALK_REQUIRE_MENTION", "0") == "1",
            card_auto_layout=os.getenv("DINGTALK_CARD_AUTO_LAYOUT", "0")
            == "1",
            at_sender_on_reply=os.getenv(
                "DINGTALK_AT_SENDER_ON_REPLY",
                "0",
            )
            == "1",
            streaming_enabled=os.getenv(
                "DINGTALK_STREAMING_ENABLED",
                "0",
            )
            == "1",
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: DingTalkChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Path | None = None,
    ) -> "DingTalkChannel":
        return cls(
            process=process,
            enabled=config.enabled,
            client_id=config.client_id or "",
            client_secret=config.client_secret or "",
            bot_prefix=config.bot_prefix or "",
            message_type=getattr(config, "message_type", "markdown"),
            cron_message_type=getattr(
                config,
                "cron_message_type",
                "markdown",
            ),
            card_template_id=getattr(config, "card_template_id", ""),
            card_template_key=getattr(config, "card_template_key", "content"),
            robot_code=(
                getattr(config, "robot_code", "") or config.client_id or ""
            ),
            media_dir=config.media_dir or "",
            workspace_dir=workspace_dir,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            dm_policy=config.dm_policy or "open",
            group_policy=config.group_policy or "open",
            allow_from=config.allow_from or [],
            deny_message=config.deny_message or "",
            filter_thinking=filter_thinking,
            require_mention=config.require_mention,
            card_auto_layout=getattr(config, "card_auto_layout", False),
            at_sender_on_reply=getattr(
                config,
                "at_sender_on_reply",
                False,
            ),
            streaming_enabled=bool(
                getattr(config, "streaming_enabled", False),
            ),
        )

    # ---------------------------
    # Proactive send: webhook store
    # ---------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Session_id = short suffix of conversation_id for cron lookup."""
        meta = channel_meta or {}
        cid = meta.get("conversation_id")
        if cid:
            return short_session_id_from_conversation_id(cid)
        return f"{self.channel}:{sender_id}"

    def build_agent_request_from_native(
        self,
        native_payload: Any,
    ) -> "AgentRequest":
        """Build AgentRequest from DingTalk native dict (runtime content)."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = dict(payload.get("meta") or {})
        if payload.get("session_webhook"):
            meta["session_webhook"] = payload["session_webhook"]
        session_id = self.resolve_session_id(sender_id, meta)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        # Set serializable channel_meta (exclude non-JSON-serializable objects)
        serializable_meta = {
            k: v
            for k, v in meta.items()
            if k not in self._NON_SERIALIZABLE_META_KEYS
        }
        setattr(request, "channel_meta", serializable_meta)
        return request

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        # Key by session_id (short suffix of conversation_id) so cron can
        # use the same session_id to look up stored sessionWebhook.
        return f"dingtalk:sw:{session_id}"

    async def _before_consume_process(self, request: "AgentRequest") -> None:
        """Save session_webhook, send processing reaction, pre-create card."""
        meta = getattr(request, "channel_meta", None) or {}

        # Store session_webhook for cron/proactive send
        session_webhook = self._get_session_webhook(meta)
        if session_webhook:
            session_id = getattr(request, "session_id", None)
            if session_id:
                webhook_key = self.to_handle_from_target(
                    user_id=getattr(request, "user_id", None) or "",
                    session_id=session_id,
                )
                logger.info(
                    "dingtalk _before_consume_process: storing webhook "
                    "session_id=%s conversation_id=%s",
                    session_id,
                    meta.get("conversation_id"),
                )
                await self._save_session_webhook(
                    webhook_key,
                    session_webhook,
                    conversation_id=meta.get("conversation_id"),
                    conversation_type=meta.get("conversation_type"),
                    sender_staff_id=meta.get("sender_staff_id"),
                )

        # Add "processing" reaction to user's incoming message
        incoming_msg_id = str(meta.get("message_id") or "")
        conversation_id = str(meta.get("conversation_id") or "")
        if incoming_msg_id and conversation_id:
            await self._send_emotion(
                incoming_msg_id,
                conversation_id,
                "🤔Thinking",
            )

        # Pre-create AI Card before LLM call so user sees it immediately.
        # The card is stored on request._precreated_card for streaming hooks
        # and on_event_message_completed to reuse.
        if self._ai_card_enabled() and conversation_id:
            try:
                card = await self._create_ai_card(
                    conversation_id,
                    meta=meta,
                    inbound=True,
                )
                if card:
                    setattr(request, "_precreated_card", card)
                    logger.info(
                        "dingtalk _before_consume_process: "
                        "AI card pre-created for conversation=%s",
                        conversation_id,
                    )
            except Exception:
                logger.exception(
                    "dingtalk _before_consume_process: "
                    "card pre-creation failed, will retry in hooks",
                )

    async def _on_consume_error(
        self,
        request: "AgentRequest",
        to_handle: str,
        err_text: str,
    ) -> None:
        """Send error emoji and error message via webhook."""
        meta = getattr(request, "channel_meta", None) or {}
        incoming_msg_id = str(meta.get("message_id") or "")
        conversation_id = str(meta.get("conversation_id") or "")
        if incoming_msg_id and conversation_id:
            await self._send_emotion(
                incoming_msg_id,
                conversation_id,
                "🤔Thinking",
                recall=True,
            )
            await self._send_emotion(
                incoming_msg_id,
                conversation_id,
                "☹️Error",
            )
        # Send error text via webhook or fallback
        session_webhook = self._get_session_webhook(meta)
        bot_prefix = self.bot_prefix or ""
        full_err = bot_prefix + err_text if err_text else bot_prefix
        if session_webhook and full_err.strip():
            await self._send_via_session_webhook(
                session_webhook,
                full_err.strip(),
                bot_prefix="",
            )
        # Release dedup msg_id so future retries are accepted
        msg_ids = meta.get("_message_ids")
        if msg_ids is None:
            msg_ids = [incoming_msg_id] if incoming_msg_id else []
        self._release_message_ids(msg_ids)

    def _route_from_handle(self, to_handle: str) -> dict:
        # to_handle:
        # - "dingtalk:sw:<sender>" -> use stored webhook by key
        # - "dingtalk:webhook:<url>" -> direct webhook URL
        # - "<url>" (starts with http/https) -> direct webhook URL
        s = (to_handle or "").strip()
        if s.startswith("http://") or s.startswith("https://"):
            return {"session_webhook": s}

        parts = s.split(":", 2)
        if len(parts) == 3 and parts[0] == "dingtalk":
            kind, ident = parts[1], parts[2]
            if kind == "sw":
                return {"webhook_key": f"dingtalk:sw:{ident}"}
            if kind == "webhook":
                return {"session_webhook": ident}
        return {"webhook_key": s} if s else {}

    def _session_webhook_store_path(self) -> Path:
        """Path to persist session webhook mapping (for cron after restart).

        Uses agent workspace directory if available, otherwise falls back
        to global config directory for backward compatibility.
        """
        if self._workspace_dir:
            return self._workspace_dir / "dingtalk_session_webhooks.json"
        return get_config_path().parent / "dingtalk_session_webhooks.json"

    def _load_session_webhook_store_from_disk(self) -> None:
        """Load session webhook mapping from disk into memory."""
        path = self._session_webhook_store_path()
        if not path.is_file():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    # Support both old format (plain string) and new format
                    # (dict with webhook, expired_time, etc.)
                    # Load any dict entry even if webhook is empty, because
                    # conversation_id etc. are needed for Open API fallback.
                    if isinstance(v, str) and v:
                        self._session_webhook_store[k] = {"webhook": v}
                    elif isinstance(v, dict):
                        self._session_webhook_store[k] = v
        except Exception:
            logger.debug(
                "dingtalk load session_webhook store from %s failed",
                path,
                exc_info=True,
            )

    def _save_session_webhook_store_to_disk(self) -> None:
        """Persist in-memory session webhook store to disk."""
        path = self._session_webhook_store_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    self._session_webhook_store,
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception:
            logger.debug(
                "dingtalk save session_webhook store to %s failed",
                path,
                exc_info=True,
            )

    async def _save_session_webhook(
        self,
        webhook_key: str,
        session_webhook: str,
        conversation_id: Optional[str] = None,
        conversation_type: Optional[str] = None,
        sender_staff_id: Optional[str] = None,
    ) -> None:
        if not webhook_key or not session_webhook:
            logger.debug(
                "dingtalk _save_session_webhook skip: key=%s has_url=%s",
                bool(webhook_key),
                bool(session_webhook),
            )
            return
        session_in_url = session_param_from_webhook_url(session_webhook)
        logger.info(
            "dingtalk _save_session_webhook: "
            "webhook_key=%s session_from_url=%s "
            "conversation_id=%s "
            "conversation_type=%s sender_staff_id=%s",
            webhook_key,
            session_in_url,
            conversation_id,
            conversation_type,
            sender_staff_id,
        )
        async with self._session_webhook_lock:
            self._session_webhook_store[webhook_key] = {
                "webhook": session_webhook,
                "conversation_id": conversation_id,
                "conversation_type": conversation_type,
                "sender_staff_id": sender_staff_id,
            }
            self._save_session_webhook_store_to_disk()

    async def _invalidate_session_webhook(self, to_handle: str) -> None:
        """Clear webhook in memory and disk after send failure.

        Keeps conversation_id and other metadata so Open API fallback
        still works on subsequent sends without a redundant failed POST.
        """
        route = self._route_from_handle(to_handle)
        webhook_key = route.get("webhook_key")
        if not webhook_key:
            return
        async with self._session_webhook_lock:
            raw = self._session_webhook_store.get(webhook_key)
            if raw is None:
                return
            entry = raw if isinstance(raw, dict) else {"webhook": raw}
            if not entry.get("webhook"):
                return
            logger.info(
                "dingtalk _invalidate_session_webhook: "
                "clearing webhook for key=%s",
                webhook_key,
            )
            entry["webhook"] = ""
            self._session_webhook_store[webhook_key] = entry
            self._save_session_webhook_store_to_disk()

    async def _load_session_webhook(self, webhook_key: str) -> Optional[str]:
        if not webhook_key:
            logger.debug("dingtalk _load_session_webhook: empty webhook_key")
            return None
        entry = await self._load_session_webhook_entry(webhook_key)
        if entry is not None:
            return entry.get("webhook")
        return None

    async def _load_session_webhook_entry(
        self,
        webhook_key: str,
    ) -> Optional[Dict[str, Any]]:
        """Load the full webhook entry dict from store (memory then disk).

        Returns None if not found or if the webhook is expired.
        """
        if not webhook_key:
            return None
        async with self._session_webhook_lock:
            raw = self._session_webhook_store.get(webhook_key)
            source = "memory"

            if raw is None:
                self._load_session_webhook_store_from_disk()
                raw = self._session_webhook_store.get(webhook_key)
                source = "disk"

            if raw is not None:
                entry = raw if isinstance(raw, dict) else {"webhook": raw}
                logger.info(
                    "dingtalk _load_session_webhook_entry hit(%s): "
                    "webhook_key=%s session_from_url=%s",
                    source,
                    webhook_key,
                    session_param_from_webhook_url(
                        entry.get("webhook", ""),
                    ),
                )
                return entry

            logger.info(
                "dingtalk _load_session_webhook_entry miss: webhook_key=%s",
                webhook_key,
            )
            return None

    @staticmethod
    def _resolve_open_api_params(
        meta: Dict[str, Any],
        webhook_entry: Optional[Dict[str, Any]],
    ) -> Dict[str, str]:
        """Extract conversation_id / conversation_type / sender_staff_id.

        Merges values from *meta* (higher priority) and *webhook_entry*
        (lower priority) so that callers don't repeat the same pattern.
        """
        entry = webhook_entry or {}
        return {
            "conversation_id": (
                meta.get("conversation_id", "")
                or entry.get("conversation_id", "")
            ),
            "conversation_type": (
                meta.get("conversation_type", "")
                or entry.get("conversation_type", "")
            ),
            "sender_staff_id": (
                meta.get("sender_staff_id", "")
                or entry.get("sender_staff_id", "")
            ),
        }

    # ---------------------------
    # Reply via stream thread
    # ---------------------------

    def _try_accept_message(self, msg_id: str) -> bool:
        """Return True if accepted; False if duplicate (msg_id already in
        progress). Thread-safe; handler in stream thread.
        """
        with self._processing_message_ids_lock:
            if msg_id and msg_id in self._processing_message_ids:
                logger.info(
                    "dingtalk dedup reject: msg_id already in progress "
                    "msg_id=%r",
                    msg_id,
                )
                return False
            if msg_id:
                self._processing_message_ids.add(msg_id)
            logger.debug(
                "dingtalk dedup accept: msg_id=%r in_flight_count=%s",
                msg_id or "(empty)",
                len(self._processing_message_ids),
            )
            return True

    def _release_message_ids(self, msg_ids: List[str]) -> None:
        """Release msg ids after reply."""
        if not msg_ids:
            return
        with self._processing_message_ids_lock:
            for mid in msg_ids:
                if mid:
                    self._processing_message_ids.discard(mid)
            logger.debug(
                "dingtalk dedup release: msg_ids=%s in_flight_count=%s",
                msg_ids,
                len(self._processing_message_ids),
            )

    def _get_session_webhook(
        self,
        meta: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Get sessionWebhook from meta."""
        if not meta:
            return None
        return meta.get("session_webhook") or meta.get("sessionWebhook")

    def _parts_to_single_text(
        self,
        parts: List[OutgoingContentPart],
        bot_prefix: str = "",
    ) -> str:
        """
        Build one reply text from parts.
        """
        text_parts: List[str] = []
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
        body = "\n".join(text_parts) if text_parts else ""
        if bot_prefix and body:
            body = bot_prefix + "  " + body
        return body

    async def _send_payload_via_session_webhook(
        self,
        session_webhook: str,
        payload: Dict[str, Any],
    ) -> bool:
        """Send one message via DingTalk sessionWebhook with given JSON
        payload (e.g. msgtype text, markdown, image, file). Returns True
        on success.
        """
        msgtype = payload.get("msgtype", "?")
        session_in_url = session_param_from_webhook_url(session_webhook)
        wh = (
            session_webhook[:60] + "..."
            if len(session_webhook) > 60
            else session_webhook
        )
        logger.info(
            "dingtalk sessionWebhook send: msgtype=%s webhook_host=%s "
            "session_from_url=%s",
            msgtype,
            wh,
            session_in_url,
        )
        logger.debug("dingtalk sessionWebhook send: payload=%s", payload)
        try:
            async with self._http.post(
                session_webhook,
                json=payload,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                },
            ) as resp:
                body_text = await resp.text()
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk sessionWebhook POST failed: msgtype=%s "
                        "status=%s body=%s",
                        msgtype,
                        resp.status,
                        body_text[:500],
                    )
                    return False
                try:
                    body_json = json.loads(body_text) if body_text else {}
                except json.JSONDecodeError:
                    body_json = {}
                errcode = body_json.get("errcode", 0)
                errmsg = body_json.get("errmsg", "")
                if errcode != 0:
                    logger.warning(
                        "dingtalk sessionWebhook POST API error: msgtype=%s "
                        "session_from_url=%s errcode=%s errmsg=%s body=%s",
                        msgtype,
                        session_in_url,
                        errcode,
                        errmsg,
                        body_text[:300],
                    )
                    return False
                logger.info(
                    "dingtalk sessionWebhook POST ok: msgtype=%s status=%s "
                    "errcode=%s",
                    msgtype,
                    resp.status,
                    errcode,
                )
                return True
        except Exception:
            logger.exception(
                f"dingtalk sessionWebhook POST failed: msgtype={msgtype}",
            )
            return False

    async def _send_via_session_webhook(
        self,
        session_webhook: str,
        body: str,
        bot_prefix: str = "",
        at_user_ids: Optional[List[str]] = None,
        at_dingtalk_ids: Optional[List[str]] = None,
    ) -> bool:
        """Send one text message via DingTalk sessionWebhook. Returns True
        on success.

        When ``at_user_ids`` or ``at_dingtalk_ids`` is provided, the
        ``at`` field is added to the webhook payload so that the
        mentioned users receive a push notification.  The @mention text
        is also prepended to the message body (DingTalk requires both).
        """
        text = (bot_prefix + "  " + body) if body else bot_prefix

        # Build at payload and prepend @mention text
        at_payload: Optional[Dict[str, Any]] = None
        if at_user_ids or at_dingtalk_ids:
            at_payload = {}
            mentions = []
            if at_user_ids:
                at_payload["atUserIds"] = at_user_ids
                mentions.extend(f"@{uid}" for uid in at_user_ids)
            if at_dingtalk_ids:
                at_payload["atDingtalkIds"] = at_dingtalk_ids
                mentions.extend(f"@{did}" for did in at_dingtalk_ids)
            text = " ".join(mentions) + "\n" + text

        if len(text) > 3500:
            payload: Dict[str, Any] = {
                "msgtype": "text",
                "text": {"content": text},
            }
        else:
            norm = dingtalk_markdown.normalize_dingtalk_markdown(text)
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"💬{norm[:10]}...",
                    "text": norm,
                },
            }

        if at_payload:
            payload["at"] = at_payload

        return await self._send_payload_via_session_webhook(
            session_webhook,
            payload,
        )

    async def _send_via_open_api(
        self,
        body: str,
        conversation_id: str,
        conversation_type: str,
        sender_staff_id: str,
        bot_prefix: str = "",
    ) -> bool:
        """Send message via DingTalk Open API as fallback when sessionWebhook
        is expired or unavailable.

        Uses robot_1_0 SDK:
        - org_group_send for groups
        - batch_send_oto for DMs
        """
        text = (bot_prefix + "  " + body) if body else bot_prefix
        is_group = conversation_type == "group"

        logger.info(
            "dingtalk _send_via_open_api: is_group=%s conversation_id=%s "
            "sender_staff_id=%s text_len=%s",
            is_group,
            conversation_id,
            sender_staff_id,
            len(text),
        )

        if len(text) > 3500:
            msg_key = "sampleText"
            msg_param = json.dumps({"content": text})
        else:
            norm = dingtalk_markdown.normalize_dingtalk_markdown(text)
            msg_key = "sampleMarkdown"
            msg_param = json.dumps({"title": f"💬{norm[:10]}...", "text": norm})

        return await self._send_robot_message(
            msg_key=msg_key,
            msg_param=msg_param,
            conversation_id=conversation_id,
            is_group=is_group,
            sender_staff_id=sender_staff_id,
            caller="_send_via_open_api",
        )

    async def _try_open_api_fallback(
        self,
        text: str,
        to_handle: str,
        meta: Optional[Dict[str, Any]],
    ) -> bool:
        """Try sending text via Open API using metadata from meta or store.

        Used when sessionWebhook is expired or send failed during
        cron agent task streaming (send_content_parts path).
        Returns True if Open API succeeded, False otherwise.
        """
        m = meta or {}
        webhook_entry: Optional[Dict[str, Any]] = None
        route = self._route_from_handle(to_handle)
        webhook_key = route.get("webhook_key")
        if webhook_key:
            async with self._session_webhook_lock:
                raw = self._session_webhook_store.get(webhook_key)
                if raw is None:
                    self._load_session_webhook_store_from_disk()
                    raw = self._session_webhook_store.get(webhook_key)
                if raw is not None:
                    webhook_entry = (
                        raw if isinstance(raw, dict) else {"webhook": raw}
                    )

        params = self._resolve_open_api_params(m, webhook_entry)

        if not params["conversation_id"]:
            logger.warning(
                "dingtalk _try_open_api_fallback: no conversation_id, skip",
            )
            return False

        return await self._send_via_open_api(
            text,
            conversation_id=params["conversation_id"],
            conversation_type=params["conversation_type"],
            sender_staff_id=params["sender_staff_id"],
            bot_prefix="",
        )

    async def _resolve_open_api_params_from_handle(
        self,
        to_handle: str,
        meta: Optional[Dict[str, Any]],
    ) -> Dict[str, str]:
        """Resolve Open API params from to_handle and meta (async).

        Uses _load_session_webhook_entry for thread-safe access with
        locking and disk-loading fallback.
        """
        m = meta or {}
        route = self._route_from_handle(to_handle)
        webhook_key: str = route.get("webhook_key", "")
        webhook_entry = await self._load_session_webhook_entry(webhook_key)
        return self._resolve_open_api_params(m, webhook_entry)

    async def _send_media_part_via_open_api(
        self,
        part: OutgoingContentPart,
        conversation_id: str,
        conversation_type: str,
        sender_staff_id: str,
    ) -> bool:
        """Upload and send one media part via DingTalk Open API.

        Supports image (sampleImageMsg) and file (sampleFile) message
        types. Falls back to sending a text placeholder if upload fails.
        """
        ptype = getattr(part, "type", None)
        upload_type = self._map_upload_type(part)
        if upload_type is None:
            return True

        default_name = {
            "image": "image.png",
            "voice": "audio.amr",
            "video": "video.mp4",
            "file": "file.bin",
        }.get(upload_type, "file.bin")
        filename, ext = self._guess_filename_and_ext(
            part,
            default=default_name,
        )

        # Resolve URL from part attributes
        url = (
            getattr(part, "file_url", None)
            or getattr(part, "image_url", None)
            or getattr(part, "video_url", None)
            or ""
        )
        if not url and ptype == ContentType.AUDIO:
            data_attr = getattr(part, "data", None)
            if isinstance(data_attr, str) and (
                data_attr.startswith("http") or data_attr.startswith("file:")
            ):
                url = data_attr
        url = (url or "").strip() if isinstance(url, str) else ""

        # AudioContent stores URL in "data"; derive real filename/ext
        if ptype == ContentType.AUDIO:
            data_attr = getattr(part, "data", None)
            if isinstance(data_attr, str) and (
                data_attr.startswith("http") or data_attr.startswith("file:")
            ):
                try:
                    path = urlparse(data_attr).path
                    base = os.path.basename(path)
                    if base and "." in base:
                        filename = base
                        ext = base.rsplit(".", 1)[-1].lower()
                except Exception:
                    pass

        # For images with public HTTP URLs, send directly via sampleImageMsg
        if upload_type == "image" and self._is_public_http_url(url):
            return await self._send_open_api_message(
                msg_key="sampleImageMsg",
                msg_param={"photoURL": url},
                conversation_id=conversation_id,
                conversation_type=conversation_type,
                sender_staff_id=sender_staff_id,
            )

        # Load bytes from base64 or URL
        data: Optional[bytes] = None
        raw_b64 = None
        if (
            isinstance(url, str)
            and url.startswith("data:")
            and "base64," in url
        ):
            raw_b64 = url
            url = ""
        if not raw_b64:
            raw_b64 = getattr(part, "base64", None)

        if raw_b64:
            if isinstance(raw_b64, str) and raw_b64.startswith("data:"):
                data, _ = parse_data_url(raw_b64)
            else:
                data = base64.b64decode(raw_b64, validate=False)
        if not data and url:
            data = await self._fetch_bytes_from_url(url)

        if not data:
            logger.warning(
                "dingtalk _send_media_part_via_open_api: no data, type=%s",
                ptype,
            )
            return False

        # Upload to get media_id
        effective_upload_type = upload_type
        if effective_upload_type == "voice":
            effective_upload_type = "file"
        if effective_upload_type == "video" and ext not in ("mp4",):
            effective_upload_type = "file"

        media_id = await self._upload_media(
            data,
            effective_upload_type,
            filename=filename,
        )
        if not media_id:
            logger.warning(
                "dingtalk _send_media_part_via_open_api: upload failed, "
                "type=%s",
                ptype,
            )
            return False

        # Send via Open API with appropriate msgKey
        # Note: sampleImageMsg does not support mediaId, so we send as
        # sampleFile for all media types including images.
        return await self._send_open_api_message(
            msg_key="sampleFile",
            msg_param={
                "mediaId": media_id,
                "fileName": filename,
                "fileType": ext,
            },
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            sender_staff_id=sender_staff_id,
        )

    async def _send_open_api_message(
        self,
        *,
        msg_key: str,
        msg_param: Dict[str, Any],
        conversation_id: str,
        conversation_type: str,
        sender_staff_id: str,
    ) -> bool:
        """Send a single message via DingTalk Open API with given msgKey."""
        is_group = conversation_type == "group"
        return await self._send_robot_message(
            msg_key=msg_key,
            msg_param=json.dumps(msg_param),
            conversation_id=conversation_id,
            is_group=is_group,
            sender_staff_id=sender_staff_id,
            caller="_send_open_api_message",
        )

    async def _send_robot_message(
        self,
        *,
        msg_key: str,
        msg_param: str,
        conversation_id: str,
        is_group: bool,
        sender_staff_id: str,
        caller: str = "",
    ) -> bool:
        """Unified robot message sender using robot_1_0 SDK."""
        token = await self._get_access_token()
        sdk_headers_kwargs = {
            "x_acs_dingtalk_access_token": token,
        }
        runtime = tea_util_models.RuntimeOptions()
        try:
            if is_group:
                request = dingtalk_robot_models.OrgGroupSendRequest(
                    robot_code=self.robot_code,
                    open_conversation_id=conversation_id,
                    msg_key=msg_key,
                    msg_param=msg_param,
                )
                headers = dingtalk_robot_models.OrgGroupSendHeaders(
                    **sdk_headers_kwargs,
                )
                await self._robot_sdk.org_group_send_with_options_async(
                    request,
                    headers,
                    runtime,
                )
            else:
                if not sender_staff_id:
                    logger.warning(
                        "dingtalk %s: no sender_staff_id for DM, "
                        "cannot send",
                        caller,
                    )
                    return False
                request = dingtalk_robot_models.BatchSendOTORequest(
                    robot_code=self.robot_code,
                    user_ids=[sender_staff_id],
                    msg_key=msg_key,
                    msg_param=msg_param,
                )
                headers = dingtalk_robot_models.BatchSendOTOHeaders(
                    **sdk_headers_kwargs,
                )
                await self._robot_sdk.batch_send_otowith_options_async(
                    request,
                    headers,
                    runtime,
                )
            logger.info(
                "dingtalk %s ok: is_group=%s msg_key=%s",
                caller,
                is_group,
                msg_key,
            )
            return True
        except Exception:
            logger.exception(
                "dingtalk %s failed: is_group=%s msg_key=%s",
                caller,
                is_group,
                msg_key,
            )
            return False

    async def _upload_media(
        self,
        data: bytes,
        media_type: str,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        """Upload media via DingTalk Open API and return media_id."""
        logger.info(
            "dingtalk upload_media: type=%s size=%s filename=%s",
            media_type,
            len(data),
            filename or "(none)",
        )
        token = await self._get_access_token()
        # Use oapi media upload (api.dingtalk.com upload returns 404).
        # Doc:
        # https://open.dingtalk.com/document/development/upload-media-files
        url = (
            "https://oapi.dingtalk.com/media/upload"
            f"?access_token={token}&type={media_type}"
        )
        ext = "jpg" if media_type == "image" else "bin"
        name = filename or f"upload.{ext}"
        logger.info(f"dingtalk upload_media: name={name}")
        form = aiohttp.FormData()
        form.add_field(
            "media",
            data,
            filename=name,
            content_type=content_type
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream",
        )
        try:
            async with self._http.post(url, data=form) as resp:
                result = await resp.json(content_type=None)
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk upload_media failed: type=%s status=%s "
                        "body=%s",
                        media_type,
                        resp.status,
                        result,
                    )
                    return None
                errcode = result.get("errcode", 0)
                if errcode != 0:
                    logger.warning(
                        "dingtalk upload_media oapi err: type=%s errcode=%s",
                        media_type,
                        errcode,
                    )
                    return None
                media_id = (
                    result.get("media_id")
                    or result.get("mediaId")
                    or (result.get("result") or {}).get("media_id")
                    or (result.get("result") or {}).get("mediaId")
                )
                if media_id:
                    mid_preview = (
                        media_id[:32] + "..."
                        if len(media_id) > 32
                        else media_id
                    )
                    logger.info(
                        "dingtalk upload_media ok: type=%s media_id=%s",
                        media_type,
                        mid_preview,
                    )
                else:
                    logger.warning(
                        "dingtalk upload_media: no media_id in response",
                    )
                return media_id
        except Exception:
            logger.exception(
                "dingtalk upload_media failed: type=%s filename=%s",
                media_type,
                filename,
            )
            return None

    async def _fetch_bytes_from_url(self, url: str) -> Optional[bytes]:
        """Download binary content from URL. Returns None on failure.

        Supports http(s):// and file:// URLs. file:// is read from local disk.
        """
        logger.info(
            "dingtalk fetch_bytes_from_url: url=%s",
            url[:80] + "..." if len(url) > 80 else url,
        )
        try:
            path = file_url_to_local_path(url)
            if path is not None:
                data = await asyncio.to_thread(Path(path).read_bytes)
                logger.info(
                    "dingtalk fetch_bytes_from_url ok: size=%s (file)",
                    len(data),
                )
                return data
            if url.strip().lower().startswith("file:"):
                logger.warning(
                    f"dingtalk fetch_bytes_from_url: empty file path for "
                    f"url={url[:80]}",
                )
                return None
            async with self._http.get(url) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk fetch_bytes_from_url failed: status=%s",
                        resp.status,
                    )
                    return None
                data = await resp.read()
                logger.info(
                    "dingtalk fetch_bytes_from_url ok: size=%s",
                    len(data),
                )
                return data
        except Exception:
            logger.exception(
                "dingtalk fetch_bytes_from_url failed: url=%s",
                url[:80],
            )
            return None

    async def _get_session_webhook_for_send(
        self,
        to_handle: str,
        meta: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Resolve session_webhook for sending. Prefer current request's
        webhook (meta); only use store for proactive send (e.g. cron).
        When this is a reply to a user message (meta has conversation_id)
        and meta has no session_webhook, do not fall back to store so we
        never use a stale/expired webhook.
        """
        m = meta or {}
        webhook = m.get("session_webhook") or m.get("sessionWebhook")
        if webhook:
            logger.info(
                "dingtalk _get_session_webhook_for_send: to_handle=%s "
                "source=meta session_from_url=%s",
                to_handle[:40] if to_handle else "",
                session_param_from_webhook_url(webhook),
            )
            return webhook
        route = self._route_from_handle(to_handle)
        webhook = route.get("session_webhook")
        if webhook:
            logger.info(
                "dingtalk _get_session_webhook_for_send: to_handle=%s "
                "source=route session_from_url=%s",
                to_handle[:40] if to_handle else "",
                session_param_from_webhook_url(webhook),
            )
            return webhook
        # Current-request context but no webhook in meta: do not use store
        # (could be expired after long idle).
        if m.get("conversation_id"):
            logger.info(
                "dingtalk _get_session_webhook_for_send: to_handle=%s "
                "current request has no session_webhook, skip store",
                to_handle[:40] if to_handle else "",
            )
            return None
        key = route.get("webhook_key")
        if key:
            webhook = await self._load_session_webhook(key)
            if webhook:
                logger.info(
                    "dingtalk _get_session_webhook_for_send: to_handle=%s "
                    "source=store webhook_key=%s",
                    to_handle[:40] if to_handle else "",
                    key,
                )
            return webhook
        logger.info(
            "dingtalk _get_session_webhook_for_send: to_handle=%s source=none",
            to_handle[:40] if to_handle else "",
        )
        return None

    def _map_upload_type(self, part: OutgoingContentPart) -> Optional[str]:
        """
        Map OutgoingContentPart type to DingTalk media/upload type.
        DingTalk upload type must be one of: image | voice | video | file
        """
        ptype = getattr(part, "type", None)
        if ptype in (ContentType.TEXT, ContentType.REFUSAL, None):
            return None  # no upload
        if ptype == ContentType.IMAGE:
            return "image"
        if ptype == ContentType.AUDIO:
            return "voice"
        if ptype == ContentType.VIDEO:
            return "video"
        if ptype == ContentType.FILE:
            return "file"
        return "file"

    async def _send_media_part_via_webhook(
        self,
        session_webhook: str,
        part: OutgoingContentPart,
    ) -> bool:
        """Upload and send one media part via session webhook."""
        ptype = getattr(part, "type", None)
        upload_type = self._map_upload_type(part)

        logger.info(
            "dingtalk _send_media_part_via_webhook: type=%s upload_type=%s",
            ptype,
            upload_type,
        )

        # text/auto/refusal: no-op here (text is handled elsewhere)
        if upload_type is None:
            return True

        # ---------- image special-case: if public picURL, send directly ------
        if upload_type == "image":
            url = getattr(part, "image_url", None) or ""
            url = (url or "").strip() if isinstance(url, str) else ""
            if self._is_public_http_url(url):
                payload = {"msgtype": "image", "image": {"picURL": url}}
                return await self._send_payload_via_session_webhook(
                    session_webhook,
                    payload,
                )
            # else: fallthrough to upload-by-bytes then send as file
            # (your existing fallback)

        # ---------- decide filename/ext ----------
        default_name = {
            "image": "image.png",
            "voice": "audio.amr",
            "video": "video.mp4",
            "file": "file.bin",
        }.get(upload_type, "file.bin")
        filename, ext = self._guess_filename_and_ext(
            part,
            default=default_name,
        )
        # AudioContent URL is in part.data; derive filename/ext for m4a etc.
        if ptype == ContentType.AUDIO:
            data_attr = getattr(part, "data", None)
            if isinstance(data_attr, str) and (
                data_attr.startswith("http") or data_attr.startswith("file:")
            ):
                try:
                    path = urlparse(data_attr).path
                    base = os.path.basename(path)
                    if base and "." in base:
                        filename = base
                        ext = base.rsplit(".", 1)[-1].lower()
                except Exception:
                    pass
        if upload_type == "video" and ext not in ("mp4",):
            upload_type = "file"
        elif upload_type == "voice":
            upload_type = "file"

        # ---------- if already has media id ----------
        # for file you used file_id;
        # keep compatibility but also accept media_id
        media_id = (
            getattr(part, "media_id", None)
            or getattr(part, "mediaId", None)
            or getattr(part, "file_id", None)
        )
        if media_id:
            media_id = str(media_id).strip()
            if not media_id:
                return False

            if upload_type == "image":
                # sendBySession supports image by picURL;
                # but if we only have mediaId, send as file
                payload = {
                    "msgtype": "file",
                    "file": {
                        "mediaId": media_id,
                        "fileType": ext,
                        "fileName": filename,
                    },
                }
                return await self._send_payload_via_session_webhook(
                    session_webhook,
                    payload,
                )

            if upload_type == "voice":
                # sendBySession returns 400105 "unsupported msgtype" for voice.
                payload = {
                    "msgtype": "file",
                    "file": {
                        "mediaId": media_id,
                        "fileType": ext,
                        "fileName": filename,
                    },
                }
                return await self._send_payload_via_session_webhook(
                    session_webhook,
                    payload,
                )

            if upload_type == "video":
                pic_media_id = (
                    getattr(part, "pic_media_id", None)
                    or getattr(part, "picMediaId", None)
                    or ""
                )
                pic_media_id = (pic_media_id or "").strip()
                if pic_media_id:
                    duration = getattr(part, "duration", None)
                    if duration is None:
                        duration = 1
                    payload = {
                        "msgtype": "video",
                        "video": {
                            "videoMediaId": media_id,
                            "duration": str(int(duration)),
                            "picMediaId": pic_media_id,
                        },
                    }
                    return await self._send_payload_via_session_webhook(
                        session_webhook,
                        payload,
                    )
                # No picMediaId: send as file so user still gets the video
                payload = {
                    "msgtype": "file",
                    "file": {
                        "mediaId": media_id,
                        "fileType": ext,
                        "fileName": filename,
                    },
                }
                return await self._send_payload_via_session_webhook(
                    session_webhook,
                    payload,
                )

            # file
            payload = {
                "msgtype": "file",
                "file": {
                    "mediaId": media_id,
                    "fileType": ext,
                    "fileName": filename,
                },
            }
            return await self._send_payload_via_session_webhook(
                session_webhook,
                payload,
            )

        # ---------- load bytes from base64 or url ----------
        data: Optional[bytes] = None
        url = (
            getattr(part, "file_url", None)
            or getattr(part, "image_url", None)
            or getattr(part, "video_url", None)
            or ""
        )
        # AudioContent stores URL in "data" (renderer _blocks_to_parts)
        if not url and ptype == ContentType.AUDIO:
            data_attr = getattr(part, "data", None)
            if isinstance(data_attr, str) and (
                data_attr.startswith("http") or data_attr.startswith("file:")
            ):
                url = data_attr
        url = (url or "").strip() if isinstance(url, str) else ""
        raw_b64 = None
        if (
            isinstance(url, str)
            and url.startswith("data:")
            and "base64," in url
        ):
            raw_b64 = url
            url = ""
        if not raw_b64:
            raw_b64 = getattr(part, "base64", None)

        if raw_b64:
            if isinstance(raw_b64, str) and raw_b64.startswith("data:"):
                data, mime = parse_data_url(raw_b64)
                content_type_for_upload = (
                    mime or getattr(part, "mime_type", None) or ""
                ).strip()
                if mime and not getattr(part, "filename", None):
                    ext_guess = (mimetypes.guess_extension(mime) or "").lstrip(
                        ".",
                    ) or ""
                    if ext_guess:
                        filename = f"upload.{ext_guess}"
                        ext = ext_guess
            else:
                data = base64.b64decode(raw_b64, validate=False)
                content_type_for_upload = (
                    getattr(part, "mime_type", None) or ""
                ).strip()
        else:
            content_type_for_upload = (
                getattr(part, "mime_type", None) or ""
            ).strip()
        if not data and url:
            data = await self._fetch_bytes_from_url(url)

        if not data:
            logger.warning(
                "dingtalk media part: no data to upload (empty file?), "
                "type=%s",
                ptype,
            )
            return False

        # ---------- upload ----------
        media_id = await self._upload_media(
            data,
            upload_type,  # image | voice | video | file
            filename=filename,
            content_type=content_type_for_upload or None,
        )
        if not media_id:
            return False

        # ---------- send ----------
        if upload_type == "image":
            # no public url -> safest is send as file (your current behavior)
            payload = {
                "msgtype": "file",
                "file": {
                    "mediaId": media_id,
                    "fileType": ext,
                    "fileName": filename,
                },
            }
            return await self._send_payload_via_session_webhook(
                session_webhook,
                payload,
            )

        if upload_type == "voice":
            # sendBySession returns 400105 for voice; send as file.
            payload = {
                "msgtype": "file",
                "file": {
                    "mediaId": media_id,
                    "fileType": ext,
                    "fileName": filename,
                },
            }
            return await self._send_payload_via_session_webhook(
                session_webhook,
                payload,
            )

        if upload_type == "video":
            pic_media_id = (
                getattr(part, "pic_media_id", None)
                or getattr(part, "picMediaId", None)
                or ""
            ).strip()
            if pic_media_id:
                duration = getattr(part, "duration", None)
                if duration is None:
                    duration = 1
                payload = {
                    "msgtype": "video",
                    "video": {
                        "videoMediaId": media_id,
                        "duration": str(int(duration)),
                        "picMediaId": pic_media_id,
                    },
                }
                return await self._send_payload_via_session_webhook(
                    session_webhook,
                    payload,
                )
            # No picMediaId: send as file so user still gets the video
            payload = {
                "msgtype": "file",
                "file": {
                    "mediaId": media_id,
                    "fileType": ext,
                    "fileName": filename,
                },
            }
            return await self._send_payload_via_session_webhook(
                session_webhook,
                payload,
            )

        payload = {
            "msgtype": "file",
            "file": {
                "mediaId": media_id,
                "fileType": ext,
                "fileName": filename,
            },
        }
        return await self._send_payload_via_session_webhook(
            session_webhook,
            payload,
        )

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Build one body from parts and send via webhook or Open API.

        When session_webhook is available, sends text then image/file
        messages (upload media first for image/file).
        """
        if not parts:
            return
        text_parts = []
        media_parts: List[OutgoingContentPart] = []
        for p in parts:
            t = getattr(p, "type", None) or (
                p.get("type") if isinstance(p, dict) else None
            )
            text_val = getattr(p, "text", None) or (
                p.get("text") if isinstance(p, dict) else None
            )
            refusal_val = getattr(p, "refusal", None) or (
                p.get("refusal") if isinstance(p, dict) else None
            )
            if t == ContentType.TEXT and text_val:
                text_parts.append(text_val or "")
            elif t == ContentType.REFUSAL and refusal_val:
                text_parts.append(refusal_val or "")
            elif t == ContentType.IMAGE:
                media_parts.append(p)
            elif t == ContentType.FILE:
                media_parts.append(p)
            elif t == ContentType.VIDEO:
                media_parts.append(p)
            elif t == ContentType.AUDIO:
                media_parts.append(p)
        body = "\n".join(text_parts) if text_parts else ""
        prefix = (meta or {}).get("bot_prefix", "") or ""
        if prefix and body:
            body = prefix + "  " + body
        elif prefix and not body and not media_parts:
            body = prefix
        session_webhook = await self._get_session_webhook_for_send(
            to_handle,
            meta,
        )
        logger.info(
            "dingtalk send_content_parts: to_handle=%s has_webhook=%s "
            "text_parts=%s media_parts=%s",
            to_handle[:40] if to_handle else "",
            bool(session_webhook),
            len(text_parts),
            len(media_parts),
        )

        # ---------- AI Card path (cron / proactive sends) ----------
        if self._cron_ai_card_enabled() and body.strip():
            params = await self._resolve_open_api_params_from_handle(
                to_handle,
                meta,
            )
            conversation_id = params["conversation_id"]
            if conversation_id:
                card_meta = {
                    "conversation_id": conversation_id,
                    "conversation_type": params["conversation_type"],
                    "sender_staff_id": params["sender_staff_id"],
                    "is_group": params["conversation_type"] == "group",
                }
                try:
                    card = await self._create_ai_card(
                        conversation_id,
                        meta=card_meta,
                        inbound=False,
                        force=True,
                    )
                    if card:
                        await self._stream_ai_card(
                            card,
                            body.strip(),
                            finalize=True,
                        )
                        logger.info(
                            "dingtalk send_content_parts: "
                            "AI card sent ok, conversation_id=%s",
                            conversation_id,
                        )
                        # Send media parts separately via Open API
                        for i, part in enumerate(media_parts):
                            logger.info(
                                "dingtalk send_content_parts: "
                                "sending media part %s/%s via Open API "
                                "(AI card path) type=%s",
                                i + 1,
                                len(media_parts),
                                getattr(part, "type", None),
                            )
                            await self._send_media_part_via_open_api(
                                part,
                                conversation_id=conversation_id,
                                conversation_type=params["conversation_type"],
                                sender_staff_id=params["sender_staff_id"],
                            )
                        return
                except Exception:
                    logger.exception(
                        "dingtalk send_content_parts: AI card failed, "
                        "falling back to webhook/Open API",
                    )

        if session_webhook and (body.strip() or media_parts):
            text_ok = True
            if body.strip():
                logger.info("dingtalk send_content_parts: sending text body")
                text_ok = await self._send_via_session_webhook(
                    session_webhook,
                    body.strip(),
                    bot_prefix="",
                )
            if not text_ok:
                await self._invalidate_session_webhook(to_handle)
                logger.warning(
                    "dingtalk send_content_parts: webhook send failed, "
                    "trying Open API fallback",
                )
                fallback_ok = await self._try_open_api_fallback(
                    body.strip(),
                    to_handle,
                    meta,
                )
                if fallback_ok:
                    return
            for i, part in enumerate(media_parts):
                logger.info(
                    "dingtalk send_content_parts: "
                    "sending media part %s/%s type=%s",
                    i + 1,
                    len(media_parts),
                    getattr(part, "type", None),
                )
                ok = await self._send_media_part_via_webhook(
                    session_webhook,
                    part,
                )
                logger.info(
                    "dingtalk send_content_parts: media part %s result=%s",
                    i + 1,
                    ok,
                )
                if not ok:
                    # Webhook media send failed: fallback to Open API
                    logger.warning(
                        "dingtalk send_content_parts: webhook media send "
                        "failed for part %s, trying Open API fallback",
                        i + 1,
                    )
                    params = await self._resolve_open_api_params_from_handle(
                        to_handle,
                        meta,
                    )
                    if params["conversation_id"]:
                        await self._send_media_part_via_open_api(
                            part,
                            conversation_id=params["conversation_id"],
                            conversation_type=params["conversation_type"],
                            sender_staff_id=params["sender_staff_id"],
                        )
            return
        # Fallback path: no session_webhook available.
        # Try sending media parts via Open API (upload + rich message)
        # instead of degrading to plain-text file paths.
        if media_parts:
            params = await self._resolve_open_api_params_from_handle(
                to_handle,
                meta,
            )
            if params["conversation_id"]:
                # Send text body first via Open API if present
                if body.strip():
                    await self._send_via_open_api(
                        body.strip(),
                        conversation_id=params["conversation_id"],
                        conversation_type=params["conversation_type"],
                        sender_staff_id=params["sender_staff_id"],
                        bot_prefix="",
                    )
                for i, part in enumerate(media_parts):
                    logger.info(
                        "dingtalk send_content_parts: "
                        "sending media part %s/%s via Open API type=%s",
                        i + 1,
                        len(media_parts),
                        getattr(part, "type", None),
                    )
                    await self._send_media_part_via_open_api(
                        part,
                        conversation_id=params["conversation_id"],
                        conversation_type=params["conversation_type"],
                        sender_staff_id=params["sender_staff_id"],
                    )
                return
            logger.warning(
                "dingtalk send_content_parts: no webhook and no "
                "conversation_id, skipping %s media part(s)",
                len(media_parts),
            )

        await self.send(to_handle, body.strip() or prefix, meta)

    def merge_native_items(self, items: List[Any]) -> Any:
        """Merge payloads (content_parts + meta) for DingTalk."""
        return self._merge_native(items)

    def _on_debounce_buffer_append(
        self,
        key: str,
        payload: Any,
        existing_items: List[Any],
    ) -> None:
        """No-op: handler ACKs immediately, no futures to unblock."""
        del key, payload, existing_items

    def _resolve_to_handle(self, request: Any) -> str:
        """Resolve target handle from request using session-aware logic."""
        user_id = getattr(request, "user_id", "") or ""
        sid = getattr(request, "session_id", "") or ""
        if sid:
            return self.to_handle_from_target(
                user_id=user_id,
                session_id=sid,
            )
        return user_id

    async def _deliver_media_parts(
        self,
        parts: list,
        webhook: Optional[str],
        to_handle: str,
        meta: Dict[str, Any],
    ) -> None:
        """Send media parts separately.

        AI Card only carries text; images, files,
        videos and audio must be delivered via
        webhook upload or Open API.
        """
        _types = (
            ContentType.IMAGE,
            ContentType.FILE,
            ContentType.VIDEO,
            ContentType.AUDIO,
        )
        for part in parts:
            pt = getattr(part, "type", None)
            if pt not in _types:
                continue
            sent = False
            if webhook:
                sent = await self._send_media_part_via_webhook(
                    webhook,
                    part,
                )
            if not sent:
                resolver = getattr(
                    self,
                    "_resolve_open_api_params_from_handle",
                )
                params = await resolver(
                    to_handle,
                    meta,
                )
                cid = params["conversation_id"]
                if cid:
                    await self._send_media_part_via_open_api(
                        part,
                        conversation_id=cid,
                        conversation_type=params["conversation_type"],
                        sender_staff_id=params["sender_staff_id"],
                    )

    # -- Base class hook overrides -----------------------------

    def get_to_handle_from_request(self, request: "AgentRequest") -> str:
        """Use session-aware handle resolution for DingTalk."""
        return self._resolve_to_handle(request)

    # -- Streaming hooks (card mode) ---------------------------

    def _get_dingtalk_stream_state(
        self,
        send_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get or create per-request streaming state in send_meta."""
        state = send_meta.get("_dt_stream")
        if state is None:
            state = {
                "cards": {},
                "at_sent": False,
            }
            send_meta["_dt_stream"] = state
        return state

    def _build_card_at_prefix(
        self,
        send_meta: Dict[str, Any],
    ) -> str:
        """Build @mention prefix for AI card content in group chats."""
        if (
            self.at_sender_on_reply
            and send_meta.get("is_group", False)
            and send_meta.get("sender_staff_id", "")
        ):
            at_id = send_meta["sender_staff_id"]
            at_nick = send_meta.get("sender_nick", "") or at_id
            return f"<a atId={at_id}>{at_nick}</a>\n"
        return ""

    async def on_streaming_start(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Card mode: reuse pre-created card or create a new AI Card."""
        conversation_id = str(send_meta.get("conversation_id") or "")
        if not conversation_id or not self._ai_card_enabled():
            return

        state = self._get_dingtalk_stream_state(send_meta)

        # Build @mention prefix for the first card only
        at_prefix = ""
        if not state["at_sent"]:
            at_prefix = self._build_card_at_prefix(send_meta)
            state["at_sent"] = True

        try:
            # Reuse pre-created card from _before_consume_process if available
            card = getattr(request, "_precreated_card", None)
            if card:
                # Consume: first streaming segment uses pre-created card
                setattr(request, "_precreated_card", None)
            else:
                # Later segments (e.g. reasoning→message) need new card
                card = await self._create_ai_card(
                    conversation_id,
                    meta=send_meta,
                    inbound=True,
                    force=True,
                )
            if card:
                prefix = "💭 " if stream_type == "reasoning" else ""
                initial_text = f"{at_prefix}{prefix}..."
                await self._stream_ai_card(card, initial_text, finalize=False)
                state["cards"][stream_type] = {
                    "card": card,
                    "at_prefix": at_prefix,
                    "display_prefix": prefix,
                }
        except Exception:
            logger.exception(
                "dingtalk on_streaming_start: card creation failed "
                "stream_type=%s",
                stream_type,
            )
            state["cards"].pop(stream_type, None)

    async def on_streaming_delta(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Card mode: stream incremental text to the AI Card."""
        state = send_meta.get("_dt_stream")
        if not state:
            return
        card_info = state["cards"].get(stream_type)
        if not card_info:
            return

        card = card_info["card"]
        at_prefix = card_info["at_prefix"]
        display_prefix = card_info["display_prefix"]
        display_text = f"{at_prefix}{display_prefix}{accumulated_text}"

        try:
            await self._stream_ai_card(card, display_text, finalize=False)
        except Exception:
            logger.debug(
                "dingtalk on_streaming_delta: card update failed "
                "stream_type=%s",
                stream_type,
            )

    async def on_streaming_end(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
        stream_type: str,
        accumulated_text: str = "",
    ) -> None:
        """Card mode: finalize the AI Card for this segment."""
        state = send_meta.get("_dt_stream")
        if not state:
            return
        card_info = state["cards"].pop(stream_type, None)
        if not card_info:
            return

        card = card_info["card"]
        at_prefix = card_info["at_prefix"]
        display_prefix = card_info["display_prefix"]
        final_text = f"{at_prefix}{display_prefix}{accumulated_text}"

        try:
            await self._stream_ai_card(card, final_text, finalize=True)
        except Exception:
            logger.exception(
                "dingtalk on_streaming_end: card finalize failed "
                "stream_type=%s",
                stream_type,
            )
            await self._mark_card_failed(
                str(send_meta.get("conversation_id") or ""),
            )

        # Deliver media parts separately (card only carries text)
        if stream_type == "message":
            parts = self._message_to_content_parts(event)
            session_webhook = self._get_session_webhook(send_meta)
            await self._deliver_media_parts(
                parts,
                session_webhook,
                to_handle,
                send_meta,
            )

    # -- Non-streaming message handler (markdown mode) ---------

    async def on_event_message_completed(
        self,
        request: "AgentRequest",
        to_handle: str,
        event: Any,
        send_meta: Dict[str, Any],
    ) -> None:
        """Send completed message via AI Card or sessionWebhook.

        Card mode (non-streaming): accumulate text into a single pre-created
        card. The card is finalized in _on_process_completed after all messages
        are processed.
        Markdown mode: send via sessionWebhook or fallback to send().
        """
        parts = self._message_to_content_parts(event)
        if not parts:
            return

        bot_prefix = self.bot_prefix or ""
        body = self._parts_to_single_text(parts, bot_prefix=bot_prefix)
        conversation_id = str(send_meta.get("conversation_id") or "")
        session_webhook = self._get_session_webhook(send_meta)

        # -- Card mode: accumulate text into pre-created card (no finalize) --
        if self._ai_card_enabled() and conversation_id and body.strip():
            state = self._get_dingtalk_stream_state(send_meta)
            at_prefix = ""
            if not state["at_sent"]:
                at_prefix = self._build_card_at_prefix(send_meta)
                state["at_sent"] = True

            # Get or initialize the active card for this request
            card = state.get("nonstream_card")
            if not card:
                card = getattr(request, "_precreated_card", None)
                if card:
                    setattr(request, "_precreated_card", None)
                else:
                    try:
                        card = await self._create_ai_card(
                            conversation_id,
                            meta=send_meta,
                            inbound=True,
                        )
                    except Exception:
                        logger.exception(
                            "dingtalk on_event_message_completed: "
                            "card creation failed, fallback to markdown",
                        )
                        await self._mark_card_failed(conversation_id)
                        card = None
                if card:
                    state["nonstream_card"] = card
                    state["card_full_text"] = ""
                    state["card_at_prefix"] = at_prefix

            if card:
                # Accumulate text
                prev_text = state.get("card_full_text") or ""
                new_body = body.strip()
                if prev_text and new_body:
                    merged = f"{prev_text}\n{new_body}"
                else:
                    merged = new_body or prev_text
                state["card_full_text"] = merged

                # Stream update (not finalize) so user sees progress
                card_at = state.get("card_at_prefix") or ""
                try:
                    await self._stream_ai_card(
                        card,
                        card_at + merged,
                        finalize=False,
                    )
                except Exception:
                    logger.exception(
                        "dingtalk on_event_message_completed: "
                        "card stream failed, fallback to markdown",
                    )
                    await self._mark_card_failed(conversation_id)
                    state.pop("nonstream_card", None)
                    # Fall through to markdown mode below
                else:
                    # Deliver media parts separately (card only carries text)
                    await self._deliver_media_parts(
                        parts,
                        session_webhook,
                        to_handle,
                        send_meta,
                    )
                    return

        # -- Markdown mode: send via webhook --
        if session_webhook and body.strip():
            at_uids = None
            at_dids = None
            is_group = send_meta.get("is_group", False)
            state = self._get_dingtalk_stream_state(send_meta)
            if self.at_sender_on_reply and not state["at_sent"] and is_group:
                staff_id = send_meta.get("sender_staff_id", "")
                dingtalk_id = send_meta.get("sender_dingtalk_id", "")
                if staff_id:
                    at_uids = [staff_id]
                elif dingtalk_id:
                    at_dids = [dingtalk_id]
                state["at_sent"] = True
            await self._send_via_session_webhook(
                session_webhook,
                body.strip(),
                bot_prefix="",
                at_user_ids=at_uids,
                at_dingtalk_ids=at_dids,
            )
            # Deliver media parts via webhook
            media_types = (
                ContentType.IMAGE,
                ContentType.FILE,
                ContentType.VIDEO,
                ContentType.AUDIO,
            )
            for part in parts:
                if getattr(part, "type", None) in media_types:
                    await self._send_media_part_via_webhook(
                        session_webhook,
                        part,
                    )
        elif body.strip() or parts:
            await self.send_content_parts(to_handle, parts, send_meta)

    # -- Native payload merging --------------------------------

    def _merge_native(self, items: list) -> dict:
        """Merge multiple native payloads into one (content_parts + meta)."""
        if not items:
            return {}
        first = items[0] if isinstance(items[0], dict) else {}
        merged_parts: List[Any] = []
        merged_meta: Dict[str, Any] = dict(first.get("meta") or {})

        message_ids_list: List[str] = []
        for it in items:
            payload = it if isinstance(it, dict) else {}
            merged_parts.extend(payload.get("content_parts") or [])
            m = payload.get("meta") or {}
            for k in (
                "conversation_id",
                "session_webhook",
                "session_webhook_expired_time",
                "conversation_type",
                "sender_staff_id",
            ):
                if k in m:
                    merged_meta[k] = m[k]
            mid = m.get("message_id") or payload.get("message_id")
            if mid:
                message_ids_list.append(str(mid))

        merged_meta["batched_count"] = len(items)
        merged_meta["_message_ids"] = message_ids_list
        # Queue is FIFO: batch = [oldest, ..., newest]. Prefer
        # session_webhook (and related metadata) from newest item so send
        # uses current session.
        out_sw: Optional[str] = None
        for it in reversed(items):
            pl = it if isinstance(it, dict) else {}
            sw = pl.get("session_webhook") or (pl.get("meta") or {}).get(
                "session_webhook",
            )
            if sw:
                out_sw = sw
                break
        out = {
            "channel_id": first.get("channel_id") or self.channel,
            "sender_id": first.get("sender_id") or "",
            "content_parts": merged_parts,
            "meta": merged_meta,
        }
        if out_sw:
            out["session_webhook"] = out_sw
            merged_meta["session_webhook"] = out_sw
        return out

    def _run_stream_forever(self) -> None:
        """Run stream loop; on _stop_event close websocket and exit cleanly."""
        logger.info(
            "dingtalk stream thread started (client_id=%s)",
            self.client_id,
        )
        try:
            if self._client:
                asyncio.run(self._stream_loop())
        except Exception:
            logger.exception("dingtalk stream thread failed")
        finally:
            self._stop_event.set()
            logger.info("dingtalk stream thread stopped")

    async def _stream_loop(self) -> None:
        """
        Drive DingTalkStreamClient.start() and stop when _stop_event is set.
        Closes client.websocket and cancels tasks to avoid "Task was destroyed
        but it is pending" on process exit.
        """
        client = self._client
        if not client:
            return
        main_task = asyncio.create_task(client.start())

        async def stop_watcher() -> None:
            while not self._stop_event.is_set():
                await asyncio.sleep(0.5)
            if client.websocket is not None:
                try:
                    await client.websocket.close()
                except Exception:
                    pass
            while not main_task.done():
                main_task.cancel()
                await asyncio.sleep(0.1)

        watcher_task = asyncio.create_task(stop_watcher())
        try:
            await main_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("dingtalk stream start() failed")
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
        # Cancel remaining tasks (e.g. background_task) so loop exits cleanly
        loop = asyncio.get_running_loop()
        pending = [
            t
            for t in asyncio.all_tasks(loop)
            if t is not asyncio.current_task() and not t.done()
        ]
        for t in pending:
            t.cancel()
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=4.0,
                )
            except asyncio.TimeoutError:
                pass

    async def health_check(self) -> Dict[str, Any]:
        """Check DingTalk stream client and HTTP session status."""
        if not self.enabled:
            return {
                "channel": self.channel,
                "status": "disabled",
                "detail": "DingTalk channel is disabled.",
            }
        issues = []
        if self._client is None:
            issues.append("Stream client not initialized")
        if self._http is None or self._http.closed:
            issues.append("HTTP session not available")
        if issues:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "; ".join(issues),
            }
        return {
            "channel": self.channel,
            "status": "healthy",
            "detail": "DingTalk stream client and HTTP session are active.",
        }

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("disabled by env DINGTALK_CHANNEL_ENABLED=0")
            return
        self._load_session_webhook_store_from_disk()
        if not self.client_id or not self.client_secret:
            raise ChannelError(
                channel_name="dingtalk",
                message=(
                    "DINGTALK_CLIENT_ID and DINGTALK_CLIENT_SECRET "
                    "are required when channel is enabled"
                ),
            )

        self._loop = asyncio.get_running_loop()

        credential = dingtalk_stream.Credential(
            self.client_id,
            self.client_secret,
        )
        self._client = dingtalk_stream.DingTalkStreamClient(credential)
        enqueue_cb = getattr(self, "_enqueue", None)
        internal_handler = DingTalkChannelHandler(
            main_loop=self._loop,
            enqueue_callback=enqueue_cb,
            bot_prefix=self.bot_prefix,
            download_url_fetcher=self._fetch_and_download_media,
            try_accept_message=self._try_accept_message,
            check_allowlist=self._check_allowlist,
            require_mention=self.require_mention,
        )
        self._client.register_callback_handler(
            ChatbotMessage.TOPIC,
            internal_handler,
        )

        self._stop_event.clear()
        self._stream_thread = threading.Thread(
            target=self._run_stream_forever,
            daemon=True,
        )
        self._stream_thread.start()
        if self._http is None:
            self._http = aiohttp.ClientSession()

        # Initialize DingTalk OpenAPI SDK clients
        sdk_config = open_api_models.Config()
        sdk_config.protocol = "https"
        sdk_config.region_id = "central"
        self._oauth_sdk = dingtalk_oauth_client.Client(sdk_config)
        self._robot_sdk = dingtalk_robot_client.Client(sdk_config)
        self._card_sdk = dingtalk_card_client.Client(sdk_config)

        await self._recover_active_cards()

    async def stop(self) -> None:
        if not self.enabled:
            return
        self._stop_event.set()
        if self._stream_thread:
            self._stream_thread.join(timeout=3)
        for task in self._debounce_timers.values():
            if task and not task.done():
                task.cancel()
        if self._debounce_timers:
            await asyncio.gather(
                *self._debounce_timers.values(),
                return_exceptions=True,
            )
        self._debounce_timers.clear()
        self._debounce_pending.clear()
        # best-effort finalize active cards before stopping
        for conv_id in list(self._active_cards.keys()):
            try:
                card = self._active_cards.get(conv_id)
                if card and card.state not in (FINISHED, FAILED):
                    await self._stream_ai_card(
                        card,
                        card.last_streamed_content
                        or AI_CARD_RECOVERY_FINAL_TEXT,
                        finalize=True,
                    )
            except Exception:
                logger.debug(
                    "dingtalk finalize active card on stop failed",
                    exc_info=True,
                )
        if self._http is not None:
            await self._http.close()
            self._http = None
        self._client = None
        self._oauth_sdk = None
        self._robot_sdk = None
        self._card_sdk = None

    async def _on_process_completed(
        self,
        request: Any,
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Finalize card, recall 'processing' reaction, release dedup."""
        incoming_msg_id = str((send_meta or {}).get("message_id") or "")
        conversation_id = str((send_meta or {}).get("conversation_id") or "")

        # Finalize non-streaming card if accumulated text exists
        state = (send_meta or {}).get("_dt_stream")
        if state:
            card = state.get("nonstream_card")
            if card:
                card_text = (
                    state.get("card_full_text")
                    or self._build_ai_card_initial_text()
                )
                card_at = state.get("card_at_prefix") or ""
                try:
                    await self._stream_ai_card(
                        card,
                        card_at + card_text,
                        finalize=True,
                    )
                except Exception:
                    logger.exception(
                        "dingtalk _on_process_completed: "
                        "card finalize failed",
                    )
                    await self._mark_card_failed(conversation_id)
                state.pop("nonstream_card", None)

        # Also finalize any unused pre-created card (e.g. no messages produced)
        unused_card = getattr(request, "_precreated_card", None)
        if unused_card:
            setattr(request, "_precreated_card", None)
            try:
                await self._stream_ai_card(
                    unused_card,
                    self._build_ai_card_initial_text(),
                    finalize=True,
                )
            except Exception:
                logger.debug(
                    "dingtalk _on_process_completed: "
                    "unused card finalize failed",
                    exc_info=True,
                )

        if incoming_msg_id and conversation_id:
            await self._send_emotion(
                incoming_msg_id,
                conversation_id,
                "🤔Thinking",
                recall=True,
            )
            await self._send_emotion(
                incoming_msg_id,
                conversation_id,
                "🥳Done",
            )
        # Release dedup msg_id so future messages with same id are accepted
        msg_ids = (send_meta or {}).get("_message_ids")
        if msg_ids is None:
            msg_ids = [incoming_msg_id] if incoming_msg_id else []
        self._release_message_ids(msg_ids)

    def _ai_card_enabled(self) -> bool:
        return (
            self.message_type == "card"
            and bool(self.card_template_id)
            and bool(self.robot_code)
        )

    def _cron_ai_card_enabled(self) -> bool:
        """Check if AI Card is enabled for cron/proactive sends."""
        return (
            self.cron_message_type == "card"
            and bool(self.card_template_id)
            and bool(self.robot_code)
        )

    # ---- Emotion reaction helpers ----

    async def _send_emotion(
        self,
        open_msg_id: str,
        open_conversation_id: str,
        emoji_name: str,
        *,
        recall: bool = False,
    ) -> None:
        """Add or recall an emoji reaction on a message.

        Args:
            open_msg_id: Target message ID.
            open_conversation_id: Conversation ID.
            emoji_name: Display name (e.g. "🤔Thinking", "🥳Done").
            recall: If True, recall the reaction instead of adding it.
        """
        if not self._robot_sdk or not open_msg_id or not open_conversation_id:
            return
        action = "recall" if recall else "reply"
        try:
            token = await self._get_access_token()
            emotion_kwargs = {
                "robot_code": self.robot_code,
                "open_msg_id": open_msg_id,
                "open_conversation_id": open_conversation_id,
                "emotion_type": 2,
                "emotion_name": emoji_name,
            }
            runtime = tea_util_models.RuntimeOptions()
            if recall:
                emotion_kwargs[
                    "text_emotion"
                ] = dingtalk_robot_models.RobotRecallEmotionRequestTextEmotion(
                    emotion_id="2659900",
                    emotion_name=emoji_name,
                    text=emoji_name,
                    background_id="im_bg_1",
                )
                request = dingtalk_robot_models.RobotRecallEmotionRequest(
                    **emotion_kwargs,
                )
                sdk_headers = dingtalk_robot_models.RobotRecallEmotionHeaders(
                    x_acs_dingtalk_access_token=token,
                )
                await self._robot_sdk.robot_recall_emotion_with_options_async(
                    request,
                    sdk_headers,
                    runtime,
                )
            else:
                emotion_kwargs[
                    "text_emotion"
                ] = dingtalk_robot_models.RobotReplyEmotionRequestTextEmotion(
                    emotion_id="2659900",
                    emotion_name=emoji_name,
                    text=emoji_name,
                    background_id="im_bg_1",
                )
                request = dingtalk_robot_models.RobotReplyEmotionRequest(
                    **emotion_kwargs,
                )
                sdk_headers = dingtalk_robot_models.RobotReplyEmotionHeaders(
                    x_acs_dingtalk_access_token=token,
                )
                await self._robot_sdk.robot_reply_emotion_with_options_async(
                    request,
                    sdk_headers,
                    runtime,
                )
            logger.info(
                "dingtalk _send_emotion: %s %s on msg=%s",
                action,
                emoji_name,
                open_msg_id[:24] if open_msg_id else "",
            )
        except Exception:
            logger.debug(
                "dingtalk _send_emotion %s failed",
                action,
                exc_info=True,
            )

    def _build_ai_card_initial_text(self) -> str:
        return self.bot_prefix + AI_CARD_PROCESSING_TEXT

    async def _save_active_cards(self) -> None:
        async with self._active_cards_lock:
            self._card_store.save(self._active_cards)

    async def _mark_card_failed(self, conversation_id: str) -> None:
        async with self._active_cards_lock:
            card = self._active_cards.get(conversation_id)
            if card:
                card.state = FAILED
                card.last_updated = int(time.time() * 1000)
                self._active_cards.pop(conversation_id, None)
            self._card_store.save(self._active_cards)

    async def _create_ai_card(
        self,
        conversation_id: str,
        meta: Optional[Dict[str, Any]] = None,
        inbound: bool = True,
        force: bool = False,
    ) -> Optional[ActiveAICard]:
        if self._card_sdk is None or (
            not force and not self._ai_card_enabled()
        ):
            logger.warning(
                "dingtalk create ai card skipped: enabled=%s sdk_ready=%s "
                "message_type=%s has_template=%s has_robot=%s force=%s",
                self._ai_card_enabled(),
                self._card_sdk is not None,
                self.message_type,
                bool(self.card_template_id),
                bool(self.robot_code),
                force,
            )
            return None
        token = await self._get_access_token()
        card_instance_id = f"card_{uuid4()}"
        meta = meta or {}
        sender_staff_id = meta.get("sender_staff_id") or ""
        is_group = bool(meta.get("is_group"))
        card_param_map: Dict[str, str] = {self.card_template_key: ""}
        if self.card_auto_layout:
            card_param_map["config"] = json.dumps({"autoLayout": True})

        sdk_headers = dingtalk_card_models.CreateCardHeaders(
            x_acs_dingtalk_access_token=token,
        )
        runtime = tea_util_models.RuntimeOptions()

        # Resolve @mention for AI card in group chat.
        # card_at_user_ids on CreateCardRequest accepts List[str] of
        # enterprise userId (senderStaffId).  Only set when available.
        card_at_user_ids: Optional[List[str]] = None
        card_user_id_type: Optional[int] = None
        if self.at_sender_on_reply and is_group and sender_staff_id:
            card_at_user_ids = [sender_staff_id]
            card_user_id_type = 1

        create_request = dingtalk_card_models.CreateCardRequest(
            card_template_id=self.card_template_id,
            out_track_id=card_instance_id,
            card_data=dingtalk_card_models.CreateCardRequestCardData(
                card_param_map=card_param_map,
            ),
            callback_type="STREAM",
            im_group_open_space_model=(
                dingtalk_card_models.CreateCardRequestImGroupOpenSpaceModel(
                    support_forward=True,
                )
            ),
            im_robot_open_space_model=(
                dingtalk_card_models.CreateCardRequestImRobotOpenSpaceModel(
                    support_forward=True,
                )
            ),
            card_at_user_ids=card_at_user_ids,
            user_id_type=card_user_id_type,
        )

        logger.info(
            "dingtalk create ai card: conversation_id=%s is_group=%s "
            "sender_staff_id=%s template_id=%s inbound=%s",
            conversation_id,
            is_group,
            sender_staff_id,
            self.card_template_id,
            inbound,
        )
        try:
            await self._card_sdk.create_card_with_options_async(
                create_request,
                sdk_headers,
                runtime,
            )
        except Exception as exc:
            raise ChannelError(
                channel_name="dingtalk",
                message=f"create ai card failed: {exc}",
            ) from exc

        if is_group:
            open_space_id = f"dtv1.card//IM_GROUP.{conversation_id}"
            deliver_request = dingtalk_card_models.DeliverCardRequest(
                out_track_id=card_instance_id,
                user_id_type=1,
                open_space_id=open_space_id,
                im_group_open_deliver_model=(
                    _GroupDeliverModel(
                        robot_code=self.robot_code,
                    )
                ),
            )
        else:
            if not sender_staff_id:
                raise ChannelError(
                    channel_name="dingtalk",
                    message=(
                        "create ai card failed: "
                        "missing sender_staff_id for IM_ROBOT"
                    ),
                )
            open_space_id = f"dtv1.card//IM_ROBOT.{sender_staff_id}"
            deliver_request = dingtalk_card_models.DeliverCardRequest(
                out_track_id=card_instance_id,
                user_id_type=1,
                open_space_id=open_space_id,
                im_robot_open_deliver_model=(
                    _RobotDeliverModel(
                        space_type="IM_ROBOT",
                    )
                ),
            )

        deliver_headers = dingtalk_card_models.DeliverCardHeaders(
            x_acs_dingtalk_access_token=token,
        )
        logger.info(
            "dingtalk deliver ai card: conversation_id=%s open_space_id=%s",
            conversation_id,
            open_space_id,
        )
        try:
            deliver_response = (
                await self._card_sdk.deliver_card_with_options_async(
                    deliver_request,
                    deliver_headers,
                    runtime,
                )
            )
        except Exception as exc:
            raise ChannelError(
                channel_name="dingtalk",
                message=f"deliver ai card failed: {exc}",
            ) from exc

        deliver_body = deliver_response.body if deliver_response else None
        if deliver_body:
            result = getattr(
                deliver_body,
                "result",
                None,
            )
            deliver_results = (
                getattr(result, "deliver_results", None) if result else None
            )
            if isinstance(deliver_results, list):
                failed = [
                    item
                    for item in deliver_results
                    if not getattr(
                        item,
                        "success",
                        False,
                    )
                ]
                if failed:
                    err = failed[0]
                    raise ChannelError(
                        channel_name="dingtalk",
                        message=(
                            "deliver ai card failed:"
                            f" spaceId="
                            f"{getattr(err, 'space_id', None)}"
                            f" spaceType="
                            f"{getattr(err, 'space_type', None)}"
                            f" errorMsg="
                            f"{getattr(err, 'error_msg', None)}"
                        ),
                    )

        logger.info(
            "dingtalk create ai card ok:"
            " conversation_id=%s card_instance_id=%s",
            conversation_id,
            card_instance_id,
        )

        now_ms = int(time.time() * 1000)
        card = ActiveAICard(
            card_instance_id=card_instance_id,
            access_token=token,
            conversation_id=conversation_id,
            account_id="default",
            store_path=str(self._card_store.path),
            created_at=now_ms,
            last_updated=now_ms,
            state=PROCESSING,
            last_streamed_content="",
        )
        async with self._active_cards_lock:
            self._active_cards[conversation_id] = card
            if inbound:
                self._card_store.save(self._active_cards)
        return card

    async def _stream_ai_card(
        self,
        card: ActiveAICard,
        content: str,
        finalize: bool = False,
    ) -> bool:
        if self._card_sdk is None or card.state in (FINISHED, FAILED):
            return False

        content = (content or "").strip()
        if not content:
            return False

        now_ms = int(time.time() * 1000)
        if not finalize:
            if content == (card.last_streamed_content or "").strip():
                return False
            if (
                card.last_updated
                and (now_ms - card.last_updated)
                < AI_CARD_STREAM_MIN_INTERVAL_SECONDS * 1000
            ):
                return False

        if (
            now_ms - card.created_at
        ) > AI_CARD_TOKEN_PREEMPTIVE_REFRESH_SECONDS * 1000:
            card.access_token = await self._get_access_token()

        request = dingtalk_card_models.StreamingUpdateRequest(
            out_track_id=card.card_instance_id,
            guid=str(uuid4()),
            key=self.card_template_key,
            content=content,
            is_full=True,
            is_finalize=finalize,
            is_error=False,
        )

        async def _do_stream(token: str):
            sdk_headers = dingtalk_card_models.StreamingUpdateHeaders(
                x_acs_dingtalk_access_token=token,
            )
            runtime = tea_util_models.RuntimeOptions()
            logger.debug(
                "dingtalk stream ai card: conversation_id=%s finalize=%s "
                "content_len=%s",
                card.conversation_id,
                finalize,
                len(content),
            )
            await self._card_sdk.streaming_update_with_options_async(
                request,
                sdk_headers,
                runtime,
            )

        try:
            await _do_stream(card.access_token)
        except Exception as first_exc:
            is_unauthorized = (
                isinstance(first_exc, TeaException)
                and getattr(first_exc, "statusCode", None) == 401
            )
            error_msg = str(first_exc)
            if is_unauthorized:
                card.access_token = await self._get_access_token()
                try:
                    await _do_stream(card.access_token)
                except Exception as retry_exc:
                    retry_msg = str(retry_exc)
                    if "unknownError" in retry_msg:
                        raise ChannelError(
                            channel_name="dingtalk",
                            message=(
                                "dingtalk ai card unknownError: "
                                "card_template_key mismatch?"
                            ),
                        ) from retry_exc
                    raise ChannelError(
                        channel_name="dingtalk",
                        message=f"stream ai card failed: {retry_exc}",
                    ) from retry_exc
            elif "unknownError" in error_msg:
                raise ChannelError(
                    channel_name="dingtalk",
                    message=(
                        "dingtalk ai card unknownError: "
                        "card_template_key mismatch?"
                    ),
                ) from first_exc
            else:
                raise ChannelError(
                    channel_name="dingtalk",
                    message=f"stream ai card failed: {first_exc}",
                ) from first_exc

        logger.debug(
            "dingtalk stream ai card ok: conversation_id=%s finalize=%s",
            card.conversation_id,
            finalize,
        )

        card.last_streamed_content = content
        card.last_updated = int(time.time() * 1000)
        if finalize:
            card.state = FINISHED
            async with self._active_cards_lock:
                self._active_cards.pop(card.conversation_id, None)
                self._card_store.save(self._active_cards)
        elif card.state == PROCESSING:
            card.state = INPUTING
            await self._save_active_cards()
        return True

    async def _recover_active_cards(self) -> None:
        if not self._ai_card_enabled() or self._card_sdk is None:
            return
        records = self._card_store.load()
        if not records:
            return
        token = await self._get_access_token()
        for item in records:
            state = str(item.get("state") or "")
            if state in (FINISHED, FAILED):
                continue
            conversation_id = item.get("conversation_id") or ""
            card_id = item.get("card_instance_id") or f"card_{uuid4()}"
            if not conversation_id:
                continue
            card = ActiveAICard(
                card_instance_id=card_id,
                access_token=token,
                conversation_id=conversation_id,
                account_id=item.get("account_id") or "default",
                store_path=str(self._card_store.path),
                created_at=int(
                    item.get("created_at") or int(time.time() * 1000),
                ),
                last_updated=int(
                    item.get("last_updated") or int(time.time() * 1000),
                ),
                state=state or PROCESSING,
                last_streamed_content="",
            )
            async with self._active_cards_lock:
                self._active_cards[conversation_id] = card
            try:
                await self._stream_ai_card(
                    card,
                    AI_CARD_RECOVERY_FINAL_TEXT,
                    finalize=True,
                )
            except Exception:
                logger.exception("dingtalk ai card recovery finalize failed")
                await self._mark_card_failed(conversation_id)

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Proactive send for DingTalk via stored sessionWebhook.

        Supports:
        1) meta["session_webhook"] or meta["sessionWebhook"]: direct url
        2) to_handle: dingtalk:sw:<sender> (stored) or http(s) url
        3) Open API fallback when webhook is expired or unavailable.

        If no webhook is found and no Open API params,
        logs warning and returns.
        """
        if not self.enabled:
            return
        if self._http is None:
            return

        meta = meta or {}

        # direct webhook provided in meta (current request, always valid)
        session_webhook = meta.get("session_webhook") or meta.get(
            "sessionWebhook",
        )
        webhook_entry: Optional[Dict[str, Any]] = None

        if not session_webhook:
            route = self._route_from_handle(to_handle)
            session_webhook = route.get("session_webhook")
            if not session_webhook:
                webhook_key = route.get("webhook_key")
                if webhook_key:
                    webhook_entry = await self._load_session_webhook_entry(
                        webhook_key,
                    )
                    if webhook_entry is not None:
                        session_webhook = webhook_entry.get("webhook")

        if not session_webhook:
            # No valid webhook: try Open API fallback directly
            logger.info(
                "DingTalkChannel.send: no sessionWebhook for to_handle=%s, "
                "trying Open API fallback",
                to_handle,
            )
            params = self._resolve_open_api_params(
                meta,
                webhook_entry,
            )
            if not params["conversation_id"]:
                logger.warning(
                    "DingTalkChannel.send: no sessionWebhook and no "
                    "conversation_id for to_handle=%s. User must have "
                    "chatted with the bot first. Skip sending.",
                    to_handle,
                )
                return
            await self._send_via_open_api(
                text,
                conversation_id=params["conversation_id"],
                conversation_type=params["conversation_type"],
                sender_staff_id=params["sender_staff_id"],
                bot_prefix="",
            )
            return

        logger.info(
            "DingTalkChannel.send to_handle=%s len=%s",
            to_handle,
            len(text),
        )

        # Caller (send_content_parts) already prepends bot_prefix to text.
        success = await self._send_via_session_webhook(
            session_webhook,
            text,
            bot_prefix="",
        )
        if success:
            return

        # Webhook send failed (possibly expired): invalidate and try fallback
        await self._invalidate_session_webhook(to_handle)
        logger.warning(
            "DingTalkChannel.send: sessionWebhook send failed, "
            "trying Open API fallback for to_handle=%s",
            to_handle,
        )
        params = self._resolve_open_api_params(
            meta,
            webhook_entry,
        )

        if not params["conversation_id"]:
            logger.warning(
                "DingTalkChannel.send: Open API fallback skipped: "
                "no conversation_id available",
            )
            return

        await self._send_via_open_api(
            text,
            conversation_id=params["conversation_id"],
            conversation_type=params["conversation_type"],
            sender_staff_id=params["sender_staff_id"],
            bot_prefix="",
        )

    async def _get_access_token(self) -> str:
        """Get and cache DingTalk accessToken for 1 hour (instance-level)."""
        if not self.client_id or not self.client_secret:
            raise ChannelError(
                channel_name="dingtalk",
                message="DingTalk client_id/client_secret missing",
            )

        now = asyncio.get_running_loop().time()
        if self._token_value and now < self._token_expires_at:
            return self._token_value

        async with self._token_lock:
            now = asyncio.get_running_loop().time()
            if self._token_value and now < self._token_expires_at:
                return self._token_value

            request = dingtalk_oauth_models.GetAccessTokenRequest(
                app_key=self.client_id,
                app_secret=self.client_secret,
            )
            try:
                response = await self._oauth_sdk.get_access_token_async(
                    request,
                )
            except Exception as exc:
                raise ChannelError(
                    channel_name="dingtalk",
                    message=f"get accessToken failed: {exc}",
                ) from exc

            token = (
                response.body.access_token
                if response and response.body
                else None
            )
            if not token:
                raise ChannelError(
                    channel_name="dingtalk",
                    message="accessToken not found in SDK response",
                )

            self._token_value = token
            self._token_expires_at = (
                asyncio.get_running_loop().time() + DINGTALK_TOKEN_TTL_SECONDS
            )
            return token

    async def _get_message_file_download_url(
        self,
        *,
        download_code: str,
        robot_code: str,
    ) -> Optional[str]:
        """Call DingTalk messageFiles/download to get a downloadable URL."""
        if not download_code or not robot_code:
            return None
        if self._robot_sdk is None:
            return None

        token = await self._get_access_token()
        request = dingtalk_robot_models.RobotMessageFileDownloadRequest(
            download_code=download_code,
            robot_code=robot_code,
        )
        sdk_headers = dingtalk_robot_models.RobotMessageFileDownloadHeaders(
            x_acs_dingtalk_access_token=token,
        )
        runtime = tea_util_models.RuntimeOptions()
        try:
            _download = (
                self._robot_sdk.robot_message_file_download_with_options_async
            )
            response = await _download(
                request,
                sdk_headers,
                runtime,
            )
        except Exception:
            logger.exception("messageFiles/download SDK call failed")
            return None

        body = response.body if response else None
        if not body:
            logger.warning("messageFiles/download: empty response body")
            return None
        logger.debug("messageFiles/download response body=%s", body)
        return getattr(body, "download_url", None)

    async def _download_media_to_local(
        self,
        url: str,
        safe_key: str,
        filename_hint: str = "file.bin",
    ) -> Optional[str]:
        """Download media to media_dir; return local path or None.
        Suffix from Content-Type then magic bytes.
        """
        if not url or not url.strip().startswith(("http://", "https://")):
            return None
        if self._http is None:
            return None
        try:
            async with self._http.get(url) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "dingtalk media download failed status=%s",
                        resp.status,
                    )
                    return None
                data = await resp.read()
                content_type = (
                    resp.headers.get("Content-Type", "").split(";")[0].strip()
                )
                disposition = resp.headers.get(
                    "Content-Disposition",
                    "",
                )
            filename = filename_hint
            if "filename=" in disposition:
                part = (
                    disposition.split("filename=", 1)[-1].strip().strip("'\"")
                )
                if part:
                    filename = part
            suffix = ".file"
            if "." in filename:
                ext = filename.rsplit(".", 1)[-1].lower().strip()
                if ext:
                    suffix = "." + ext
            elif content_type:
                suffix = mimetypes.guess_extension(content_type) or ".file"
            self._media_dir.mkdir(parents=True, exist_ok=True)
            path = self._media_dir / f"{safe_key}{suffix}"
            path.write_bytes(data)
            # Fix .file/.bin with magic bytes so images get .png/.jpg etc.
            if path.suffix in (".file", ".bin"):
                real_suffix = guess_suffix_from_file_content(path)
                if real_suffix:
                    new_path = path.with_suffix(real_suffix)
                    path.rename(new_path)
                    path = new_path
                    logger.debug(
                        "dingtalk replaced suffix with %s for %s",
                        real_suffix,
                        path,
                    )
            return str(path)
        except Exception:
            logger.exception("dingtalk _download_media_to_local failed")
            return None

    async def _fetch_and_download_media(
        self,
        *,
        download_code: str,
        robot_code: str,
        filename_hint: str = "file.bin",
    ) -> Optional[str]:
        """Get download URL from API, save to local, return path."""
        url = await self._get_message_file_download_url(
            download_code=download_code,
            robot_code=robot_code,
        )
        if not url:
            return None
        key = hashlib.md5(
            (download_code + robot_code).encode(),
        ).hexdigest()[:24]
        return await self._download_media_to_local(
            url,
            key,
            filename_hint,
        )

    def _guess_filename_and_ext(
        self,
        part: OutgoingContentPart,
        default: str,
    ) -> tuple[str, str]:
        """
        Return (filename, ext) where ext has no dot.
        Tries: part.filename -> url path basename -> default
        """
        filename = (getattr(part, "filename", None) or "").strip()

        if not filename:
            url = (
                getattr(part, "file_url", None)
                or getattr(part, "image_url", None)
                or getattr(part, "video_url", None)
                or ""
            )
            url = (url or "").strip() if isinstance(url, str) else ""
            if url:
                try:
                    path = urlparse(url).path
                    base = os.path.basename(path)
                    if base:
                        filename = base
                except Exception:
                    pass

        if not filename:
            filename = default

        ext = ""
        if "." in filename:
            ext = filename.rsplit(".", 1)[-1].lower().strip()

        if not ext:
            # try from mime_type if provided
            mime = (
                getattr(part, "mime_type", None)
                or getattr(part, "content_type", None)
                or ""
            ).strip()
            if mime:
                guess = mimetypes.guess_extension(mime)  # like ".png"
                if guess:
                    ext = guess.lstrip(".").lower()

        if not ext:
            ext = (
                default.rsplit(".", 1)[-1].lower() if "." in default else "bin"
            )

        # normalize common cases
        if ext == "jpeg":
            ext = "jpg"

        return filename, ext

    def _is_public_http_url(self, s: Optional[str]) -> bool:
        if not s or not isinstance(s, str):
            return False
        s = s.strip()
        return s.startswith("http://") or s.startswith("https://")
