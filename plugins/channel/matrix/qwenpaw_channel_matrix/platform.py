# -*- coding: utf-8 -*-
"""Matrix SDK algorithms, owned exclusively by one shared worker instance."""

from __future__ import annotations

import asyncio
import html
import inspect
import io
import logging
import mimetypes
import re
import time
import urllib.parse
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

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
from nio.crypto import ENCRYPTION_ENABLED
from nio.event_builders.direct_messages import ToDeviceMessage
from nio.events.to_device import RoomKeyRequest, RoomKeyRequestCancellation
from nio.responses import (
    JoinedMembersResponse,
    RoomGetStateEventResponse,
    SyncError,
    WhoamiResponse,
)

from qwenpaw.schemas import (
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    TextContent,
    VideoContent,
)

logger = logging.getLogger("qwenpaw.plugins.matrix")


CHANNEL_KEY = "matrix"

# Tunables: sync / typing / DM membership cache TTL
SYNC_TIMEOUT_MS = 30000
TYPING_SERVER_TIMEOUT_MS = 30000
TYPING_RENEWAL_INTERVAL_S = 25
TYPING_MAX_DURATION_S = 120
DM_CACHE_TTL_MS = 30_000
DM_ROOM_CACHE_MAX_ENTRIES = 1_000
ROOM_HISTORY_MAX_ROOMS = 256
VERIFICATION_STATE_MAX_ENTRIES = 1_024
VERIFICATION_STATE_TTL_S = 60 * 60

# nio's _send() retries transport errors but not unparseable HTTP
# responses (e.g. 502 before Synapse is ready).  login()/whoami()
# return LoginError/WhoamiError with status_code=None and start()
# gives up.  These constants drive a retry loop covering that gap.
_NON_RETRYABLE_AUTH_CODES = frozenset(
    {
        "M_FORBIDDEN",
        "M_MISSING_TOKEN",
        "M_UNKNOWN_TOKEN",
        "M_USER_DEACTIVATED",
    },
)
_LOGIN_RETRY_INITIAL_DELAY = 5.0
_LOGIN_RETRY_MAX_DELAY = 60.0

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


@dataclass(frozen=True)
class _UploadedMedia:
    """Metadata shared by the media upload and its room event."""

    uri: str
    filename: str
    mime_type: str
    size: int


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


from qwenpaw.app.channels.utils import (  # noqa: E402
    data_url_filename,
    parse_data_url_async,
)  # noqa: E402
from qwenpaw.utils.media_paths import local_media_path  # noqa: E402
from .errors import MatrixDeliveryError  # noqa: E402
from .state import MatrixStateStore  # noqa: E402


class MatrixPlatform:
    def __init__(self, config, on_event, on_state):
        self.config = dict(config)
        self.on_event, self.on_state = on_event, on_state
        self.homeserver = str(config.get("homeserver") or "").rstrip("/")
        self.matrix_user_id = config.get("user_id", "")
        self.access_token = config.get("access_token", "")
        self.password = config.get("password", "")
        self.device_name = config.get("device_name", "qwenpaw-worker")
        self.device_id = config.get("device_id", "")  # legacy raw-only input
        self.encryption = config.get("encryption", False)
        self.enabled = config.get("enabled", True)
        self.dm_disabled = config.get("dm_disabled", False)
        self.group_disabled = config.get("group_disabled", False)
        self.groups = config.get("groups") or {}
        self.vision_enabled = config.get("vision_enabled", False)
        self.history_limit = max(
            0,
            config.get("history_limit", DEFAULT_HISTORY_LIMIT),
        )
        self.sync_timeout_ms = config.get("sync_timeout_ms", SYNC_TIMEOUT_MS)
        self.share_session_in_group = config.get(
            "share_session_in_group",
            True,
        )
        self._workspace_dir = (
            Path(config["workspace_dir"]).expanduser().resolve()
            if config.get("workspace_dir")
            else None
        )
        self._state = MatrixStateStore(config)
        self._client = None
        self._http_client = None
        self._user_id = None
        self._stop_event = None
        self._sync_task = None
        self._start_task = None
        self._stopping = False
        self._tasks = set()
        self._operations = set()
        self._decoders = set()
        self._typing_tasks = {}
        self._typing_lock = asyncio.Lock()
        self._typing_owners = {}
        self._room_histories = OrderedDict()
        self._dm_room_cache = OrderedDict()
        self._handled_verification_requests = OrderedDict()
        self._verification_tx_peers = OrderedDict()
        self._verification_tx_timestamps = OrderedDict()
        self._sent_verification_done = OrderedDict()

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._task_finished)
        return task

    def _task_finished(self, task):
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Matrix background task failed",
                exc_info=task.exception(),
            )

    async def start(self):
        if self._client is not None or self._start_task is not None:
            raise RuntimeError("MATRIX_RESOURCES_ALREADY_OWNED")
        if not self.enabled or not self.homeserver:
            await self.on_state("disconnected")
            return
        self._start_task = asyncio.current_task()
        self._stopping = False
        self._stop_event = asyncio.Event()
        try:
            self._state.begin()
            self._preflight_e2ee_dependencies()
            login_user = (self.matrix_user_id or "").strip()
            has_password_creds = bool(login_user and self.password)
            self._restore_auth_state_before_start(
                has_password_creds=has_password_creds,
                has_token_cred=bool(self.access_token),
            )
            resolved_device_id = (
                self.device_id
                or self._derive_device_id_from_name(
                    self.device_name,
                )
            )
            self._init_async_client(resolved_device_id)
            if has_password_creds:
                authenticated = await self._login_with_password(
                    login_user,
                    resolved_device_id,
                )
            elif self.access_token:
                authenticated = await self._login_with_access_token()
            else:
                raise RuntimeError("MATRIX_CREDENTIALS_REQUIRED")
            if not authenticated or self._is_stopping():
                raise RuntimeError("MATRIX_AUTHENTICATION_FAILED")
            self._register_plain_room_callbacks()
            if not await self._setup_e2ee_after_login():
                raise RuntimeError("MATRIX_E2EE_KEYS_UPLOAD_FAILED")
            self._http_client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=60,
            )
            await self.on_state("connected")
            self._sync_task = self._spawn(self._sync_loop())
        except BaseException:
            # Retain the SDK and claims for explicit, retryable stop cleanup.
            await self.on_state("failed")
            raise
        finally:
            self._start_task = None

    async def stop(self):
        self._stopping = True
        if self._stop_event is not None:
            self._stop_event.set()
        current = asyncio.current_task()
        tasks = {*self._tasks, *self._typing_tasks.values(), *self._operations}
        if self._start_task is not None:
            tasks.add(self._start_task)
        tasks.discard(current)
        for task in tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        results.extend(
            await asyncio.gather(
                *tuple(self._decoders),
                return_exceptions=True,
            ),
        )
        errors = [
            r
            for r in results
            if isinstance(r, BaseException)
            and not isinstance(r, asyncio.CancelledError)
        ]
        # Keep all failed resource references and OS claims until a later
        # successful stop. A close failure cannot authorize a replacement.
        if self._client is not None:
            for room_id in set(self._typing_owners.values()):
                try:
                    await self._client.room_typing(room_id, typing_state=False)
                except Exception as exc:
                    errors.append(exc)
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except Exception as exc:
                errors.append(exc)
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:
                errors.append(exc)
        if self._client is not None and self._client.store is not None:
            try:
                self._client.store.database.close()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError("MATRIX_STOP_INCOMPLETE") from errors[0]
        self._client = self._http_client = self._sync_task = None
        self._typing_tasks.clear()
        self._typing_owners.clear()
        for cache in (
            self._room_histories,
            self._dm_room_cache,
            self._handled_verification_requests,
            self._verification_tx_peers,
            self._verification_tx_timestamps,
            self._sent_verification_done,
        ):
            cache.clear()
        self._state.close()
        await self.on_state("disconnected")

    def _load_auth_state(self, restore_token=True, restore_identity=True):
        try:
            payload = self._state.auth_hint() or {}
            if restore_token and not self.access_token:
                self.access_token = str(payload.get("access_token", ""))
            if restore_identity:
                self.matrix_user_id = self.matrix_user_id or str(
                    payload.get("user_id", ""),
                )
                self.device_id = self.device_id or str(
                    payload.get("device_id", ""),
                )
        except Exception as exc:
            logger.warning("Matrix auth hint could not be read: %s", exc)

    async def _bind_authenticated_state(self, whoami=None):
        user_id = self._user_id or ""
        device_id = self._client.device_id or ""
        verified = False
        if self._state.has_legacy_state():
            hint = self._state.legacy_auth() or {}
            if (
                hint.get("user_id") != user_id
                or hint.get("device_id", "") != device_id
            ):
                raise RuntimeError("MATRIX_LEGACY_IDENTITY_CONFLICT")
            expected_owner = {
                "homeserver": self.homeserver,
                "user_id": user_id,
                "device_id": device_id,
                "workspace_dir": str(self._workspace_dir),
            }
            owner = self._state.legacy_owner()
            if owner is not None:
                if owner != expected_owner:
                    raise RuntimeError("MATRIX_LEGACY_OWNER_CONFLICT")
                verified = True
            elif self._state.has_legacy_authorization:
                verified = self._state.captured_legacy_verified(
                    user_id,
                    device_id,
                )
                if not verified:
                    raise RuntimeError("MATRIX_LEGACY_OWNER_UNVERIFIED")
            else:
                # The old JSON has no homeserver. Only a token the user has
                # explicitly provided for THIS server may be checked here.
                # Never transmit an unrelated cached token to a new server.
                explicit_token = self.config.get("access_token") or ""
                if not explicit_token or explicit_token != hint.get(
                    "access_token",
                ):
                    raise RuntimeError("MATRIX_LEGACY_OWNER_UNVERIFIED")
                if whoami is None:
                    current_token = self._client.access_token
                    try:
                        self._client.access_token = explicit_token
                        whoami = await self._client.whoami()
                    finally:
                        self._client.access_token = current_token
                verified = (
                    isinstance(whoami, WhoamiResponse)
                    and whoami.user_id == user_id
                    and whoami.device_id == device_id
                )
                if not verified:
                    raise RuntimeError("MATRIX_LEGACY_OWNER_UNVERIFIED")
        self._state.bind(
            user_id,
            device_id,
            legacy_verified=verified,
            encryption_enabled=self.encryption,
        )
        if self.encryption:
            self._state.crypto_dir.mkdir(parents=True, exist_ok=True)
            self._client.store_path = str(self._state.crypto_dir)

    def _save_auth_state(self):
        if (
            not self._client
            or not self._client.access_token
            or not self._user_id
        ):
            return
        try:
            self._state.save_auth(
                self._client.access_token,
                self._user_id,
                self._client.device_id or "",
            )
        except OSError as exc:
            logger.warning("Matrix auth state could not be saved: %s", exc)
        self.access_token = self._client.access_token
        self.matrix_user_id = self._user_id
        self.device_id = self._client.device_id or self.device_id

    def _load_sync_token(self):
        return self._state.load_sync()

    def _save_sync_token(self, token):
        try:
            self._state.save_sync(token)
        except OSError as exc:
            logger.warning("Matrix sync token could not be saved: %s", exc)

    def _media_dir(self):
        path = (
            Path(self.config.get("media_dir") or self._workspace_dir / "media")
            .expanduser()
            .resolve()
        )
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _media_destination(self, filename):
        # Matrix body is remote input; keep only a safe basename.
        safe = (
            re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(filename)).strip(". ")
            or "matrix_media"
        )
        path = self._media_dir() / safe
        if path.is_symlink():
            raise ValueError("MATRIX_MEDIA_PATH_UNSAFE")
        return path

    def _build_client_config(
        self,
        encryption: bool = False,
    ) -> AsyncClientConfig:
        sync_s = self.sync_timeout_ms / 1000
        request_timeout = max(sync_s + 30, 60)
        return AsyncClientConfig(
            store_sync_tokens=False,
            encryption_enabled=encryption,
            request_timeout=request_timeout,
        )

    @staticmethod
    def _derive_device_id_from_name(device_name: str) -> str:
        return (device_name or "").strip()

    def _restore_auth_state_before_start(
        self,
        *,
        has_password_creds: bool,
        has_token_cred: bool,
    ) -> None:
        has_explicit_identity = (
            has_password_creds or has_token_cred or self.matrix_user_id
        )
        self._load_auth_state(
            restore_token=False,
            restore_identity=not has_explicit_identity,
        )

    def _preflight_e2ee_dependencies(self) -> None:
        if not self.encryption:
            return
        if ENCRYPTION_ENABLED:
            return
        logger.error(
            "matrix-nio has no E2EE backend; encryption=False. Install the optional "
            "matrix-nio[e2e] extra and platform libolm to enable encryption.",
        )
        self.encryption = False

    def _init_async_client(self, resolved_device_id):
        self._client = AsyncClient(
            self.homeserver,
            user="",
            store_path="",
            config=self._build_client_config(encryption=self.encryption),
        )
        if resolved_device_id:
            self._client.device_id = resolved_device_id

    def _password_login_kwargs_for_nio(
        self,
        login_user: str,
        resolved_device_id: str,
    ) -> dict[str, Any]:
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
                return (resp, None)
            except TypeError as exc:
                last_exc = exc
        return (None, last_exc)

    async def _handle_password_login_success(
        self,
        resp: LoginResponse,
    ) -> None:
        self._user_id = resp.user_id
        self._client.user_id = resp.user_id
        self._client.user = resp.user_id
        if getattr(resp, "device_id", None):
            self._client.device_id = resp.device_id
        if getattr(resp, "access_token", None):
            self._client.access_token = resp.access_token
        logger.info(
            "MatrixChannel: logged in as %s (password, device=%s, device_name=%s)",
            self._user_id,
            getattr(self._client, "device_id", ""),
            self.device_name,
        )
        await self._bind_authenticated_state()
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
                    "MatrixChannel: password login returned no device_id; E2EE store may not be reusable",
                )

    def _is_stopping(self) -> bool:
        return self._stop_event is not None and self._stop_event.is_set()

    def _is_retryable_auth_failure(self, response: Any) -> bool:
        code = getattr(response, "status_code", None)
        if code in _NON_RETRYABLE_AUTH_CODES:
            return False
        http_status = getattr(
            getattr(response, "transport_response", None),
            "status",
            None,
        )
        if http_status is None:
            return True
        return http_status >= 500 or http_status in (408, 429)

    async def _wait_backoff_or_stop(self, delay: float) -> bool:
        if self._stop_event is None:
            await asyncio.sleep(delay)
            return False
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            return True
        except asyncio.TimeoutError:
            return False

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
        delay = _LOGIN_RETRY_INITIAL_DELAY
        while True:
            if self._is_stopping():
                return False
            resp, last_exc = await self._try_password_login_variants(attempts)
            if last_exc is not None:
                raise last_exc
            if isinstance(resp, LoginResponse):
                if self._is_stopping():
                    return False
                await self._handle_password_login_success(resp)
                return True
            if not self._is_retryable_auth_failure(resp):
                logger.error(
                    "MatrixChannel: password login rejected: %s",
                    resp,
                )
                return False
            logger.warning(
                "MatrixChannel: password login temporarily failed, retrying in %.1fs: %s",
                delay,
                resp,
            )
            if await self._wait_backoff_or_stop(delay):
                return False
            delay = min(delay * 2, _LOGIN_RETRY_MAX_DELAY)

    async def _login_with_access_token(self) -> bool:
        self._client.access_token = self.access_token
        delay = _LOGIN_RETRY_INITIAL_DELAY
        while True:
            if self._is_stopping():
                return False
            whoami = await self._client.whoami()
            if isinstance(whoami, WhoamiResponse):
                if self._is_stopping():
                    return False
                return await self._handle_token_login_success(whoami)
            if not self._is_retryable_auth_failure(whoami):
                logger.error("MatrixChannel: token login rejected: %s", whoami)
                return False
            logger.warning(
                "MatrixChannel: token login temporarily failed, retrying in %.1fs: %s",
                delay,
                whoami,
            )
            if await self._wait_backoff_or_stop(delay):
                return False
            delay = min(delay * 2, _LOGIN_RETRY_MAX_DELAY)

    async def _handle_token_login_success(
        self,
        whoami: WhoamiResponse,
    ) -> bool:
        if self.matrix_user_id and self.matrix_user_id != whoami.user_id:
            logger.error(
                "MatrixChannel: configured user_id=%s does not match access_token owner=%s; refusing stale credentials",
                self.matrix_user_id,
                whoami.user_id,
            )
            return False
        self._user_id = whoami.user_id
        self._client.user_id = whoami.user_id
        self._client.user = whoami.user_id
        if whoami.device_id:
            self._client.device_id = whoami.device_id
        logger.info(
            "MatrixChannel: logged in as %s (token, device=%s)",
            self._user_id,
            whoami.device_id,
        )
        await self._bind_authenticated_state(whoami)
        self._save_auth_state()
        if self.encryption and self._client.store_path:
            if self._client.device_id:
                self._client.load_store()
                logger.info(
                    "MatrixChannel: crypto store loaded from %s",
                    self._client.store_path,
                )
            else:
                logger.error(
                    "MatrixChannel: E2EE enabled but whoami returned no device_id "
                    "— encryption disabled (token may lack device scope)",
                )
                self.encryption = False
        return True

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
        self._client.add_event_callback(
            self._on_room_encrypted_media_event,
            (
                RoomEncryptedImage,
                RoomEncryptedAudio,
                RoomEncryptedVideo,
                RoomEncryptedFile,
            ),
        )
        self._client.add_event_callback(self._on_megolm_event, (MegolmEvent,))
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
            (RoomKeyRequest, RoomKeyRequestCancellation),
        )
        logger.info(
            "MatrixChannel: key verification to-device callback registered",
        )
        logger.info(
            "MatrixChannel: E2EE enabled, encrypted event handlers registered",
        )
        return True

    async def _e2ee_maintenance(self) -> None:
        if not self.encryption or not self._client or (not self._client.olm):
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
        if not self._client or not self._client.olm:
            logger.info(
                "MatrixChannel: verification event received but olm is not ready (event=%s, tx=%s, sender=%s)",
                type(event).__name__,
                getattr(event, "transaction_id", ""),
                getattr(event, "sender", ""),
            )
            return
        try:
            logger.info(
                "MatrixChannel: verification event received (event=%s, tx=%s, sender=%s, from_device=%s)",
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
                    "MatrixChannel: key verification MAC received (tx=%s, verified=%s, verified_devices=%s)",
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
                        "MatrixChannel: key verification cancelled by %s (tx=%s, reason=%s)",
                        event.sender,
                        event.transaction_id,
                        getattr(event, "reason", ""),
                    )
                else:
                    logger.info(
                        "MatrixChannel: key verification cancelled for unknown "
                        "key verification tx=%s from %s (reason=%s)",
                        event.transaction_id,
                        event.sender,
                        getattr(event, "reason", ""),
                    )
                self._clear_verification_transaction(event.transaction_id)
            else:
                logger.info(
                    "MatrixChannel: unhandled verification event type=%s (tx=%s, sender=%s)",
                    type(event).__name__,
                    getattr(event, "transaction_id", ""),
                    getattr(event, "sender", ""),
                )
        except Exception as exc:
            logger.warning(
                "MatrixChannel: key verification handling failed: %s",
                exc,
            )

    async def _on_to_device_probe_event(self, event: ToDeviceEvent) -> None:
        raw_type = getattr(event, "type", "")
        if not raw_type:
            raw_type = getattr(event, "source", {}).get("type", "")
        if not isinstance(raw_type, str) or not raw_type.startswith(
            "m.key.verification.",
        ):
            return
        logger.info(
            "MatrixChannel: raw to-device verification event (type=%s, parsed=%s, sender=%s)",
            raw_type,
            type(event).__name__,
            getattr(event, "sender", ""),
        )
        if raw_type in (
            "m.key.verification.request",
            "m.key.verification.ready",
        ):
            logger.warning(
                "MatrixChannel: homeserver sent %s but current matrix-nio cannot "
                "parse it into KeyVerificationEvent; handling via raw "
                "to-device compatibility path",
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
        if isinstance(event, RoomKeyRequest):
            logger.warning(
                "MatrixChannel: room key request received; other device may show "
                "'Review' until trust decision is made (sender=%s device=%s "
                "request_id=%s room_id=%s session_id=%s)",
                event.sender,
                event.requesting_device_id,
                event.request_id,
                getattr(event, "room_id", ""),
                getattr(event, "session_id", ""),
            )
        else:
            logger.info(
                "MatrixChannel: room key request cancelled (sender=%s device=%s request_id=%s)",
                event.sender,
                event.requesting_device_id,
                event.request_id,
            )

    async def _handle_unknown_key_verification_request(
        self,
        event: ToDeviceEvent,
    ) -> None:
        if not self._client or not self._client.olm:
            return
        source = getattr(event, "source", {}) or {}
        content = source.get("content", {}) or {}
        sender = getattr(event, "sender", "")
        from_device = str(content.get("from_device", "") or "")
        transaction_id = str(content.get("transaction_id", "") or "")
        methods = content.get("methods", []) or []
        request_key = f"{sender}|{from_device}|{transaction_id}"
        self._prune_verification_state()
        if request_key in self._handled_verification_requests:
            logger.debug(
                "MatrixChannel: verification request already handled (sender=%s, device=%s, tx=%s)",
                sender,
                from_device,
                transaction_id,
            )
            return
        self._remember_verification_request(request_key)
        if not sender or not from_device:
            logger.warning(
                "MatrixChannel: cannot handle verification request without sender/device (sender=%s, device=%s, tx=%s)",
                sender,
                from_device,
                transaction_id,
            )
            return
        self._remember_verification_peer(transaction_id, sender, from_device)
        our_device = getattr(self._client, "device_id", "") or ""
        if not our_device:
            logger.warning(
                "MatrixChannel: cannot reply verification request without local "
                "device_id (sender=%s, device=%s, tx=%s)",
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
            self._handled_verification_requests.pop(request_key, None)
            logger.warning(
                "MatrixChannel: failed to send verification ready (sender=%s, device=%s, tx=%s): %s",
                sender,
                from_device,
                transaction_id,
                exc,
            )
            return
        if isinstance(resp, ToDeviceError):
            self._handled_verification_requests.pop(request_key, None)
            logger.warning(
                "MatrixChannel: homeserver rejected verification ready (sender=%s, device=%s, tx=%s): %s",
                sender,
                from_device,
                transaction_id,
                resp,
            )
            return
        logger.info(
            "MatrixChannel: sent verification ready for request (sender=%s, device=%s, tx=%s, methods=%s)",
            sender,
            from_device,
            transaction_id,
            methods,
        )

    async def _handle_unknown_key_verification_done(
        self,
        event: ToDeviceEvent,
    ) -> None:
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
        if not self._client or not self._client.olm:
            return
        self._prune_verification_state()
        self._remember_verification_peer(
            event.transaction_id,
            event.sender,
            event.from_device,
        )
        if event.transaction_id not in self._client.key_verifications:
            await self._recover_key_verification_start(event)
        if event.transaction_id not in self._client.key_verifications:
            logger.warning(
                "MatrixChannel: cannot accept key verification from %s "
                "(device=%s, tx=%s) because no SAS state exists yet; retry "
                "verification after the next sync",
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
            "MatrixChannel: accepted key verification from %s (device=%s, tx=%s)",
            event.sender,
            event.from_device,
            event.transaction_id,
        )

    async def _send_verification_done(self, transaction_id: str) -> None:
        if (
            not self._client
            or not transaction_id
            or transaction_id in self._sent_verification_done
        ):
            return
        peer = self._verification_tx_peers.get(transaction_id)
        if not peer:
            logger.warning(
                "MatrixChannel: cannot send verification done for tx=%s because peer device is unknown",
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
                "MatrixChannel: failed to send verification done (tx=%s, sender=%s, device=%s): %s",
                transaction_id,
                sender,
                device_id,
                exc,
            )
            return
        if isinstance(resp, ToDeviceError):
            logger.warning(
                "MatrixChannel: homeserver rejected verification done (tx=%s, sender=%s, device=%s): %s",
                transaction_id,
                sender,
                device_id,
                resp,
            )
            return
        self._remember_sent_verification_done(transaction_id)
        self._clear_verification_transaction(transaction_id)
        logger.info(
            "MatrixChannel: sent verification done (tx=%s, sender=%s, device=%s)",
            transaction_id,
            sender,
            device_id,
        )

    def _prune_verification_state(self) -> None:
        cutoff = time.monotonic() - VERIFICATION_STATE_TTL_S
        for store in (
            self._handled_verification_requests,
            self._sent_verification_done,
        ):
            while store:
                key, timestamp = next(iter(store.items()))
                if (
                    timestamp >= cutoff
                    and len(store) <= VERIFICATION_STATE_MAX_ENTRIES
                ):
                    break
                store.pop(key)
        while self._verification_tx_timestamps:
            transaction_id, timestamp = next(
                iter(self._verification_tx_timestamps.items()),
            )
            if (
                timestamp >= cutoff
                and len(self._verification_tx_timestamps)
                <= VERIFICATION_STATE_MAX_ENTRIES
            ):
                break
            self._verification_tx_timestamps.pop(transaction_id)
            self._verification_tx_peers.pop(transaction_id, None)

    def _remember_verification_request(self, request_key: str) -> None:
        self._handled_verification_requests[request_key] = time.monotonic()
        self._handled_verification_requests.move_to_end(request_key)
        self._prune_verification_state()

    def _remember_sent_verification_done(self, transaction_id: str) -> None:
        self._sent_verification_done[transaction_id] = time.monotonic()
        self._sent_verification_done.move_to_end(transaction_id)
        self._prune_verification_state()

    def _remember_verification_peer(
        self,
        transaction_id: str,
        sender: str,
        device_id: str,
    ) -> None:
        self._verification_tx_peers[transaction_id] = (sender, device_id)
        self._verification_tx_peers.move_to_end(transaction_id)
        self._verification_tx_timestamps[transaction_id] = time.monotonic()
        self._verification_tx_timestamps.move_to_end(transaction_id)
        self._prune_verification_state()

    def _clear_verification_transaction(self, transaction_id: str) -> None:
        self._verification_tx_peers.pop(transaction_id, None)
        self._verification_tx_timestamps.pop(transaction_id, None)

    async def _recover_key_verification_start(
        self,
        event: KeyVerificationStart,
    ) -> None:
        assert self._client is not None
        assert self._client.olm is not None
        try:
            if self._client.should_query_keys:
                await self._client.keys_query()
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to query keys for verification from %s: %s",
                event.sender,
                exc,
            )
            return
        try:
            self._client.olm.handle_key_verification(event)
        except Exception as exc:
            logger.warning(
                "MatrixChannel: failed to rebuild key verification state for tx=%s: %s",
                event.transaction_id,
                exc,
            )

    async def _handle_key_verification_key(
        self,
        event: KeyVerificationKey,
    ) -> None:
        if not self._client:
            return
        sas = self._client.key_verifications.get(event.transaction_id)
        if sas is None:
            logger.warning(
                "MatrixChannel: key verification key for unknown tx=%s from %s; ask Element to restart verification",
                event.transaction_id,
                event.sender,
            )
            return
        logger.warning(
            "MatrixChannel: Element key verification challenge from %s (tx=%s): %s",
            event.sender,
            event.transaction_id,
            self._format_sas_challenge(sas),
        )
        await self._client.send_to_device_messages()
        try:
            resp = await self._client.confirm_short_auth_string(
                event.transaction_id,
            )
        except LocalProtocolError as exc:
            logger.warning(
                "MatrixChannel: confirm_short_auth_string failed for tx=%s: %s",
                event.transaction_id,
                exc,
            )
            return
        if isinstance(resp, ToDeviceError):
            logger.warning(
                "MatrixChannel: confirm_short_auth_string failed for tx=%s: %s",
                event.transaction_id,
                resp,
            )
            return
        logger.info(
            "MatrixChannel: confirmed local SAS side for tx=%s; compare the "
            "challenge in Element and accept there if it matches",
            event.transaction_id,
        )

    @staticmethod
    def _format_sas_challenge(sas: Any) -> str:
        parts: list[str] = []
        get_emoji = getattr(sas, "get_emoji", None)
        if callable(get_emoji):
            try:
                emojis = get_emoji()
                if emojis:
                    parts.append(
                        "emoji="
                        + " ".join(
                            (
                                f"{symbol}({description})"
                                for symbol, description in emojis
                            )
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
                        "decimal=" + " ".join((str(n) for n in decimals)),
                    )
            except Exception as exc:
                logger.debug("MatrixChannel: get_decimal failed: %s", exc)
        return "; ".join(parts) if parts else "unavailable"

    async def _sync_loop(self) -> None:
        next_batch: Optional[str] = self._load_sync_token()
        if next_batch is None:
            logger.info(
                "MatrixChannel: no sync token found, performing catch-up sync (messages suppressed)",
            )
            try:
                saved_cbs = self._client.event_callbacks[:]
                self._client.event_callbacks.clear()
                try:
                    resp = await self._client.sync(
                        timeout=self.sync_timeout_ms,
                        full_state=True,
                    )
                    if not await self._sync_valid(resp):
                        return
                finally:
                    self._client.event_callbacks.extend(saved_cbs)
                if isinstance(resp, SyncResponse):
                    next_batch = resp.next_batch
                    if next_batch is not None:
                        self._save_sync_token(next_batch)
                    for room_id in resp.rooms.invite:
                        logger.info("MatrixChannel: auto-joining %s", room_id)
                        await self._client.join(room_id)
                    await self._e2ee_maintenance()
                    logger.info(
                        "MatrixChannel: catch-up sync done, will process messages from next sync",
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
            logger.info(
                "MatrixChannel: restored token, performing full-state sync to load room state",
            )
            try:
                resp = await self._client.sync(
                    timeout=self.sync_timeout_ms,
                    since=next_batch,
                    full_state=True,
                )
                if not await self._sync_valid(resp):
                    return
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
        while not self._is_stopping():
            try:
                resp = await self._client.sync(
                    timeout=self.sync_timeout_ms,
                    since=next_batch,
                    full_state=False,
                )
                if not await self._sync_valid(resp):
                    return
                if isinstance(resp, SyncResponse):
                    next_batch = resp.next_batch
                    if next_batch is not None:
                        self._save_sync_token(next_batch)
                    for room_id in resp.rooms.invite:
                        logger.info("MatrixChannel: auto-joining %s", room_id)
                        await self._client.join(room_id)
                    await self._e2ee_maintenance()
                else:
                    if isinstance(resp, SyncError) and getattr(
                        resp,
                        "status_code",
                        None,
                    ) in {"M_UNKNOWN_TOKEN", "M_MISSING_TOKEN"}:
                        logger.error(
                            "MatrixChannel: sync stopped due to invalid/missing "
                            "access token; please re-login (password or fresh token)",
                        )
                        if self._client:
                            self._client.access_token = ""
                        self.access_token = ""
                        await self.on_state("failed")
                        return
                    logger.warning("MatrixChannel: sync error: %s", resp)
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.debug("MatrixChannel: sync loop cancelled")
                raise
            except Exception as exc:
                logger.exception("MatrixChannel: sync exception: %s", exc)
                await asyncio.sleep(5)

    def _is_channel_disabled(
        self,
        sender_id: str,
        room_id: str,
        is_dm: bool,
    ) -> bool:
        if is_dm and self.dm_disabled:
            logger.warning(
                "MatrixChannel: dropping DM message (dm_disabled) sender=%s room=%s",
                sender_id,
                room_id,
            )
            return True
        if not is_dm and self.group_disabled:
            logger.warning(
                "MatrixChannel: dropping group message (group_disabled) sender=%s room=%s",
                sender_id,
                room_id,
            )
            return True
        return False

    def _require_mention(self, room_id: str) -> bool:
        room_cfg = self.groups.get(room_id) or self.groups.get("*")
        if room_cfg:
            if room_cfg.get("autoReply") is True:
                return False
            if "requireMention" in room_cfg:
                return bool(room_cfg["requireMention"])
        return True

    def _was_mentioned(self, event: Any, text: str) -> bool:
        if not self._user_id:
            return False
        content = event.source.get("content", {})
        mentions = content.get("m.mentions", {})
        if self._user_id in mentions.get("user_ids", []):
            return True
        if mentions.get("room"):
            return True
        formatted_body = content.get("formatted_body", "")
        if formatted_body and self._user_id:
            escaped_uid = re.escape(self._user_id)
            if re.search(
                f"""href=["\\']https://matrix\\.to/#/{escaped_uid}["\\']""",
                formatted_body,
                re.IGNORECASE,
            ):
                return True
            encoded_uid = re.escape(urllib.parse.quote(self._user_id))
            if re.search(
                f"""href=["\\']https://matrix\\.to/#/{encoded_uid}["\\']""",
                formatted_body,
                re.IGNORECASE,
            ):
                return True
        if self._user_id and re.search(
            re.escape(self._user_id),
            text,
            re.IGNORECASE,
        ):
            return True
        return False

    def _strip_mention_prefix(self, text: str, room: Any = None) -> str:
        if not self._user_id:
            return text
        escaped = re.escape(self._user_id)
        result = re.sub(f"^{escaped}\\s*:?\\s*", "", text, flags=re.IGNORECASE)
        if result != text:
            return result.strip()
        if room and self._user_id:
            display_name = self._get_display_name(room, self._user_id)
            logger.debug(
                "strip_mention_prefix: user_id=%s display_name=%r room_users=%d",
                self._user_id,
                display_name,
                len(getattr(room, "users", {})),
            )
            if display_name and display_name != self._user_id:
                result = re.sub(
                    f"^{re.escape(display_name)}\\s*:?\\s*",
                    "",
                    text,
                    flags=re.IGNORECASE,
                )
                if result != text:
                    result = re.sub("^[^\\w/]+", "", result)
                    return result.strip()
        localpart = self._user_id.split(":")[0].lstrip("@")
        if localpart:
            result = re.sub(
                f"^{re.escape(localpart)}\\s*:?\\s*",
                "",
                text,
                flags=re.IGNORECASE,
            )
            if result != text:
                result = re.sub("^[^\\w/]+", "", result)
                return result.strip()
        return text

    def _get_display_name(self, room: Any, user_id: str) -> str:
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
        if self._client:
            room_id = getattr(room, "room_id", None)
            if room_id:
                client_room = self._client.rooms.get(room_id)
                if client_room and client_room is not room:
                    try:
                        name = client_room.user_name(user_id)
                        if name:
                            logger.debug(
                                "display_name resolved via client.rooms fallback: %s -> %r",
                                user_id,
                                name,
                            )
                            return name
                    except Exception as exc:
                        logger.debug(
                            "MatrixChannel: client_room user_name failed for %s: %s",
                            user_id,
                            exc,
                        )
        logger.debug(
            "display_name fallback to localpart for %s (room.users=%d, client_rooms=%d)",
            user_id,
            len(getattr(room, "users", {})),
            len(self._client.rooms) if self._client else 0,
        )
        return user_id.split(":")[0].lstrip("@") or user_id

    def _record_history(self, room_id: str, entry: HistoryEntry) -> None:
        limit = self.history_limit
        if limit <= 0:
            return
        history = self._room_histories.setdefault(room_id, [])
        self._room_histories.move_to_end(room_id)
        if entry.message_id and any(
            previous.message_id == entry.message_id for previous in history
        ):
            return
        history.append(entry)
        while len(history) > limit:
            history.pop(0)
        while len(self._room_histories) > ROOM_HISTORY_MAX_ROOMS:
            self._room_histories.popitem(last=False)

    def _build_history_prefix(self, room_id: str) -> str:
        entries = self._room_histories.get(room_id, [])
        if not entries:
            return ""
        self._room_histories.move_to_end(room_id)
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
        if self.history_limit <= 0:
            return content_parts
        history_text = self._build_history_prefix(room_id)
        if not history_text:
            return content_parts
        history_media: list[Any] = []
        for entry in self._room_histories.get(room_id, []):
            if entry.media_parts:
                history_media.extend(entry.media_parts)
        first = content_parts[0] if content_parts else None
        if first and getattr(first, "type", None) == ContentType.TEXT:
            current_text = first.text or ""
            combined = f"{HISTORY_CONTEXT_MARKER}\n{history_text}\n\n{CURRENT_MESSAGE_MARKER}\n{current_text}"
            return (
                [TextContent(type=ContentType.TEXT, text=combined)]
                + history_media
                + content_parts[1:]
            )
        prefix_part = TextContent(
            type=ContentType.TEXT,
            text=f"{HISTORY_CONTEXT_MARKER}\n{history_text}\n\n{CURRENT_MESSAGE_MARKER}",
        )
        return [prefix_part] + history_media + content_parts

    def _clear_history(self, room_id: str) -> None:
        self._room_histories.pop(room_id, None)

    async def _record_media_history(
        self,
        room: Any,
        event: Any,
        sender_id: str,
        room_id: str,
    ) -> None:
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

    def _mxc_to_http(self, mxc_url: str) -> str:
        if not mxc_url:
            return mxc_url
        if not mxc_url.startswith("mxc://"):
            return mxc_url
        rest = mxc_url[6:]
        if "/" not in rest:
            return mxc_url
        server, media_id = rest.split("/", 1)
        return (
            f"{self.homeserver}/_matrix/media/v3/download/{server}/{media_id}"
        )

    async def _download_mxc(
        self,
        mxc_url: str,
        filename: str,
    ) -> Optional[str]:
        if not mxc_url.startswith("mxc://"):
            return None
        if not self._client:
            logger.warning(
                "MatrixChannel: _download_mxc called without client",
            )
            return None
        try:
            resp = await self._client.download(mxc=mxc_url)
            from nio.responses import DownloadError

            if isinstance(resp, DownloadError):
                logger.warning(
                    "MatrixChannel: failed to download mxc %s: %s %s",
                    mxc_url,
                    type(resp).__name__,
                    getattr(resp, "message", ""),
                )
                return None
            dest = self._media_destination(filename)
            dest.write_bytes(resp.body)
            logger.debug("MatrixChannel: downloaded %s → %s", mxc_url, dest)
            return str(dest)
        except Exception as exc:
            logger.exception(
                "MatrixChannel: unexpected error downloading %s: %s",
                mxc_url,
                exc,
            )
            return None

    async def _download_encrypted_mxc(
        self,
        mxc_url: str,
        filename: str,
        key: dict,
        hashes: dict,
        iv: str,
    ) -> Optional[str]:
        if not mxc_url.startswith("mxc://") or not self._client:
            return None
        try:
            resp = await self._client.download(mxc=mxc_url)
            from nio.responses import DownloadError

            if isinstance(resp, DownloadError):
                logger.warning(
                    "MatrixChannel: failed to download encrypted %s: %s %s",
                    mxc_url,
                    type(resp).__name__,
                    getattr(resp, "message", ""),
                )
                return None
            from nio.crypto.attachments import decrypt_attachment

            jwk_key = key.get("k", "")
            sha256_hash = hashes.get("sha256", "")
            plaintext = decrypt_attachment(resp.body, jwk_key, sha256_hash, iv)
            dest = self._media_destination(filename)
            dest.write_bytes(plaintext)
            logger.debug(
                "MatrixChannel: downloaded+decrypted %s → %s",
                mxc_url,
                dest,
            )
            return str(dest)
        except Exception as exc:
            logger.exception(
                "MatrixChannel: failed to download encrypted %s: %s",
                mxc_url,
                exc,
            )
            return None

    async def _on_megolm_event(
        self,
        room: MatrixRoom,
        event: MegolmEvent,
    ) -> None:
        logger.warning(
            "MatrixChannel: could not decrypt event %s in %s (session_id=%s)",
            event.event_id,
            room.room_id,
            getattr(event, "session_id", "?"),
        )

    async def _on_room_encrypted_media_event(
        self,
        room: MatrixRoom,
        event: Any,
    ) -> None:
        if event.sender == self._user_id:
            return
        sender_id = event.sender
        room_id = room.room_id
        is_dm = await self._is_dm_room(room_id, sender_id, room)
        if self._is_channel_disabled(sender_id, room_id, is_dm):
            return
        if not is_dm:
            if self._require_mention(room_id) and (
                not self._was_mentioned(event, "")
            ):
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
                            "[User sent an image (current model does not support "
                            f"image input): {body or filename}]"
                        )
                        content_parts.append(
                            TextContent(type=ContentType.TEXT, text=_no_vis),
                        )
                elif isinstance(event, RoomEncryptedAudio):
                    content_parts.append(
                        AudioContent(type=ContentType.AUDIO, data=file_uri),
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
                    TextContent(type=ContentType.TEXT, text=f"{sender_name}:"),
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
        if await self.on_event(payload):
            if not is_dm:
                self._clear_history(room_id)

    async def _upload_file(
        self,
        file_ref: str,
        filename_hint: Optional[str] = None,
    ) -> Optional[_UploadedMedia]:
        if not self._client:
            return None
        try:
            data_media = await self._parse_data_url_owned(file_ref)
            if data_media is not None:
                data = data_media.data
                mime_type = data_media.media_type
                filename = data_url_filename(filename_hint, data_media.suffix)
                resp, _ = await self._client.upload(
                    io.BytesIO(data),
                    content_type=mime_type,
                    filename=filename,
                    filesize=len(data),
                )
                if isinstance(resp, UploadResponse):
                    return _UploadedMedia(
                        uri=resp.content_uri,
                        filename=filename,
                        mime_type=mime_type,
                        size=len(data),
                    )
                logger.warning(
                    f"MatrixChannel: data URL upload failed: {resp}",
                )
                return None
            local_path = local_media_path(file_ref)
            if local_path is None:
                return None
            path = Path(local_path).expanduser().resolve()
            if not any(
                path.is_relative_to(root)
                for root in (self._workspace_dir, self._media_dir())
            ):
                raise ValueError("MATRIX_MEDIA_OUTSIDE_WORKSPACE")
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
                return _UploadedMedia(
                    uri=resp.content_uri,
                    filename=path.name,
                    mime_type=mime_type,
                    size=len(data),
                )
            logger.warning("MatrixChannel: upload failed: %s", resp)
            return None
        except Exception as exc:
            logger.warning(
                "MatrixChannel: upload error for %s: %s",
                file_ref,
                exc,
            )
            return None

    def _is_dm_room_fallback(
        self,
        room: Optional[MatrixRoom],
        sender_id: str,
    ) -> bool:
        if not room or not self._user_id:
            return False
        try:
            users = list(getattr(room, "users", {}).keys())
            if users:
                return (
                    len(users) == 2
                    and self._user_id in users
                    and (sender_id in users)
                )
            member_count = int(getattr(room, "member_count", 0) or 0)
            return member_count == 2
        except Exception:
            return False

    def _prune_dm_room_cache(self, now_ms: int) -> None:
        cutoff = now_ms - DM_CACHE_TTL_MS
        while self._dm_room_cache:
            room_id, cached = next(iter(self._dm_room_cache.items()))
            if (
                cached["ts"] >= cutoff
                and len(self._dm_room_cache) <= DM_ROOM_CACHE_MAX_ENTRIES
            ):
                break
            self._dm_room_cache.pop(room_id)

    async def _is_dm_room(
        self,
        room_id: str,
        sender_id: str,
        room: Optional[MatrixRoom] = None,
    ) -> bool:
        if not self._client or not self._user_id:
            return False
        now = int(time.time() * 1000)
        cached = self._dm_room_cache.get(room_id)
        if cached and now - cached["ts"] < DM_CACHE_TTL_MS:
            self._dm_room_cache.move_to_end(room_id)
            members = cached["members"]
            is_dm = (
                len(members) == 2
                and self._user_id in members
                and (sender_id in members)
            )
            logger.debug(
                "MatrixChannel: DM check (cached) room=%s members=%d is_dm=%s",
                room_id,
                len(members),
                is_dm,
            )
            return is_dm
        try:
            resp = await self._client.joined_members(room_id)
            if isinstance(resp, JoinedMembersResponse):
                members = [m.user_id for m in resp.members]
                self._dm_room_cache[room_id] = {"members": members, "ts": now}
                self._dm_room_cache.move_to_end(room_id)
                self._prune_dm_room_cache(now)
                is_dm = (
                    len(members) == 2
                    and self._user_id in members
                    and (sender_id in members)
                )
                logger.debug(
                    "MatrixChannel: DM check (API) room=%s members=%d is_dm=%s members=%s",
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
                    "MatrixChannel: joined_members fallback for %s -> is_dm=%s",
                    room_id,
                    fallback,
                )
                return fallback
        except Exception as exc:
            fallback = self._is_dm_room_fallback(room, sender_id)
            logger.warning(
                "MatrixChannel: joined_members error for %s: %s; fallback is_dm=%s",
                room_id,
                exc,
                fallback,
            )
            return fallback

    async def _on_room_event(
        self,
        room: MatrixRoom,
        event: RoomMessageText,
    ) -> None:
        room_id = room.room_id
        if event.sender == self._user_id:
            return
        sender_id = event.sender
        text = event.body or ""
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
        if not is_dm:
            if self._require_mention(room_id) and (
                not self._was_mentioned(event, text)
            ):
                logger.info(
                    "MatrixChannel: group text not mentioned, cached to history (room=%s sender=%s event_id=%s)",
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
        await self._send_read_receipt(room_id, event.event_id)
        command_text = text
        stripped = self._strip_mention_prefix(text, room)
        if stripped.strip() == "NO_REPLY":
            logger.info(
                "MatrixChannel: received NO_REPLY from %s in %s, ignoring",
                sender_id,
                room_id,
            )
            return
        cmd = (
            stripped.lstrip("/").split()[0] if stripped.startswith("/") else ""
        )
        if cmd in _SLASH_COMMANDS:
            command_text = stripped
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
        content_parts: list[Any] = [
            TextContent(type=ContentType.TEXT, text=command_text),
        ]
        is_slash_cmd = command_text.startswith("/")
        if not is_dm and (not is_slash_cmd):
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
        if await self.on_event(payload):
            if not is_dm:
                self._clear_history(room_id)

    async def _on_room_media_event(self, room: MatrixRoom, event: Any) -> None:
        if event.sender == self._user_id:
            return
        sender_id = event.sender
        room_id = room.room_id
        is_dm = await self._is_dm_room(room_id, sender_id, room)
        if self._is_channel_disabled(sender_id, room_id, is_dm):
            return
        if not is_dm:
            if self._require_mention(room_id) and (
                not self._was_mentioned(event, "")
            ):
                logger.info(
                    "MatrixChannel: group media not mentioned, cached to history (room=%s sender=%s event_id=%s)",
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
        mxc_url: str = getattr(event, "url", "") or ""
        body: str = event.body or ""
        content_parts: list[Any] = []
        if mxc_url:
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
                        _no_vis = (
                            "[User sent an image (current model does not support "
                            f"image input): {body or filename}]"
                        )
                        content_parts.append(
                            TextContent(type=ContentType.TEXT, text=_no_vis),
                        )
                elif isinstance(event, RoomMessageAudio):
                    content_parts.append(
                        AudioContent(type=ContentType.AUDIO, data=file_uri),
                    )
                elif isinstance(event, RoomMessageVideo):
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
                        text=f"[Media unavailable: {body}]",
                    ),
                )
        if not content_parts:
            return
        if not is_dm:
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
                    TextContent(type=ContentType.TEXT, text=f"{sender_name}:"),
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
        if await self.on_event(payload):
            if not is_dm:
                self._clear_history(room_id)

    async def _send_read_receipt(self, room_id: str, event_id: str) -> None:
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

    _MATRIX_USER_ID_RE = re.compile(
        "@[a-zA-Z0-9._=+/\\-]+:[a-zA-Z0-9.\\-]+(?::\\d+)?",
    )

    def _extract_mentions_from_text(self, text: str) -> list[str]:
        matches = self._MATRIX_USER_ID_RE.findall(text)
        return list(dict.fromkeys(matches))

    def _apply_mention(
        self,
        content: dict[str, Any],
        user_id: str,
        room_id: str,
    ) -> None:
        body = content.get("body", "")
        mentioned_ids = self._extract_mentions_from_text(body)
        if mentioned_ids:
            content["m.mentions"] = {"user_ids": mentioned_ids}

    def _mark_room_encrypted(
        self,
        room_id: str,
        room: Optional[MatrixRoom] = None,
    ) -> None:
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
        if not self.encryption:
            return
        if not self._client or not getattr(self._client, "olm", None):
            logger.warning(
                "MatrixChannel: E2EE configured but Olm is not ready; outbound message to %s will not be encrypted",
                room_id,
            )
            return
        await self._e2ee_maintenance()
        if self._room_will_encrypt(room_id):
            return
        if room_id not in getattr(self._client, "rooms", {}):
            logger.warning(
                "MatrixChannel: room %s not in client cache; cannot confirm E2EE before send (wait for sync / join)",
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
                "MatrixChannel: E2EE on but room %s is not encrypted in client "
                "after state check; outbound send may be plaintext",
                room_id,
            )

    async def _sync_valid(self, response):
        if isinstance(response, SyncError) and response.status_code in {
            "M_UNKNOWN_TOKEN",
            "M_MISSING_TOKEN",
        }:
            self._client.access_token = self.access_token = ""
            await self.on_state("failed")
            return False
        return not self._is_stopping()

    async def start_typing(self, owner, route):
        async with self._typing_lock:
            if owner in self._typing_owners:
                return
            if self._stopping or not self._client:
                raise MatrixDeliveryError("NOT_CONNECTED")
            room_id = route["room_id"]
            self._typing_owners[owner] = room_id
            if room_id not in self._typing_tasks:
                try:
                    await self._client.room_typing(
                        room_id,
                        typing_state=True,
                        timeout=TYPING_SERVER_TIMEOUT_MS,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    raise MatrixDeliveryError(
                        "MATRIX_TYPING_UNKNOWN",
                        side_effect_possible=True,
                    ) from exc
                self._typing_tasks[room_id] = self._spawn(
                    self._typing_renewal_loop(room_id),
                )

    async def stop_typing(self, owner, room_id=None, *, local_only=False):
        async with self._typing_lock:
            room_id = self._typing_owners.get(owner) or room_id
            if room_id is None:
                return
            if any(
                (
                    key != owner and room == room_id
                    for key, room in self._typing_owners.items()
                )
            ):
                self._typing_owners.pop(owner, None)
                return
            task = self._typing_tasks.get(room_id)
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if local_only:
                # Retire local ownership without repeating an uncertain stop.
                self._typing_owners.pop(owner, None)
                self._typing_tasks.pop(room_id, None)
                return
            try:
                if self._client is None:
                    raise MatrixDeliveryError("NOT_CONNECTED")
                await self._client.room_typing(room_id, typing_state=False)
            except asyncio.CancelledError:
                raise
            except MatrixDeliveryError:
                raise
            except Exception as exc:
                raise MatrixDeliveryError(
                    "MATRIX_TYPING_STOP_UNKNOWN",
                    side_effect_possible=True,
                ) from exc
            self._typing_owners.pop(owner, None)
            self._typing_tasks.pop(room_id, None)

    async def _typing_renewal_loop(self, room_id):
        elapsed = 0
        try:
            while elapsed < TYPING_MAX_DURATION_S and not self._stopping:
                await asyncio.sleep(TYPING_RENEWAL_INTERVAL_S)
                elapsed += TYPING_RENEWAL_INTERVAL_S
                if elapsed >= TYPING_MAX_DURATION_S:
                    break
                await self._client.room_typing(
                    room_id,
                    typing_state=True,
                    timeout=TYPING_SERVER_TIMEOUT_MS,
                )
            if not self._stopping and self._client:
                await self._client.room_typing(room_id, typing_state=False)
        finally:
            if self._typing_tasks.get(room_id) is asyncio.current_task():
                self._typing_tasks.pop(room_id, None)

    async def _room_send(self, room_id, content, transaction_id):
        if self._stopping or self._client is None:
            raise MatrixDeliveryError("NOT_CONNECTED")
        # Encryption/state preparation has not yet attempted a visible room
        # message; errors here can be reported as definitely unsent.
        try:
            await self._prepare_room_send(room_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise MatrixDeliveryError(
                "MATRIX_SEND_PREPARATION_FAILED",
            ) from exc
        try:
            response = await self._client.room_send(
                room_id,
                "m.room.message",
                content,
                tx_id=transaction_id,
                ignore_unverified_devices=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise MatrixDeliveryError(
                "MATRIX_SEND_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        from nio.responses import RoomSendResponse, RoomSendError

        if isinstance(response, RoomSendResponse) and response.event_id:
            return response.event_id
        if isinstance(response, RoomSendError):
            status = getattr(
                getattr(response, "transport_response", None),
                "status",
                None,
            )
            definitive = (
                status is not None and 400 <= status < 500 and status != 408
            )
            # A structured forbidden/invalid token response is authoritative
            # even when nio did not retain the HTTP transport response.
            definitive = (
                definitive or response.status_code in _NON_RETRYABLE_AUTH_CODES
            )
            raise MatrixDeliveryError(
                "MATRIX_SEND_REJECTED"
                if definitive
                else "MATRIX_SEND_UNKNOWN",
                side_effect_possible=not definitive,
                retryable=definitive and status == 429,
            )
        raise MatrixDeliveryError(
            "MATRIX_SEND_UNKNOWN",
            side_effect_possible=True,
        )

    def _text_content(self, text, route):
        content = {
            "msgtype": "m.text",
            "body": text,
            "format": "org.matrix.custom.html",
            "formatted_body": _md_to_html(text),
        }
        sender_id = route.get("sender_id") or route.get("user_id")
        if sender_id:
            self._apply_mention(content, sender_id, route["room_id"])
        return content

    async def send_parts(self, route, parts, content_source, delivery_id):
        text = "\n".join(p["text"] for p in parts if p["type"] == "text")
        media = [p for p in parts if p["type"] != "text"]
        source = getattr(content_source, "value", content_source)
        # Preserve BaseChannel's content-parts presentation. Direct text and
        # send_media have their own host formatting entry points.
        if source == "content_parts":
            for part in media:
                kind = part["type"]
                locator = "data" if kind == "audio" else kind + "_url"
                text += (
                    "\n[Audio]"
                    if kind == "audio"
                    else f"\n[{kind.title()}: {part[locator]}]"
                )
            text = text.strip()
        sent = []
        try:
            if text.strip() == "NO_REPLY":
                return {"room_id": route["room_id"], "suppressed": "true"}
            if text or source == "direct":
                sent.append(
                    await self._room_send(
                        route["room_id"],
                        self._text_content(text, route),
                        delivery_id + "-text",
                    ),
                )
            for index, part in enumerate(media):
                kind = part["type"]
                locator = "data" if kind == "audio" else kind + "_url"
                file_ref = part.get(locator)
                if not file_ref:
                    continue
                uploaded = await self._upload_file(
                    file_ref,
                    filename_hint=part.get("filename"),
                )
                if uploaded is None:
                    raise MatrixDeliveryError("MATRIX_MEDIA_UNAVAILABLE")
                content = {
                    "msgtype": "m." + kind,
                    "body": uploaded.filename,
                    "url": uploaded.uri,
                    "info": {
                        "mimetype": uploaded.mime_type,
                        "size": uploaded.size,
                    },
                }
                sender_id = route.get("sender_id") or route.get("user_id")
                if sender_id:
                    self._apply_mention(content, sender_id, route["room_id"])
                sent.append(
                    await self._room_send(
                        route["room_id"],
                        content,
                        delivery_id + "-media-" + str(index),
                    ),
                )
        except MatrixDeliveryError as exc:
            if sent and not exc.side_effect_possible:
                raise MatrixDeliveryError(
                    "MATRIX_PARTIAL_SEND_UNKNOWN",
                    side_effect_possible=True,
                ) from exc
            raise
        return {"room_id": route["room_id"], "event_ids": "\n".join(sent)}

    async def start_stream(self, route, stream_type, delivery_id):
        event_id = await self._room_send(
            route["room_id"],
            self._text_content("...", route),
            delivery_id,
        )
        return {
            "room_id": route["room_id"],
            "event_id": event_id,
            "sender_id": route.get("sender_id", ""),
            "stream_type": stream_type,
            "sequence": "0",
            "final": "false",
        }

    async def update_stream(self, resource, text, delivery_id, *, final):
        room_id, event_id = resource["room_id"], resource["event_id"]
        if final and not text:
            return {**resource, "final": "true"}
        if text.strip() == "NO_REPLY":
            return {**resource, "final": "true", "suppressed": "true"}
        new_content = self._text_content(text, resource)
        content = {
            **new_content,
            "body": "* " + text,
            "formatted_body": "* " + new_content["formatted_body"],
            "m.new_content": new_content,
            "m.relates_to": {"rel_type": "m.replace", "event_id": event_id},
        }
        await self._room_send(room_id, content, delivery_id)
        # No fallback new-message send: a lost edit receipt is unknown.
        return {**resource, "final": "true" if final else "false"}

    @asynccontextmanager
    async def operation(self):
        if self._stopping:
            raise MatrixDeliveryError("NOT_CONNECTED")
        task = asyncio.current_task()
        self._operations.add(task)
        try:
            yield
        finally:
            self._operations.discard(task)

    async def _parse_data_url_owned(self, value):
        task = asyncio.create_task(parse_data_url_async(value))
        self._decoders.add(task)
        try:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # Base64 decoding uses a shared helper's thread. Settle that
                # thread before releasing this instance's operation custody.
                await asyncio.shield(task)
                raise
        finally:
            self._decoders.discard(task)
