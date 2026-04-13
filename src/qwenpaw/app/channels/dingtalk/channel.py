# -*- coding: utf-8 -*-
# pylint: disable=too-many-statements,too-many-branches
# pylint: disable=too-many-return-statements
"""DingTalk Channel.

Why only one reply by default: DingTalk Stream callback is request-reply.
The handler process() is awaited until reply_future is set once,
then reply_text() is called once.
So we merge all streamed content into one reply. When sessionWebhook is
present we can send multiple messages via that webhook (one POST per
completed message), then set the future to a sentinel so process() skips the
single reply_text.
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
    AsyncGenerator,
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
from agentscope_runtime.engine.schemas.agent_schemas import RunStatus

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
    SENT_VIA_AI_CARD,
    SENT_VIA_WEBHOOK,
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

    # Keys to exclude when creating serializable channel_meta
    _NON_SERIALIZABLE_META_KEYS = (
        "incoming_message",
        "reply_future",
        "reply_loop",
        "_reply_futures_list",
    )

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        client_id: str,
        client_secret: str,
        bot_prefix: str,
        message_type: str = "markdown",
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
    ):
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
        )
        self.enabled = enabled
        self.client_id = client_id
        self.client_secret = client_secret
        self.bot_prefix = bot_prefix
        self.message_type = (message_type or "markdown").strip().lower()
        self.card_template_id = card_template_id or ""
        self.card_template_key = card_template_key or "content"
        self.robot_code = robot_code or self.client_id
        self.card_auto_layout = card_auto_layout
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
        """Save session_webhook from meta for cron/proactive send."""
        meta = getattr(request, "channel_meta", None) or {}
        session_webhook = self._get_session_webhook(meta)
        if not session_webhook:
            return
        session_id = getattr(request, "session_id", None)
        if not session_id:
            return
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

    @staticmethod
    def _safe_set_future_result(
        future: "asyncio.Future[str]",
        text: str,
    ) -> None:
        """Set future result only if not already done (idempotent).

        Guards against InvalidStateError when _ack_early already resolved
        the future before _reply_sync_batch is called at stream end.
        """
        if not future.done():
            future.set_result(text)

    def _reply_sync(self, meta: Dict[str, Any], text: str) -> None:
        """Resolve reply_future on the stream thread's loop so process()
        can continue and reply.
        """
        reply_loop = meta.get("reply_loop")
        reply_future = meta.get("reply_future")
        if reply_loop is None or reply_future is None:
            return
        reply_loop.call_soon_threadsafe(
            self._safe_set_future_result,
            reply_future,
            text,
        )
        if "_message_ids" in meta:
            ids = meta["_message_ids"]
        else:
            ids = [meta.get("message_id")] if meta.get("message_id") else []
        self._release_message_ids(ids)

    def _reply_sync_batch(self, meta: Dict[str, Any], text: str) -> None:
        """
        Resolve all reply_futures (merged batch) so every waiter unblocks.
        """
        lst = meta.get("_reply_futures_list") or []
        if lst:
            for reply_loop, reply_future in lst:
                if reply_loop and reply_future:
                    reply_loop.call_soon_threadsafe(
                        self._safe_set_future_result,
                        reply_future,
                        text,
                    )
            ids = meta["_message_ids"] if "_message_ids" in meta else []
            self._release_message_ids(ids)
        else:
            self._reply_sync(meta, text)

    def _ack_early(self, meta: Dict[str, Any], text: str) -> None:
        """Resolve reply_futures immediately for streaming paths (AI card /
        sessionWebhook) WITHOUT releasing dedup msg_ids.

        Unblocks the DingTalk stream callback handler so it can return
        STATUS_OK to the SDK quickly, preventing DingTalk retry storms
        during long LLM generation. Dedup msg_ids are released later by
        _reply_sync_batch once streaming fully completes, so any DingTalk
        re-delivery before that point is still correctly rejected.
        """
        lst = meta.get("_reply_futures_list") or []
        if lst:
            for reply_loop, reply_future in lst:
                if reply_loop and reply_future:
                    reply_loop.call_soon_threadsafe(
                        self._safe_set_future_result,
                        reply_future,
                        text,
                    )
            futures_count = len(lst)
        else:
            reply_loop = meta.get("reply_loop")
            reply_future = meta.get("reply_future")
            if reply_loop and reply_future:
                reply_loop.call_soon_threadsafe(
                    self._safe_set_future_result,
                    reply_future,
                    text,
                )
            futures_count = 1 if meta.get("reply_future") else 0
        logger.debug(
            "dingtalk _ack_early: text=%r futures_count=%s",
            text,
            futures_count,
        )

    def _get_session_webhook(
        self,
        meta: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Get sessionWebhook from meta (persisted) or incoming_message."""
        if not meta:
            return None
        out = meta.get("session_webhook") or meta.get("sessionWebhook")
        if out:
            return out
        inc = meta.get("incoming_message")
        if inc is None:
            return None
        return getattr(inc, "sessionWebhook", None) or getattr(
            inc,
            "session_webhook",
            None,
        )

    def _parts_to_single_text(
        self,
        parts: List[OutgoingContentPart],
        bot_prefix: str = "",
    ) -> str:
        """Build one reply text from parts
        (same logic as send_content_parts body).
        """
        text_parts: List[str] = []
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
            elif t == ContentType.IMAGE and getattr(p, "image_url", None):
                text_parts.append(f"[Image: {p.image_url}]")
            elif t == ContentType.VIDEO and getattr(p, "video_url", None):
                text_parts.append(f"[Video: {p.video_url}]")
            elif t == ContentType.FILE and (
                getattr(p, "file_url", None) or getattr(p, "file_id", None)
            ):
                url_or_id = getattr(p, "file_url", None) or getattr(
                    p,
                    "file_id",
                    None,
                )
                text_parts.append(f"[File: {url_or_id}]")
            elif t == ContentType.AUDIO and getattr(p, "data", None):
                text_parts.append("[Audio]")
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
    ) -> bool:
        """Send one text message via DingTalk sessionWebhook. Returns True
        on success."""
        text = (bot_prefix + "  " + body) if body else bot_prefix
        if len(text) > 3500:
            payload = {"msgtype": "text", "text": {"content": text}}
        else:
            norm = dingtalk_markdown.normalize_dingtalk_markdown(text)
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"💬{norm[:10]}...",
                    "text": norm,
                },
            }
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

        return await self._send_robot_message(
            msg_key="sampleText",
            msg_param=json.dumps({"content": text}),
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
        When this is a reply to a user message (meta has reply_future or
        conversation_id) and meta has no session_webhook, do not fall back
        to store so we never use a stale/expired webhook.
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
        if m.get("reply_future") is not None or m.get("conversation_id"):
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
        """Build one body from parts. If meta has reply_future (reply path),
        deliver via _reply_sync; otherwise proactive send via send().
        When session_webhook is available, sends text then image/file
        messages (upload media first for image/file).
        """
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
        m = meta or {}
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
                    if m.get("reply_loop") is not None and m.get(
                        "reply_future",
                    ):
                        self._reply_sync(m, SENT_VIA_WEBHOOK)
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
            if m.get("reply_loop") is not None and m.get("reply_future"):
                self._reply_sync(m, SENT_VIA_WEBHOOK)
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
                if (
                    m.get("reply_loop") is not None
                    and m.get("reply_future") is not None
                ):
                    self._reply_sync(m, SENT_VIA_WEBHOOK)
                return
            # Open API unavailable: append text placeholders so the user
            # is at least aware of the attachments.
            for p in media_parts:
                pt = getattr(p, "type", None)
                if pt == ContentType.IMAGE and getattr(
                    p,
                    "image_url",
                    None,
                ):
                    body += f"\n[Image: {p.image_url}]"
                elif pt == ContentType.FILE and (
                    getattr(p, "file_url", None) or getattr(p, "file_id", None)
                ):
                    furl = getattr(p, "file_url", None) or getattr(
                        p,
                        "file_id",
                        None,
                    )
                    body += f"\n[File: {furl}]"
                elif pt == ContentType.VIDEO and getattr(
                    p,
                    "video_url",
                    None,
                ):
                    body += f"\n[Video: {p.video_url}]"
                elif pt == ContentType.AUDIO and getattr(p, "data", None):
                    body += "\n[Audio]"

        if (
            m.get("reply_loop") is not None
            and m.get("reply_future") is not None
        ):
            self._reply_sync(m, body)
        else:
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
        """Unblock previous reply_future so stream callback does not block."""
        del key
        del payload
        if not existing_items:
            return
        prev = existing_items[-1]
        pm = prev.get("meta") or {} if isinstance(prev, dict) else {}
        if (
            pm.get("reply_loop") is not None
            and pm.get("reply_future") is not None
        ):
            self._reply_sync(pm, SENT_VIA_WEBHOOK)

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

    async def _run_process_loop(
        self,
        request: Any,
        to_handle: str,
        send_meta: Dict[str, Any],
    ) -> None:
        """Use webhook multi-message send instead of default loop."""
        del to_handle

        is_group = bool((send_meta or {}).get("is_group", False))
        if not self._check_group_mention(is_group, send_meta):
            return

        logger.info(
            "dingtalk _run_process_loop: send_meta has_sw=%s "
            "req.channel_meta has_sw=%s",
            bool((send_meta or {}).get("session_webhook")),
            bool(
                (getattr(request, "channel_meta", None) or {}).get(
                    "session_webhook",
                ),
            ),
        )
        # Keep only JSON-serializable keys on request for tracing; pass full
        # send_meta as reply_meta for _reply_sync_batch / send_content_parts.
        safe_meta = {
            k: v
            for k, v in (send_meta or {}).items()
            if k not in self._NON_SERIALIZABLE_META_KEYS
        }
        request.channel_meta = safe_meta
        logger.info(
            "dingtalk _run_process_loop: after set channel_meta has_sw=%s",
            bool((request.channel_meta or {}).get("session_webhook")),
        )
        try:
            await self._process_one_request(request, reply_meta=send_meta)
        except Exception as e:
            logger.exception("dingtalk _process_one_request failed")
            # Recall "processing" reaction on error
            incoming_msg_id = str(
                (send_meta or {}).get("message_id") or "",
            )
            conv_id = str(
                (send_meta or {}).get("conversation_id") or "",
            )
            if incoming_msg_id and conv_id:
                await self._send_emotion(
                    incoming_msg_id,
                    conv_id,
                    "🤔Thinking",
                    recall=True,
                )
                await self._send_emotion(
                    incoming_msg_id,
                    conv_id,
                    "☹️Error",
                )
            err_msg = str(e).strip() or "An error occurred while processing."
            self._reply_sync_batch(
                send_meta,
                self.bot_prefix + f"Error: {err_msg}",
            )
            raise

    async def _process_dingtalk_core(  # noqa: C901
        self,
        request: Any,
        *,
        reply_meta: Dict[str, Any],
        to_handle: str,
    ) -> AsyncGenerator[Any, None]:
        """Core DingTalk processing shared by both paths.

        Handles AI Card creation, streaming updates, webhook sends,
        media delivery, finalization and reply_future resolution.
        Yields raw events from ``self._process(request)`` so callers
        can optionally serialize them (e.g. as SSE).

        Args:
            request: AgentRequest
            reply_meta: Meta dict that carries reply_future /
                reply_loop for ACK and _reply_sync_batch.
            to_handle: Resolved target handle for
                send_content_parts / _on_consume_error.
        """
        meta = getattr(request, "channel_meta", None) or {}
        session_webhook = self._get_session_webhook(meta)
        use_multi = bool(session_webhook)
        bot_prefix = self.bot_prefix or ""

        logger.info(
            "dingtalk core: meta has_sw=%s use_multi=%s",
            bool(meta.get("session_webhook")),
            use_multi,
        )

        last_response = None
        accumulated_parts: list = []
        _acked_early = False
        conversation_id = str(meta.get("conversation_id") or "")
        incoming_msg_id = str(meta.get("message_id") or "")

        # Add "processing" reaction to the user's incoming message
        if incoming_msg_id and conversation_id:
            await self._send_emotion(
                incoming_msg_id,
                conversation_id,
                "🤔Thinking",
            )

        use_ai_card = self._ai_card_enabled() and bool(conversation_id)
        logger.info(
            "dingtalk ai card gate: enabled=%s "
            "message_type=%s has_template=%s "
            "has_robot=%s has_conversation=%s",
            use_ai_card,
            self.message_type,
            bool(self.card_template_id),
            bool(self.robot_code),
            bool(conversation_id),
        )

        card: Optional[ActiveAICard] = None
        card_full_text = ""
        if use_ai_card:
            try:
                card = await self._create_ai_card(
                    conversation_id,
                    meta=meta,
                    inbound=True,
                )
                # ACK DingTalk immediately so the stream callback
                # handler returns STATUS_OK without waiting for the
                # full LLM response.  Dedup msg_ids are kept until
                # streaming finishes (_reply_sync_batch below).
                self._ack_early(reply_meta, SENT_VIA_AI_CARD)
                _acked_early = True
                logger.info(
                    "dingtalk core: AI card created, "
                    "handler unblocked early",
                )
            except Exception:
                logger.exception(
                    "dingtalk create ai card failed, fallback to markdown",
                )
                use_ai_card = False

        async for event in self._process(request):
            # Yield raw event so callers can do SSE / debug log
            yield event

            obj = getattr(event, "object", None)
            status = getattr(event, "status", None)

            if obj == "message" and status == RunStatus.Completed:
                parts = self._message_to_content_parts(event)
                body = self._parts_to_single_text(
                    parts,
                    bot_prefix="",
                )
                if use_ai_card and card:
                    next_text = self._merge_ai_card_text(
                        card_full_text,
                        body,
                    )
                    try:
                        if next_text != card_full_text:
                            card_full_text = next_text
                            await self._stream_ai_card(
                                card,
                                card_full_text,
                                finalize=False,
                            )
                    except Exception:
                        logger.exception(
                            "dingtalk stream ai card failed,"
                            " fallback to markdown",
                        )
                        await self._mark_card_failed(
                            conversation_id,
                        )
                        use_ai_card = False
                        fb = body.strip() or card_full_text.strip()
                        if use_multi and session_webhook and fb:
                            await self._send_via_session_webhook(
                                session_webhook,
                                fb,
                                bot_prefix="",
                            )
                        else:
                            accumulated_parts.extend(parts)
                elif use_multi and parts and session_webhook:
                    if body.strip():
                        await self._send_via_session_webhook(
                            session_webhook,
                            body.strip(),
                            bot_prefix="",
                        )
                        if not _acked_early:
                            self._ack_early(
                                reply_meta,
                                SENT_VIA_WEBHOOK,
                            )
                            _acked_early = True
                    _media_types = (
                        ContentType.IMAGE,
                        ContentType.FILE,
                        ContentType.VIDEO,
                        ContentType.AUDIO,
                    )
                    for part in parts:
                        if getattr(part, "type", None) in _media_types:
                            await self._send_media_part_via_webhook(
                                session_webhook,
                                part,
                            )
                else:
                    accumulated_parts.extend(parts)
            elif obj == "response":
                last_response = event

        # ---- Finalize ----
        err_msg = self._get_response_error_message(last_response)
        # Recall "processing" reaction on error (success path handled
        # by _on_process_completed via the hook call below)
        if err_msg and incoming_msg_id and conversation_id:
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
        if use_ai_card and card:
            final_text = card_full_text or self._build_ai_card_initial_text()
            try:
                if err_msg:
                    final_text = bot_prefix + f"Error: {err_msg}"
                await self._stream_ai_card(
                    card,
                    final_text,
                    finalize=True,
                )
            except Exception:
                logger.exception(
                    "dingtalk finalize ai card failed",
                )
                await self._mark_card_failed(conversation_id)
                if use_multi and session_webhook:
                    await self._send_via_session_webhook(
                        session_webhook,
                        final_text,
                        bot_prefix="",
                    )
            self._reply_sync_batch(
                reply_meta,
                SENT_VIA_AI_CARD,
            )
        elif err_msg:
            err_text = bot_prefix + f"Error: {err_msg}"
            if use_multi and session_webhook:
                await self._send_via_session_webhook(
                    session_webhook,
                    err_text,
                    bot_prefix="",
                )
            self._reply_sync_batch(
                reply_meta,
                SENT_VIA_WEBHOOK if use_multi else err_text,
            )
        elif use_multi:
            self._reply_sync_batch(
                reply_meta,
                SENT_VIA_WEBHOOK,
            )
        elif accumulated_parts:
            await self.send_content_parts(
                to_handle,
                accumulated_parts,
                reply_meta,
            )
        elif last_response is None:
            self._reply_sync_batch(
                reply_meta,
                bot_prefix + "An error occurred while processing "
                "your request.",
            )

        if not err_msg:
            await self._on_process_completed(
                request,
                to_handle,
                reply_meta,
            )

        if self._on_reply_sent:
            self._on_reply_sent(
                self.channel,
                request.user_id or "",
                request.session_id or f"{self.channel}:{request.user_id}",
            )

    # -- workspace path (TaskTracker) --------------------------

    async def _stream_with_tracker(
        self,
        payload: Any,
    ) -> AsyncGenerator[str, None]:
        """Override to integrate AI Card logic in workspace path.

        Delegates to _process_dingtalk_core and yields SSE events
        for TaskTracker.
        """
        request = self._payload_to_request(payload)

        if isinstance(payload, dict):
            send_meta = dict(payload.get("meta") or {})
            if payload.get("session_webhook"):
                send_meta["session_webhook"] = payload["session_webhook"]
        else:
            send_meta = getattr(request, "channel_meta", None) or {}

        bot_prefix = self.bot_prefix or ""
        if bot_prefix and "bot_prefix" not in send_meta:
            send_meta = {**send_meta, "bot_prefix": bot_prefix}

        to_handle = self._resolve_to_handle(request)

        # Allowlist / mention checks
        sender_id = getattr(request, "user_id", "") or ""
        is_group = bool(send_meta.get("is_group", False))
        allowed, error_msg = self._check_allowlist(
            sender_id,
            is_group,
        )
        if not allowed:
            logger.info(
                "dingtalk allowlist blocked: sender=%s is_group=%s",
                sender_id,
                is_group,
            )
            deny_text = bot_prefix + (error_msg or "")
            sw = self._get_session_webhook(send_meta)
            if sw:
                await self._send_via_session_webhook(
                    sw,
                    deny_text,
                    bot_prefix="",
                )
                self._reply_sync_batch(
                    send_meta,
                    SENT_VIA_WEBHOOK,
                )
            else:
                self._reply_sync_batch(
                    send_meta,
                    deny_text,
                )
            return

        if not self._check_group_mention(is_group, send_meta):
            return

        # Strip non-serializable keys for request.channel_meta
        safe_meta = {
            k: v
            for k, v in send_meta.items()
            if k not in self._NON_SERIALIZABLE_META_KEYS
        }
        request.channel_meta = safe_meta

        await self._before_consume_process(request)

        core_iter = None
        try:
            core_iter = self._process_dingtalk_core(
                request,
                reply_meta=send_meta,
                to_handle=to_handle,
            )
            async for event in core_iter:
                # SSE serialization
                if hasattr(event, "model_dump_json"):
                    data = event.model_dump_json()
                elif hasattr(event, "json"):
                    data = event.json()
                else:
                    data = json.dumps({"text": str(event)})
                yield f"data: {data}\n\n"

                obj = getattr(event, "object", None)
                if obj == "response":
                    await self.on_event_response(
                        request,
                        event,
                    )

        except asyncio.CancelledError:
            logger.info(
                "dingtalk task cancelled: session=%s",
                getattr(request, "session_id", "")[:30],
            )
            if core_iter is not None:
                await core_iter.aclose()
            raise

        except Exception as exc:
            logger.exception(
                "dingtalk _stream_with_tracker failed: %s",
                exc,
            )
            err_detail = str(exc).strip() or "Internal error"
            await self._on_consume_error(
                request,
                to_handle,
                err_detail,
            )
            self._reply_sync_batch(
                send_meta,
                bot_prefix + err_detail,
            )
            raise

    # -- legacy path -------------------------------------------

    async def _process_one_request(
        self,
        request: Any,
        reply_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Process a single request using the shared core.

        Called by _run_process_loop (legacy / non-workspace path).
        """
        meta = getattr(request, "channel_meta", None) or {}
        reply_meta = reply_meta or meta
        to_handle = self._resolve_to_handle(request)

        async for _event in self._process_dingtalk_core(
            request,
            reply_meta=reply_meta,
            to_handle=to_handle,
        ):
            pass  # events consumed by core; nothing extra needed

    def _merge_native(self, items: list) -> dict:
        """Merge multiple native payloads into one (content_parts + meta)."""
        if not items:
            return {}
        first = items[0] if isinstance(items[0], dict) else {}
        merged_parts: List[Any] = []
        merged_meta: Dict[str, Any] = dict(first.get("meta") or {})

        reply_futures_list: List[tuple] = []
        message_ids_list: List[str] = []
        for it in items:
            payload = it if isinstance(it, dict) else {}
            merged_parts.extend(payload.get("content_parts") or [])
            m = payload.get("meta") or {}
            for k in (
                "reply_future",
                "reply_loop",
                "incoming_message",
                "conversation_id",
                "session_webhook",
                "session_webhook_expired_time",
                "conversation_type",
                "sender_staff_id",
            ):
                if k in m:
                    merged_meta[k] = m[k]
            if m.get("reply_loop") and m.get("reply_future"):
                reply_futures_list.append((m["reply_loop"], m["reply_future"]))
            mid = m.get("message_id") or payload.get("message_id")
            if mid:
                message_ids_list.append(str(mid))

        merged_meta["batched_count"] = len(items)
        merged_meta["_reply_futures_list"] = reply_futures_list
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
        """Recall 'processing' reaction and add 'done' reaction."""
        incoming_msg_id = str((send_meta or {}).get("message_id") or "")
        conversation_id = str((send_meta or {}).get("conversation_id") or "")
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

    def _ai_card_enabled(self) -> bool:
        return (
            self.message_type == "card"
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

    def _merge_ai_card_text(self, current: str, incoming: str) -> str:
        current = (current or "").strip()
        incoming = (incoming or "").strip()
        if not incoming:
            return current
        if not current:
            return incoming
        if incoming == current or current.endswith(incoming):
            return current
        return f"{current}\n{incoming}".strip()

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
    ) -> Optional[ActiveAICard]:
        if not self._ai_card_enabled() or self._card_sdk is None:
            logger.warning(
                "dingtalk create ai card skipped: enabled=%s sdk_ready=%s "
                "message_type=%s has_template=%s has_robot=%s",
                self._ai_card_enabled(),
                self._card_sdk is not None,
                self.message_type,
                bool(self.card_template_id),
                bool(self.robot_code),
            )
            return None
        token = await self._get_access_token()
        card_instance_id = f"card_{uuid4()}"
        meta = meta or {}
        incoming_message = meta.get("incoming_message")
        sender_staff_id = (
            meta.get("sender_staff_id")
            or getattr(incoming_message, "sender_staff_id", None)
            or getattr(incoming_message, "senderStaffId", None)
            or ""
        )
        is_group = bool(meta.get("is_group"))
        card_param_map: Dict[str, str] = {self.card_template_key: ""}
        if self.card_auto_layout:
            card_param_map["config"] = json.dumps({"autoLayout": True})

        sdk_headers = dingtalk_card_models.CreateCardHeaders(
            x_acs_dingtalk_access_token=token,
        )
        runtime = tea_util_models.RuntimeOptions()

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
            logger.info(
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

        logger.info(
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

    async def _finish_ai_card(
        self,
        conversation_id: str,
        final_content: str,
    ) -> bool:
        async with self._active_cards_lock:
            card = self._active_cards.get(conversation_id)
        if not card:
            return False
        return await self._stream_ai_card(card, final_content, finalize=True)

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
