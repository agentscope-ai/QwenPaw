# -*- coding: utf-8 -*-
"""Bounded, best-effort worker stderr forwarding to host logging."""

from __future__ import annotations

import asyncio
import atexit
from collections import deque
from collections.abc import Iterable
import logging
import os
import queue
import re
import sys
import threading
from time import monotonic
from typing import Callable

_LINE_BYTES = 4096
_LINES_PER_SECOND = 32
_BYTES_PER_SECOND = 64 * 1024
_QUEUE_SIZE = 256
_PRIORITY_LINES = 4
_PRIORITY_BYTES = 8 * 1024
_TRUNCATED = " [truncated]"
_ANSI = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))",
)
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029]")
_HEADERS = re.compile(
    r"(\b(?:(?:proxy-)?authorization|(?:set-)?cookie)"
    r"\b[\"']?\s*[:=]\s*).*",
    re.I,
)
_BEARER = re.compile(r"\b(Bearer|Basic)\s+[^\s,;\"'<>]+", re.I)
_TELEGRAM = re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+", re.I)
_KEY = re.compile(r"[\w.-]+")
_CREDENTIAL = re.compile(
    rf"token|secret|password|passwd|api[_-]?key|^authorization$|^cookie$"
    rf"|^(?:ticket|typing[_-]?ticket|qr[_-]?code|aes[_-]?key|file[_-]?key"
    rf"|(?:x-)?encrypt(?:ed)?[_-]?(?:query[_-]?)?param)$",
    re.I,
)
_VALUE = re.compile(
    r"[\"']?\s*[:=]\s*(\"[^\"]*(?:\"|$)|'[^']*(?:'|$)|[^\s&,;}]+)",
)
_URL_AUTH = re.compile(r"(https?://)[^/\s@]+@", re.I)
_CHANNEL_RECORD = re.compile(rb"^channel_log (\d{1,3}) (\S{1,256}) ")
_LARK_RECORD = re.compile(rb"^\[Lark\] \[[^\]]{1,64}\] \[([A-Z]{1,12})\] ")
_LEVELS = logging.getLevelNamesMapping()
_WORKER_LOGGER = f"qwenpaw.plugins.worker"
_FATAL_STARTUP_EVENT = re.compile(
    rb'"event": "(?:worker_error|component_failed|component_stop_failed)"',
)


class _WorkerLogWriter:
    """Write queued channel log lines outside producer threads."""

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._ready = threading.Condition()
        self._pending: deque[bytes] = deque()
        self._dropped = 0
        self._closed = False
        self._thread = threading.Thread(
            target=self._consume,
            name=f"qwenpaw-channel-log-writer",
            daemon=True,
        )
        self._thread.start()

    def submit(self, line: str) -> None:
        """Queue one line, retaining a byte to signal host truncation."""
        limit = _LINE_BYTES + 1
        data = line[:limit].encode(f"utf-8", f"backslashreplace")[:limit]
        priority = data.startswith(b"startup_diagnostic_error ")
        if record := _CHANNEL_RECORD.match(data):
            priority = int(record[1]) >= logging.WARNING
        elif record := _LARK_RECORD.match(data):
            level = _LEVELS.get(record[1].decode(f"ascii"), logging.WARNING)
            priority = level >= logging.WARNING
        capacity = _QUEUE_SIZE - (0 if priority else _PRIORITY_LINES)
        with self._ready:
            if self._closed:
                return
            if len(self._pending) >= capacity:
                self._dropped += 1
                return
            self._pending.append(data + b"\n")
            self._ready.notify()

    def _write(self, line: bytes) -> None:
        remaining = memoryview(line)
        while remaining:
            written = os.write(self._fd, remaining)
            remaining = remaining[written:]

    def _consume(self) -> None:
        next_summary = 0.0
        try:
            while True:
                with self._ready:
                    self._ready.wait_for(
                        lambda: self._pending or self._dropped or self._closed,
                    )
                    line = self._pending.popleft() if self._pending else None
                    now = monotonic()
                    dropped = 0
                    if self._dropped and (line is None or now >= next_summary):
                        dropped, self._dropped = self._dropped, 0
                        next_summary = now + 1.0
                if dropped:
                    summary = (
                        f"channel_log {logging.WARNING} {_WORKER_LOGGER} "
                        f"worker log queue dropped {dropped} records\n"
                    )
                    self._write(summary.encode(f"utf-8"))
                if line is None and not dropped:
                    return
                if line is not None:
                    self._write(line)
        except OSError:
            with self._ready:
                self._closed = True
                self._pending.clear()
                self._dropped = 0

    def close(self) -> None:
        with self._ready:
            self._closed = True
            self._ready.notify()
        self._thread.join(timeout=0.05)


class _WorkerLogStream:
    """Queue complete Python text lines; leave native/binary output alone."""

    def __init__(self, stream, writer: _WorkerLogWriter) -> None:
        self._stream = stream
        self._writer = writer
        self._partial = f""
        self._lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def write(self, text: str) -> int:
        with self._lock:
            start = 0
            while start < len(text):
                end = text.find(f"\n", start)
                stop = len(text) if end < 0 else end
                room = _LINE_BYTES + 1 - len(self._partial)
                self._partial += text[start : min(stop, start + room)]
                if end < 0:
                    break
                self._writer.submit(self._partial)
                self._partial = f""
                start = end + 1
        return len(text)

    def writelines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        with self._lock:
            if self._partial:
                self._writer.submit(self._partial)
                self._partial = f""


class _ChannelFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Keep a traceback and its severity together on the stderr pipe.
        return f" ".join(super().format(record).splitlines())


def configure_channel_logging(level: int) -> _WorkerLogWriter:
    """Route Python channel records over the isolated worker stderr pipe."""
    # Bootstrap redirects stdout to the stderr pipe with UTF-8 encoding.
    writer = _WorkerLogWriter(sys.stdout.fileno())
    sys.stdout = _WorkerLogStream(sys.stdout, writer)
    sys.stderr = _WorkerLogStream(sys.stderr, writer)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(
        _ChannelFormatter(f"channel_log %(levelno)d %(name)s %(message)s"),
    )
    # Feishu SDK writes its formatted records directly to redirected stdout.
    # Let the host decode those lines once, including for installed plugins.
    handler.addFilter(
        lambda record: record.name != f"Lark"
        or not any(
            isinstance(sink, logging.StreamHandler)
            and sink.stream in (sys.stdout, sys.stderr)
            for sink in logging.getLogger(f"Lark").handlers
        ),
    )
    logging.basicConfig(handlers=[handler], level=level, force=True)
    # Transport wire logs can contain credentials and complete messages.
    for name in (
        f"aiohttp.access",
        f"httpx",
        f"httpcore",
        f"websockets",
        f"urllib3",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)
    for name in (
        f"discord.gateway",
        f"paho.mqtt",
        f"telegram",
        f"slack_bolt",
        f"slack_sdk",
    ):
        logging.getLogger(name).setLevel(logging.INFO)
    for name in (f"twilio.http_client", f"twilio.async_http_client"):
        logging.getLogger(name).addFilter(
            lambda record: record.levelno >= logging.WARNING
            or record.getMessage().startswith(f"Response Status Code: "),
        )
    return writer


def _credentials(text: str) -> str:
    # Consume each whole key once: restarting a greedy key pattern at every
    # word boundary makes long dotted/hyphenated tokens quadratic.
    parts = []
    position = copied = 0
    while key := _KEY.search(text, position):
        position = key.end()
        if not _CREDENTIAL.search(key.group()):
            continue
        value = _VALUE.match(text, position)
        if value is not None:
            parts.extend((text[copied : value.start(1)], "[REDACTED]"))
            position = copied = value.end()
    parts.append(text[copied:])
    return "".join(parts)


def _clean(text: str) -> str:
    # This boundary handles recognizable credentials, not arbitrary SDK secrets.
    text = _CONTROLS.sub("", _ANSI.sub("", text)).replace("\n", " ")
    text = _HEADERS.sub(r"\1[REDACTED]", text)
    text = _TELEGRAM.sub(r"\1[REDACTED]", text)
    text = _BEARER.sub(r"\1 [REDACTED]", text)
    text = _credentials(text)
    return _URL_AUTH.sub(r"\1[REDACTED]@", text)


def _prefix_value(value: object) -> str:
    text = _clean(str(value)[:128])
    return text.encode("utf-8")[:128].decode("utf-8", "ignore")


class _LogSink:
    """One host-owned consumer; never wait on handlers from the event loop."""

    def __init__(self) -> None:
        self.queue: queue.Queue[
            tuple[str, threading.Event, str, int]
        ] = queue.Queue(maxsize=_QUEUE_SIZE)
        self.closed = threading.Event()
        self.thread = threading.Thread(
            target=self._consume,
            name="qwenpaw-worker-logs",
            daemon=True,
        )
        self.thread.start()
        atexit.register(self.close)

    def submit(
        self,
        message: str,
        logger_name: str,
        level: int,
    ) -> threading.Event | None:
        if self.closed.is_set():
            return None
        delivered = threading.Event()
        try:
            self.queue.put_nowait((message, delivered, logger_name, level))
        except queue.Full:
            return None
        return delivered

    def _consume(self) -> None:
        while not self.closed.is_set() or not self.queue.empty():
            try:
                message, delivered, name, level = self.queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                logging.getLogger(name).log(level, "%s", message)
            except Exception:
                # A broken handler must not kill forwarding or pipe draining.
                pass
            finally:
                delivered.set()
                self.queue.task_done()

    def close(self) -> None:
        self.closed.set()
        # Bound this facility's exit work. Existing logging.shutdown can still
        # wait on a custom handler's own lock; do not alter global logging.
        self.thread.join(timeout=0.2)


_sink: _LogSink | None = None
_sink_lock = threading.Lock()


def _submit(
    message: str,
    *,
    logger_name: str = _WORKER_LOGGER,
    level: int = logging.WARNING,
) -> threading.Event | None:
    global _sink
    if _sink is None:
        with _sink_lock:
            if _sink is None:
                _sink = _LogSink()
    return _sink.submit(message, logger_name, level)


class WorkerLogs:
    """One bounded line/rate accumulator with an immutable launch identity."""

    def __init__(
        self,
        spec: object,
        mode: str,
        *,
        channel_clean: Callable[[str], str] | None = None,
    ) -> None:
        fields = [
            f"{name}={_prefix_value(getattr(spec, name))}"
            for name in ("plugin_id", "instance_id", "generation")
        ]
        fields.append(f"mode={_prefix_value(mode)}")
        workspace = getattr(spec, "workspace_id", None)
        if workspace is not None:
            fields.append(f"workspace_id={_prefix_value(workspace)}")
        self.prefix = "[worker stderr " + " ".join(fields) + "] "
        self.prefix_bytes = len(self.prefix.encode("utf-8"))
        self.buffer = bytearray()
        self.line_bytes = 0
        self.window = monotonic()
        self.attempts = self.bytes = 0
        self.omitted_lines = self.omitted_bytes = 0
        self.last_delivery: threading.Event | None = None
        self.startup_records = 0
        self.channel_clean = channel_clean
        self.logger = logging.getLogger(_WORKER_LOGGER)

    def feed(self, chunk: bytes) -> None:
        for index, part in enumerate(chunk.split(b"\n")):
            if index:
                self._line()
            self.line_bytes += len(part)
            remaining = _LINE_BYTES - len(self.buffer)
            if remaining > 0:
                self.buffer.extend(part[:remaining])

    def _refresh(self) -> None:
        now = monotonic()
        if now - self.window >= 1.0:
            self.window, self.attempts, self.bytes = now, 0, 0

    def _admit(self, *, summary: bool = False, priority: bool = False) -> bool:
        # Reserve one record and 256 bytes for a merged omission summary.
        line_limit = _LINES_PER_SECOND - (0 if summary else 1)
        byte_limit = _BYTES_PER_SECOND - (0 if summary else 256)
        if self.channel_clean is not None and not (summary or priority):
            line_limit -= _PRIORITY_LINES
            byte_limit -= _PRIORITY_BYTES
        if (
            self.attempts >= line_limit
            or self.bytes + self.prefix_bytes > byte_limit
        ):
            return False
        # Charge before decoding/cleaning, even if the queue is full or the
        # resulting record cannot fit. Only successfully queued bytes count.
        self.attempts += 1
        return True

    def _offer(
        self,
        text: str,
        *,
        summary: bool = False,
        level: int = logging.WARNING,
        priority: bool = False,
    ) -> bool:
        message = self.prefix + text
        size = len(message.encode("utf-8"))
        byte_limit = _BYTES_PER_SECOND - (0 if summary else 256)
        if self.channel_clean is not None and not (summary or priority):
            byte_limit -= _PRIORITY_BYTES
        if self.bytes + size > byte_limit:
            return False
        delivered = _submit(message, level=level)
        if delivered is None:
            return False
        self.last_delivery = delivered
        self.bytes += size
        return True

    def _summary(self) -> None:
        if (
            self.omitted_lines
            and self._admit(summary=True)
            and self._offer(
                f"omitted {self.omitted_lines} lines "
                f"({self.omitted_bytes} bytes)",
                summary=True,
            )
        ):
            self.omitted_lines = self.omitted_bytes = 0

    def _line(self) -> None:
        try:
            self._publish_line()
        finally:
            self.buffer.clear()
            self.line_bytes = 0

    def _publish_line(self) -> None:
        self._refresh()
        clean = self.channel_clean or _clean
        # Root causes and one slow-start sample must survive an SDK log flood.
        # This separate lifetime budget cannot turn into unbounded forwarding.
        if (
            self.buffer.startswith(b"startup_diagnostic_error ")
            and self.startup_records < 32
        ):
            self.startup_records += 1
            text = clean(self.buffer.decode(f"utf-8", f"replace"))
            message = (self.prefix + text).encode("utf-8")[:_LINE_BYTES]
            fatal = (
                self.channel_clean is not None
                and _FATAL_STARTUP_EVENT.search(self.buffer)
            )
            level = logging.ERROR if fatal else logging.WARNING
            self.last_delivery = _submit(
                message.decode(f"utf-8", f"ignore"),
                level=level,
            )
            return
        level, offset, source = logging.WARNING, 0, b""
        if self.channel_clean is not None:
            if self.buffer.startswith(b"startup_diagnostic "):
                level = logging.DEBUG
            elif record := _CHANNEL_RECORD.match(self.buffer):
                level, offset, source = int(record[1]), record.end(), record[2]
            elif record := _LARK_RECORD.match(self.buffer):
                severity = record[1].decode(f"ascii")
                level = _LEVELS.get(severity, logging.WARNING)
                offset, source = record.end(), b"Lark"
            if not self.logger.isEnabledFor(level):
                return
        # Retry a pending summary once on window rollover (or at EOF), rather
        # than spending every remaining attempt on a full sink.
        if self.attempts == 0:
            self._summary()
        accepted = False
        priority = bool(source) and level >= logging.WARNING
        if self._admit(priority=priority):
            # Redact the bounded raw prefix before final output truncation.
            text = self.buffer[offset:].decode(f"utf-8", f"replace")
            if source:
                name = source.decode(f"utf-8", f"replace")
                text = f"[{name}] {text}"
            text = clean(text)
            data = text.encode("utf-8")
            limit = _LINE_BYTES - self.prefix_bytes
            if self.line_bytes > len(self.buffer) or len(data) > limit:
                text = data[: limit - len(_TRUNCATED)].decode(
                    "utf-8",
                    "ignore",
                )
                text += _TRUNCATED
            accepted = self._offer(text, level=level, priority=priority)
        if not accepted:
            self.omitted_lines += 1
            self.omitted_bytes += self.line_bytes

    async def finish(self) -> None:
        if self.line_bytes:
            self._line()
        self._refresh()
        self._summary()
        # Normal EOF hands accepted lines to fast handlers. Slow host logging
        # gets no ownership over worker shutdown and remains shared on restart.
        deadline = asyncio.get_running_loop().time() + 0.05
        while (
            self.last_delivery is not None and not self.last_delivery.is_set()
        ):
            if asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(0.001)
