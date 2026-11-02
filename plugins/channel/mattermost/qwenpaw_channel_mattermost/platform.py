# -*- coding: utf-8 -*-
"""Worker-owned Mattermost REST, authenticated WebSocket and media effects."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
import websockets
from qwenpaw.app.channels.utils import (
    file_url_to_local_path,
    materialize_data_url,
)

logger = logging.getLogger(__name__)
MATTERMOST_POST_CHUNK_SIZE = 4000
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}


class MattermostDeliveryError(Exception):
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


class MattermostPlatform:
    def __init__(self, config, on_event, on_state):
        self.config, self.on_event, self.on_state = config, on_event, on_state
        self._url = config.get("url", "").strip().rstrip("/")
        self._bot_token = config.get("bot_token", "").strip()
        workspace = config.get("workspace_dir")
        if config.get("media_dir"):
            self._media_dir = Path(config["media_dir"]).expanduser()
        elif workspace:
            self._media_dir = Path(workspace) / "media"
        else:
            from qwenpaw.constant import WORKING_DIR

            self._media_dir = WORKING_DIR / "media" / "mattermost"
        self._thread_follow = bool(config.get("thread_follow_without_mention"))
        self._bot_id, self._bot_username = "", ""
        self._participated_threads, self._seen_sessions = (
            OrderedDict(),
            OrderedDict(),
        )
        self._processed = OrderedDict()
        self._session_locks = {}
        self._typing_tasks, self._event_tasks = {}, set()
        self._task, self._http, self._ws = None, None, None
        self._stopping, self.connected = False, False
        self._epoch = 0

    @staticmethod
    def _bounded_add(store, key, max_items=10000):
        store[key] = None
        store.move_to_end(key)
        while len(store) > max_items:
            store.popitem(last=False)

    async def start(self):
        if not self._url or not self._bot_token:
            raise ValueError("MATTERMOST_URL_AND_TOKEN_REQUIRED")
        self._http = httpx.AsyncClient(
            headers={"Authorization": "Bearer " + self._bot_token},
            timeout=30,
            follow_redirects=True,
        )
        response = await self._http.get(self._url + "/api/v4/users/me")
        response.raise_for_status()
        identity = response.json()
        self._bot_id, self._bot_username = identity.get(
            "id",
            "",
        ), identity.get("username", "")
        if not self._bot_id:
            raise ValueError("MATTERMOST_BOT_IDENTITY_INVALID")
        self._task = asyncio.create_task(self._websocket_loop())

    async def _websocket_loop(self):
        url = (
            self._url.replace("http://", "ws://").replace("https://", "wss://")
            + "/api/v4/websocket"
        )
        delay = 1
        while not self._stopping:
            try:
                await self.on_state("connecting")
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    self._ws = ws
                    self._epoch += 1
                    await ws.send(
                        json.dumps(
                            {
                                "seq": 1,
                                "action": "authentication_challenge",
                                "data": {"token": self._bot_token},
                            },
                        ),
                    )
                    authenticated = False
                    async for raw in ws:
                        event = json.loads(raw)
                        if not authenticated:
                            if event.get("seq_reply") == 1:
                                if event.get("status") != "OK":
                                    raise ValueError(
                                        "MATTERMOST_AUTHENTICATION_REJECTED",
                                    )
                                authenticated = self.connected = True
                                await self.on_state("connected")
                                delay = 1
                            continue
                        if event.get("event") == "posted":
                            self._spawn_event(event, self._epoch)
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._stopping:
                    raise
                logger.warning(
                    "Mattermost listener disconnected",
                    exc_info=True,
                )
            finally:
                self.connected = False
                self._epoch += 1
                if not self._stopping:
                    self._ws = None
                if not self._stopping:
                    await self.on_state("disconnected")
            if not self._stopping:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    def _spawn_event(self, event, epoch):
        if self._stopping or len(self._event_tasks) >= 500:
            return
        task = asyncio.create_task(self._on_posted_event(event, epoch))
        self._event_tasks.add(task)
        task.add_done_callback(self._event_done)

    def _event_done(self, task):
        self._event_tasks.discard(task)
        if not task.cancelled() and task.exception():
            logger.warning("Mattermost event failed: %s", task.exception())

    @asynccontextmanager
    async def _session_lock(self, session):
        entry = self._session_locks.setdefault(session, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self._session_locks.pop(session, None)

    async def _on_posted_event(self, event, epoch):
        data = event.get("data", {})
        post = json.loads(data.get("post", "{}"))
        channel_type = data.get("channel_type", "")
        sender, channel, post_id = (
            str(post.get(key) or "") for key in ("user_id", "channel_id", "id")
        )
        if not sender or not channel or not post_id:
            return
        is_dm = channel_type == "D"
        original_root = str(post.get("root_id") or "")
        root = original_root if is_dm else original_root or post_id
        session = (
            "mattermost_dm:" + channel
            if is_dm
            else "mattermost_thread:" + root
        )
        # First-context fetch and ACK commit serialize per session; unrelated
        # conversations retain independent REST and admission progress.
        async with self._session_lock(session):
            if (
                self._stopping
                or epoch != self._epoch
                or post_id in self._processed
            ):
                return
            if not self._is_triggered(post, channel_type):
                return
            if original_root and not is_dm:
                context = await self._fetch_thread_history(
                    original_root,
                    triggering_post_id=post_id,
                )
            elif session not in self._seen_sessions:
                context = await self._fetch_channel_history(
                    channel,
                    per_page=20 if is_dm else 10,
                    triggering_post_id=post_id,
                )
            else:
                context = ""
            parts = []
            if context:
                parts.append({"type": "text", "text": context})
            text = (
                re.sub(
                    re.escape("@" + self._bot_username),
                    "",
                    post.get("message", ""),
                    flags=re.IGNORECASE,
                ).strip()
                if self._bot_username
                else post.get("message", "").strip()
            )
            if text:
                parts.append({"type": "text", "text": text})
            parts.extend(await self._process_attachments(post))
            accepted = await self.on_event(
                {
                    "post_id": post_id,
                    "sender": sender,
                    "channel": channel,
                    "root": root,
                    "channel_type": channel_type,
                    "session": session,
                    "parts": parts or [{"type": "text", "text": ""}],
                    "mentioned": bool(self._bot_username)
                    and "@" + self._bot_username.lower()
                    in post.get("message", "").lower(),
                },
            )
            if accepted:
                self._bounded_add(self._processed, post_id)
                self._bounded_add(self._seen_sessions, session)
                if root:
                    self._bounded_add(self._participated_threads, root)

    async def _process_attachments(self, post):
        hints = {
            item.get("id"): item.get("name", "")
            for item in (post.get("metadata") or {}).get("files", [])
        }
        parts = []
        for file_id in post.get("file_ids") or []:
            local = await self._download_file(
                file_id,
                filename_hint=hints.get(file_id, ""),
            )
            if local:
                kind = (
                    "image"
                    if Path(local).suffix.lower() in _IMAGE_SUFFIXES
                    else "file"
                )
                parts.append({"type": kind, kind + "_url": local})
        return parts

    async def start_typing(self, handle, channel, root):
        if handle in self._typing_tasks:
            return
        response = await self._http.post(
            f"{self._url}/api/v4/users/{self._bot_id}/typing",
            json={"channel_id": channel, "parent_id": root},
        )
        response.raise_for_status()
        self._typing_tasks[handle] = asyncio.create_task(
            self._typing_loop(handle, channel, root),
        )

    async def _typing_loop(self, handle, channel, root):
        deadline = asyncio.get_running_loop().time() + 180
        try:
            while not self._stopping:
                await asyncio.sleep(4)
                if asyncio.get_running_loop().time() >= deadline:
                    break
                try:
                    await self._http.post(
                        f"{self._url}/api/v4/users/{self._bot_id}/typing",
                        json={"channel_id": channel, "parent_id": root},
                    )
                except httpx.HTTPError:
                    logger.debug("Mattermost typing refresh failed")
        finally:
            self._typing_tasks.pop(handle, None)

    async def stop_typing(self, handle):
        task = self._typing_tasks.get(handle)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._typing_tasks.pop(handle, None)

    async def stop(self):
        self._stopping = True
        self._epoch += 1
        retry_socket = (
            self._ws if self._task is not None and self._task.done() else None
        )
        if self._task is not None:
            # Fence the listener immediately, but allow independent local
            # effects and HTTP closure to finish while WS closes its socket.
            self._task.cancel()
        for task in tuple(self._event_tasks):
            task.cancel()
        if self._event_tasks:
            await asyncio.gather(
                *tuple(self._event_tasks),
                return_exceptions=True,
            )
        for handle in tuple(self._typing_tasks):
            await self.stop_typing(handle)
        if self._http is not None:
            # Retain the client on failure so stop can be retried by the owner.
            await self._http.aclose()
            self._http = None
        if retry_socket is not None:
            # A done failed listener is historical evidence, not a fresh close.
            # Retry the same retained socket; retain both refs if it fails again.
            await retry_socket.close()
            await retry_socket.wait_closed()
            self._task = None
            self._ws = None
        if self._task is not None:
            outcomes = await asyncio.gather(self._task, return_exceptions=True)
            for outcome in outcomes:
                if isinstance(outcome, BaseException) and not isinstance(
                    outcome,
                    asyncio.CancelledError,
                ):
                    raise outcome
            self._task = None
            self._ws = None
        self.connected = False

    async def _post_message(self, channel, text, root="", file_ids=None):
        payload = {"channel_id": channel, "message": text, "root_id": root}
        if file_ids:
            payload["file_ids"] = file_ids
        try:
            response = await self._http.post(
                self._url + "/api/v4/posts",
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise MattermostDeliveryError(
                "MATTERMOST_POST_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        if response.status_code != 201:
            raise MattermostDeliveryError(
                "MATTERMOST_POST_REJECTED",
                side_effect_possible=False,
            )
        message_id = response.json().get("id")
        if not message_id:
            raise MattermostDeliveryError(
                "MATTERMOST_POST_UNKNOWN",
                side_effect_possible=True,
            )
        return str(message_id)

    async def send_parts(self, channel, root, parts):
        sent = []
        uploaded = False
        try:
            for part in parts:
                kind = part["type"]
                if kind in {"text", "refusal"}:
                    for chunk in self._chunk_text(
                        part.get("text") or part.get("refusal") or "",
                    ):
                        sent.append(
                            await self._post_message(channel, chunk, root),
                        )
                    continue
                value = (
                    part.get(kind + "_url")
                    if kind in {"image", "video", "file"}
                    else part.get("data")
                )
                if not value:
                    continue
                async with materialize_data_url(
                    str(value),
                    self._media_dir,
                    filename_hint=part.get("filename") or "media",
                ) as materialized:
                    if materialized is None:
                        raise MattermostDeliveryError(
                            "MEDIA_INVALID",
                            side_effect_possible=bool(sent),
                        )
                    local = (
                        file_url_to_local_path(materialized.path)
                        or materialized.path
                    )
                    file_id = await self._upload_file(
                        channel,
                        local,
                        filename=materialized.filename,
                    )
                    if file_id:
                        uploaded = True
                        sent.append(
                            await self._post_message(
                                channel,
                                "",
                                root,
                                [file_id],
                            ),
                        )
                    else:
                        sent.append(
                            await self._post_message(
                                channel,
                                f"[Attachment: {local}]",
                                root,
                            ),
                        )
        except MattermostDeliveryError as exc:
            if (sent or uploaded) and not exc.side_effect_possible:
                raise MattermostDeliveryError(
                    exc.reason_code,
                    side_effect_possible=True,
                ) from exc
            raise
        return {"message_id": ",".join(sent)}

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
        triggering_post_id: str = "",
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
                if any("create_at" in posts.get(pid, {}) for pid in order):
                    order.sort(
                        key=lambda pid: posts.get(pid, {}).get("create_at", 0),
                    )
                else:
                    order.reverse()
                order = [pid for pid in order if pid != triggering_post_id]
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
        filename: Optional[str] = None,
    ) -> Optional[str]:
        """Upload a local file; return Mattermost file_id or None.

        Uses multipart/form-data — httpx sets the Content-Type boundary
        automatically when 'files=' is passed, so we do NOT include
        Content-Type: application/json in this request.
        """
        path = Path(local_path).expanduser()
        roots = [self._media_dir.resolve()]
        if self.config.get("workspace_dir"):
            roots.append(Path(self.config["workspace_dir"]).resolve())
        if path.exists() and not any(
            path.resolve().is_relative_to(root) for root in roots
        ):
            raise MattermostDeliveryError("MEDIA_PATH_UNAUTHORIZED")
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
                    files={"files": (filename or path.name, fh)},
                    # No json= here; httpx handles Content-Type automatically
                )
            if resp.status_code in (200, 201):
                file_infos = resp.json().get("file_infos", [])
                if file_infos and file_infos[0].get("id"):
                    return str(file_infos[0]["id"])
                raise MattermostDeliveryError(
                    "MATTERMOST_UPLOAD_UNKNOWN",
                    side_effect_possible=True,
                )
            logger.warning(
                "mattermost: file upload failed %s: %s",
                resp.status_code,
                resp.text[:200],
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise MattermostDeliveryError(
                "MATTERMOST_UPLOAD_UNKNOWN",
                side_effect_possible=True,
            ) from exc
        except OSError:
            logger.exception("mattermost: upload failed for %s", local_path)
        return None

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
