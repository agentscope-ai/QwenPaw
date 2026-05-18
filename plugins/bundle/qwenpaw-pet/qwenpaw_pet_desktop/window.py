# -*- coding: utf-8 -*-
"""Transparent Qt desktop pet window."""

from __future__ import annotations

import textwrap
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from . import runtime
from .pet_package import validate_pet_package
from .sprites import CELL_HEIGHT, CELL_WIDTH, STATE_SPECS, state_for_event


class PetWindow(QWidget):
    """Small draggable always-on-top pet window."""

    def __init__(self, pet_dir: Path, scale: float = 0.58):
        super().__init__()
        manifest, sheet_path = validate_pet_package(pet_dir)
        self.pet_dir = pet_dir
        self.manifest = manifest
        self.sheet = QPixmap(str(sheet_path))
        if self.sheet.isNull():
            raise RuntimeError(f"could not load spritesheet: {sheet_path}")

        self.scale = scale
        self.pet_width = int(CELL_WIDTH * scale)
        self.pet_height = int(CELL_HEIGHT * scale)
        self.bubble_height = 46
        self.margin = 8
        self.resize(
            self.pet_width + self.margin * 2,
            self.pet_height + self.bubble_height + self.margin * 2,
        )

        self.state = "idle"
        self.frame = 0
        self.bubble_text = ""
        self._approval_pending = False
        self.drag_start: QPoint | None = None
        self._state_counter = 0

        # Use Qt.Window, not Qt.Tool: on macOS, Tool maps to NSPanel and the
        # system hides tool panels when the app loses activation (clicking
        # another app makes the pet vanish).
        # NoDropShadowWindowHint avoids a rectangular macOS drop-shadow "card"
        # around the frameless window (often mistaken for a background box).
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Window
            | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self._next_frame)
        self.frame_timer.start(STATE_SPECS[self.state]["dur"])

        self.move(40, 80)
        self._write_state()

    def reload_pet(self, pet_dir: Path) -> None:
        """Replace spritesheet and manifest without restarting the process."""
        manifest, sheet_path = validate_pet_package(pet_dir)
        sheet = QPixmap(str(sheet_path))
        if sheet.isNull():
            raise RuntimeError(f"could not load spritesheet: {sheet_path}")
        self.pet_dir = pet_dir
        self.manifest = manifest
        self.sheet = sheet
        self.bubble_text = ""
        self._approval_pending = False
        self.frame = 0
        if self.state != "idle":
            self.set_state("idle")
        else:
            self.frame_timer.start(STATE_SPECS["idle"]["dur"])
            self.update()
        self._write_state({"event": "pet.reload"})

    def apply_event(self, event: dict[str, Any]) -> None:
        ev_name = event.get("event")
        text = event.get("text")
        text_s = text.strip() if isinstance(text, str) else ""

        if ev_name == "query.received":
            self._approval_pending = False
        elif ev_name == "approval.pending":
            self._approval_pending = True
        elif ev_name in (
            "approval.resolved",
            "approval.bulk_cancel",
            "query.cancelled",
            "query.error",
        ):
            self._approval_pending = False

        # End-of-stream events can race ahead of or behind
        # ``approval.pending`` on the HTTP queue. Dropping an empty
        # ``idle`` or a premature ``query.done`` while we are waiting
        # on tool approval restores the approval bubble/state.
        if self._approval_pending:
            if ev_name == "idle" and not text_s:
                self.update()
                return
            if ev_name == "query.done":
                self.update()
                return

        state = state_for_event(ev_name, event.get("state"))
        if isinstance(text, str):
            # Empty ``text`` clears the bubble only for intentional
            # lifecycle events; otherwise a stray "" could erase e.g.
            # "Approval required" before the user looks at it.
            if text or ev_name in ("idle", "qwenpaw.shutdown"):
                self.bubble_text = text[:200]
        self.set_state(state)
        self._write_state(event)
        duration_ms = event.get("duration_ms")
        delay_ms = event.get("delay_ms")
        if (
            isinstance(duration_ms, int)
            and duration_ms > 0
            and state != "idle"
        ):

            def _revert_after_duration() -> None:
                if self._approval_pending:
                    return
                self.set_state("idle")

            QTimer.singleShot(duration_ms, _revert_after_duration)
        elif state == "idle" and isinstance(delay_ms, int) and delay_ms > 0:

            def _revert_after_delay() -> None:
                if self._approval_pending:
                    return
                self.set_state("idle")

            QTimer.singleShot(delay_ms, _revert_after_delay)
        self.update()

    def set_state(self, state: str) -> None:
        if state not in STATE_SPECS:
            state = "idle"
        if state != self.state:
            self.state = state
            self.frame = 0
            self.frame_timer.start(STATE_SPECS[self.state]["dur"])
            self._write_state()
            self.update()

    def _write_state(self, event: dict[str, Any] | None = None) -> None:
        self._state_counter += 1
        runtime.write_json(
            runtime.state_path(),
            {
                "state": self.state,
                "event": event.get("event") if event else None,
                "text": self.bubble_text,
                "updatedAt": int(time.time() * 1000),
                "counter": self._state_counter,
            },
        )

    def _next_frame(self) -> None:
        spec = STATE_SPECS[self.state]
        self.frame = (self.frame + 1) % int(spec["frames"])
        delay = spec["last"] if self.frame == 0 else spec["dur"]
        self.frame_timer.start(int(delay))
        self.update()

    def _pet_rect(self) -> QRect:
        return QRect(
            self.margin,
            self.bubble_height + self.margin,
            self.pet_width,
            self.pet_height,
        )

    # pylint: disable-next=unused-argument
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # Translucent frameless windows do not erase prior pixels each frame.
        # Pet cells also use partial transparency: without clearing first,
        # a hot-swapped spritesheet leaves the *previous* pet visible in alpha
        # holes (e.g. goose silhouette behind a snow leopard).
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(self.rect(), QColor())
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        self._draw_bubble(painter)

        spec = STATE_SPECS[self.state]
        row = int(spec["row"])
        frames = int(spec["frames"])
        col = self.frame % frames
        source = QRect(
            col * CELL_WIDTH,
            row * CELL_HEIGHT,
            CELL_WIDTH,
            CELL_HEIGHT,
        )
        painter.drawPixmap(self._pet_rect(), self.sheet, source)

    def _draw_bubble(self, painter: QPainter) -> None:
        if not self.bubble_text:
            return
        rect = QRect(
            self.margin,
            self.margin,
            self.width() - self.margin * 2,
            self.bubble_height - 6,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawRoundedRect(rect, 9, 9)
        painter.setPen(QColor(22, 24, 28))
        painter.setFont(QFont(".AppleSystemUIFont", 10))
        wrapped = "\n".join(textwrap.wrap(self.bubble_text, width=24)[:2])
        painter.drawText(
            rect.adjusted(8, 5, -8, -5),
            Qt.AlignLeft | Qt.AlignVCenter,
            wrapped,
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.drag_start = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
        elif event.button() == Qt.RightButton:
            self._open_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self.drag_start is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_start)

    # pylint: disable-next=unused-argument
    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.drag_start = None

    def _open_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        title = self.manifest.get("displayName", "QwenPaw Pet")
        menu.addAction(title).setEnabled(False)
        menu.addSeparator()
        menu.addAction("Idle", lambda: self.set_state("idle"))
        menu.addAction("Wave", lambda: self.set_state("waving"))
        menu.addAction("Thinking", lambda: self.set_state("running"))
        menu.addAction("Waiting", lambda: self.set_state("waiting"))
        menu.addSeparator()
        menu.addAction("Quit", QApplication.instance().quit)
        menu.exec(pos)
