# -*- coding: utf-8 -*-
"""Signal subprocess client: signal-cli jsonRpc over stdin/stdout.

Spawns `signal-cli -a <account> --output=json jsonRpc` as a child process and
speaks newline-delimited JSON-RPC 2.0 over its pipes. Replaces the previous
HTTP+SSE `SignalDaemon` (which required signal-cli running as an external
HTTP service).

Design notes:
- One subprocess per SignalChannel instance; lifecycle owned here.
- Requests keyed by auto-incrementing id, correlated via asyncio.Futures.
- Inbound notifications (method="receive") dispatched to on_notify callback.
- On process exit, supervisor respawns with backoff 5s → 60s.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

NotifyCallback = Callable[[Dict[str, Any]], Awaitable[None]]

_RPC_TIMEOUT = 15.0
_BACKOFF_START = 5.0
_BACKOFF_MAX = 60.0
_TERM_GRACE_SEC = 3.0


class SignalSubprocessClient:
    """signal-cli subprocess client speaking JSON-RPC over stdin/stdout."""

    def __init__(
        self,
        account: str,
        signal_cli_path: str = "signal-cli",
        extra_args: Optional[List[str]] = None,
    ):
        self._account = account
        self._signal_cli_path = signal_cli_path
        self._extra_args = list(extra_args or [])
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._supervisor_task: Optional[asyncio.Task] = None
        self._pending: Dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._on_notify: Optional[NotifyCallback] = None
        self._connected = asyncio.Event()
        self._stopping = False
        self._write_lock = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def account(self) -> str:
        return self._account

    async def connect(self, on_notify: NotifyCallback) -> bool:
        """Start supervisor; returns True if initial spawn succeeded."""
        if self._supervisor_task and not self._supervisor_task.done():
            return self._connected.is_set()
        self._on_notify = on_notify
        self._stopping = False
        if not self._binary_available():
            logger.error(
                "signal-cli not found (looked for %r). Signal channel disabled.\n"
                "  Install — pick the distribution for your platform:\n"
                "    Linux x86_64: download signal-cli-X.Y.Z-Linux-native.tar.gz\n"
                "                  (~97 MB, self-contained, no Java runtime needed)\n"
                "                  https://github.com/AsamK/signal-cli/releases\n"
                "    Linux ARM64 / macOS / Windows: download signal-cli-X.Y.Z.tar.gz\n"
                "                  (~98 MB JAR bundle, requires Java 21+)\n"
                "                  + brew install openjdk@21 (mac) /\n"
                "                    apt install openjdk-21-jre (Debian/Ubuntu) /\n"
                "                    MSI installer (Windows)\n"
                "  Then either put signal-cli on your $PATH or set\n"
                "  channels.signal.signal_cli_path to an absolute path in config.",
                self._signal_cli_path,
            )
            return False
        self._supervisor_task = asyncio.create_task(
            self._supervise(), name="signal_supervisor",
        )
        # Wait for first successful spawn (or initial failure)
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=10.0)
            return True
        except asyncio.TimeoutError:
            logger.error("signal: subprocess failed to become ready within 10s")
            return False

    async def disconnect(self) -> None:
        """Stop supervisor and terminate subprocess."""
        self._stopping = True
        if self._supervisor_task:
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except (asyncio.CancelledError, Exception):
                pass
            self._supervisor_task = None
        await self._terminate_proc()
        self._connected.clear()
        # Fail any remaining pending futures
        self._fail_pending(ConnectionResetError("signal subprocess disconnected"))
        logger.info("signal: subprocess client stopped")

    async def call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = _RPC_TIMEOUT,
    ) -> Any:
        """Issue a JSON-RPC request and await the response."""
        if not self._connected.is_set() or not self._proc or self._proc.returncode is not None:
            raise ConnectionError("signal subprocess not connected")
        req_id = self._next_id
        self._next_id += 1
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params:
            payload["params"] = params
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            async with self._write_lock:
                assert self._proc.stdin is not None
                self._proc.stdin.write(line.encode("utf-8"))
                await self._proc.stdin.drain()
        except Exception as e:
            self._pending.pop(req_id, None)
            raise ConnectionError(f"signal stdin write failed: {e}") from e
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise
        finally:
            self._pending.pop(req_id, None)

    # ── Convenience RPCs ──────────────────────────────────────────────

    async def send_message(
        self,
        target: str,
        text: str,
        is_group: bool = False,
        quote_timestamp: int = 0,
        quote_author: str = "",
        attachments: Optional[List[str]] = None,
        text_style: Optional[List[str]] = None,
        mentions: Optional[List[str]] = None,
    ) -> Optional[int]:
        """Send a Signal message. Returns sent timestamp on success."""
        params: Dict[str, Any] = {"account": self._account}
        if text:
            params["message"] = text
        if text_style:
            params["text-style"] = text_style
        if mentions:
            params["mention"] = mentions
        if is_group:
            params["groupId"] = target
        else:
            params["recipients"] = [target]
        if quote_timestamp and quote_author:
            params["quoteTimestamp"] = quote_timestamp
            params["quoteAuthor"] = quote_author
        if attachments:
            params["attachments"] = attachments
        try:
            result = await self.call("send", params)
        except Exception as e:
            logger.error("signal: send failed to %s: %s", target, e)
            return None
        if isinstance(result, dict) and "timestamp" in result:
            return int(result["timestamp"])
        logger.error("signal: unexpected send result: %r", result)
        return None

    async def send_reaction(
        self,
        target: str,
        emoji: str,
        target_author: str,
        target_timestamp: int,
        is_group: bool = False,
        remove: bool = False,
    ) -> bool:
        params: Dict[str, Any] = {
            "account": self._account,
            "emoji": emoji,
            "targetAuthor": target_author,
            "targetTimestamp": target_timestamp,
        }
        if remove:
            params["remove"] = True
        if is_group:
            params["groupId"] = target
        else:
            params["recipients"] = [target]
        try:
            await self.call("sendReaction", params)
            return True
        except Exception as e:
            logger.error("signal: sendReaction failed: %s", e)
            return False

    async def send_typing(
        self, target: str, start: bool = True, is_group: bool = False,
    ) -> None:
        method = "sendTyping" if start else "stopTyping"
        params: Dict[str, Any] = {"account": self._account}
        if is_group:
            params["groupId"] = target
        else:
            params["recipients"] = [target]
        try:
            await self.call(method, params)
        except Exception:
            # Typing is best-effort
            pass

    async def download_attachment(
        self, attachment_id: str, dest_dir: Path,
    ) -> Optional[Path]:
        """Download an attachment. signal-cli >=0.13 autosaves to
        ~/.local/share/signal-cli/attachments/<id>; we try that first, then
        fall back to the getAttachment RPC (which returns base64 data)."""
        # Fast path: file already saved by signal-cli
        default_dir = Path.home() / ".local" / "share" / "signal-cli" / "attachments"
        candidate = default_dir / attachment_id
        if candidate.is_file():
            return candidate
        # RPC fallback
        try:
            result = await self.call(
                "getAttachment", {"account": self._account, "id": attachment_id},
            )
        except Exception as e:
            logger.error("signal: getAttachment failed: %s", e)
            return None
        if isinstance(result, str):
            p = Path(result)
            return p if p.is_file() else None
        if isinstance(result, dict) and result.get("data"):
            dest_dir.mkdir(parents=True, exist_ok=True)
            ctype = result.get("contentType", "application/octet-stream")
            ext = ctype.split("/")[-1] or "bin"
            dest = dest_dir / f"signal_att_{attachment_id[:8]}.{ext}"
            try:
                dest.write_bytes(base64.b64decode(result["data"]))
            except Exception as e:
                logger.error("signal: attachment decode failed: %s", e)
                return None
            return dest
        return None

    async def whoami(self) -> Optional[Dict[str, Any]]:
        try:
            return await self.call("version")
        except Exception:
            return None

    # ── Subprocess supervision ────────────────────────────────────────

    def _binary_available(self) -> bool:
        # Allow absolute paths; otherwise look on PATH
        if os.path.sep in self._signal_cli_path or self._signal_cli_path.startswith("./"):
            return Path(self._signal_cli_path).is_file()
        return shutil.which(self._signal_cli_path) is not None

    def _build_cmd(self) -> List[str]:
        cmd = [self._signal_cli_path]
        if self._account:
            cmd += ["-a", self._account]
        cmd += ["--output=json", "jsonRpc"]
        cmd += self._extra_args
        return cmd

    async def _supervise(self) -> None:
        backoff = _BACKOFF_START
        while not self._stopping:
            spawned = await self._spawn_once()
            if not spawned:
                if self._stopping:
                    return
                logger.warning(
                    "signal: subprocess spawn failed; retrying in %.0fs", backoff,
                )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    return
                backoff = min(backoff * 2, _BACKOFF_MAX)
                continue
            backoff = _BACKOFF_START
            # Wait for the process to exit
            assert self._proc is not None
            try:
                rc = await self._proc.wait()
            except asyncio.CancelledError:
                await self._terminate_proc()
                return
            logger.warning("signal: subprocess exited with code %s", rc)
            self._connected.clear()
            self._fail_pending(ConnectionResetError("signal subprocess exited"))
            if self._stopping:
                return
            logger.info("signal: respawning in %.0fs", backoff)
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                return
            backoff = min(backoff * 2, _BACKOFF_MAX)

    async def _spawn_once(self) -> bool:
        cmd = self._build_cmd()
        logger.info("signal: spawning %s", " ".join(cmd))
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("signal: binary not found: %s", self._signal_cli_path)
            return False
        except Exception as e:
            logger.exception("signal: failed to spawn: %s", e)
            return False
        # Start reader / stderr tasks
        self._reader_task = asyncio.create_task(
            self._read_stdout(), name="signal_reader",
        )
        self._stderr_task = asyncio.create_task(
            self._read_stderr(), name="signal_stderr",
        )
        self._connected.set()
        return True

    async def _terminate_proc(self) -> None:
        proc = self._proc
        if not proc:
            return
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=_TERM_GRACE_SEC)
            except asyncio.TimeoutError:
                logger.warning("signal: SIGTERM grace expired; sending SIGKILL")
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await proc.wait()
                except Exception:
                    pass
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._reader_task = None
        self._stderr_task = None
        self._proc = None

    async def _read_stdout(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    return  # EOF
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    logger.debug("signal: non-JSON stdout line ignored: %s", text[:200])
                    continue
                await self._dispatch(msg)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("signal: reader task crashed")

    async def _read_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.warning("signal-cli: %s", text)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("signal: stderr task crashed")

    async def _dispatch(self, msg: Dict[str, Any]) -> None:
        # Response to a pending call
        if "id" in msg and (msg.get("jsonrpc") == "2.0" or "result" in msg or "error" in msg):
            req_id = msg["id"]
            try:
                req_id_int = int(req_id)
            except (TypeError, ValueError):
                req_id_int = None
            fut = self._pending.pop(req_id_int, None) if req_id_int is not None else None
            if fut and not fut.done():
                err = msg.get("error")
                if err:
                    fut.set_exception(
                        RuntimeError(f"signal RPC error: {err}"),
                    )
                else:
                    fut.set_result(msg.get("result"))
            return
        # Inbound notification
        method = msg.get("method")
        if method == "receive":
            params = msg.get("params") or {}
            if self._on_notify:
                try:
                    await self._on_notify(params)
                except Exception:
                    logger.exception("signal: on_notify handler failed")
            return
        # Anything else — just log
        logger.debug("signal: ignored stdout frame: %s", json.dumps(msg)[:200])

    def _fail_pending(self, exc: BaseException) -> None:
        pending = self._pending
        self._pending = {}
        for fut in pending.values():
            if not fut.done():
                fut.set_exception(exc)
