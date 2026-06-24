# -*- coding: utf-8 -*-
"""Ultra-lightweight desktop preloader.

Shows a tkinter splash window *immediately* on launch (before any
heavy ``qwenpaw`` imports), then hands off to the real desktop
command once all modules have loaded.

The ``.bat`` launcher in the NSIS installer calls this script
directly so the user sees visual feedback within ~150 ms of
double-clicking the shortcut.
"""

# pylint: disable=wrong-import-position,broad-exception-caught,import-outside-toplevel

from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk


def _show_splash():  # pylint: disable=too-many-locals
    """Create and return a tkinter splash window with orange arc."""
    root = tk.Tk()
    root.title("QwenPaw Desktop")
    root.configure(bg="#f5f7fa")
    root.overrideredirect(True)
    root.attributes("-topmost", True)

    w, h = 400, 360
    sx = (root.winfo_screenwidth() - w) // 2
    sy = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{sx}+{sy}")

    canvas = tk.Canvas(
        root,
        width=w,
        height=h,
        highlightthickness=0,
        bg="#f5f7fa",
    )
    canvas.pack()

    # White card background
    card_x, card_y, card_w, card_h = 40, 20, 320, 320
    canvas.create_rectangle(
        card_x,
        card_y,
        card_x + card_w,
        card_y + card_h,
        fill="white",
        outline="#e0e0e0",
        width=1,
    )

    # Brand text
    canvas.create_text(
        w // 2,
        card_y + 55,
        text="QwenPaw",
        font=("Segoe UI", 26, "bold"),
        fill="#ff7f16",
    )

    # Orange arc (270 degree trail)
    arc_size = 120
    arc_cx, arc_cy = w // 2, card_y + 170
    canvas.create_arc(
        arc_cx - arc_size // 2,
        arc_cy - arc_size // 2,
        arc_cx + arc_size // 2,
        arc_cy + arc_size // 2,
        start=225,
        extent=270,
        style="arc",
        outline="#f0f0f0",
        width=7,
    )
    active_arc = canvas.create_arc(
        arc_cx - arc_size // 2,
        arc_cy - arc_size // 2,
        arc_cx + arc_size // 2,
        arc_cy + arc_size // 2,
        start=225,
        extent=0,
        style="arc",
        outline="#ff7f16",
        width=7,
    )

    # Timer label
    timer_id = canvas.create_text(
        w // 2,
        arc_cy,
        text="0s",
        font=("Segoe UI", 22),
        fill="#333333",
    )

    # Status text
    canvas.create_text(
        w // 2,
        card_y + 280,
        text="Starting...",
        font=("Segoe UI", 12),
        fill="#888888",
    )

    t0 = time.monotonic()
    _after_id: list[str | None] = [None]

    def get_elapsed():
        return int(time.monotonic() - t0)

    def _tick():
        elapsed = get_elapsed()
        extent = min(elapsed / 300 * 270, 270)
        canvas.itemconfigure(active_arc, extent=extent)
        canvas.itemconfigure(timer_id, text=f"{elapsed}s")
        _after_id[0] = root.after(1000, _tick)

    _tick()
    root.update()

    def update():
        elapsed = get_elapsed()
        extent = min(elapsed / 300 * 270, 270)
        canvas.itemconfigure(active_arc, extent=extent)
        canvas.itemconfigure(timer_id, text=f"{elapsed}s")
        root.update()

    def destroy():
        if _after_id[0] is not None:
            try:
                root.after_cancel(_after_id[0])
            except Exception:
                pass
        root.destroy()

    return root, update, get_elapsed, destroy


# Show splash immediately (before any heavy imports)
splash = _show_splash()

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
_dc.desktop_cmd(
    host="127.0.0.1",
    log_level=_log_level,
    standalone_mode=False,
)
