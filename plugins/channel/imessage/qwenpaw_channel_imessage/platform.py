# -*- coding: utf-8 -*-
"""Owned read-only SQLite polling and bounded macOS imsg commands."""

from __future__ import annotations

import asyncio
import logging
import math
import shutil
import sqlite3
import sys
from pathlib import Path

import httpx

from .media import IMessageMedia, extract_url_and_filename

logger = logging.getLogger(__name__)
COMMAND_TIMEOUT = 30.0
RESOURCE_TIMEOUT = 1.0
_QUERY = """
SELECT m.ROWID, m.text, m.is_from_me, c.ROWID AS chat_rowid, h.id AS sender
FROM message m
JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
JOIN chat c ON c.ROWID = cmj.chat_id
LEFT JOIN handle h ON h.ROWID = m.handle_id
WHERE m.ROWID > ? ORDER BY m.ROWID ASC LIMIT 64
"""


class IMessageDeliveryError(Exception):
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


class IMessagePlatform:
    def __init__(self, config, on_event, on_state):
        self.config, self.on_event, self.on_state = config, on_event, on_state
        self.db_path = Path(
            config.get("db_path") or "~/Library/Messages/chat.db",
        ).expanduser()
        self.poll_sec = float(config.get("poll_sec", 1.0))
        if not math.isfinite(self.poll_sec) or self.poll_sec <= 0:
            raise ValueError("IMESSAGE_POLL_SEC_INVALID")
        self.bot_prefix = config.get("bot_prefix") or ""
        self.media = IMessageMedia(config, IMessageDeliveryError)
        self._conn, self._watcher, self._http, self._imsg_path = (
            None,
            None,
            None,
            None,
        )
        self._senders, self._spawns, self._commands = set(), set(), {}
        self._operations = set()
        self._pending = None
        self._last_rowid = 0
        self._stopping = False

    async def start(self):
        if self._conn is not None or self._watcher is not None:
            raise RuntimeError("IMESSAGE_RESOURCES_ALREADY_OWNED")
        if sys.platform != "darwin":
            raise RuntimeError("IMESSAGE_MACOS_REQUIRED")
        self._imsg_path = shutil.which("imsg")
        if not self._imsg_path:
            raise RuntimeError("IMESSAGE_EXECUTABLE_NOT_FOUND: imsg")
        try:
            self._conn = sqlite3.connect(
                self.db_path.absolute().as_uri() + "?mode=ro",
                uri=True,
                timeout=0.2,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA query_only=ON")
            self._last_rowid = self._conn.execute(
                "SELECT IFNULL(MAX(ROWID),0) FROM message",
            ).fetchone()[0]
            self._conn.execute(_QUERY, (self._last_rowid,)).fetchall()
        except sqlite3.Error as exc:
            # Keep any opened connection for explicit stop/retry custody.
            raise RuntimeError(
                "IMESSAGE_DATABASE_UNREADABLE: check Messages database "
                "path, schema and read permission",
            ) from exc
        self.media.start()
        self._http = httpx.AsyncClient(timeout=30, follow_redirects=True)
        self._stopping = False
        await self.on_state("connected")
        self._watcher = asyncio.create_task(
            self._watch(),
            name="imessage-sqlite-watcher",
        )

    async def _watch(self):
        while not self._stopping:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "iMessage poll/admission failed; row retained",
                )
            await asyncio.sleep(self.poll_sec)

    async def _poll_once(self):
        if self._stopping:
            return
        if self._pending is not None:
            await self.on_state("connected")
            await self.on_event(self._pending)
            self._last_rowid = self._pending["rowid"]
            self._pending = None
        try:
            rows = self._conn.execute(_QUERY, (self._last_rowid,)).fetchall()
        except sqlite3.Error as exc:
            await self.on_state("failed")
            raise RuntimeError("IMESSAGE_DATABASE_READ_FAILED") from exc
        await self.on_state("connected")
        for row in rows:
            if self._stopping:
                return
            text = row["text"]
            sender = (row["sender"] or "").strip()
            if (
                row["is_from_me"] == 1
                or not text
                or (self.bot_prefix and str(text).startswith(self.bot_prefix))
                or not sender
            ):
                self._last_rowid = row["ROWID"]
                continue
            value = {
                "sender": sender,
                "text": str(text),
                "rowid": int(row["ROWID"]),
                "chat_rowid": str(row["chat_rowid"]),
                "event_id": "imessage:row:"
                + str(row["ROWID"])
                + ":"
                + str(row["chat_rowid"]),
            }
            # Shared admission resolves accepted/duplicate or explicit denial;
            # exceptions/unknown retain the cursor and stable native event ID.
            self._pending = value
            await self.on_event(value)
            self._last_rowid = row["ROWID"]
            self._pending = None

    @staticmethod
    async def _read_pipe(pipe):
        preview = bytearray()
        while chunk := await pipe.read(65536):
            if len(preview) < 4096:
                preview.extend(chunk[: 4096 - len(preview)])
        return bytes(preview)

    async def _command_result(self, process):
        # Keep both readers attached to their process until EOF, including
        # inherited pipes held by descendants after the command leader exits.
        stdout, stderr = await asyncio.gather(
            self._read_pipe(process.stdout),
            self._read_pipe(process.stderr),
        )
        await process.wait()
        return process.returncode, stdout, stderr

    async def _settle_command(self, process, result):
        for force in (False, True):
            if process.returncode is None:
                try:
                    process.kill() if force else process.terminate()
                except ProcessLookupError:
                    pass
            done, _ = await asyncio.wait((result,), timeout=RESOURCE_TIMEOUT)
            if done:
                # Fetch exceptions as well as exit status; no orphaned task.
                result.result()
                self._commands.pop(process, None)
                return True
        return False

    async def _send_command(self, target, text, file_path=None):
        if self._stopping or not self._imsg_path:
            raise IMessageDeliveryError("IMESSAGE_NOT_STARTED")
        command = [self._imsg_path, "send", "--to", target]
        if text:
            command.extend(("--text", text))
        if file_path:
            command.extend(("--file", file_path))
        owner = asyncio.current_task()
        self._senders.add(owner)
        spawn = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Inherit worker session/pgid for generic host tree custody.
            ),
        )
        self._spawns.add(spawn)
        process, result = None, None
        try:
            try:
                process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                # Spawn may already have crossed the OS effect boundary.
                process = await spawn
                result = asyncio.create_task(self._command_result(process))
                self._commands[process] = result
                raise
            result = asyncio.create_task(self._command_result(process))
            self._commands[process] = result
            done, _ = await asyncio.wait((result,), timeout=COMMAND_TIMEOUT)
            if not done:
                raise IMessageDeliveryError(
                    "IMESSAGE_COMMAND_TIMEOUT",
                    side_effect_possible=True,
                )
            code, _, stderr = result.result()
            self._commands.pop(process, None)
            if code:
                logger.warning(
                    "imsg exited %s: %s",
                    code,
                    stderr.decode(errors="replace"),
                )
                raise IMessageDeliveryError(
                    "IMESSAGE_COMMAND_FAILED",
                    side_effect_possible=True,
                )
        except asyncio.CancelledError:
            if process is not None:
                await self._settle_command(process, result)
            raise
        except IMessageDeliveryError:
            if process is not None and process in self._commands:
                await self._settle_command(process, result)
            raise
        except OSError as exc:
            raise IMessageDeliveryError(
                "IMESSAGE_COMMAND_START_FAILED",
                side_effect_possible=process is not None,
            ) from exc
        finally:
            if spawn.done():
                self._spawns.discard(spawn)
            self._senders.discard(owner)

    async def send_parts(self, target, parts, content_source=None, prefix=""):
        if self._stopping:
            raise IMessageDeliveryError("IMESSAGE_NOT_STARTED")
        owner = asyncio.current_task()
        self._operations.add(owner)
        try:
            return await self._send_parts(
                target,
                parts,
                content_source,
                prefix,
            )
        finally:
            self._operations.discard(owner)

    async def _send_parts(self, target, parts, content_source, prefix):
        origin = getattr(content_source, "value", content_source)
        texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
        text = "\n".join(value for value in texts if value)
        if origin != "direct":
            text = (prefix + text).strip()
        sent = False
        try:
            if text:
                await self._send_command(target, text)
                sent = True
            for part in parts:
                if part.get("type") == "text":
                    continue
                try:
                    try:
                        path = await self.media.resolve(self._http, part)
                    except (OSError, ValueError) as exc:
                        raise IMessageDeliveryError(
                            "MEDIA_PREPARATION_FAILED",
                        ) from exc
                    if path:
                        await self._send_command(target, "", path)
                        sent = True
                except IMessageDeliveryError as exc:
                    if exc.side_effect_possible or origin == "media":
                        raise
                    _, _, kind = extract_url_and_filename(part)
                    value = next(
                        (
                            part.get(key)
                            for key in (
                                "url",
                                "file_url",
                                "image_url",
                                "audio_url",
                                "video_url",
                            )
                            if part.get(key)
                        ),
                        None,
                    )
                    fallback = (
                        f"[File: {value}]"
                        if value
                        else f"[File could not be sent ({kind})]"
                    )
                    await self._send_command(target, fallback)
                    sent = True
        except IMessageDeliveryError as exc:
            raise IMessageDeliveryError(
                exc.reason_code,
                side_effect_possible=sent or exc.side_effect_possible,
                retryable=exc.retryable and not sent,
            ) from exc
        return {"sent": "true" if sent else "false"}

    async def stop(self):
        self._stopping = True
        failures = []
        watcher = self._watcher
        if watcher is not None:
            if not watcher.done():
                watcher.cancel()
            done, _ = await asyncio.wait((watcher,), timeout=RESOURCE_TIMEOUT)
            if done:
                if not watcher.cancelled():
                    watcher.exception()
                self._watcher = None
            else:
                failures.append("watcher")
        senders = tuple(self._senders | self._operations)
        for sender in senders:
            sender.cancel()
        if senders:
            _, pending = await asyncio.wait(
                senders,
                timeout=3 * RESOURCE_TIMEOUT,
            )
            if pending:
                failures.append("senders")
        for process, result in tuple(self._commands.items()):
            if not await self._settle_command(process, result):
                failures.append("command_or_pipe")
        if self._spawns:
            failures.append("command_spawn")
        if self._watcher is None and self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                failures.append("sqlite")
            else:
                self._conn = None
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                failures.append("http")
            else:
                self._http = None
        if failures:
            raise RuntimeError(
                "IMESSAGE_STOP_UNCONFIRMED:" + ",".join(failures),
            )
        await self.on_state("disconnected")
