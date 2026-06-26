# -*- coding: utf-8 -*-
"""Ultra-lightweight desktop preloader.

Shows a tkinter splash window *immediately* on launch (before any
heavy ``qwenpaw`` imports), then hands off to the real desktop
command once all modules have loaded.

The ``.bat`` launcher in the NSIS installer calls this script
directly so the user sees visual feedback within ~150 ms of
double-clicking the shortcut.
"""

# pylint: disable=wrong-import-position,broad-exception-caught
# pylint: disable=import-outside-toplevel

from __future__ import annotations

import os
import queue
import sys
import threading
import time

# Ensure the src directory is importable when running as a standalone script
# from the packaged env root (where desktop_preloader.py is copied).
_src_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "Lib",
    "site-packages",
)
if os.path.isdir(_src_dir) and _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from qwenpaw.cli._splash import show_splash  # noqa: E402

# Show splash immediately (before any heavy imports)
splash = show_splash()

# Parse --log-level from command line (passed by .bat launcher)
_log_level = "info"
for i, arg in enumerate(sys.argv[1:], 1):
    if arg == "--log-level" and i < len(sys.argv) - 1:
        _log_level = sys.argv[i + 1]
        break
    if arg.startswith("--log-level="):
        _log_level = arg.split("=", 1)[1]
        break

# Import the heavy desktop_cmd module in a background thread so the
# tkinter splash stays responsive (timer/arc animate) during the load.
_import_q: queue.Queue = queue.Queue()


def _import_desktop_cmd() -> None:
    """Import desktop_cmd module and put it on the queue."""
    try:
        from qwenpaw.cli import desktop_cmd as _dc  # noqa: E402

        _import_q.put(("ok", _dc))
    except Exception as exc:  # noqa: BLE001
        _import_q.put(("err", exc))


threading.Thread(target=_import_desktop_cmd, daemon=True).start()

# Main thread keeps splash alive/animated while import runs
while _import_q.empty():
    splash[1]()  # update timer and arc
    time.sleep(0.05)

status, payload = _import_q.get()
if status == "err":
    raise payload

_dc = payload

# Share splash state with desktop_cmd so it reuses instead of recreating
_dc.preloader_splash["callbacks"] = splash
_dc.preloader_splash["start_time"] = time.monotonic()

# Run the desktop command on the main thread (webview needs main thread)
# Pass arguments via sys.argv for Click to parse, not as function kwargs
sys.argv = ["desktop", "--host", "127.0.0.1", "--log-level", _log_level]
_dc.desktop_cmd()
