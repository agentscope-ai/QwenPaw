# -*- coding: utf-8 -*-
"""Bounded startup evidence; never changes execution or exposes launch data."""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
import re
import sys
import threading
import time
import types

_URL = re.compile(r"(?:https?|wss?)://[^\s\"'<>]+", re.I)
_SECRET = re.compile(
    r"secret|token|password|passwd|api[_-]?key|credential|authorization|cookie|encrypt|private_key",
    re.I,
)
ERROR_PREFIX = "startup_diagnostic_error "


class StartupDiagnostics:
    """One launch's safe context, first errors and optional slow-start sample."""

    def __init__(self, packet, *, write=None, clean=None):
        if clean is None:
            from .worker_logs import _clean

            clean = _clean
        self._clean = clean
        self._write = write or (
            lambda text: print(text, file=sys.stderr, flush=True)
        )
        self._secrets = []

        def collect(value, sensitive=False, depth=0):
            if depth > 8:
                return
            if isinstance(value, dict):
                for key, item in value.items():
                    collect(
                        item,
                        sensitive or bool(_SECRET.search(str(key))),
                        depth + 1,
                    )
            elif isinstance(value, (tuple, list)):
                for item in value:
                    collect(item, sensitive, depth + 1)
            elif sensitive and isinstance(value, str) and value:
                self._secrets.append(value)

        collect(packet.get("config", {}))
        collect(packet.get("private_env", {}), True)
        capability = os.environ.get("QWENPAW_DEPENDENCY_MAINTENANCE")
        if capability:
            self._secrets.append(capability)
        self.identity = {
            key: self._safe(packet.get(key))
            for key in (
                "plugin_id",
                "channel_key",
                "workspace_id",
                "instance_id",
                "generation",
                "mode",
            )
        }
        self.started = time.monotonic()
        self.identity["pid"] = os.getpid()
        self.phase = "bootstrap"
        self._timer = None
        self._task = None
        self._records = self._errors = 0

    @contextmanager
    def background_errors(self, loop):
        """Observe SDK logging and unhandled tasks/threads; retain their handlers."""
        previous = loop.get_exception_handler()
        thread_hook = threading.excepthook
        factory = logging.getLogRecordFactory()
        seen = set()

        def record(error, event, **fields):
            if error is not None and id(error) not in seen and len(seen) < 2:
                seen.add(id(error))
                self.failure(error, event=event, **fields)

        def logged(*args, **kwargs):
            entry = factory(*args, **kwargs)
            if entry.exc_info:
                record(entry.exc_info[1], "sdk_exception", logger=entry.name)
            return entry

        def loop_error(loop, context):
            record(context.get("exception"), "task_exception")
            if previous is None:
                loop.default_exception_handler(context)
            else:
                previous(loop, context)

        def thread_error(args):
            record(args.exc_value, "thread_exception", thread=args.thread.name)
            thread_hook(args)

        logging.setLogRecordFactory(logged)
        loop.set_exception_handler(loop_error)
        threading.excepthook = thread_error
        try:
            yield
        finally:
            if logging.getLogRecordFactory() is logged:
                logging.setLogRecordFactory(factory)
            # Respect a handler deliberately installed by the component itself.
            if loop.get_exception_handler() is loop_error:
                loop.set_exception_handler(previous)
            if threading.excepthook is thread_error:
                threading.excepthook = thread_hook

    def _safe(self, value, *, limit=256):
        if isinstance(value, str):
            for secret in sorted(set(self._secrets), key=len, reverse=True):
                value = value.replace(secret, "[REDACTED]")
            value = _URL.sub(
                lambda match: re.sub(
                    r"(?<=//)[^/@]+@",
                    "[REDACTED]@",
                    match[0],
                )
                .split("?", 1)[0]
                .split("#", 1)[0],
                value,
            )
            return self._clean(value)[:limit]
        if isinstance(value, dict):
            return {key: self._safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._safe(item) for item in value[:16]]
        return value

    def emit(self, event, *, critical=False, **fields):
        try:
            if critical:
                if self._errors >= 32:
                    return
                self._errors += 1
            else:
                if self._records >= 64:
                    return
                self._records += 1
            row = {
                **self.identity,
                "event": event,
                "phase": self.phase,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                **self._safe(fields),
            }
            prefix = ERROR_PREFIX if critical else "startup_diagnostic "
            self._write(prefix + json.dumps(row, ensure_ascii=True))
        except Exception:
            # Diagnostics cannot replace the original error or stop cleanup.
            pass

    def mark(self, phase, **fields):
        self.phase = phase
        self.emit("phase", **fields)

    def _frame(self, frame, line=None):
        code = frame.f_code
        return {
            "file": self._safe(
                code.co_filename.replace("\\", "/"),
                limit=None,
            )[-96:],
            "line": frame.f_lineno if line is None else line,
            "function": self._safe(code.co_name)[:48],
        }

    def failure(self, error, *, event="worker_error", **fields):
        try:
            self._failure(error, event=event, **fields)
        except Exception:
            pass

    def _failure(self, error, *, event, **fields):
        errors, seen = [], set()
        while error is not None and id(error) not in seen and len(errors) < 32:
            seen.add(id(error))
            errors.append(error)
            error = error.__cause__ or error.__context__
        # Root first: a long outer chain must not hide the actionable cause.
        for index, error in enumerate(reversed(errors[-4:])):
            frames, trace = [], error.__traceback__
            while trace is not None:
                frames.append(self._frame(trace.tb_frame, trace.tb_lineno))
                trace = trace.tb_next
            try:
                message = str(error)
            except Exception:
                message = "<unprintable exception>"
            self.emit(
                event,
                critical=True,
                **fields,
                cause_index=index,
                chain_length=len(errors),
                exception_type=type(error).__name__,
                message=message,
                frames=frames[-6:],
            )

    def watch(self, task, timeout):
        self.cancel_watch()
        try:
            self._task = task
            self._timer = threading.Timer(
                max(0.05, timeout * 0.8),
                self._slow,
                args=(task,),
            )
            self._timer.daemon = True
            self._timer.start()
        except Exception:
            self.cancel_watch()

    def cancel_watch(self):
        if self._timer is not None:
            self._timer.cancel()
        self._timer = self._task = None

    def _slow(self, task):
        try:
            if task is None or task is not self._task or task.done():
                return
            awaited, frames = task.get_coro(), []
            while isinstance(
                awaited,
                (types.CoroutineType, types.GeneratorType),
            ):
                frame = getattr(awaited, "cr_frame", None) or getattr(
                    awaited,
                    "gi_frame",
                    None,
                )
                if frame is not None:
                    frames.append(self._frame(frame))
                awaited = getattr(awaited, "cr_await", None) or getattr(
                    awaited,
                    "gi_yieldfrom",
                    None,
                )
            self.emit("startup_slow", critical=True, await_frames=frames[-8:])
            current = sys._current_frames()
            for thread in threading.enumerate()[:8]:
                if thread.ident == threading.get_ident():
                    continue
                frame, frames = current.get(thread.ident), []
                while frame is not None:
                    frames.append(self._frame(frame))
                    frame = frame.f_back
                self.emit(
                    "startup_slow",
                    critical=True,
                    thread=thread.name,
                    frames=frames[:6],
                )
        except Exception:
            pass
