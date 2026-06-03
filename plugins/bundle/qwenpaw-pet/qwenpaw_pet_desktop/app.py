# -*- coding: utf-8 -*-
"""Desktop app entry point."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from copy import deepcopy
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Any, Callable

import uvicorn
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import runtime
from .pet_package import resolve_pet_dir
from .server import build_app
from .window import PetWindow

logger = logging.getLogger(__name__)

# Events arrive from uvicorn on a background thread; updating QWidget from
# there via Qt signals is unreliable on some platforms. Drain this queue
# on the GUI thread with a QTimer instead.
_PET_EVENT_QUEUE: SimpleQueue[dict[str, Any]] = SimpleQueue()
_PET_SWITCH_QUEUE: SimpleQueue[Path] = SimpleQueue()


def enqueue_pet_event(payload: dict[str, Any]) -> None:
    """Thread-safe handoff from HTTP worker to the pet window (main thread)."""
    try:
        _PET_EVENT_QUEUE.put_nowait(deepcopy(payload))
    except Exception:
        logger.exception("Failed to enqueue pet event")


def enqueue_switch_pet(pet_dir: Path) -> None:
    """Thread-safe: reload sprites on the GUI thread."""
    try:
        _PET_SWITCH_QUEUE.put_nowait(pet_dir)
    except Exception:
        logger.exception("Failed to enqueue pet switch")


def run_http_server(
    on_event: Callable[[dict[str, Any]], None],
    on_switch_pet: Callable[[Path], None],
    host: str,
    port: int,
) -> None:
    app = build_app(on_event, on_switch_pet)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("QWENPAW_PET_LOG_LEVEL", "warning"),
    )
    server = uvicorn.Server(config)
    server.run()


def run_desktop(pet_dir: Path, host: str, port: int, scale: float) -> int:
    runtime.ensure_runtime()
    runtime.ensure_token()
    runtime.write_pid(os.getpid())
    runtime.write_json(runtime.bubble_path(), {"text": "", "counter": 0})
    # Local QwenPaw plugin always calls ``127.0.0.1`` even when the
    # server binds ``0.0.0.0`` — record a loopback URL for ``emitter``.
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::", "[::]") else host
    runtime.write_bridge_url(f"http://{display_host}:{port}")

    qt_app = QApplication(sys.argv)
    window = PetWindow(pet_dir, scale=scale)

    # SIGTERM is what the QwenPaw plugin sends on shutdown (see
    # ``emitter.stop_desktop``). Python's default handler would let the
    # OS kill us without giving Qt a chance to close the window — route
    # the signal through ``QApplication.quit`` so ``exec()`` returns
    # cleanly and the PID file is removed below.
    def _request_shutdown(signum: int, _frame: Any) -> None:
        logger.info("Pet desktop received signal %s; quitting", signum)
        # ``QTimer.singleShot(0, ...)`` re-enters the GUI thread; calling
        # ``qt_app.quit()`` directly from a signal handler is documented
        # as unsafe on some platforms.
        QTimer.singleShot(0, qt_app.quit)

    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_sig, _request_shutdown)
        except (OSError, ValueError):
            # ``signal.signal`` only works on the main thread; ignore
            # if we somehow ended up elsewhere (e.g. embedded test).
            pass

    pump = QTimer(window)

    def _drain_pet_events() -> None:
        try:
            while True:
                pet_path = _PET_SWITCH_QUEUE.get_nowait()
                try:
                    window.reload_pet(pet_path)
                except Exception:
                    logger.exception("Pet reload failed for %s", pet_path)
        except Empty:
            pass
        try:
            while True:
                payload = _PET_EVENT_QUEUE.get_nowait()
                window.apply_event(payload)
        except Empty:
            pass

    pump.timeout.connect(_drain_pet_events)
    pump.start(40)

    server_thread = threading.Thread(
        target=run_http_server,
        args=(enqueue_pet_event, enqueue_switch_pet, host, port),
        daemon=True,
    )
    server_thread.start()
    window.show()
    try:
        return qt_app.exec()
    finally:
        # Best-effort PID file cleanup so a follow-up health probe
        # immediately sees ``running=False`` and the next QwenPaw start
        # can autostart a fresh desktop without confusion.
        try:
            runtime.pid_path().unlink(missing_ok=True)
        except OSError:
            logger.exception("Failed to remove pid file at shutdown")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run QwenPaw Pet Desktop")
    parser.add_argument("--pet-dir", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scale", type=float, default=0.58)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = parse_args(argv)
    if not runtime.try_acquire_instance_lock():
        logger.info(
            "Another QwenPaw Pet Desktop instance is already running; exiting",
        )
        return 0
    try:
        pet_dir = resolve_pet_dir(args.pet_dir)
        return run_desktop(
            pet_dir=pet_dir,
            host=args.host,
            port=args.port,
            scale=args.scale,
        )
    finally:
        runtime.release_instance_lock()


if __name__ == "__main__":
    raise SystemExit(main())
