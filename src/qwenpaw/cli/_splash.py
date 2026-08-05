# -*- coding: utf-8 -*-
"""Shared tkinter splash window for desktop startup.

This module is intentionally kept lightweight — it only imports
``tkinter`` and ``time`` so it can be loaded before any heavy
``qwenpaw`` dependencies.
"""

from __future__ import annotations

import time
import tkinter as tk


def show_splash():  # pylint: disable=too-many-locals
    """Create and show a branded splash window with animated orange arc.

    Returns a tuple of ``(root, update, get_elapsed, destroy)``
    callbacks that the caller uses to keep the splash alive and
    eventually tear it down.
    """
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

    def get_elapsed() -> int:
        return int(time.monotonic() - t0)

    def _tick() -> None:
        elapsed = get_elapsed()
        extent = min(elapsed / 300 * 270, 270)
        canvas.itemconfigure(active_arc, extent=extent)
        canvas.itemconfigure(timer_id, text=f"{elapsed}s")
        _after_id[0] = root.after(1000, _tick)

    _tick()
    root.update()

    def update() -> None:
        """Refresh splash animation (call from main thread loop)."""
        elapsed = get_elapsed()
        extent = min(elapsed / 300 * 270, 270)
        canvas.itemconfigure(active_arc, extent=extent)
        canvas.itemconfigure(timer_id, text=f"{elapsed}s")
        root.update()

    def destroy() -> None:
        """Tear down splash window safely."""
        if _after_id[0] is not None:
            try:
                root.after_cancel(_after_id[0])
            except Exception:
                pass
        try:
            root.withdraw()
            root.update()
            root.destroy()
        except Exception:
            pass

    return root, update, get_elapsed, destroy
