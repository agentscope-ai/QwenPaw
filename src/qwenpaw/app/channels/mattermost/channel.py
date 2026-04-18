# -*- coding: utf-8 -*-
# pylint: disable=too-many-instance-attributes,too-many-arguments
"""Mattermost channel: WebSocket event listener + REST API replies."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Optional, Union

import httpx
from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    FileContent,
    ImageContent,
    TextContent,
)

from ....config.config import MattermostConfig as MattermostChannelConfig
from ....constant import WORKING_DIR
from ..base import (
    BaseChannel,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
)

logger = logging.getLogger(__name__)

MATTERMOST_POST_CHUNK_SIZE = 4000  # chars per post (hard limit ~16383)

_DEFAULT_MEDIA_DIR = WORKING_DIR / "media" / "mattermost"
_TYPING_TIMEOUT_S = 180

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


async def _download_mattermost_file(
    *,
    http: httpx.AsyncClient,
    url: str,
    file_id: str,
    media_dir: Path,
    filename_hint: str = "",
) -> Optional[str]:
    """Stream-download a Mattermost file to local media_dir; return path."""
    try:
        media_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename_hint).suffix if filename_hint else ""
        local_name = f"{uuid.uuid4().hex[:12]}{suffix or '.bin'}"
        local_path = media_dir / local_name
        async with http.stream("GET", url) as resp:
            if resp.status_code != 200:
                logger.warning(
                    "mattermost: download %s returned %s",
                    file_id,
                    resp.status_code,
                )
                return None
            with open(local_path, "wb") as fh:
                async for chunk in resp.aiter_bytes(65536):
                    fh.write(chunk)
        return str(local_path)
    except Exception:
        logger.exception("mattermost: download failed for file_id=%s", file_id)
        return None


class MattermostChannel(BaseChannel):
    """Mattermost channel: WebSocket listener + REST API replies.

    Session model
    -------------
    - DM  (channel_type == 'D')  → session_id = mattermost_dm:{mm_channel_id}
    - Group/Channel (threaded)   → session_id = mattermost_thread:{root_id}

    Native payload format
    ---------------------
    {
        "channel_id":    "mattermost",        # framework channel type key
        "sender_id":     "<mattermost user_id>",
        "content_parts": [...],               # TextContent / ImageContent / …
        "meta": {
            "mm_channel_id": "<mattermost channel id>",
            "root_id":       "<thread root post id or ''>",
            "channel_type":  "D" | "O" | "P" | …,
            "post_id":       "<triggering post id>",
        },
    }
    """

    channel = "mattermost"
    uses_manager_queue = True

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        url: str,
        bot_token: str,
        bot_prefix: str = "",
        media_dir: str = "",
        show_typing: Optional[bool] = None,
        thread_follow_without_mention: bool = False,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        dm_policy: str = "open",
        group_policy: str = "open",
        allow_from: Optional[list] = None,
        deny_message: str = "",
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
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix
        self._url = url.rstrip("/")
        self._bot_token = bot_token
        self._media_dir = (
            Path(media_dir).expanduser() if media_dir else _DEFAULT_MEDIA_DIR
        )
        self._show_typing = show_typing if show_typing is not None else True
        self._thread_follow = thread_follow_without_mention

        # Runtime state
        self._bot_id: str = ""
        self._bot_username: str = ""
        self._task: Optional[asyncio.Task] = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._participated_threads: set[str] = set()
        self._seen_sessions: set[str] = set()

        # Reuse a single HTTP client (BaseChannel._http field)
        # Only Authorization header — Content-Type is set per-request by httpx
        # (json= → application/json, files= → multipart/form-data)
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self._bot_token}"},
            timeout=30.0,
            follow_redirects=True,
        )

        if self.enabled and not self._url:
            logger.warning("mattermost: enabled but url is empty — disabled")
            self.enabled = False
        if self.enabled and not self._bot_token:
            logger.warning(
                "mattermost: enabled but bot_token is empty — disabled",
            )
            self.enabled = False

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: Union[MattermostChannelConfig, dict],
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
    ) -> "MattermostChannel":
        if isinstance(config, dict):
            c = config
        else:
            c = config.model_dump()

        def _s(key: str) -> str:
            return (c.get(key) or "").strip()

        return cls(
            process=process,
            enabled=bool(c.get("enabled", False)),
            url=_s("url"),
            bot_token=_s("bot_token"),
            bot_prefix=_s("bot_prefix"),
            media_dir=_s("media_dir"),
            show_typing=c.get("show_typing"),
            thread_follow_without_mention=bool(
                c.get("thread_follow_without_mention", False),
            ),
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            dm_policy=c.get("dm_policy") or "open",
            group_policy=c.get("group_policy") or "open",
            allow_from=c.get("allow_from") or [],
            deny_message=c.get("deny_message") or "",
        )

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "MattermostChannel":
        import os

        allow_from_env = os.getenv("MATTERMOST_ALLOW_FROM", "")
        allow_from = (
            [s.strip() for s in allow_from_env.split(",") if s.strip()]
            if allow_from_env
            else []
        )
        return cls(
            process=process,
            enabled=os.getenv("MATTERMOST_CHANNEL_ENABLED", "0") == "1",
            url=os.getenv("MATTERMOST_URL", ""),
            bot_token=os.getenv("MATTERMOST_BOT_TOKEN", ""),
            bot_prefix=os.getenv("MATTERMOST_BOT_PREFIX", ""),
            media_dir=os.getenv("MATTERMOST_MEDIA_DIR", ""),
            show_typing=os.getenv("MATTERMOST_SHOW_TYPING", "1") == "1",
            thread_follow_without_mention=(
                os.getenv("MATTERMOST_THREAD_FOLLOW", "0") == "1"
            ),
            on_reply_sent=on_reply_sent,
            dm_policy=os.getenv("MATTERMOST_DM_POLICY", "open"),
            group_policy=os.getenv("MATTERMOST_GROUP_POLICY", "open"),
            allow_from=allow_from,
            deny_message=os.getenv("MATTERMOST_DENY_MESSAGE", ""),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("mattermost: start() skipped (enabled=false)")
            return
        self._task = asyncio.create_task(
            self._run(),
            name="mattermost_websocket",
        )
        logger.info("mattermost: channel started (websocket task created)")

    async def stop(self) -> None:
        if not self.enabled:
            return
        for cid in list(self._typing_tasks):
            self._stop_typing(cid)
        if self._task:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
            self._task = None
        try:
            await self._http.aclose()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # WebSocket loop
    # ------------------------------------------------------------------

    async def _init_bot_info(self) -> bool:
        """Fetch and cache bot_id / bot_username. Returns True on success."""
        try:
            resp = await self._http.get(f"{self._url}/api/v4/users/me")
            if resp.status_code == 200:
                data = resp.json()
                self._bot_id = data.get("id", "")
                self._bot_username = data.get("username", "")
                logger.info(
                    "mattermost: bot ready — id=%s username=@%s",
                    self._bot_id,
                    self._bot_username,
                )
                return True
            logger.error(
                "mattermost: /users/me returned %s — check bot_token",
                resp.status_code,
            )
        except Exception:
            logger.exception("mattermost: failed to fetch bot info")
        return False

    async def _run(self) -> None:
        """Top-level task: fetch bot info, then enter WS reconnect loop."""
        if not await self._init_bot_info():
            logger.error("mattermost: cannot start — bot info fetch failed")
            return
        await self._websocket_loop()

    async def _websocket_loop(self) -> None:
        """WebSocket listener with exponential backoff reconnect."""
        try:
            import websockets  # type: ignore
        except ImportError:
            logger.error(
                "mattermost: 'websockets' not installed. "
                "Run: uv pip install websockets",
            )
            return

        ws_url = (
            self._url.replace("http://", "ws://").replace("https://", "wss://")
            + "/api/v4/websocket"
        )
        reconnect_delay = 1

        while True:
            seq = 1
            try:
                async with websockets.connect(
                    ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    auth_req = {
                        "seq": seq,
                        "action": "authentication_challenge",
                        "data": {"token": self._bot_token},
                    }
                    await ws.send(json.dumps(auth_req))
                    reconnect_delay = 1  # reset on successful connect
                    logger.info(
                        "mattermost: websocket connected and authenticated",
                    )

                    async for raw in ws:
                        data = json.loads(raw)
                        if data.get("event") == "posted":
                            asyncio.create_task(self._on_posted_event(data))

            except asyncio.CancelledError:
                logger.debug("mattermost: websocket loop cancelled")
                return
            except Exception as exc:
                logger.warning(
                    "mattermost: websocket error: %s — retrying in %ds",
                    exc,
                    reconnect_delay,
                )
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)

    # ------------------------------------------------------------------
    # Message event helper
    # ------------------------------------------------------------------

    def _is_triggered(self, post: dict, channel_type: str) -> bool:
        """Check if the bot should respond to this post."""
        sender_id = post.get("user_id", "")
        if sender_id == self._bot_id:
            return False

        message_text = post.get("message", "")
        original_root_id = post.get("root_id", "")

        is_dm = channel_type == "D"
        bot_mention = f"@{self._bot_username}"
        is_mentioned = bool(
            self._bot_username and bot_mention.lower() in message_text.lower(),
        )
        is_in_thread = bool(original_root_id)
        thread_followed = (
            self._thread_follow
            and is_in_thread
            and original_root_id in self._participated_threads
        )
        return is_dm or is_mentioned or thread_followed

    async def _get_context_prefix(
        self,
        session_id: str,
        mm_channel_id: str,
        original_root_id: str,
        post_id: str,
        is_dm: bool,
    ) -> str:
        """Fetch history context if needed."""
        if is_dm:
            if session_id not in self._seen_sessions:
                self._seen_sessions.add(session_id)
                logger.info(
                    "mattermost: first DM contact on %s — "
                    "fetching channel history",
                    session_id,
                )
                return await self._fetch_channel_history(mm_channel_id)
        elif original_root_id:
            logger.info("mattermost: fetching thread gap for %s", session_id)
            return await self._fetch_thread_history(
                original_root_id,
                triggering_post_id=post_id,
            )
        else:
            if session_id not in self._seen_sessions:
                self._seen_sessions.add(session_id)
                logger.info(
                    "mattermost: new thread on %s — "
                    "fetching channel history as background",
                    session_id,
                )
                return await self._fetch_channel_history(
                    mm_channel_id,
                    per_page=10,
                )
        return ""

    async def _process_attachments(self, post: dict) -> list[Any]:
        """Download and wrap attachments."""
        parts = []
        file_ids: list[str] = post.get("file_ids") or []
        # Build filename hints from post metadata when available
        metadata = post.get("metadata") or {}
        file_infos: list[dict] = metadata.get("files") or []
        hint_map: dict[str, str] = {
            fi.get("id", ""): fi.get("name", "")
            for fi in file_infos
            if fi.get("id")
        }
        for fid in file_ids:
            local_path = await self._download_file(
                fid,
                filename_hint=hint_map.get(fid, ""),
            )
            if local_path:
                suffix = Path(local_path).suffix.lower()
                if suffix in _IMAGE_SUFFIXES:
                    parts.append(
                        ImageContent(
                            type=ContentType.IMAGE,
                            image_url=local_path,
                        ),
                    )
                else:
                    parts.append(
                        FileContent(
                            type=ContentType.FILE,
                            file_url=local_path,
                        ),
                    )
        return parts

    # ------------------------------------------------------------------
    # Message event handler
    # ------------------------------------------------------------------

    async def _on_posted_event(self, event_data: dict) -> None:
        """Handle one 'posted' WebSocket event end-to-end."""
        raw_post = event_data.get("data", {}).get("post", "{}")
        post: dict = json.loads(raw_post)
        channel_type: str = event_data.get("data", {}).get("channel_type", "")

        if not self._is_triggered(post, channel_type):
            return

        sender_id: str = post.get("user_id", "")
        mm_channel_id: str = post.get("channel_id", "")
        post_id: str = post.get("id", "")
        message_text: str = post.get("message", "")
        original_root_id: str = post.get("root_id", "")
        is_dm = channel_type == "D"

        # ACL check
        allowed, error_msg = self._check_allowlist(sender_id, not is_dm)
        if not allowed:
            logger.info(
                "mattermost allowlist blocked: sender=%s",
                sender_id,
            )
            if error_msg:
                target_root = original_root_id or post_id
                await self._post_message(
                    mm_channel_id,
                    error_msg,
                    target_root,
                )
            return

        # 3. Determine effective root_id and session_id
        #
        # DM:  session always tied to the DM channel (unified memory).
        #      root_id is preserved so replies land inside the thread when
        #      the user triggered from within one; flat otherwise.
        #
        # Channel: each thread is its own session.
        #      A flat @mention seeds a new thread (root_id = post_id).
        if is_dm:
            target_root_id = (
                original_root_id  # "" for flat DM, non-empty for thread
            )
            session_id = f"mattermost_dm:{mm_channel_id}"
        else:
            target_root_id = original_root_id if original_root_id else post_id
            session_id = f"mattermost_thread:{target_root_id}"

        # 4. Start typing indicator loop
        if self._show_typing:
            self._start_typing(mm_channel_id, target_root_id)

        # 5. Clean @mention from text
        bot_mention = f"@{self._bot_username}"
        clean_text = re.sub(
            re.escape(bot_mention),
            "",
            message_text,
            flags=re.IGNORECASE,
        ).strip()

        # 6. Context fetching
        context_prefix = await self._get_context_prefix(
            session_id,
            mm_channel_id,
            original_root_id,
            post_id,
            is_dm,
        )

        # 7. Build content_parts
        content_parts: list[Any] = []

        if context_prefix:
            content_parts.append(
                TextContent(type=ContentType.TEXT, text=context_prefix),
            )
        if clean_text:
            content_parts.append(
                TextContent(type=ContentType.TEXT, text=clean_text),
            )

        # 8. Download and classify attachments
        content_parts.extend(await self._process_attachments(post))

        if not content_parts:
            content_parts.append(TextContent(type=ContentType.TEXT, text=""))

        # 9. Enqueue native payload
        native = {
            "channel_id": self.channel,  # "mattermost" — framework key
            "sender_id": sender_id,
            "content_parts": content_parts,
            "meta": {
                "mm_channel_id": mm_channel_id,
                "root_id": target_root_id,
                "channel_type": channel_type,
                "post_id": post_id,
            },
        }
        if self._enqueue is not None:
            self._enqueue(native)
        else:
            logger.warning("mattermost: _enqueue not set, message dropped")
            self._stop_typing(mm_channel_id)
            return

        # 10. Record thread participation
        if target_root_id:
            self._participated_threads.add(target_root_id)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def _start_typing(self, mm_channel_id: str, root_id: str = "") -> None:
        """Start (or restart) the typing indicator loop for a channel."""
        self._stop_typing(mm_channel_id)
        self._typing_tasks[mm_channel_id] = asyncio.create_task(
            self._typing_loop(mm_channel_id, root_id),
        )

    def _stop_typing(self, mm_channel_id: str) -> None:
        """Cancel the typing indicator loop for a channel."""
        task = self._typing_tasks.pop(mm_channel_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(
        self,
        mm_channel_id: str,
        root_id: str = "",
    ) -> None:
        """Send 'typing' status every 4 s until cancelled.

        Mattermost typing state expires in ~5 s so we refresh at 4 s.
        Safety timeout at _TYPING_TIMEOUT_S to avoid infinite loops.
        """
        try:
            deadline = asyncio.get_event_loop().time() + _TYPING_TIMEOUT_S
            while True:
                try:
                    await self._http.post(
                        f"{self._url}/api/v4/users/{self._bot_id}/typing",
                        json={
                            "channel_id": mm_channel_id,
                            "parent_id": root_id,
                        },
                    )
                except Exception:
                    logger.debug("mattermost: typing indicator send failed")
                await asyncio.sleep(4)
                if asyncio.get_event_loop().time() >= deadline:
                    break
        except asyncio.CancelledError:
            pass
        finally:
            if self._typing_tasks.get(mm_channel_id) is asyncio.current_task():
                self._typing_tasks.pop(mm_channel_id, None)

    def _get_thread_target_order(
        self,
        order: list[str],
        posts: dict,
        last_bot_idx: int,
    ) -> tuple[list[str], str]:
        """Helper to determine the slice of thread posts to show as context."""
        if last_bot_idx >= 0:
            # Bot has replied before.
            # Walk backwards to find the start of the consecutive bot-reply seq
            bot_seq_start = last_bot_idx
            while bot_seq_start > 0:
                prev_pid = order[bot_seq_start - 1]
                if posts.get(prev_pid, {}).get("user_id") != self._bot_id:
                    break
                bot_seq_start -= 1

            # The user trigger that produced this bot reply sequence is
            # the post immediately before it.
            trigger_idx = bot_seq_start - 1

            # Gap = all NON-bot posts after the trigger (inclusive of
            # messages posted during bot processing AND after bot reply).
            if trigger_idx >= 0:
                gap = [
                    pid
                    for pid in order[trigger_idx + 1 :]
                    if posts.get(pid, {}).get("user_id") != self._bot_id
                ]
            else:
                # Bot reply sequence starts at the very beginning
                gap = [
                    pid
                    for pid in order
                    if posts.get(pid, {}).get("user_id") != self._bot_id
                ]
            return gap, "[Thread context supplement (unprocessed by bot)]"

        # Bot joining this thread for the first time: full history
        return order, "[Thread history]"

    # ------------------------------------------------------------------
    # History helpers (lazy context — first session contact only)
    # ------------------------------------------------------------------

    async def _fetch_thread_history(
        self,
        root_id: str,
        triggering_post_id: str = "",
    ) -> str:
        """Pull thread posts and return a formatted context prefix.

        Smart fetch strategy:
        - If bot has never replied in this thread: return all posts
          (bot is joining the thread for the first time).
        - If bot has replied before: return only the "unseen" user
          messages — i.e. messages the bot hasn't processed yet.
          This includes messages posted *during* bot processing
          (which land chronologically before the bot reply) as well
          as messages posted after the bot reply.

        In all cases the triggering post itself is excluded (it is sent
        separately as the main user message).
        """
        try:
            resp = await self._http.get(
                f"{self._url}/api/v4/posts/{root_id}/thread",
            )
            if resp.status_code != 200:
                return ""
            data = resp.json()
            order: list[str] = list(data.get("order", []))
            posts: dict = data.get("posts", {})

            # Sort by create_at to guarantee chronological order
            # (thread API order direction may differ across MM versions)
            order.sort(key=lambda pid: posts.get(pid, {}).get("create_at", 0))

            # Exclude the triggering post (processed as main message)
            if triggering_post_id:
                order = [pid for pid in order if pid != triggering_post_id]

            # Find the last bot reply to determine the "gap" start
            last_bot_idx = -1
            for i, pid in enumerate(order):
                if posts.get(pid, {}).get("user_id") == self._bot_id:
                    last_bot_idx = i

            target_order, label = self._get_thread_target_order(
                order,
                posts,
                last_bot_idx,
            )

            lines = [label]
            for pid in target_order:
                p = posts.get(pid, {})
                role = "Bot" if p.get("user_id") == self._bot_id else "User"
                msg = p.get("message", "").strip()
                if msg:
                    lines.append(f"{role}: {msg}")
            if len(lines) == 1:
                return ""  # only label, no actual content
            lines.append(
                "[The above is supplementary context, "
                "please answer based on existing memory]",
            )
            return "\n".join(lines)
        except Exception:
            logger.exception("mattermost: fetch thread history failed")
        return ""

    async def _fetch_channel_history(
        self,
        mm_channel_id: str,
        per_page: int = 20,
    ) -> str:
        """Pull recent DM posts and return a formatted prefix string."""
        try:
            resp = await self._http.get(
                f"{self._url}/api/v4/channels/{mm_channel_id}/posts",
                params={"per_page": per_page},
            )
            if resp.status_code == 200:
                data = resp.json()
                order: list[str] = list(data.get("order", []))
                posts: dict = data.get("posts", {})
                order.reverse()
                lines = [f"[Recent {per_page} DM context messages]"]
                for pid in order:
                    p = posts.get(pid, {})
                    role = (
                        "Bot" if p.get("user_id") == self._bot_id else "User"
                    )
                    msg = p.get("message", "").strip()
                    if msg:
                        lines.append(f"{role}: {msg}")
                lines.append(
                    "[History ended, please answer the following questions "
                    "based on the above context]",
                )
                return "\n".join(lines)
        except Exception:
            logger.exception("mattermost: fetch channel history failed")
        return ""

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    async def _download_file(
        self,
        file_id: str,
        filename_hint: str = "",
    ) -> Optional[str]:
        """Download a Mattermost attachment; return local path or None."""
        return await _download_mattermost_file(
            http=self._http,
            url=f"{self._url}/api/v4/files/{file_id}",
            file_id=file_id,
            media_dir=self._media_dir,
            filename_hint=filename_hint,
        )

    async def _upload_file(
        self,
        mm_channel_id: str,
        local_path: str,
    ) -> Optional[str]:
        """Upload a local file; return Mattermost file_id or None.

        Uses multipart/form-data — httpx sets the Content-Type boundary
        automatically when 'files=' is passed, so we do NOT include
        Content-Type: application/json in this request.
        """
        path = Path(local_path)
        if not path.exists():
            logger.warning(
                "mattermost: upload — file not found: %s",
                local_path,
            )
            return None
        try:
            with open(path, "rb") as fh:
                resp = await self._http.post(
                    f"{self._url}/api/v4/files",
                    params={"channel_id": mm_channel_id},
                    files={"files": (path.name, fh)},
                    # No json= here; httpx handles Content-Type automatically
                )
            if resp.status_code in (200, 201):
                file_infos = resp.json().get("file_infos", [])
                if file_infos:
                    return file_infos[0].get("id")
            logger.warning(
                "mattermost: file upload failed %s: %s",
                resp.status_code,
                resp.text[:200],
            )
        except Exception:
            logger.exception("mattermost: upload failed for %s", local_path)
        return None

    # ------------------------------------------------------------------
    # Internal post helper
    # ------------------------------------------------------------------

    async def _post_message(
        self,
        mm_channel_id: str,
        text: str,
        root_id: str = "",
        file_ids: Optional[list[str]] = None,
    ) -> bool:
        """Call POST /api/v4/posts. Returns True on success."""
        payload: dict[str, Any] = {
            "channel_id": mm_channel_id,
            "message": text,
            "root_id": root_id,
        }
        if file_ids:
            payload["file_ids"] = file_ids
        try:
            resp = await self._http.post(
                f"{self._url}/api/v4/posts",
                json=payload,
            )
            if resp.status_code == 201:
                return True
            logger.error(
                "mattermost: post failed %s: %s",
                resp.status_code,
                resp.text[:300],
            )
        except Exception:
            logger.exception("mattermost: _post_message error")
        return False

    # ------------------------------------------------------------------
    # Send interface
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str) -> list[str]:
        """Split text at boundaries under post size limit."""
        if not text or len(text) <= MATTERMOST_POST_CHUNK_SIZE:
            return [text] if text else []
        chunks: list[str] = []
        rest = text
        while rest:
            if len(rest) <= MATTERMOST_POST_CHUNK_SIZE:
                chunks.append(rest)
                break
            chunk = rest[:MATTERMOST_POST_CHUNK_SIZE]
            last_nl = chunk.rfind("\n")
            if last_nl > MATTERMOST_POST_CHUNK_SIZE // 2:
                chunk = chunk[: last_nl + 1]
            else:
                last_space = chunk.rfind(" ")
                if last_space > MATTERMOST_POST_CHUNK_SIZE // 2:
                    chunk = chunk[: last_space + 1]
            chunks.append(chunk)
            rest = rest[len(chunk) :].lstrip("\n ")
        return chunks

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[dict] = None,
    ) -> None:
        """Send text reply to Mattermost.

        to_handle = mm_channel_id (resolved by get_to_handle_from_request).
        root_id from meta guarantees the reply threads correctly.
        """
        if not self.enabled:
            return
        meta = meta or {}
        mm_channel_id = meta.get("mm_channel_id") or to_handle
        root_id: str = meta.get("root_id") or ""
        if not mm_channel_id:
            logger.warning(
                "mattermost send: no mm_channel_id in meta or to_handle",
            )
            return
        self._stop_typing(mm_channel_id)
        for chunk in self._chunk_text(text):
            await self._post_message(mm_channel_id, chunk, root_id)

    async def send_media(
        self,
        to_handle: str,
        part: OutgoingContentPart,
        meta: Optional[dict] = None,
    ) -> None:
        """Upload a local file and post it as a Mattermost attachment."""
        if not self.enabled:
            return
        meta = meta or {}
        mm_channel_id = meta.get("mm_channel_id") or to_handle
        root_id: str = meta.get("root_id") or ""
        if not mm_channel_id:
            logger.warning("mattermost send_media: no mm_channel_id")
            return
        self._stop_typing(mm_channel_id)

        part_type = getattr(part, "type", None)
        local_path: Optional[str] = None
        if part_type == ContentType.IMAGE:
            local_path = getattr(part, "image_url", None)
        elif part_type == ContentType.VIDEO:
            local_path = getattr(part, "video_url", None)
        elif part_type == ContentType.FILE:
            local_path = getattr(part, "file_url", None)
        elif part_type == ContentType.AUDIO:
            local_path = getattr(part, "data", None)

        if not local_path:
            return
        if local_path.startswith("file://"):
            local_path = local_path[len("file://") :]

        file_id = await self._upload_file(mm_channel_id, local_path)
        if file_id:
            await self._post_message(mm_channel_id, "", root_id, [file_id])
        else:
            # Fallback: send file path as plain text
            await self._post_message(
                mm_channel_id,
                f"[Attachment: {local_path}]",
                root_id,
            )

    # ------------------------------------------------------------------
    # BaseChannel interface
    # ------------------------------------------------------------------

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[dict] = None,
    ) -> str:
        """Map meta to session_id.

        DM  → mattermost_dm:{mm_channel_id}
        Group/Thread → mattermost_thread:{root_id or post_id}
        """
        meta = channel_meta or {}
        channel_type = meta.get("channel_type", "")
        mm_channel_id = meta.get("mm_channel_id", "")
        root_id = meta.get("root_id", "")
        post_id = meta.get("post_id", "")

        if channel_type == "D":
            return f"mattermost_dm:{mm_channel_id}"
        effective_root = root_id if root_id else post_id
        return f"mattermost_thread:{effective_root}"

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """Convert Mattermost native dict → AgentRequest."""
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.user_id = sender_id
        request.channel_meta = meta
        return request

    def get_to_handle_from_request(self, request: Any) -> str:
        """Return mm_channel_id for the send() call."""
        meta = getattr(request, "channel_meta", None) or {}
        mm_channel_id = meta.get("mm_channel_id")
        if mm_channel_id:
            return str(mm_channel_id)
        # Fallback: extract from DM session_id
        sid = getattr(request, "session_id", "")
        if sid.startswith("mattermost_dm:"):
            return sid.split(":", 1)[-1]
        return getattr(request, "user_id", "") or ""

    def to_handle_from_target(self, *, user_id: str, session_id: str) -> str:
        """Cron/proactive dispatch: resolve send target from session_id."""
        if session_id.startswith("mattermost_dm:"):
            return session_id.split(":", 1)[-1]
        return user_id
