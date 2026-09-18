# -*- coding: utf-8 -*-
"""Event loop lag watchdog and stall diagnostics.

Detects event loop stalls caused by synchronous blocking operations
(e.g., synchronous file/network I/O, heavy computation, or blocking system
calls inside async handlers or plugins) and captures live stack traces of
the stalled loop thread for real-time attribution.
"""

import asyncio
import os
import re
import sys
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)

# Default stall warning threshold (override via
# QWENPAW_EVENT_LOOP_LAG_WARN_SECONDS)
DEFAULT_STALL_THRESHOLD = 2.0
# Default check interval (override via QWENPAW_EVENT_LOOP_WATCHDOG_INTERVAL)
DEFAULT_CHECK_INTERVAL = 0.25

# Regex to detect plugin paths in stack frames
_PLUGIN_PATH_PATTERN = re.compile(
    r"[\\/]plugins[\\/](?P<plugin_id>[a-zA-Z0-9_\-]+)[\\/]",
)
_PLUGIN_MODULE_PATTERN = re.compile(
    r"_plugin_(?:validation_)??(?P<plugin_id>[a-zA-Z0-9_]+)",
)


class EventLoopWatchdog:
    """Monitors an asyncio event loop from a dedicated background thread.

    Heartbeats are scheduled on the event loop via ``call_soon_threadsafe``.
    When heartbeats fall behind by more than ``stall_threshold`` seconds,
    the watchdog captures the current executing frame of the loop thread,
    identifies culprit plugins (if any), and logs actionable diagnostics.
    """

    def __init__(
        self,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        stall_threshold: Optional[float] = None,
        check_interval: Optional[float] = None,
    ) -> None:
        self._loop = loop
        self._loop_thread_id: Optional[int] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        if stall_threshold is not None:
            self._stall_threshold = float(stall_threshold)
        else:
            env_val = os.environ.get("QWENPAW_EVENT_LOOP_LAG_WARN_SECONDS")
            self._stall_threshold = (
                float(env_val) if env_val else DEFAULT_STALL_THRESHOLD
            )

        if check_interval is not None:
            self._check_interval = float(check_interval)
        else:
            env_val = os.environ.get("QWENPAW_EVENT_LOOP_WATCHDOG_INTERVAL")
            self._check_interval = (
                float(env_val) if env_val else DEFAULT_CHECK_INTERVAL
            )

        self._lock = threading.Lock()
        self._last_heartbeat = time.time()
        self._stall_start_time: Optional[float] = None
        self._is_stalled = False
        self._stall_count = 0
        self._max_lag = 0.0
        self._last_stall_duration = 0.0
        self._last_culprit: Optional[str] = None
        self._last_stall_stack: Optional[str] = None
        self._last_warn_time = 0.0

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start the watchdog monitoring thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            if loop is not None:
                self._loop = loop
            if self._loop is None:
                try:
                    self._loop = asyncio.get_running_loop()
                except RuntimeError:
                    self._loop = asyncio.get_event_loop()

            # Identify target thread
            try:
                # If we are starting from the loop thread itself
                current_loop = asyncio.get_running_loop()
                if current_loop is self._loop:
                    self._loop_thread_id = threading.get_ident()
            except RuntimeError:
                pass

            if self._loop_thread_id is None:
                # Fallback to main thread
                main_th = threading.main_thread()
                self._loop_thread_id = main_th.ident

            self._stop_event.clear()
            self._last_heartbeat = time.time()
            self._is_stalled = False

            self._thread = threading.Thread(
                target=self._run_watchdog,
                name="qwenpaw-event-loop-watchdog",
                daemon=True,
            )
            self._thread.start()
            logger.debug(
                "EventLoopWatchdog started (threshold=%.2fs, "
                "interval=%.2fs, target_thread=%s)",
                self._stall_threshold,
                self._check_interval,
                self._loop_thread_id,
            )

    def stop(self) -> None:
        """Stop the watchdog monitoring thread."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.debug("EventLoopWatchdog stopped")

    def is_running(self) -> bool:
        """Return whether the watchdog is active."""
        return self._thread is not None and self._thread.is_alive()

    def _heartbeat_callback(self) -> None:
        """Callback executed on the monitored event loop."""
        now = time.time()
        with self._lock:
            self._last_heartbeat = now

    def _run_watchdog(self) -> None:
        """Main loop of the watchdog thread."""
        while not self._stop_event.is_set():
            # Schedule next heartbeat on the loop
            if self._loop and self._loop.is_running():
                try:
                    self._loop.call_soon_threadsafe(
                        self._heartbeat_callback
                    )
                except (RuntimeError, AssertionError):
                    # Loop closed or shutting down
                    break
            elif self._loop and self._loop.is_closed():
                break

            self._stop_event.wait(self._check_interval)
            if self._stop_event.is_set():
                break

            self._check_lag()

    def _check_lag(self) -> None:
        """Check for loop stall and capture live stack trace if stalled."""
        now = time.time()
        should_capture = False
        continuing = False
        stall_duration: Optional[float] = None
        lag = 0.0

        with self._lock:
            lag = now - self._last_heartbeat
            if lag > self._max_lag:
                self._max_lag = lag

            was_stalled = self._is_stalled
            if lag >= self._stall_threshold:
                if not was_stalled:
                    self._is_stalled = True
                    self._stall_start_time = self._last_heartbeat
                    self._stall_count += 1
                    should_capture = True
                    continuing = False
                elif now - self._last_warn_time >= 5.0:
                    should_capture = True
                    continuing = True
            else:
                if was_stalled:
                    self._is_stalled = False
                    stall_duration = now - (
                        self._stall_start_time or self._last_heartbeat
                    )
                    self._last_stall_duration = stall_duration

        if should_capture:
            self._capture_stall(lag, now, continuing=continuing)
        elif stall_duration is not None:
            logger.info(
                "✓ [EventLoopWatchdog] Event loop recovered after "
                "%.2fs stall.",
                stall_duration,
            )

    def _capture_stall(
        self, lag: float, now: float, continuing: bool = False
    ) -> None:
        """Capture the live call stack of the monitored loop thread and
        extract culprit.
        """
        self._last_warn_time = now
        loop_thread_id = self._loop_thread_id
        if loop_thread_id is None:
            return

        frames = sys._current_frames()
        frame = frames.get(loop_thread_id)
        if frame is None:
            logger.warning(
                "⚠ [EventLoopWatchdog] Event loop stalled for %.2fs, "
                "but thread frame is unavailable.",
                lag,
            )
            return

        formatted_stack = "".join(traceback.format_stack(frame))
        self._last_stall_stack = formatted_stack

        # Analyze stack for culprit plugin
        culprit = self._identify_culprit(frame, formatted_stack)
        self._last_culprit = culprit

        state_str = "still stalled" if continuing else "stalled"
        if culprit:
            logger.warning(
                "⚠ [EventLoopWatchdog] Event loop %s (current lag: %.2fs)!\n"
                "Culprit identified inside plugin: '%s'\n"
                "Live stack trace on loop thread %s:\n%s",
                state_str,
                lag,
                culprit,
                loop_thread_id,
                formatted_stack,
            )
        else:
            logger.warning(
                "⚠ [EventLoopWatchdog] Event loop %s (current lag: %.2fs)!\n"
                "Live stack trace on loop thread %s:\n%s",
                state_str,
                lag,
                loop_thread_id,
                formatted_stack,
            )

    def _identify_culprit(
        self, frame: Any, formatted_stack: str
    ) -> Optional[str]:
        """Scan stack frames from deepest to root to find culprit plugin."""
        curr = frame
        frames_list: List[Any] = []
        while curr is not None:
            frames_list.append(curr)
            curr = curr.f_back

        # Check from deepest (where execution currently is) upward
        for f in frames_list:
            co_filename = f.f_code.co_filename
            m_path = _PLUGIN_PATH_PATTERN.search(co_filename)
            if m_path:
                return m_path.group("plugin_id")

            # Check globals for module name
            mod_name = f.f_globals.get("__name__", "")
            m_mod = _PLUGIN_MODULE_PATTERN.search(mod_name)
            if m_mod:
                return m_mod.group("plugin_id").replace("_", "-")

        # Check raw formatted stack as fallback
        m_fallback = _PLUGIN_PATH_PATTERN.search(formatted_stack)
        if m_fallback:
            return m_fallback.group("plugin_id")

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Return watchdog health and lag statistics."""
        with self._lock:
            now = time.time()
            current_lag = now - self._last_heartbeat
            return {
                "is_running": self.is_running(),
                "is_stalled": self._is_stalled,
                "current_lag": current_lag,
                "max_lag": self._max_lag,
                "stall_count": self._stall_count,
                "last_stall_duration": self._last_stall_duration,
                "last_culprit": self._last_culprit,
                "last_stall_stack": self._last_stall_stack,
            }


# Global singleton instance
_GLOBAL_WATCHDOG: Optional[EventLoopWatchdog] = None
_GLOBAL_WATCHDOG_LOCK = threading.Lock()


def get_event_loop_watchdog() -> Optional[EventLoopWatchdog]:
    """Return the global EventLoopWatchdog singleton."""
    return _GLOBAL_WATCHDOG


def start_event_loop_watchdog(
    loop: Optional[asyncio.AbstractEventLoop] = None,
    stall_threshold: Optional[float] = None,
    check_interval: Optional[float] = None,
) -> EventLoopWatchdog:
    """Start and register the global event loop watchdog."""
    global _GLOBAL_WATCHDOG
    with _GLOBAL_WATCHDOG_LOCK:
        if _GLOBAL_WATCHDOG is None:
            _GLOBAL_WATCHDOG = EventLoopWatchdog(
                loop=loop,
                stall_threshold=stall_threshold,
                check_interval=check_interval,
            )
        _GLOBAL_WATCHDOG.start(loop=loop)
        return _GLOBAL_WATCHDOG


def stop_event_loop_watchdog() -> None:
    """Stop and clear the global event loop watchdog."""
    global _GLOBAL_WATCHDOG
    with _GLOBAL_WATCHDOG_LOCK:
        if _GLOBAL_WATCHDOG is not None:
            _GLOBAL_WATCHDOG.stop()
            _GLOBAL_WATCHDOG = None
