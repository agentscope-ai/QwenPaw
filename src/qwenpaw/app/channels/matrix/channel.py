# -*- coding: utf-8 -*-
"""
MatrixChannel: QwenPaw BaseChannel implementation for Matrix (via matrix-nio).

"""

from __future__ import annotations

import asyncio
import html
import importlib
import inspect
import io
import logging
import mimetypes
import os
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from nio import (
    AsyncClient,
    AsyncClientConfig,
    KeysUploadResponse,
    LoginResponse,
    KeyVerificationCancel,
    KeyVerificationEvent,
    KeyVerificationKey,
    KeyVerificationMac,
    KeyVerificationStart,
    LocalProtocolError,
    MatrixRoom,
    MegolmEvent,
    RoomEncryptedAudio,
    RoomEncryptedFile,
    RoomEncryptedImage,
    RoomEncryptedVideo,
    RoomMessageAudio,
    RoomMessageFile,
    RoomMessageImage,
    RoomMessageText,
    RoomMessageVideo,
    SyncResponse,
    ToDeviceEvent,
    ToDeviceError,
    UploadResponse,
)
from nio.event_builders.direct_messages import ToDeviceMessage
from nio.events.to_device import RoomKeyRequest, RoomKeyRequestCancellation
from nio.responses import (
    JoinedMembersResponse,
    RoomGetStateEventResponse,
    SyncError,
    WhoamiResponse,
)

from agentscope_runtime.engine.schemas.agent_schemas import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    TextContent,
    VideoContent,
)

from ....app.channels.base import BaseChannel
from ....app.channels.utils import file_url_to_local_path
from ....constant import WORKING_DIR

logger = logging.getLogger("qwenpaw.channels.matrix")


CHANNEL_KEY = "matrix"

# Tunables: sync / typing / DM membership cache TTL
SYNC_TIMEOUT_MS = 30000
TYPING_SERVER_TIMEOUT_MS = 30000
TYPING_RENEWAL_INTERVAL_S = 25
TYPING_MAX_DURATION_S = 120
DM_CACHE_TTL_MS = 30_000

# Known QwenPaw slash commands — used to decide whether to strip
# @mention prefix
_SLASH_COMMANDS = frozenset(
    {
        "message",
        "history",
        "compact_str",
        "compact",
        "new",
        "clear",
        "reset",
    },
)

# Aliases: map alternative command names to their canonical form.
_SLASH_ALIASES: dict[str, str] = {
    "reset": "clear",
}


def _md_to_html(text: str) -> str:
    """Convert Markdown text to HTML for Matrix ``formatted_body``.

    Uses ``markdown-it-py`` (the Python port of markdown-it) with the same
    configuration as OpenClaw's Matrix extension so rendering is consistent
    across both runtimes:

    - html disabled (raw HTML is escaped)
    - linkify enabled (bare URLs become clickable links)
    - breaks enabled (single newlines become ``<br>``)
    - strikethrough enabled (``~~text~~``)

    Falls back to simple HTML-escape + ``<br>`` if the library is missing.
    """
    try:
        from markdown_it import MarkdownIt

        md = MarkdownIt(
            "commonmark",
            {
                "html": False,
                "linkify": True,
                "breaks": True,
                "typographer": False,
            },
        )
        md.enable("strikethrough")
        md.enable("table")

        # linkify support requires linkify-it-py
        try:
            from linkify_it import LinkifyIt

            md.linkify = LinkifyIt()
        except ImportError:
            logger.debug(
                "linkify-it-py not installed; bare URLs may not be linkified",
            )

        return md.render(text).rstrip("\n")
    except ImportError:
        logger.warning(
            "markdown-it-py not installed; formatted_body will be plain text",
        )
        return html.escape(text).replace("\n", "<br>\n")


# Markers that separate accumulated history from the triggering message,
# matching the convention used by OpenClaw so agents can parse uniformly.
HISTORY_CONTEXT_MARKER = "[Chat messages since your last reply - for context]"
CURRENT_MESSAGE_MARKER = "[Current message - respond to this]"
DEFAULT_HISTORY_LIMIT = 50


class QwenPawMatrixClient(AsyncClient):
    """Keep query-token auth for homeservers/proxies that drop auth headers."""

    async def send(
        self,
        method: str,
        path: str,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
        trace_context: Optional[Any] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        if self.access_token and "access_token=" not in path:
            url = urllib.parse.urlparse(path)
            query = urllib.parse.parse_qs(url.query)
            query["access_token"] = [self.access_token]
            path = urllib.parse.urlunparse(
                url._replace(
                    query=urllib.parse.urlencode(query, doseq=True),
                ),
            )
        return await super().send(
            method,
            path,
            data,
            headers,
            trace_context,
            timeout,
        )


@dataclass
class HistoryEntry:
    """A buffered room message that didn't mention the bot."""

    sender: str
    body: str
    timestamp: Optional[int] = None
    message_id: Optional[str] = None
    # Optional structured media parts (e.g. downloaded images for vision
    # models) to be included alongside the text history when the mention
    # arrives.
    media_parts: Optional[List[Any]] = None


class MatrixChannel(BaseChannel):
    """QwenPaw channel that connects to a Matrix homeserver via matrix-nio."""

    channel = CHANNEL_KEY  # type: ignore[assignment]
    uses_manager_queue: bool = True

    def __init__(
        self,
        process: Callable,
        homeserver: str = "",
        matrix_user_id: str = "",
        access_token: str = "",
        password: str = "",
        device_name: str = "qwenpaw-worker",
        device_id: str = "",
        encryption: bool = False,
        dm_disabled: bool = False,
        group_disabled: bool = False,
        groups: Optional[Dict[str, Any]] = None,
        vision_enabled: bool = False,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        sync_timeout_ms: int = 30000,
        on_reply_sent: Optional[Callable] = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Path | None = None,
        access_control_dm: bool = False,
        access_control_group: bool = False,
        enabled: bool = True,
        **_kwargs: Any,
    ) -> None:
        super().__init__(
            process=process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            access_control_dm=access_control_dm,
            access_control_group=access_control_group,
        )
        # Matrix connection
        self.homeserver: str = homeserver.rstrip("/")
        self.matrix_user_id: str = matrix_user_id
        self.access_token: str = access_token
        self.password: str = password
        self.device_name: str = device_name
        self.device_id: str = device_id
        self.encryption: bool = encryption
        self.enabled: bool = enabled
        # Channel-level mute
        self.dm_disabled: bool = dm_disabled
        self.group_disabled: bool = group_disabled
        # Per-room overrides
        self.groups: Dict[str, Any] = groups or {}
        # Media / history
        self.vision_enabled: bool = vision_enabled
        self.history_limit: int = max(0, history_limit)
        self.sync_timeout_ms: int = sync_timeout_ms

        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )
        self._client: Optional[AsyncClient] = None
        self._user_id: Optional[str] = None
        self._sync_task: Optional[asyncio.Task] = None
        self._typing_tasks: Dict[str, asyncio.Task] = {}
        self._room_histories: Dict[str, List[HistoryEntry]] = {}
        self._dm_room_cache: Dict[str, Dict[str, Any]] = {}
        self._http_client: Optional[httpx.AsyncClient] = None
        self._handled_verification_requests: set[str] = set()
        self._verification_tx_peers: dict[str, tuple[str, str]] = {}
        self._sent_verification_done: set[str] = set()

    # ------------------------------------------------------------------
    # Debounce key — serialize by room_id (avoid concurrent session access)
    # ------------------------------------------------------------------

    def get_debounce_key(self, payload: Any) -> str:
        if isinstance(payload, dict):
            meta = payload.get("meta") or {}
            room_id = meta.get("room_id")
            if room_id:
                return f"matrix:{room_id}"
            return payload.get("sender_id") or ""
        return getattr(payload, "session_id", "") or ""

    # ------------------------------------------------------------------
    # Factory — from_config / from_env
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        process: Callable,
        config: Any,
        on_reply_sent: Optional[Callable] = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Path | None = None,
    ) -> "MatrixChannel":
        # Support pydantic model, dict, or SimpleNamespace
        if isinstance(config, dict):
            raw = config
        else:
            raw = (
                config.model_dump()
                if hasattr(config, "model_dump")
                else vars(config)
            )
        return cls(
            process=process,
            homeserver=raw.get("homeserver", ""),
            matrix_user_id=raw.get("user_id", ""),
            access_token=raw.get("access_token", ""),
            password=raw.get("password", ""),
            device_name=raw.get("device_name", "qwenpaw-worker"),
            device_id=raw.get("device_id", ""),
            encryption=raw.get("encryption", False),
            dm_disabled=raw.get("dm_disabled", False),
            group_disabled=raw.get("group_disabled", False),
            groups=raw.get("groups"),
            vision_enabled=raw.get("vision_enabled", False),
            history_limit=raw.get("history_limit", DEFAULT_HISTORY_LIMIT),
            sync_timeout_ms=raw.get("sync_timeout_ms", 30000),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=(
                filter_tool_messages or raw.get("filter_tool_messages", False)
            ),
            filter_thinking=(
                filter_thinking or raw.get("filter_thinking", False)
            ),
            workspace_dir=workspace_dir,
            access_control_dm=bool(raw.get("access_control_dm", False)),
            access_control_group=bool(raw.get("access_control_group", False)),
            enabled=raw.get("enabled", True),
        )

    @classmethod
    def from_env(
        cls,
        process: Callable,
        on_reply_sent=None,
    ) -> "MatrixChannel":
        return cls(
            process=process,
            homeserver=os.environ.get("HICLAW_MATRIX_SERVER", ""),
            access_token=os.environ.get("HICLAW_MATRIX_TOKEN", ""),
            on_reply_sent=on_reply_sent,
        )

    # ------------------------------------------------------------------
    # Lifecycle — client, login, event callbacks, _sync_loop
    # token + user_id/password login (§2); optional
    # E2EE client config + store; cleartext + encrypted event callbacks;
    # starts _sync_loop (§3).
    # ------------------------------------------------------------------

    def _build_client_config(
        self,
        encryption: bool = False,
    ) -> AsyncClientConfig:
        """Build an AsyncClientConfig with proper request timeout.

        The HTTP request timeout must exceed the sync long-poll timeout
        so the HTTP layer doesn't kill the connection while the
        homeserver is legitimately waiting for new events.
        """
        sync_s = self.sync_timeout_ms / 1000
        request_timeout = max(sync_s + 30, 60)
        return AsyncClientConfig(
            store_sync_tokens=False,
            encryption_enabled=encryption,
            request_timeout=request_timeout,
        )

    @staticmethod
    def _derive_device_id_from_name(device_name: str) -> str:
        """Use configured device_name directly as fallback device_id."""
        return (device_name or "").strip()

    async def health_check(self) -> Dict[str, Any]:
        """Check Matrix client connection status."""
        if not getattr(self, "enabled", True) or not self.homeserver:
            return {
                "channel": self.channel,
                "status": "disabled",
                "detail": "Matrix homeserver not configured.",
            }
        if self._client is None:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "Matrix client not initialized.",
            }
        has_token = bool(self._client.access_token)
        if not has_token:
            return {
                "channel": self.channel,
                "status": "unhealthy",
                "detail": "Matrix client has no access token (not logged in).",
            }
        return {
            "channel": self.channel,
            "status": "healthy",
            "detail": "Matrix client is connected.",
        }

    def _restore_auth_state_before_start(
        self,
        *,
        has_password_creds: bool,
        has_token_cred: bool,
    ) -> None:
        # Auth source priority:
        # 1) Explicit user_id/password from config/UI
        # 2) Explicit access_token from config/UI
        # 3) Cached auth_state fallback
        #
        # When token or user_id/password is explicitly configured, do not
        # restore cached token, otherwise we may accidentally bypass the
        # intended auth path.
        has_explicit_identity = (
            has_password_creds or has_token_cred or self.matrix_user_id
        )
        self._load_auth_state(
            restore_token=False,
            restore_identity=not has_explicit_identity,
        )

    def _preflight_e2ee_dependencies(self) -> None:
        """Probe olm before creating AsyncClientConfig;
        disable E2EE if absent."""
        if not self.encryption:
            return
        try:
            importlib.import_module("olm")
        except ImportError:
            logger.error(
                "MatrixChannel: olm not installed — falling back to "
                "non-encrypted mode. "
                "To enable E2EE: pip install matrix-nio[e2e] && "
                "apt/dnf install libolm-dev",
            )
            self.encryption = False

    def _init_async_client(self, resolved_device_id: str) -> None:
        # E2EE: when encryption is enabled, provide store_path so matrix-nio
        # persists Olm/Megolm keys, and set config to auto-trust all devices
        # (appropriate for bot use cases where interactive verification is
        # impractical).
        store_path = None
        if self.encryption:
            store_path = self._e2ee_store_path()
            store_path.mkdir(parents=True, exist_ok=True)
        client_config = self._build_client_config(
            encryption=self.encryption,
        )
        self._client = QwenPawMatrixClient(
            self.homeserver,
            # Keep user neutral before auth; token/whoami or login response
            # will set the canonical MXID.
            user="",
            store_path=str(store_path) if store_path else "",
            config=client_config,
        )
        if resolved_device_id:
            self._client.device_id = resolved_device_id

    def _password_login_kwargs_for_nio(
        self,
        login_user: str,
        resolved_device_id: str,
    ) -> dict[str, Any]:
        # matrix-nio login() signature differs across versions. Build
        # kwargs from runtime signature to avoid argument collisions.
        login_sig = inspect.signature(self._client.login)
        login_kwargs: dict[str, Any] = {}
        login_params = login_sig.parameters
        if "user" in login_params:
            login_kwargs["user"] = login_user
        elif "user_id" in login_params:
            login_kwargs["user_id"] = login_user
        if "password" in login_params:
            login_kwargs["password"] = self.password
        if "device_name" in login_params and self.device_name:
            login_kwargs["device_name"] = self.device_name
        if "device_id" in login_params:
            stable_device_id = (
                self._client.device_id or resolved_device_id or ""
            )
            if stable_device_id:
                login_kwargs["device_id"] = stable_device_id
        # For nio versions that derive username from client.user.
        if "user" not in login_params and "user_id" not in login_params:
            self._client.user = login_user
        return login_kwargs

    def _password_login_attempts(
        self,
        login_user: str,
        login_kwargs: dict[str, Any],
        resolved_device_id: str,
    ) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        login_attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        if login_kwargs:
            login_attempts.append(((), login_kwargs))
        login_attempts.append(
            (
                (self.password,),
                {
                    "device_name": self.device_name,
                    **(
                        {"device_id": resolved_device_id}
                        if resolved_device_id
                        else {}
                    ),
                },
            ),
        )
        login_attempts.append(
            (
                (login_user, self.password),
                {
                    "device_name": self.device_name,
                    **(
                        {"device_id": resolved_device_id}
                        if resolved_device_id
                        else {}
                    ),
                },
            ),
        )
        return login_attempts

    async def _try_password_login_variants(
        self,
        login_attempts: list[tuple[tuple[Any, ...], dict[str, Any]]],
    ) -> tuple[Any, Optional[TypeError]]:
        last_exc: Optional[TypeError] = None
        for args, kwargs in login_attempts:
            try:
                resp = await self._client.login(*args, **kwargs)
                return resp, None
            except TypeError as exc:
                last_exc = exc
        return None, last_exc

    def _handle_password_login_success(self, resp: LoginResponse) -> None:
        self._user_id = resp.user_id
        self._client.user_id = resp.user_id
        self._client.user = resp.user_id
        if getattr(resp, "device_id", None):
            self._client.device_id = resp.device_id
        if getattr(resp, "access_token", None):
            self._client.access_token = resp.access_token
        logger.info(
            "MatrixChannel: logged in as %s (password, device=%s, "
            "device_name=%s)",
            self._user_id,
            getattr(self._client, "device_id", ""),
            self.device_name,
        )
        self._save_auth_state()
        if self.encryption and self._client.store_path:
            if self._client.device_id:
                self._client.load_store()
                logger.info(
                    "MatrixChannel: crypto store loaded from %s",
                    self._client.store_path,
                )
            else:
                logger.warning(
                    "MatrixChannel: password login returned no "
                    "device_id; E2EE store may not be reusable",
                )

    async def _login_with_password(
        self,
        login_user: str,
        resolved_device_id: str,
    ) -> bool:
        login_kwargs = self._password_login_kwargs_for_nio(
            login_user,
            resolved_device_id,
        )
        attempts = self._password_login_attempts(
            login_user,
            login_kwargs,
            resolved_device_id,
        )
        resp, last_exc = await self._try_password_login_variants(attempts)
        if last_exc is not None:
            raise last_exc
        if isinstance(resp, LoginResponse):
            self._handle_password_login_success(resp)
            return True
        logger.error("MatrixChannel: password login failed: %s", resp)
        return False

    async def _login_with_access_token(self) -> bool:
        self._client.access_token = self.access_token
        whoami = await self._client.whoami()
        if isinstance(whoami, WhoamiResponse):
            if self.matrix_user_id and self.matrix_user_id != whoami.user_id:
                logger.error(
                    "MatrixChannel: configured user_id=%s does not match "
                    "access_token owner=%s; refusing stale credentials",
                    self.matrix_user_id,
                    whoami.user_id,
                )
                return False
            self._user_id = whoami.user_id
            self._client.user_id = whoami.user_id
            self._client.user = whoami.user_id
            # E2EE requires device_id to associate Olm keys with this
            # device
            if whoami.device_id:
                self._client.device_id = whoami.device_id
            logger.info(
                "MatrixChannel: logged in as %s (token, device=%s)",
                self._user_id,
                whoami.device_id,
            )
            self._save_auth_state()
            # Load crypto store after user_id and device_id are set
            if self.encryption and self._client.store_path:
                if self._client.device_id:
                    self._client.load_store()
                    logger.info(
                        "MatrixChannel: crypto store loaded from %s",
                        self._client.store_path,
                    )
                else:
                    logger.error(
                        "MatrixChannel: E2EE enabled but whoami returned "
                        "no device_id — encryption disabled "
                        "(token may lack device scope)",
                    )
                    self.encryption = False
            return True
        logger.error("MatrixChannel: token login failed: %s", whoami)
        return False

    def _register_plain_room_callbacks(self) -> None:
        self._client.add_event_callback(
            self._on_room_event,
            (RoomMessageText,),
        )
        self._client.add_event_callback(
            self._on_room_media_event,
            (
                RoomMessageImage,
                RoomMessageFile,
                RoomMessageAudio,
                RoomMessageVideo,
            ),
        )

    async def _setup_e2ee_after_login(self) -> bool:
        if not self.encryption:
            return True
        if self._client.should_upload_keys:
            resp = await self._client.keys_upload()
            if not isinstance(resp, KeysUploadResponse):
                logger.error(
                    "MatrixChannel: E2E keys upload failed after login: %s",
                    resp,
                )
                return False
            logger.info("MatrixChannel: E2E keys uploaded")
        # Encrypted media events (decrypted by nio, delivered as
        # RoomEncrypted* types)
        self._client.add_event_callback(
            self._on_room_encrypted_media_event,
            (
                RoomEncryptedImage,
                RoomEncryptedAudio,
                RoomEncryptedVideo,
                RoomEncryptedFile,
            ),
        )
        # Undecryptable events (missing session key)
        self._client.add_event_callback(
            self._on_megolm_event,
            (MegolmEvent,),
        )
        self._client.add_to_device_callback(
            self._on_key_verification_event,
            (KeyVerificationEvent,),
        )
        self._client.add_to_device_callback(
            self._on_to_device_probe_event,
            (ToDeviceEvent,),
        )
        self._client.add_to_device_callback(
            self._on_room_key_request_event,
            (
                RoomKeyRequest,
                RoomKeyRequestCancellation,
            ),
        )
        logger.info(
            "MatrixChannel: key verification to-device callback registered",
        )
        logger.info(
            "MatrixChannel: E2EE enabled, encrypted event handlers registered",
        )
        return True

    async def start(self) -> None:
        if not self.homeserver:
            logger.warning(
                "MatrixChannel: homeserver not configured, skipping",
            )
            return
        self._preflight_e2ee_dependencies()
        login_user = (self.matrix_user_id or "").strip()
        has_password_creds = bool(login_user and self.password)
        has_token_cred = bool(self.access_token)
        self._restore_auth_state_before_start(
            has_password_creds=has_password_creds,
            has_token_cred=has_token_cred,
        )
        resolved_device_id = (
            self.device_id
            or self._derive_device_id_from_name(self.device_name)
        )
        self._init_async_client(resolved_device_id)

        if has_password_creds:
            if not await self._login_with_password(
                login_user,
                resolved_device_id,
            ):
                return
        elif self.access_token:
            if not await self._login_with_access_token():
                return
        else:
            logger.error("MatrixChannel: no credentials configured")
            return

        self._register_plain_room_callbacks()
        if not await self._setup_e2ee_after_login():
            return

        self._http_client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=60,
        )

        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("MatrixChannel: sync loop started")

    async def stop(self) -> None:
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                logger.debug("MatrixChannel: sync task cancelled during stop")
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        if self._client:
            await self._client.close()
        logger.info("MatrixChannel: stopped")

    # ------------------------------------------------------------------
    # Sync loop — token persistence, catch-up, incremental sync, E2EE
    # maintenance
    # catch-up sync suppresses replay; incremental sync; E2EE maintenance
    # between syncs when encryption on.
    # ------------------------------------------------------------------

    @staticmethod
    def _sync_token_path() -> Optional[Path]:
        """Return the file path for persisting the Matrix sync token."""
        return WORKING_DIR / "matrix_sync_token"

    @staticmethod
    def _auth_state_path() -> Path:
        """Return the file path for persisted Matrix auth state."""
        return WORKING_DIR / "matrix_auth_state.json"

    def _load_auth_state(
        self,
        restore_token: bool = True,
        restore_identity: bool = True,
    ) -> None:
        """Best-effort load persisted access_token/user_id/device_id."""
        path = self._auth_state_path()
        if not path.exists():
            return
        try:
            import json

            payload = json.loads(path.read_text())
            restored_any = False
            if restore_token and not self.access_token:
                self.access_token = str(payload.get("access_token", ""))
                restored_any = bool(self.access_token)
            if restore_identity:
                if not self.matrix_user_id:
                    self.matrix_user_id = str(payload.get("user_id", ""))
                    restored_any = restored_any or bool(self.matrix_user_id)
                if not self.device_id:
                    self.device_id = str(payload.get("device_id", ""))
                    restored_any = restored_any or bool(self.device_id)
            if restored_any:
                logger.info(
                    "MatrixChannel: restored auth state from %s "
                    "(token=%s, user=%s, device=%s)",
                    path,
                    bool(self.access_token),
                    self.matrix_user_id or "<unknown>",
                    self.device_id or "<unknown>",
                )
            else:
                logger.debug(
                    "MatrixChannel: auth state present at %s but not applied "
                    "(restore_token=%s restore_identity=%s)",
                    path,
                    restore_token,
                    restore_identity,
                )
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to load auth state from %s: %s",
                path,
                exc,
            )

    def _save_auth_state(self) -> None:
        """Persist access_token/user_id/device_id for stable restarts."""
        if not self._client:
            return
        token = getattr(self._client, "access_token", "") or ""
        user_id = getattr(self._client, "user_id", "") or self._user_id or ""
        device_id = getattr(self._client, "device_id", "") or ""
        if not token or not user_id:
            return
        try:
            import json

            payload = {
                "access_token": token,
                "user_id": user_id,
                "device_id": device_id,
            }
            path = self._auth_state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload))
            self.access_token = token
            self.matrix_user_id = user_id
            if device_id:
                self.device_id = device_id
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to persist auth state: %s",
                exc,
            )

    def _load_sync_token(self) -> Optional[str]:
        """Load persisted next_batch token from disk, or None.

        The token file is pulled from MinIO by FileSync.pull_all() during
        startup, so it's already on disk when this runs — even on a fresh
        container after destroy/recreate.
        """
        path = self._sync_token_path()
        if path and path.exists():
            try:
                token = path.read_text().strip()
                if token:
                    logger.info(
                        "MatrixChannel: restored sync token from %s",
                        path,
                    )
                    return token
            except Exception as exc:
                logger.warning(
                    "MatrixChannel: failed to read sync token: %s",
                    exc,
                )
        return None

    def _save_sync_token(self, token: str) -> None:
        """Persist next_batch token to disk (push_loop uploads it to MinIO)."""
        path = self._sync_token_path()
        if path:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(token)
            except Exception as exc:
                logger.warning(
                    "MatrixChannel: failed to save sync token: %s",
                    exc,
                )

    async def _e2ee_maintenance(self) -> None:
        """Perform E2EE key maintenance tasks after each sync.

        Mirrors what nio's sync_forever() does between syncs:
        - Upload device keys when needed
        - Query device keys for new/changed users
        - Claim one-time keys to establish Olm sessions
        - Send outgoing to-device messages (key shares, key requests)
        """
        if not self.encryption or not self._client or not self._client.olm:
            return
        try:
            if self._client.should_upload_keys:
                await self._client.keys_upload()
            if self._client.should_query_keys:
                await self._client.keys_query()
            if self._client.should_claim_keys:
                await self._client.keys_claim(
                    self._client.get_users_for_key_claiming(),
                )
            await self._client.send_to_device_messages()
        except Exception as exc:
            logger.warning("MatrixChannel: E2EE maintenance error: %s", exc)

    async def _on_key_verification_event(
        self,
        event: KeyVerificationEvent,
    ) -> None:
        """Complete the bot side of an Element SAS verification challenge."""
        if not self._client or not self._client.olm:
            logger.info(
                "MatrixChannel: verification event received "
                "but olm is not ready (event=%s, tx=%s, sender=%s)",
                type(event).__name__,
                getattr(event, "transaction_id", ""),
                getattr(event, "sender", ""),
            )
            return

        try:
            logger.info(
                "MatrixChannel: verification event received "
                "(event=%s, tx=%s, sender=%s, from_device=%s)",
                type(event).__name__,
                getattr(event, "transaction_id", ""),
                getattr(event, "sender", ""),
                getattr(event, "from_device", ""),
            )
            if isinstance(event, KeyVerificationStart):
                await self._handle_key_verification_start(event)
            elif isinstance(event, KeyVerificationKey):
                await self._handle_key_verification_key(event)
            elif isinstance(event, KeyVerificationMac):
                sas = self._client.key_verifications.get(event.transaction_id)
                logger.info(
                    "MatrixChannel: key verification MAC received "
                    "(tx=%s, verified=%s, verified_devices=%s)",
                    event.transaction_id,
                    getattr(sas, "verified", False),
                    getattr(sas, "verified_devices", []),
                )
                if getattr(sas, "verified", False):
                    await self._send_verification_done(event.transaction_id)
            elif isinstance(event, KeyVerificationCancel):
                known_tx = event.transaction_id in getattr(
                    self._client,
                    "key_verifications",
                    {},
                )
                if known_tx:
                    logger.info(
                        "MatrixChannel: key verification cancelled by %s "
                        "(tx=%s, reason=%s)",
                        event.sender,
                        event.transaction_id,
                        getattr(event, "reason", ""),
                    )
                else:
                    logger.info(
                        "MatrixChannel: key verification cancelled for "
                        "unknown key verification tx=%s from %s (reason=%s)",
                        event.transaction_id,
                        event.sender,
                        getattr(event, "reason", ""),
                    )
            else:
                logger.info(
                    "MatrixChannel: unhandled verification event type=%s "
                    "(tx=%s, sender=%s)",
                    type(event).__name__,
                    getattr(event, "transaction_id", ""),
                    getattr(event, "sender", ""),
                )
        except Exception as exc:
            logger.warning(
                "MatrixChannel: key verification handling failed: %s",
                exc,
            )

    async def _on_to_device_probe_event(
        self,
        event: ToDeviceEvent,
    ) -> None:
        """Probe raw to-device verification event types for troubleshooting."""
        raw_type = getattr(event, "type", "")
        if not raw_type:
            raw_type = getattr(event, "source", {}).get("type", "")
        if not isinstance(raw_type, str) or not raw_type.startswith(
            "m.key.verification.",
        ):
            return
        logger.info(
            "MatrixChannel: raw to-device verification event "
            "(type=%s, parsed=%s, sender=%s)",
            raw_type,
            type(event).__name__,
            getattr(event, "sender", ""),
        )
        if raw_type in (
            "m.key.verification.request",
            "m.key.verification.ready",
        ):
            logger.warning(
                "MatrixChannel: homeserver sent %s but current matrix-nio "
                "cannot parse it into KeyVerificationEvent; handling via "
                "raw to-device compatibility path",
                raw_type,
            )
        if raw_type == "m.key.verification.request":
            await self._handle_unknown_key_verification_request(event)
        elif raw_type == "m.key.verification.done":
            await self._handle_unknown_key_verification_done(event)

    async def _on_room_key_request_event(
        self,
        event: RoomKeyRequest | RoomKeyRequestCancellation,
    ) -> None:
        """Log room-key request events that often require manual review."""
        if isinstance(event, RoomKeyRequest):
            logger.warning(
                "MatrixChannel: room key request received; other device may "
                "show 'Review' until trust decision is made "
                "(sender=%s device=%s request_id=%s room_id=%s session_id=%s)",
                event.sender,
                event.requesting_device_id,
                event.request_id,
                getattr(event, "room_id", ""),
                getattr(event, "session_id", ""),
            )
        else:
            logger.info(
                "MatrixChannel: room key request cancelled "
                "(sender=%s device=%s request_id=%s)",
                event.sender,
                event.requesting_device_id,
                event.request_id,
            )

    async def _handle_unknown_key_verification_request(
        self,
        event: ToDeviceEvent,
    ) -> None:
        """Compat path for m.key.verification.request on older matrix-nio."""
        if not self._client or not self._client.olm:
            return

        source = getattr(event, "source", {}) or {}
        content = source.get("content", {}) or {}
        sender = getattr(event, "sender", "")
        from_device = str(content.get("from_device", "") or "")
        transaction_id = str(content.get("transaction_id", "") or "")
        methods = content.get("methods", []) or []

        request_key = f"{sender}|{from_device}|{transaction_id}"
        if request_key in self._handled_verification_requests:
            logger.debug(
                "MatrixChannel: verification request already handled "
                "(sender=%s, device=%s, tx=%s)",
                sender,
                from_device,
                transaction_id,
            )
            return
        self._handled_verification_requests.add(request_key)

        if not sender or not from_device:
            logger.warning(
                "MatrixChannel: cannot handle verification request without "
                "sender/device (sender=%s, device=%s, tx=%s)",
                sender,
                from_device,
                transaction_id,
            )
            return

        self._verification_tx_peers[transaction_id] = (sender, from_device)

        our_device = getattr(self._client, "device_id", "") or ""
        if not our_device:
            logger.warning(
                "MatrixChannel: cannot reply verification request without "
                "local device_id (sender=%s, device=%s, tx=%s)",
                sender,
                from_device,
                transaction_id,
            )
            return

        ready_content = {
            "from_device": our_device,
            "methods": ["m.sas.v1"],
            "transaction_id": transaction_id,
        }
        ready_message = ToDeviceMessage(
            "m.key.verification.ready",
            sender,
            from_device,
            ready_content,
        )
        try:
            resp = await self._client.to_device(ready_message)
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to send verification ready "
                "(sender=%s, device=%s, tx=%s): %s",
                sender,
                from_device,
                transaction_id,
                exc,
            )
            return

        if isinstance(resp, ToDeviceError):
            logger.warning(
                "MatrixChannel: homeserver rejected verification ready "
                "(sender=%s, device=%s, tx=%s): %s",
                sender,
                from_device,
                transaction_id,
                resp,
            )
            return

        logger.info(
            "MatrixChannel: sent verification ready for request "
            "(sender=%s, device=%s, tx=%s, methods=%s)",
            sender,
            from_device,
            transaction_id,
            methods,
        )

    async def _handle_unknown_key_verification_done(
        self,
        event: ToDeviceEvent,
    ) -> None:
        """Handle done event emitted as UnknownToDeviceEvent on older nio."""
        source = getattr(event, "source", {}) or {}
        content = source.get("content", {}) or {}
        tx = str(content.get("transaction_id", "") or "")
        if not tx:
            return
        logger.info(
            "MatrixChannel: received verification done from %s (tx=%s)",
            getattr(event, "sender", ""),
            tx,
        )
        if tx not in self._sent_verification_done:
            await self._send_verification_done(tx)

    async def _handle_key_verification_start(
        self,
        event: KeyVerificationStart,
    ) -> None:
        """Accept Element's SAS start, querying device keys if needed."""
        if not self._client or not self._client.olm:
            return
        self._verification_tx_peers[event.transaction_id] = (
            event.sender,
            event.from_device,
        )

        if event.transaction_id not in self._client.key_verifications:
            await self._recover_key_verification_start(event)

        if event.transaction_id not in self._client.key_verifications:
            logger.warning(
                "MatrixChannel: cannot accept key verification from %s "
                "(device=%s, tx=%s) because no SAS state exists yet; "
                "retry verification after the next sync",
                event.sender,
                event.from_device,
                event.transaction_id,
            )
            return

        try:
            resp = await self._client.accept_key_verification(
                event.transaction_id,
            )
        except LocalProtocolError as exc:
            logger.warning(
                "MatrixChannel: accept_key_verification failed for tx=%s: %s",
                event.transaction_id,
                exc,
            )
            return

        if isinstance(resp, ToDeviceError):
            logger.warning(
                "MatrixChannel: accept_key_verification failed for tx=%s: %s",
                event.transaction_id,
                resp,
            )
            return

        logger.info(
            "MatrixChannel: accepted key verification from %s "
            "(device=%s, tx=%s)",
            event.sender,
            event.from_device,
            event.transaction_id,
        )

    async def _send_verification_done(self, transaction_id: str) -> None:
        """Send m.key.verification.done for runtimes lacking done helpers."""
        if (
            not self._client
            or not transaction_id
            or transaction_id in self._sent_verification_done
        ):
            return

        peer = self._verification_tx_peers.get(transaction_id)
        if not peer:
            logger.warning(
                "MatrixChannel: cannot send verification done for tx=%s "
                "because peer device is unknown",
                transaction_id,
            )
            return

        sender, device_id = peer
        done_message = ToDeviceMessage(
            "m.key.verification.done",
            sender,
            device_id,
            {"transaction_id": transaction_id},
        )
        try:
            resp = await self._client.to_device(done_message)
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to send verification done "
                "(tx=%s, sender=%s, device=%s): %s",
                transaction_id,
                sender,
                device_id,
                exc,
            )
            return

        if isinstance(resp, ToDeviceError):
            logger.warning(
                "MatrixChannel: homeserver rejected verification done "
                "(tx=%s, sender=%s, device=%s): %s",
                transaction_id,
                sender,
                device_id,
                resp,
            )
            return

        self._sent_verification_done.add(transaction_id)
        logger.info(
            "MatrixChannel: sent verification done "
            "(tx=%s, sender=%s, device=%s)",
            transaction_id,
            sender,
            device_id,
        )

    async def _recover_key_verification_start(
        self,
        event: KeyVerificationStart,
    ) -> None:
        """Re-process start event after matrix-nio queried unknown devices."""
        assert self._client is not None
        assert self._client.olm is not None

        try:
            if self._client.should_query_keys:
                await self._client.keys_query()
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to query keys for verification "
                "from %s: %s",
                event.sender,
                exc,
            )
            return

        try:
            self._client.olm.handle_key_verification(event)
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to rebuild key verification state "
                "for tx=%s: %s",
                event.transaction_id,
                exc,
            )

    async def _handle_key_verification_key(
        self,
        event: KeyVerificationKey,
    ) -> None:
        """Log the SAS challenge and confirm the bot side."""
        if not self._client:
            return

        sas = self._client.key_verifications.get(event.transaction_id)
        if sas is None:
            logger.warning(
                "MatrixChannel: key verification key for unknown tx=%s "
                "from %s; ask Element to restart verification",
                event.transaction_id,
                event.sender,
            )
            return

        logger.warning(
            "MatrixChannel: Element key verification challenge from %s "
            "(tx=%s): %s",
            event.sender,
            event.transaction_id,
            self._format_sas_challenge(sas),
        )

        # Receiving Key queues share_key in nio; flush it before sending MAC.
        await self._client.send_to_device_messages()
        try:
            resp = await self._client.confirm_short_auth_string(
                event.transaction_id,
            )
        except LocalProtocolError as exc:
            logger.warning(
                "MatrixChannel: confirm_short_auth_string failed "
                "for tx=%s: %s",
                event.transaction_id,
                exc,
            )
            return

        if isinstance(resp, ToDeviceError):
            logger.warning(
                "MatrixChannel: confirm_short_auth_string failed "
                "for tx=%s: %s",
                event.transaction_id,
                resp,
            )
            return

        logger.info(
            "MatrixChannel: confirmed local SAS side for tx=%s; "
            "compare the challenge in Element and accept there if it matches",
            event.transaction_id,
        )

    @staticmethod
    def _format_sas_challenge(sas: Any) -> str:
        """Return a human-readable SAS challenge for logs."""
        parts: list[str] = []

        get_emoji = getattr(sas, "get_emoji", None)
        if callable(get_emoji):
            try:
                emojis = get_emoji()
                if emojis:
                    parts.append(
                        "emoji="
                        + " ".join(
                            f"{symbol}({description})"
                            for symbol, description in emojis
                        ),
                    )
            except Exception as exc:
                logger.debug("MatrixChannel: get_emoji failed: %s", exc)

        get_decimal = getattr(sas, "get_decimal", None)
        if callable(get_decimal):
            try:
                decimals = get_decimal()
                if decimals:
                    parts.append(
                        "decimal=" + " ".join(str(n) for n in decimals),
                    )
            except Exception as exc:
                logger.debug("MatrixChannel: get_decimal failed: %s", exc)

        return "; ".join(parts) if parts else "unavailable"

    # pylint: disable=too-many-branches,too-many-statements
    async def _sync_loop(self) -> None:
        next_batch: Optional[str] = self._load_sync_token()

        # When no persisted token exists (old version upgrade or first
        # deploy), do an initial sync with callbacks suppressed — only capture
        # next_batch so subsequent syncs are incremental.  This prevents
        # replaying old messages when the token file doesn't exist yet.
        #
        # To truly suppress callbacks, temporarily remove event callbacks
        # before the sync and restore them after, because nio's sync()
        # internally calls receive_response() which fires callbacks.
        if next_batch is None:
            logger.info(
                "MatrixChannel: no sync token found, "
                "performing catch-up sync (messages suppressed)",
            )
            try:
                saved_cbs = self._client.event_callbacks[:]
                self._client.event_callbacks.clear()
                try:
                    resp = await self._client.sync(
                        timeout=self.sync_timeout_ms,
                        full_state=True,
                    )
                finally:
                    self._client.event_callbacks.extend(saved_cbs)
                if isinstance(resp, SyncResponse):
                    next_batch = resp.next_batch
                    if next_batch is not None:
                        self._save_sync_token(next_batch)
                    # Still auto-join invited rooms during catch-up
                    for room_id in resp.rooms.invite:
                        logger.info("MatrixChannel: auto-joining %s", room_id)
                        await self._client.join(room_id)
                    await self._e2ee_maintenance()
                    logger.info(
                        "MatrixChannel: catch-up sync done, "
                        "will process messages from next sync",
                    )
                else:
                    logger.warning(
                        "MatrixChannel: catch-up sync error: %s",
                        resp,
                    )
            except Exception as exc:
                logger.exception(
                    "MatrixChannel: catch-up sync exception: %s",
                    exc,
                )
        else:
            # Restored from token — do a full_state sync to populate room
            # member display names (nio needs full state for user_name()).
            # Event callbacks are already registered so any messages received
            # during the offline window will be processed normally.
            logger.info(
                "MatrixChannel: restored token, "
                "performing full-state sync to load room state",
            )
            try:
                resp = await self._client.sync(
                    timeout=self.sync_timeout_ms,
                    since=next_batch,
                    full_state=True,
                )
                if isinstance(resp, SyncResponse):
                    next_batch = resp.next_batch
                    if next_batch is not None:
                        self._save_sync_token(next_batch)
                    for room_id in resp.rooms.invite:
                        logger.info("MatrixChannel: auto-joining %s", room_id)
                        await self._client.join(room_id)
                    await self._e2ee_maintenance()
                else:
                    logger.warning(
                        "MatrixChannel: full-state sync error: %s",
                        resp,
                    )
            except Exception as exc:
                logger.exception(
                    "MatrixChannel: full-state sync exception: %s",
                    exc,
                )

        while True:
            try:
                resp = await self._client.sync(
                    timeout=self.sync_timeout_ms,
                    since=next_batch,
                    full_state=False,
                )
                if isinstance(resp, SyncResponse):
                    next_batch = resp.next_batch
                    if next_batch is not None:
                        self._save_sync_token(next_batch)
                    # Auto-join invited rooms
                    for room_id in resp.rooms.invite:
                        logger.info("MatrixChannel: auto-joining %s", room_id)
                        await self._client.join(room_id)
                    # E2EE: full key maintenance (upload, query, claim,
                    # to-device)
                    await self._e2ee_maintenance()
                else:
                    if isinstance(resp, SyncError) and getattr(
                        resp,
                        "status_code",
                        None,
                    ) in {"M_UNKNOWN_TOKEN", "M_MISSING_TOKEN"}:
                        logger.error(
                            "MatrixChannel: sync stopped due to "
                            "invalid/missing access token; please re-login "
                            "(password or fresh token)",
                        )
                        if self._client:
                            self._client.access_token = ""
                        self.access_token = ""
                        return
                    logger.warning("MatrixChannel: sync error: %s", resp)
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.debug("MatrixChannel: sync loop cancelled")
                raise
            except Exception as exc:
                logger.exception("MatrixChannel: sync exception: %s", exc)
                await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Channel-level mute, per-room requireMention, strip @mention prefix
    # ------------------------------------------------------------------

    def _is_channel_disabled(
        self,
        sender_id: str,
        room_id: str,
        is_dm: bool,
    ) -> bool:
        """Return True if chat type is muted at channel level."""
        if is_dm and self.dm_disabled:
            logger.warning(
                "MatrixChannel: dropping DM message (dm_disabled) "
                "sender=%s room=%s",
                sender_id,
                room_id,
            )
            return True
        if not is_dm and self.group_disabled:
            logger.warning(
                "MatrixChannel: dropping group message (group_disabled) "
                "sender=%s room=%s",
                sender_id,
                room_id,
            )
            return True
        return False

    def _require_mention(self, room_id: str) -> bool:
        """Per-room config; default is require mention in group rooms."""
        room_cfg = self.groups.get(room_id) or self.groups.get("*")
        if room_cfg:
            if room_cfg.get("autoReply") is True:
                return False
            if "requireMention" in room_cfg:
                return bool(room_cfg["requireMention"])
        return True  # default: require mention in group rooms

    # pylint: disable=too-many-return-statements
    def _was_mentioned(self, event: Any, text: str) -> bool:
        if not self._user_id:
            return False
        # 1. Check m.mentions (structured mention from Matrix spec)
        content = event.source.get("content", {})
        mentions = content.get("m.mentions", {})
        if self._user_id in mentions.get("user_ids", []):
            return True
        if mentions.get("room"):
            return True
        # 2. formatted_body: matrix.to mention links (Element HTML format)
        formatted_body = content.get("formatted_body", "")
        if formatted_body and self._user_id:
            escaped_uid = re.escape(self._user_id)
            if re.search(
                rf'href=["\']https://matrix\.to/#/{escaped_uid}["\']',
                formatted_body,
                re.IGNORECASE,
            ):
                return True
            encoded_uid = re.escape(urllib.parse.quote(self._user_id))
            if re.search(
                rf'href=["\']https://matrix\.to/#/{encoded_uid}["\']',
                formatted_body,
                re.IGNORECASE,
            ):
                return True
        # 3. Fallback: match full MXID in plain text
        if self._user_id and re.search(
            re.escape(self._user_id),
            text,
            re.IGNORECASE,
        ):
            return True
        return False

    def _strip_mention_prefix(self, text: str, room: Any = None) -> str:
        """Strip leading @mention prefix so slash commands can be detected.

        Handles MXID format (@user:server), room display name, and localpart.
        E.g. ``"@worker:hs.example /new"`` → ``"/new"``
             ``"math 💕: /clear"`` → ``"/clear"``.
        """
        if not self._user_id:
            return text
        # 1. Strip MXID (@user:server) at start
        escaped = re.escape(self._user_id)
        result = re.sub(rf"^{escaped}\s*:?\s*", "", text, flags=re.IGNORECASE)
        if result != text:
            return result.strip()
        # 2. Strip room display name (e.g. "math 💕") at start — try before
        #    localpart so that "math 💕: /clear" is not partially matched by
        #    the shorter localpart "math".
        if room and self._user_id:
            display_name = self._get_display_name(room, self._user_id)
            logger.debug(
                "strip_mention_prefix: user_id=%s display_name=%r "
                "room_users=%d",
                self._user_id,
                display_name,
                len(getattr(room, "users", {})),
            )
            if display_name and display_name != self._user_id:
                result = re.sub(
                    rf"^{re.escape(display_name)}\s*:?\s*",
                    "",
                    text,
                    flags=re.IGNORECASE,
                )
                if result != text:
                    # Clean leftover decoration (e.g. emoji suffix) between
                    # the display name and the actual message content.
                    result = re.sub(r"^[^\w/]+", "", result)
                    return result.strip()
        # 3. Strip localpart (e.g. "math") at start — only if display name
        #    didn't match.
        localpart = self._user_id.split(":")[0].lstrip("@")
        if localpart:
            result = re.sub(
                rf"^{re.escape(localpart)}\s*:?\s*",
                "",
                text,
                flags=re.IGNORECASE,
            )
            if result != text:
                # After stripping localpart, there may be leftover decoration
                # from the display name (e.g. emoji suffix "💕: " from
                # "math 💕: /clear").  Strip non-alphanumeric prefix so the
                # slash command is exposed.
                result = re.sub(r"^[^\w/]+", "", result)
                return result.strip()
        return text

    # ------------------------------------------------------------------
    # Display names & group history buffer (requireMention context)
    # display names from room / client.rooms (§5–§6);
    # per-room history buffer + history_limit; media_parts in buffer when
    # applicable; prefix merged into AgentRequest on mention (§6).
    # ------------------------------------------------------------------

    def _get_display_name(self, room: Any, user_id: str) -> str:
        """Best-effort human-readable name for a Matrix user in *room*.

        Tries the room object passed by nio first, then falls back to
        looking up the room in the nio client's rooms dict (which is
        populated by full_state sync at startup).
        """
        # 1. Try the room object directly (passed by nio callback)
        try:
            name = room.user_name(user_id)
            if name:
                return name
        except Exception as exc:
            logger.debug(
                "MatrixChannel: user_name failed for %s: %s",
                user_id,
                exc,
            )
        # 2. Fallback: look up from nio client's rooms dict
        if self._client:
            room_id = getattr(room, "room_id", None)
            if room_id:
                client_room = self._client.rooms.get(room_id)
                if client_room and client_room is not room:
                    try:
                        name = client_room.user_name(user_id)
                        if name:
                            logger.debug(
                                "display_name resolved via client.rooms "
                                "fallback: %s -> %r",
                                user_id,
                                name,
                            )
                            return name
                    except Exception as exc:
                        logger.debug(
                            "MatrixChannel: client_room user_name failed "
                            "for %s: %s",
                            user_id,
                            exc,
                        )
        # 3. Fallback: localpart of MXID (e.g. "@alice:hs" → "alice")
        logger.debug(
            "display_name fallback to localpart for %s "
            "(room.users=%d, client_rooms=%d)",
            user_id,
            len(getattr(room, "users", {})),
            len(self._client.rooms) if self._client else 0,
        )
        return user_id.split(":")[0].lstrip("@") or user_id

    def _record_history(self, room_id: str, entry: HistoryEntry) -> None:
        """Append *entry* to the per-room history buffer (respect limit)."""
        limit = self.history_limit
        if limit <= 0:
            return
        history = self._room_histories.setdefault(room_id, [])
        history.append(entry)
        while len(history) > limit:
            history.pop(0)

    def _build_history_prefix(self, room_id: str) -> str:
        """Format buffered history entries as a multi-line text block."""
        entries = self._room_histories.get(room_id, [])
        if not entries:
            return ""
        lines: list[str] = []
        for e in entries:
            line = f"{e.sender}: {e.body}"
            if e.message_id:
                line += f" [id:{e.message_id}]"
            lines.append(line)
        return "\n".join(lines)

    def _apply_history_to_parts(
        self,
        room_id: str,
        content_parts: list[Any],
    ) -> list[Any]:
        """Prepend accumulated history context to *content_parts*.

        If the first part is text, the history block is merged into it;
        otherwise a new text part is prepended.  Any media parts stored
        in history entries (e.g. downloaded images) are inserted between
        the history text block and the current message parts so that
        vision models can see them.

        Returns a (possibly new) list — the original is not mutated.
        """
        if self.history_limit <= 0:
            return content_parts
        history_text = self._build_history_prefix(room_id)
        if not history_text:
            return content_parts

        # Collect media content parts carried by history entries
        history_media: list[Any] = []
        for entry in self._room_histories.get(room_id, []):
            if entry.media_parts:
                history_media.extend(entry.media_parts)

        # Merge into the leading text part when possible
        first = content_parts[0] if content_parts else None
        if first and getattr(first, "type", None) == ContentType.TEXT:
            current_text = first.text or ""
            combined = (
                f"{HISTORY_CONTEXT_MARKER}\n{history_text}\n\n"
                f"{CURRENT_MESSAGE_MARKER}\n{current_text}"
            )
            return (
                [TextContent(type=ContentType.TEXT, text=combined)]
                + history_media
                + content_parts[1:]
            )
        # No leading text part (e.g. pure media) — prepend a dedicated block
        prefix_part = TextContent(
            type=ContentType.TEXT,
            text=(
                f"{HISTORY_CONTEXT_MARKER}\n{history_text}\n\n"
                f"{CURRENT_MESSAGE_MARKER}"
            ),
        )
        return [prefix_part] + history_media + content_parts

    def _clear_history(self, room_id: str) -> None:
        """Drop the buffered history for *room_id*."""
        self._room_histories.pop(room_id, None)

    async def _record_media_history(
        self,
        room: Any,
        event: Any,
        sender_id: str,
        room_id: str,
    ) -> None:
        """Record a non-mentioned media message as a history entry.

        Produces a typed text description (e.g. ``[sent an image: photo.jpg]``)
        and, for images when vision is enabled, downloads the actual file so it
        can be included as an image content part later.
        """
        body = event.body or ""
        media_parts: list[Any] = []

        if isinstance(event, RoomMessageImage):
            body_desc = (
                f"[sent an image: {body}]" if body else "[sent an image]"
            )
            if self.vision_enabled:
                mxc_url: str = getattr(event, "url", "") or ""
                if mxc_url:
                    eid = event.event_id[:8].lstrip("$")
                    filename = body or f"matrix_media_{eid}"
                    filename = f"{eid}_{filename}"
                    local_path = await self._download_mxc(mxc_url, filename)
                    if local_path:
                        media_parts.append(
                            ImageContent(
                                type=ContentType.IMAGE,
                                image_url=Path(local_path).as_uri(),
                            ),
                        )
        elif isinstance(event, RoomMessageFile):
            body_desc = f"[sent a file: {body}]" if body else "[sent a file]"
            mxc_url = getattr(event, "url", "") or ""
            if mxc_url:
                eid = event.event_id[:8].lstrip("$")
                filename = body or f"matrix_media_{eid}"
                filename = f"{eid}_{filename}"
                local_path = await self._download_mxc(mxc_url, filename)
                if local_path:
                    media_parts.append(
                        FileContent(
                            type=ContentType.FILE,
                            file_url=Path(local_path).as_uri(),
                            filename=body or filename,
                        ),
                    )
        elif isinstance(event, RoomMessageAudio):
            body_desc = f"[sent audio: {body}]" if body else "[sent audio]"
        elif isinstance(event, RoomMessageVideo):
            body_desc = f"[sent a video: {body}]" if body else "[sent a video]"
        else:
            body_desc = body or "[media]"

        self._record_history(
            room_id,
            HistoryEntry(
                sender=self._get_display_name(room, sender_id),
                body=body_desc,
                timestamp=getattr(event, "server_timestamp", None),
                message_id=event.event_id,
                media_parts=media_parts or None,
            ),
        )

    # ------------------------------------------------------------------
    # Media — local dirs, mxc download, E2EE decrypt, inbound handlers
    # local media dir; mxc fetch; AES decrypt for
    # encrypted attachments; cleartext + RoomEncrypted* inbound paths (§7).
    # ------------------------------------------------------------------

    def _media_dir(self) -> Path:
        """Return (and create) the local media storage directory."""
        if self._workspace_dir:
            return self._workspace_dir / "media"
        return WORKING_DIR / "media"

    def _mxc_to_http(self, mxc_url: str) -> str:
        """Convert an mxc:// URL to an HTTP download URL.

        Returns the original URL unchanged if it is not an mxc:// URL or if
        the format is invalid.
        """
        if not mxc_url:
            return mxc_url
        if not mxc_url.startswith("mxc://"):
            return mxc_url
        rest = mxc_url[6:]  # strip "mxc://"
        if "/" not in rest:
            return mxc_url
        server, media_id = rest.split("/", 1)
        return (
            f"{self.homeserver}/_matrix/media/v3/download"
            f"/{server}/{media_id}"
        )

    async def _download_mxc(
        self,
        mxc_url: str,
        filename: str,
    ) -> Optional[str]:
        """Download mxc:// to a local file; return path or None."""
        if not mxc_url.startswith("mxc://"):
            return None
        try:
            rest = mxc_url[6:]  # strip "mxc://"
            server, media_id = rest.split("/", 1)
            url = (
                f"{self.homeserver}/_matrix/media/v3/download"
                f"/{server}/{media_id}"
            )
            headers = {"Authorization": f"Bearer {self.access_token}"}
            if not self._http_client:
                logger.warning("MatrixChannel: HTTP client not initialized")
                return None
            resp = await self._http_client.get(url, headers=headers)
            resp.raise_for_status()
            dest = self._media_dir() / filename
            dest.write_bytes(resp.content)
            logger.debug("MatrixChannel: downloaded %s → %s", mxc_url, dest)
            return str(dest)
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to download %s: %s",
                mxc_url,
                exc,
            )
            return None

    def _e2ee_store_path(self) -> Path:
        """Return the directory for persisting Olm/Megolm crypto state."""
        return WORKING_DIR / "matrix_crypto_store"

    async def _download_encrypted_mxc(
        self,
        mxc_url: str,
        filename: str,
        key: dict,
        hashes: dict,
        iv: str,
    ) -> Optional[str]:
        """Download an encrypted mxc:// URI, decrypt it, and save locally."""
        if not mxc_url.startswith("mxc://") or not self._client:
            return None
        try:
            rest = mxc_url[6:]
            server, media_id = rest.split("/", 1)
            url = (
                f"{self.homeserver}/_matrix/media/v3/download"
                f"/{server}/{media_id}"
            )
            headers = {"Authorization": f"Bearer {self.access_token}"}
            if not self._http_client:
                logger.warning("MatrixChannel: HTTP client not initialized")
                return None
            resp = await self._http_client.get(url, headers=headers)
            resp.raise_for_status()

            from nio.crypto.attachments import decrypt_attachment

            jwk_key = key.get("k", "")
            sha256_hash = hashes.get("sha256", "")
            plaintext = decrypt_attachment(
                resp.content,
                jwk_key,
                sha256_hash,
                iv,
            )

            dest = self._media_dir() / filename
            dest.write_bytes(plaintext)
            logger.debug(
                "MatrixChannel: downloaded+decrypted %s → %s",
                mxc_url,
                dest,
            )
            return str(dest)
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to download encrypted %s: %s",
                mxc_url,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Incoming E2EE — undecryptable log + decrypted media (§7)
    # MegolmEvent warning; RoomEncrypted* same allow/
    # history/vision path as cleartext media when nio decrypts (optional E2EE).
    # ------------------------------------------------------------------

    async def _on_megolm_event(
        self,
        room: MatrixRoom,
        event: MegolmEvent,
    ) -> None:
        """Handle undecryptable encrypted events (missing session key)."""
        logger.warning(
            "MatrixChannel: could not decrypt event %s in %s (session_id=%s)",
            event.event_id,
            room.room_id,
            getattr(event, "session_id", "?"),
        )

    # pylint: disable=too-many-branches,too-many-statements
    async def _on_room_encrypted_media_event(
        self,
        room: MatrixRoom,
        event: Any,
    ) -> None:
        """Handle decrypted encrypted media (RoomEncryptedImage, etc.).

        Delivered by matrix-nio after Megolm decrypt. File bytes are still
        AES-encrypted; download + decrypt with key/iv/hashes from the event.
        """
        if event.sender == self._user_id:
            return

        sender_id = event.sender
        room_id = room.room_id
        # Use Matrix API for reliable DM detection (room.users unreliable
        # after token restore)
        is_dm = await self._is_dm_room(room_id, sender_id, room)

        if self._is_channel_disabled(sender_id, room_id, is_dm):
            return

        if not is_dm:
            if self._require_mention(room_id) and not self._was_mentioned(
                event,
                "",
            ):
                # Record as history (text description only)
                body = event.body or ""
                if isinstance(event, RoomEncryptedImage):
                    desc = (
                        f"[sent an encrypted image: {body}]"
                        if body
                        else "[sent an encrypted image]"
                    )
                elif isinstance(event, RoomEncryptedAudio):
                    desc = (
                        f"[sent encrypted audio: {body}]"
                        if body
                        else "[sent encrypted audio]"
                    )
                elif isinstance(event, RoomEncryptedVideo):
                    desc = (
                        f"[sent an encrypted video: {body}]"
                        if body
                        else "[sent an encrypted video]"
                    )
                else:
                    desc = (
                        f"[sent an encrypted file: {body}]"
                        if body
                        else "[sent an encrypted file]"
                    )
                self._record_history(
                    room_id,
                    HistoryEntry(
                        sender=self._get_display_name(room, sender_id),
                        body=desc,
                        timestamp=getattr(event, "server_timestamp", None),
                        message_id=event.event_id,
                    ),
                )
                return

        await self._send_read_receipt(room_id, event.event_id)
        await self._send_typing(room_id, True)

        body = event.body or ""
        mxc_url = getattr(event, "url", "") or ""
        key = getattr(event, "key", {}) or {}
        hashes = getattr(event, "hashes", {}) or {}
        iv = getattr(event, "iv", "") or ""

        content_parts: list[Any] = []

        if mxc_url and key and iv:
            eid = event.event_id[:8].lstrip("$")
            filename = body or f"matrix_media_{eid}"
            filename = f"{eid}_{filename}"
            local_path = await self._download_encrypted_mxc(
                mxc_url,
                filename,
                key,
                hashes,
                iv,
            )
            if local_path:
                file_uri = Path(local_path).as_uri()
                if isinstance(event, RoomEncryptedImage):
                    if self.vision_enabled:
                        content_parts.append(
                            ImageContent(
                                type=ContentType.IMAGE,
                                image_url=file_uri,
                            ),
                        )
                    else:
                        _no_vis = (
                            "[User sent an image (current model does not "
                            f"support image input): {body or filename}]"
                        )
                        content_parts.append(
                            TextContent(
                                type=ContentType.TEXT,
                                text=_no_vis,
                            ),
                        )
                elif isinstance(event, RoomEncryptedAudio):
                    content_parts.append(
                        AudioContent(
                            type=ContentType.AUDIO,
                            data=file_uri,
                        ),
                    )
                elif isinstance(event, RoomEncryptedVideo):
                    content_parts.append(
                        VideoContent(
                            type=ContentType.VIDEO,
                            video_url=file_uri,
                        ),
                    )
                else:
                    content_parts.append(
                        FileContent(
                            type=ContentType.FILE,
                            file_url=file_uri,
                            filename=body or filename,
                        ),
                    )
            else:
                content_parts.append(
                    TextContent(
                        type=ContentType.TEXT,
                        text=f"[Encrypted media unavailable: {body}]",
                    ),
                )

        if not content_parts:
            return

        if not is_dm:
            # Prefix sender identity so the LLM can distinguish participants
            sender_name = self._get_display_name(room, sender_id)
            first = content_parts[0] if content_parts else None
            if first and getattr(first, "type", None) == ContentType.TEXT:
                content_parts[0] = TextContent(
                    type=ContentType.TEXT,
                    text=f"{sender_name}: {first.text}",
                )
            else:
                content_parts.insert(
                    0,
                    TextContent(
                        type=ContentType.TEXT,
                        text=f"{sender_name}:",
                    ),
                )
            content_parts = self._apply_history_to_parts(
                room_id,
                content_parts,
            )

        worker_name = (self._user_id or "").split(":")[0].lstrip("@")
        payload = {
            "channel_id": CHANNEL_KEY,
            "sender_id": sender_id,
            "content_parts": content_parts,
            "acl_sender_id": sender_id,
            "meta": {
                "room_id": room_id,
                "is_dm": is_dm,
                "is_group": not is_dm,
                "worker_name": worker_name,
                "event_id": event.event_id,
                "sender_id": sender_id,
                "user_name": self._get_display_name(room, sender_id),
            },
        }

        if self._enqueue:
            self._enqueue(payload)
            if not is_dm:
                self._clear_history(room_id)

    # ------------------------------------------------------------------
    # Media upload (local file → mxc://)
    # upload to homeserver media repo; shared by
    # send_media outbound path (same role as worker _upload_file).
    # ------------------------------------------------------------------

    async def _upload_file(self, file_ref: str) -> Optional[str]:
        """Upload a local file to Matrix; return mxc:// URI or None."""
        if not self._client:
            return None
        try:
            # file_ref may be a file:// URI or a plain path
            path = Path(file_url_to_local_path(file_ref) or file_ref)
            if not path.exists():
                logger.warning(
                    "MatrixChannel: upload source not found: %s",
                    file_ref,
                )
                return None
            mime_type, _ = mimetypes.guess_type(str(path))
            mime_type = mime_type or "application/octet-stream"
            data = path.read_bytes()
            resp, _ = await self._client.upload(
                io.BytesIO(data),
                content_type=mime_type,
                filename=path.name,
                filesize=len(data),
            )
            if isinstance(resp, UploadResponse):
                logger.debug(
                    "MatrixChannel: uploaded %s → %s",
                    path.name,
                    resp.content_uri,
                )
                return resp.content_uri
            logger.warning("MatrixChannel: upload failed: %s", resp)
            return None
        except Exception as exc:
            logger.warning(
                "MatrixChannel: upload error for %s: %s",
                file_ref,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # DM room detection (joined_members API + short-lived cache)
    # reliable DM vs group after token restore (§8);
    # feeds allowlist / requireMention / history behavior.
    # ------------------------------------------------------------------

    def _is_dm_room_fallback(
        self,
        room: Optional[MatrixRoom],
        sender_id: str,
    ) -> bool:
        """Best-effort DM check when joined_members API is unavailable."""
        if not room or not self._user_id:
            return False
        try:
            users = list(getattr(room, "users", {}).keys())
            if users:
                return (
                    len(users) == 2
                    and self._user_id in users
                    and sender_id in users
                )
            member_count = int(getattr(room, "member_count", 0) or 0)
            return member_count == 2
        except Exception:
            return False

    async def _is_dm_room(
        self,
        room_id: str,
        sender_id: str,
        room: Optional[MatrixRoom] = None,
    ) -> bool:
        """Check if a room is a DM (direct message) between self and sender.

        Uses Matrix API to get actual joined members, because nio's room.users
        can be unreliable after token restore.

        Args:
            room_id: The Matrix room ID
            sender_id: The sender's user ID

        Returns:
            True if the room has exactly 2 members (self and sender)
        """
        if not self._client or not self._user_id:
            return False

        now = int(time.time() * 1000)

        # Check cache
        cached = self._dm_room_cache.get(room_id)
        if cached and (now - cached["ts"]) < DM_CACHE_TTL_MS:
            members = cached["members"]
            is_dm = (
                len(members) == 2
                and self._user_id in members
                and sender_id in members
            )
            logger.debug(
                "MatrixChannel: DM check (cached) room=%s members=%d is_dm=%s",
                room_id,
                len(members),
                is_dm,
            )
            return is_dm

        # Fetch from Matrix API
        try:
            resp = await self._client.joined_members(room_id)
            if isinstance(resp, JoinedMembersResponse):
                members = [m.user_id for m in resp.members]
                # Update cache
                self._dm_room_cache[room_id] = {"members": members, "ts": now}

                is_dm = (
                    len(members) == 2
                    and self._user_id in members
                    and sender_id in members
                )
                logger.debug(
                    "MatrixChannel: DM check (API) room=%s members=%d "
                    "is_dm=%s members=%s",
                    room_id,
                    len(members),
                    is_dm,
                    members,
                )
                return is_dm
            else:
                logger.warning(
                    "MatrixChannel: joined_members failed for %s: %s",
                    room_id,
                    resp,
                )
                fallback = self._is_dm_room_fallback(room, sender_id)
                logger.warning(
                    "MatrixChannel: joined_members fallback for %s "
                    "-> is_dm=%s",
                    room_id,
                    fallback,
                )
                return fallback
        except Exception as exc:
            fallback = self._is_dm_room_fallback(room, sender_id)
            logger.warning(
                "MatrixChannel: joined_members error for %s: %s; "
                "fallback is_dm=%s",
                room_id,
                exc,
                fallback,
            )
            return fallback

    # ------------------------------------------------------------------
    # Incoming message handling — text
    # text receive; allowlist + per-room rules +
    # mention gating; history buffer when no mention; enqueue AgentRequest
    # (§9).
    # ------------------------------------------------------------------

    async def _on_room_event(
        self,
        room: MatrixRoom,
        event: RoomMessageText,
    ) -> None:
        room_id = room.room_id

        # Skip own messages early
        if event.sender == self._user_id:
            return

        sender_id = event.sender
        text = event.body or ""

        # Use Matrix API to reliably detect DM rooms
        # (nio's room.users is unreliable after token restore)
        is_dm = await self._is_dm_room(room_id, sender_id, room)

        logger.info(
            "_on_room_event: sender=%s room=%s body=%r is_dm=%s",
            event.sender,
            room_id,
            (event.body or "")[:80],
            is_dm,
        )

        if self._is_channel_disabled(sender_id, room_id, is_dm):
            return

        # Mention check for group rooms
        if not is_dm:
            if self._require_mention(room_id) and not self._was_mentioned(
                event,
                text,
            ):
                logger.info(
                    "MatrixChannel: group text not mentioned, cached to "
                    "history (room=%s sender=%s event_id=%s)",
                    room_id,
                    sender_id,
                    event.event_id,
                )
                self._record_history(
                    room_id,
                    HistoryEntry(
                        sender=self._get_display_name(room, sender_id),
                        body=text,
                        timestamp=getattr(event, "server_timestamp", None),
                        message_id=event.event_id,
                    ),
                )
                return

        # Mark as read + start typing immediately so the sender sees feedback
        await self._send_read_receipt(room_id, event.event_id)
        await self._send_typing(room_id, True)

        # Strip leading @mention so slash commands and NO_REPLY are detected
        # regardless of room type (group or DM).
        command_text = text
        stripped = self._strip_mention_prefix(text, room)

        # NO_REPLY protocol: the sender explicitly signals "nothing to say".
        # Drop it silently to prevent infinite ping-pong between agents.
        if stripped.strip() == "NO_REPLY":
            logger.info(
                "MatrixChannel: received NO_REPLY from %s in %s, ignoring",
                sender_id,
                room_id,
            )
            await self._send_typing(room_id, False)
            return

        cmd = (
            stripped.lstrip("/").split()[0] if stripped.startswith("/") else ""
        )
        if cmd in _SLASH_COMMANDS:
            command_text = stripped
            # Apply alias (e.g. /reset -> /clear)
            if cmd in _SLASH_ALIASES:
                canonical = _SLASH_ALIASES[cmd]
                command_text = command_text.replace(
                    f"/{cmd}",
                    f"/{canonical}",
                    1,
                )
            if stripped != text:
                logger.info(
                    "Stripped mention prefix for slash command: %r -> %r",
                    text,
                    command_text,
                )

        # Build content parts, prepending accumulated history for group rooms.
        # Skip history prepend for slash commands — QwenPaw's command parser
        # requires the message to start with "/" to recognise it.
        content_parts: list[Any] = [
            TextContent(type=ContentType.TEXT, text=command_text),
        ]
        is_slash_cmd = command_text.startswith("/")
        if not is_dm and not is_slash_cmd:
            # Prefix sender identity so the LLM can distinguish participants
            sender_name = self._get_display_name(room, sender_id)
            content_parts[0] = TextContent(
                type=ContentType.TEXT,
                text=f"{sender_name}: {command_text}",
            )
            content_parts = self._apply_history_to_parts(
                room_id,
                content_parts,
            )

        worker_name = (self._user_id or "").split(":")[0].lstrip("@")
        payload = {
            "channel_id": CHANNEL_KEY,
            "sender_id": sender_id,
            "content_parts": content_parts,
            "acl_sender_id": sender_id,
            "meta": {
                "room_id": room_id,
                "is_dm": is_dm,
                "is_group": not is_dm,
                "worker_name": worker_name,
                "event_id": event.event_id,
                "sender_id": sender_id,
                "user_name": self._get_display_name(room, sender_id),
            },
        }

        if self._enqueue:
            self._enqueue(payload)
            if not is_dm:
                self._clear_history(room_id)

    # ------------------------------------------------------------------
    # Incoming message handling — media (image / file / audio / video)
    # media receive + mxc download; vision_enabled
    # gates image→model vs text downgrade; same allow/history path as text
    # (§9–§11).
    # ------------------------------------------------------------------

    # pylint: disable=too-many-branches,too-many-statements
    async def _on_room_media_event(self, room: MatrixRoom, event: Any) -> None:
        """Handle incoming media messages (image, file, audio, video)."""
        if event.sender == self._user_id:
            return

        sender_id = event.sender
        room_id = room.room_id
        # Use Matrix API for reliable DM detection (room.users unreliable
        # after token restore)
        is_dm = await self._is_dm_room(room_id, sender_id, room)

        if self._is_channel_disabled(sender_id, room_id, is_dm):
            return

        # For group rooms, apply the same mention policy as text messages.
        # Media body (filename) rarely contains a mention, but respect
        # m.mentions if the client sends it.
        if not is_dm:
            if self._require_mention(room_id) and not self._was_mentioned(
                event,
                "",
            ):
                logger.info(
                    "MatrixChannel: group media not mentioned, cached to "
                    "history (room=%s sender=%s event_id=%s)",
                    room_id,
                    sender_id,
                    event.event_id,
                )
                await self._record_media_history(
                    room,
                    event,
                    sender_id,
                    room_id,
                )
                return

        await self._send_read_receipt(room_id, event.event_id)
        await self._send_typing(room_id, True)

        mxc_url: str = getattr(event, "url", "") or ""
        body: str = event.body or ""  # filename or caption

        content_parts: list[Any] = []

        if mxc_url:
            # Use the body as filename, fall back to a safe default.
            # Strip leading '$' from Matrix event IDs to avoid URI encoding
            # issues ($→%24 breaks agentscope's image extension check).
            eid = event.event_id[:8].lstrip("$")
            filename = body or f"matrix_media_{eid}"
            filename = f"{eid}_{filename}"
            local_path = await self._download_mxc(mxc_url, filename)
            if local_path:
                file_uri = Path(local_path).as_uri()
                if isinstance(event, RoomMessageImage):
                    if self.vision_enabled:
                        content_parts.append(
                            ImageContent(
                                type=ContentType.IMAGE,
                                image_url=file_uri,
                            ),
                        )
                    else:
                        # No vision: downgrade image to text
                        _no_vis = (
                            "[User sent an image (current model does not "
                            f"support image input): {body or filename}]"
                        )
                        content_parts.append(
                            TextContent(
                                type=ContentType.TEXT,
                                text=_no_vis,
                            ),
                        )
                elif isinstance(event, RoomMessageAudio):
                    content_parts.append(
                        AudioContent(
                            type=ContentType.AUDIO,
                            data=file_uri,
                        ),
                    )
                elif isinstance(event, RoomMessageVideo):
                    content_parts.append(
                        VideoContent(
                            type=ContentType.VIDEO,
                            video_url=file_uri,
                        ),
                    )
                else:  # RoomMessageFile
                    content_parts.append(
                        FileContent(
                            type=ContentType.FILE,
                            file_url=file_uri,
                            filename=body or filename,
                        ),
                    )
            else:
                content_parts.append(
                    TextContent(
                        type=ContentType.TEXT,
                        text=f"[Media unavailable: {body}]",
                    ),
                )

        if not content_parts:
            return

        # Prepend accumulated history for group rooms
        if not is_dm:
            # Prefix sender identity so the LLM can distinguish participants
            sender_name = self._get_display_name(room, sender_id)
            first = content_parts[0] if content_parts else None
            if first and getattr(first, "type", None) == ContentType.TEXT:
                content_parts[0] = TextContent(
                    type=ContentType.TEXT,
                    text=f"{sender_name}: {first.text}",
                )
            else:
                content_parts.insert(
                    0,
                    TextContent(
                        type=ContentType.TEXT,
                        text=f"{sender_name}:",
                    ),
                )
            content_parts = self._apply_history_to_parts(
                room_id,
                content_parts,
            )

        worker_name = (self._user_id or "").split(":")[0].lstrip("@")
        payload = {
            "channel_id": CHANNEL_KEY,
            "sender_id": sender_id,
            "content_parts": content_parts,
            "acl_sender_id": sender_id,
            "meta": {
                "room_id": room_id,
                "is_dm": is_dm,
                "is_group": not is_dm,
                "worker_name": worker_name,
                "event_id": event.event_id,
                "sender_id": sender_id,
                "user_name": self._get_display_name(room, sender_id),
            },
        }

        if self._enqueue:
            self._enqueue(payload)
            if not is_dm:
                self._clear_history(room_id)

    # ------------------------------------------------------------------
    # Read receipt & typing indicator
    # read markers on handled messages; typing on/off
    # + renewal until cap (optional UX; §10).
    # ------------------------------------------------------------------

    async def _send_read_receipt(self, room_id: str, event_id: str) -> None:
        """Mark a message as read (sends both read receipt and read marker)."""
        if not self._client or not event_id:
            return
        try:
            await self._client.room_read_markers(
                room_id,
                fully_read_event=event_id,
                read_event=event_id,
            )
        except Exception as exc:
            logger.debug(
                "MatrixChannel: read receipt failed for %s: %s",
                event_id,
                exc,
            )

    async def _send_typing(
        self,
        room_id: str,
        typing: bool,
        timeout: int = TYPING_SERVER_TIMEOUT_MS,
    ) -> None:
        """Set typing indicator on/off for a room.

        When turning on, starts a background renewal task that re-sends the
        typing indicator periodically (see ``TYPING_RENEWAL_INTERVAL_S``)
        before the server timeout, up to ``TYPING_MAX_DURATION_S``.
        When turning off, cancels the renewal task.
        """
        if not self._client:
            return
        # Cancel any existing renewal task for this room
        existing = self._typing_tasks.pop(room_id, None)
        if existing and not existing.done():
            existing.cancel()
        try:
            await self._client.room_typing(
                room_id,
                typing_state=typing,
                timeout=timeout,
            )
        except Exception as exc:
            logger.debug(
                "MatrixChannel: typing indicator failed for %s: %s",
                room_id,
                exc,
            )
        # Start renewal loop if turning on
        if typing:
            self._typing_tasks[room_id] = asyncio.create_task(
                self._typing_renewal_loop(room_id, timeout),
            )

    async def _typing_renewal_loop(
        self,
        room_id: str,
        timeout: int = TYPING_SERVER_TIMEOUT_MS,
    ) -> None:
        """Re-send typing=true until cap or cancellation."""
        elapsed = 0
        try:
            while elapsed < TYPING_MAX_DURATION_S:
                await asyncio.sleep(TYPING_RENEWAL_INTERVAL_S)
                elapsed += TYPING_RENEWAL_INTERVAL_S
                if not self._client:
                    break
                await self._client.room_typing(
                    room_id,
                    typing_state=True,
                    timeout=timeout,
                )
        except asyncio.CancelledError:
            logger.debug(
                "MatrixChannel: typing renewal cancelled for %s",
                room_id,
            )
            raise
        except Exception as exc:
            logger.debug(
                "MatrixChannel: typing renewal failed for %s: %s",
                room_id,
                exc,
            )
        finally:
            # If we hit the cap, explicitly stop typing
            if elapsed >= TYPING_MAX_DURATION_S and self._client:
                try:
                    await self._client.room_typing(room_id, typing_state=False)
                except Exception as exc:
                    logger.debug(
                        "MatrixChannel: typing stop after cap failed "
                        "for %s: %s",
                        room_id,
                        exc,
                    )
            self._typing_tasks.pop(room_id, None)

    # ------------------------------------------------------------------
    # build_agent_request_from_native (BaseChannel protocol)
    # native content_parts → QwenPaw Content; same
    # vision_enabled guard as inbound media for image parts (§11).
    # ------------------------------------------------------------------

    # pylint: disable=too-many-return-statements
    def _build_content_part(self, p: dict[str, Any]) -> Any:
        """Convert a native content-part dict to a QwenPaw Content object."""
        t = p.get("type")
        if t == "text" and p.get("text"):
            return TextContent(type=ContentType.TEXT, text=p["text"])
        if t == "image" and p.get("image_url"):
            if not self.vision_enabled:
                # Downgrade silently; _on_room_media_event should have already
                # converted this, but guard here for any code path that builds
                # content_parts directly.
                return TextContent(
                    type=ContentType.TEXT,
                    text=(
                        "[Image omitted: current model does not support "
                        "image input]"
                    ),
                )
            return ImageContent(
                type=ContentType.IMAGE,
                image_url=p["image_url"],
            )
        if t == "file":
            return FileContent(
                type=ContentType.FILE,
                file_url=p.get("file_url", ""),
            )
        if t == "audio" and p.get("data"):
            return AudioContent(type=ContentType.AUDIO, data=p["data"])
        if t == "video" and p.get("video_url"):
            return VideoContent(
                type=ContentType.VIDEO,
                video_url=p["video_url"],
            )
        return None

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        parts = native_payload.get("content_parts", [])
        meta = native_payload.get("meta", {})
        sender_id = native_payload.get("sender_id", "")
        room_id = meta.get("room_id", sender_id)
        session_id = f"matrix:{room_id}"

        # content_parts are already ContentType objects (from both
        # _on_room_event and _on_room_media_event); filter out None.
        content = [p for p in parts if p is not None]
        if not content:
            content = [TextContent(type=ContentType.TEXT, text="")]

        # Use room_id as the AgentRequest user_id so that all participants
        # in the same room share one session (QwenPaw keys session state on
        # both session_id AND user_id).  The real sender is preserved in
        # meta["sender_id"] for reply mentions.
        req = self.build_agent_request_from_user_content(
            channel_id=CHANNEL_KEY,
            sender_id=room_id,
            session_id=session_id,
            content_parts=content,
            channel_meta=meta,
        )
        req.channel_meta = meta  # type: ignore[attr-defined]
        return req

    def resolve_session_id(self, sender_id: str, channel_meta=None) -> str:
        room_id = (channel_meta or {}).get("room_id", sender_id)
        return f"matrix:{room_id}"

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        """For Matrix, return room_id (session_id), not user_id.

        Matrix requires room_id to send messages, not user_id.
        Override BaseChannel's default implementation which returns user_id.
        The session_id carries a ``matrix:`` prefix added by
        :meth:`resolve_session_id`; strip it so the value is a raw
        Matrix room_id that can be passed directly to ``room_send``.
        """
        if session_id.startswith("matrix:"):
            return session_id[len("matrix:") :]
        return session_id

    def get_to_handle_from_request(self, request: Any) -> str:
        meta = getattr(request, "channel_meta", {}) or {}
        return meta.get("room_id", getattr(request, "user_id", ""))

    # ------------------------------------------------------------------
    # Mention helper — MSC3952 m.mentions from body text scan
    # ------------------------------------------------------------------

    # Regex to match Matrix user IDs: @localpart:domain (with optional port)
    _MATRIX_USER_ID_RE = re.compile(
        r"@[a-zA-Z0-9._=+/\-]+:[a-zA-Z0-9.\-]+(?::\d+)?",
    )

    def _extract_mentions_from_text(self, text: str) -> list[str]:
        """Extract all @user:domain Matrix IDs from message text."""
        matches = self._MATRIX_USER_ID_RE.findall(text)
        return list(dict.fromkeys(matches))  # dedupe, preserve order

    def _apply_mention(  # pylint: disable=unused-argument
        self,
        content: dict[str, Any],
        user_id: str,
        room_id: str,
    ) -> None:
        """Add Matrix mentions to an outgoing event content dict.

        Scans the message body for @user:domain patterns and populates
        ``m.mentions.user_ids`` (MSC3952). Only includes user IDs that
        actually appear in the text. Does NOT modify the body text.
        """
        body = content.get("body", "")
        mentioned_ids = self._extract_mentions_from_text(body)
        if mentioned_ids:
            content["m.mentions"] = {"user_ids": mentioned_ids}

    def _resolve_display_name(self, user_id: str, room_id: str) -> str:
        """Best-effort display name for *user_id* in *room_id*."""
        if self._client:
            room = self._client.rooms.get(room_id)
            if room:
                try:
                    name = room.user_name(user_id)
                    if name:
                        return name
                except Exception as exc:
                    logger.debug(
                        "MatrixChannel: resolve_display_name user_name failed "
                        "for %s: %s",
                        user_id,
                        exc,
                    )
        return user_id.split(":")[0].lstrip("@") or user_id

    def _mark_room_encrypted(
        self,
        room_id: str,
        room: Optional[MatrixRoom] = None,
    ) -> None:
        """Keep nio's encrypted room state consistent for outbound sends."""
        if not self._client:
            return
        encrypted_rooms = getattr(self._client, "encrypted_rooms", None)
        if encrypted_rooms is not None:
            encrypted_rooms.add(room_id)
        target_room = room
        if target_room is None:
            rooms = getattr(self._client, "rooms", {})
            target_room = rooms.get(room_id) if rooms else None
        if target_room is not None:
            try:
                target_room.encrypted = True
            except Exception as exc:
                logger.debug(
                    "MatrixChannel: failed to mark %s encrypted: %s",
                    room_id,
                    exc,
                )

    def _room_will_encrypt(self, room_id: str) -> bool:
        """Return whether matrix-nio will encrypt room_send for this room."""
        if not self._client or not getattr(self._client, "olm", None):
            return False
        rooms = getattr(self._client, "rooms", {})
        room = rooms.get(room_id) if rooms else None
        if room is not None and getattr(room, "encrypted", False) is True:
            return True
        encrypted_rooms = (
            getattr(self._client, "encrypted_rooms", set()) or set()
        )
        if room_id in encrypted_rooms:
            self._mark_room_encrypted(room_id, room)
            return True
        return False

    async def _prepare_room_send(self, room_id: str) -> None:
        """Align local encryption flags with the homeserver before
        ``room_send``.

        matrix-nio only wraps ``room_send`` as ``m.room.encrypted`` when
        ``client.rooms[room_id].encrypted`` is true. If incremental sync never
        applied ``m.room.encryption`` to that object (common after restoring
        tokens or partial state), sends are still plaintext and Element shows
        "not encrypted". Fetch room state once per send attempt when needed.
        """
        if not self.encryption:
            return
        if not self._client or not getattr(self._client, "olm", None):
            logger.warning(
                "MatrixChannel: E2EE configured but Olm is not ready; "
                "outbound message to %s will not be encrypted",
                room_id,
            )
            return
        await self._e2ee_maintenance()
        if self._room_will_encrypt(room_id):
            return
        if room_id not in getattr(self._client, "rooms", {}):
            logger.warning(
                "MatrixChannel: room %s not in client cache; "
                "cannot confirm E2EE before send (wait for sync / join)",
                room_id,
            )
            return
        try:
            enc_state = await self._client.room_get_state_event(
                room_id,
                "m.room.encryption",
                "",
            )
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to get m.room.encryption for %s: %s",
                room_id,
                exc,
            )
            enc_state = None

        if isinstance(enc_state, RoomGetStateEventResponse):
            algo = (enc_state.content or {}).get("algorithm")
            if algo:
                self._mark_room_encrypted(room_id)
                logger.debug(
                    "MatrixChannel: marked %s encrypted from server (%s)",
                    room_id,
                    algo,
                )

        if not self._room_will_encrypt(room_id):
            logger.warning(
                "MatrixChannel: E2EE on but room %s is not encrypted in "
                "client after state check; outbound send may be plaintext",
                room_id,
            )

    # ------------------------------------------------------------------
    # Outgoing send — text
    # Markdown→HTML (formatted_body); m.mentions when meta has sender_id.
    # ------------------------------------------------------------------

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._client:
            logger.error("MatrixChannel: send called but client not ready")
            return

        room_id = (meta or {}).get("room_id") or to_handle

        # NO_REPLY protocol: agent decided it has nothing to say.
        # Suppress the outgoing message entirely to avoid triggering the
        # recipient (which would cause an infinite NO_REPLY ping-pong).
        if text.strip() == "NO_REPLY":
            logger.info(
                "MatrixChannel: suppressing NO_REPLY send to %s",
                room_id,
            )
            await self._send_typing(room_id, False)
            return

        html_body = _md_to_html(text)
        content: dict[str, Any] = {
            "msgtype": "m.text",
            "body": text,
            "format": "org.matrix.custom.html",
            "formatted_body": html_body,
        }
        logger.debug(
            "MatrixChannel (custom): sending message with formatted_body, "
            "text_len=%d html_len=%d",
            len(text),
            len(html_body),
        )

        sender_id = (meta or {}).get("sender_id") or (meta or {}).get(
            "user_id",
        )
        if sender_id:
            self._apply_mention(content, sender_id, room_id)

        try:
            await self._prepare_room_send(room_id)
            await self._client.room_send(
                room_id,
                "m.room.message",
                content,
                ignore_unverified_devices=True,
            )
        except Exception as exc:
            logger.exception(
                "MatrixChannel: send failed to %s: %s",
                room_id,
                exc,
            )
        finally:
            await self._send_typing(room_id, False)

    # ------------------------------------------------------------------
    # Outgoing send — media
    # ------------------------------------------------------------------

    async def send_media(
        self,
        to_handle: str,
        part: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Upload a local file to Matrix and send as m.image / m.file / etc."""
        if not self._client:
            return

        room_id = (meta or {}).get("room_id") or to_handle
        t = getattr(part, "type", None)

        # Extract the local file reference from the content part
        if t == ContentType.IMAGE:
            file_ref = getattr(part, "image_url", "")
            matrix_msgtype = "m.image"
        elif t == ContentType.VIDEO:
            file_ref = getattr(part, "video_url", "")
            matrix_msgtype = "m.video"
        elif t == ContentType.AUDIO:
            file_ref = getattr(part, "data", "")
            matrix_msgtype = "m.audio"
        elif t == ContentType.FILE:
            file_ref = getattr(part, "file_url", "") or getattr(
                part,
                "file_id",
                "",
            )
            matrix_msgtype = "m.file"
        else:
            return

        if not file_ref:
            return

        # Upload to Matrix media repository
        mxc_uri = await self._upload_file(file_ref)
        if not mxc_uri:
            logger.warning(
                "MatrixChannel: send_media upload failed for %s",
                file_ref,
            )
            return

        # Build and send the Matrix room event
        try:
            path_str = file_url_to_local_path(file_ref) or file_ref
            filename = os.path.basename(path_str) or "file"
            mime_type, _ = mimetypes.guess_type(path_str)
            mime_type = mime_type or "application/octet-stream"
            try:
                file_size = os.path.getsize(path_str)
            except OSError:
                file_size = 0

            event_content: dict[str, Any] = {
                "msgtype": matrix_msgtype,
                "body": filename,
                "url": mxc_uri,
                "info": {
                    "mimetype": mime_type,
                    "size": file_size,
                },
            }
            sender_id = (meta or {}).get("sender_id") or (meta or {}).get(
                "user_id",
            )
            if sender_id:
                self._apply_mention(event_content, sender_id, room_id)

            await self._prepare_room_send(room_id)
            await self._client.room_send(
                room_id,
                "m.room.message",
                event_content,
                ignore_unverified_devices=True,
            )
            logger.debug(
                "MatrixChannel: sent %s %s to %s",
                matrix_msgtype,
                filename,
                room_id,
            )
        except Exception as exc:
            logger.exception(
                "MatrixChannel: send_media failed for %s: %s",
                room_id,
                exc,
            )
