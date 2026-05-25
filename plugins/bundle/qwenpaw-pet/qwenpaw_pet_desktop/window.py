# -*- coding: utf-8 -*-
"""Transparent Qt desktop pet window."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from . import runtime
from .pet_package import validate_pet_package
from .sprites import CELL_HEIGHT, CELL_WIDTH, STATE_SPECS, state_for_event

# Query lifecycle events that may arrive after ``approval.pending`` and
# would clobber the approval bubble or animation. ``tool.result`` and
# ``query.done`` are excluded: the former updates animation mid-flight;
# the latter must always land (HTTP may deliver it before ``approval.*``).
_LIFECYCLE_WHILE_APPROVAL_BLOCKED = frozenset(
    {
        "idle",
        "query.received",
        "query.running",
        "query.first_token",
        "tool.detected",
    },
)

# Lifecycle events that may arrive out-of-order *after* ``query.done`` and
# would replace the Done bubble (e.g. a slow HTTP POST for ``tool.result``).
_LIFECYCLE_AFTER_DONE_BLOCKED = frozenset(
    {
        "idle",
        "query.running",
        "query.first_token",
        "tool.detected",
        "tool.result",
    },
)

# After ``query.done``, keep the Done bubble but revert animation to idle.
_POST_DONE_ANIMATION_MS = 3500

# After ``query.received``, keep jumping + bubble before ``query.running``.
_POST_RECEIVED_ANIMATION_MS = 1500

_LIFECYCLE_DURING_RECEIVED_HOLD = frozenset({"query.running"})


def _bubble_font() -> QFont:
    """Pick a UI font that renders CJK bubble text on macOS and Windows."""
    font = QFont()
    if sys.platform == "win32":
        font.setFamilies(["Microsoft YaHei UI", "Segoe UI", "Sans Serif"])
    elif sys.platform == "darwin":
        font.setFamilies([".AppleSystemUIFont", "PingFang SC", "Sans Serif"])
    else:
        font.setFamilies(["Noto Sans CJK SC", "Sans Serif"])
    font.setPointSize(10)
    return font


def _wrap_bubble_text(
    text: str,
    font: QFont,
    max_width: int,
    *,
    max_lines: int = 2,
) -> str:
    """Lay out bubble copy within ``max_width`` (up to ``max_lines``)."""
    fm = QFontMetrics(font)
    lines: list[str] = []

    def _append(line: str) -> None:
        line = line.strip()
        if line and len(lines) < max_lines:
            lines.append(line)

    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph or len(lines) >= max_lines:
            continue

        current = ""
        for token in paragraph.split():
            trial = token if not current else f"{current} {token}"
            if fm.horizontalAdvance(trial) <= max_width:
                current = trial
                continue
            _append(current)
            current = token
            if len(lines) >= max_lines:
                break

        if len(lines) >= max_lines:
            break

        if current:
            while current and len(lines) < max_lines:
                if fm.horizontalAdvance(current) <= max_width:
                    _append(current)
                    break
                # Long tool names without spaces: break by character.
                cut = 1
                while cut < len(current):
                    if fm.horizontalAdvance(current[:cut]) > max_width:
                        break
                    cut += 1
                cut = max(1, cut - 1)
                _append(current[:cut])
                current = current[cut:]

    return "\n".join(lines)


def _ends_approval_wait(ev_name: str | None) -> bool:
    """``approval.*`` follow-ups that clear the approval-wait interlock."""
    return (
        isinstance(ev_name, str)
        and ev_name.startswith("approval.")
        and ev_name != "approval.pending"
    )


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
        self._turn_complete = False
        self._last_event_serial = 0
        self._state_revert_token = 0
        self._received_hold_token = 0
        self._deferred_lifecycle_event: dict[str, Any] | None = None
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
        self._turn_complete = False
        self._last_event_serial = 0
        self._state_revert_token = 0
        self._received_hold_token = 0
        self._deferred_lifecycle_event = None
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

        if self._is_stale_event(event):
            return
        if self._handle_early_lifecycle(ev_name, event):
            return

        self._advance_event_serial(event)
        state = state_for_event(ev_name, event.get("state"))
        self._apply_bubble_text(ev_name, text)
        self.set_state(state)
        self._write_state(event)
        self._schedule_post_event_timing(ev_name, state, event)
        self.update()

    def _is_stale_event(self, event: dict[str, Any]) -> bool:
        serial = event.get("serial")
        if isinstance(serial, int) and serial > 0:
            if serial < self._last_event_serial:
                self.update()
                return True
        return False

    def _advance_event_serial(self, event: dict[str, Any]) -> None:
        serial = event.get("serial")
        if isinstance(serial, int) and serial > self._last_event_serial:
            self._last_event_serial = serial

    def _handle_early_lifecycle(
        self,
        ev_name: str | None,
        event: dict[str, Any],
    ) -> bool:
        if ev_name == "query.received":
            self._approval_pending = False
            self._turn_complete = False
            self._deferred_lifecycle_event = None
            self._received_hold_token = 0
            self._bump_state_revert_token()
        elif ev_name == "approval.pending":
            self._approval_pending = True
        elif ev_name == "query.done":
            self._approval_pending = False
            self._turn_complete = True
        elif _ends_approval_wait(ev_name):
            self._approval_pending = False
            if self._turn_complete:
                self.update()
                return True
        elif ev_name in ("query.cancelled", "query.error"):
            self._approval_pending = False

        if self._turn_complete and ev_name in _LIFECYCLE_AFTER_DONE_BLOCKED:
            self.update()
            return True

        if (
            ev_name != "query.received"
            and self._received_hold_active()
            and ev_name in _LIFECYCLE_DURING_RECEIVED_HOLD
        ):
            self._deferred_lifecycle_event = dict(event)
            self.update()
            return True

        if (
            self._approval_pending
            and ev_name in _LIFECYCLE_WHILE_APPROVAL_BLOCKED
        ):
            self.update()
            return True

        if self._approval_pending and ev_name == "tool.result":
            self._advance_event_serial(event)
            state = state_for_event(ev_name, event.get("state"))
            self.set_state(state)
            self._write_state(event)
            self.update()
            return True

        return False

    def _apply_bubble_text(
        self,
        ev_name: str | None,
        text: Any,
    ) -> None:
        if not isinstance(text, str):
            return
        # Empty ``text`` clears the bubble only for intentional lifecycle
        # events; otherwise a stray "" could erase e.g. "Approval required".
        if text or ev_name in ("idle", "qwenpaw.shutdown"):
            self.bubble_text = text[:200]

    def _schedule_post_event_timing(
        self,
        ev_name: str | None,
        state: str,
        event: dict[str, Any],
    ) -> None:
        duration_ms = event.get("duration_ms")
        if ev_name == "query.received":
            hold_ms = (
                duration_ms
                if isinstance(duration_ms, int) and duration_ms > 0
                else _POST_RECEIVED_ANIMATION_MS
            )
            self._begin_received_hold(hold_ms)
            return
        if ev_name == "query.done":
            if not isinstance(duration_ms, int) or duration_ms <= 0:
                duration_ms = _POST_DONE_ANIMATION_MS
            self._schedule_state_revert(duration_ms)
            return

        delay_ms = event.get("delay_ms")
        if (
            isinstance(duration_ms, int)
            and duration_ms > 0
            and state != "idle"
        ):
            self._schedule_state_revert(duration_ms)
        elif state == "idle" and isinstance(delay_ms, int) and delay_ms > 0:
            self._schedule_state_revert(delay_ms)

    def _received_hold_active(self) -> bool:
        return (
            self._received_hold_token != 0
            and self._received_hold_token == self._state_revert_token
        )

    def _begin_received_hold(self, duration_ms: int) -> None:
        """Hold ``query.received``; defer ``query.running`` until hold ends."""
        token = self._bump_state_revert_token()
        self._received_hold_token = token

        def _flush_received_hold() -> None:
            if token != self._state_revert_token:
                return
            self._received_hold_token = 0
            deferred = self._deferred_lifecycle_event
            self._deferred_lifecycle_event = None
            if deferred is not None:
                self.apply_event(deferred)
            elif not self._approval_pending:
                self.set_state("idle")

        QTimer.singleShot(duration_ms, _flush_received_hold)

    def _bump_state_revert_token(self) -> int:
        self._state_revert_token += 1
        return self._state_revert_token

    def _schedule_state_revert(self, duration_ms: int) -> None:
        """Revert animation to idle after ``duration_ms``; keep bubble text."""
        token = self._bump_state_revert_token()

        def _revert_animation_only() -> None:
            if token != self._state_revert_token:
                return
            if self._approval_pending:
                return
            self._turn_complete = False
            self.set_state("idle")

        QTimer.singleShot(duration_ms, _revert_animation_only)

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
        font = _bubble_font()
        painter.setPen(QColor(22, 24, 28))
        painter.setFont(font)
        text_rect = rect.adjusted(8, 5, -8, -5)
        wrapped = _wrap_bubble_text(
            self.bubble_text,
            font,
            text_rect.width(),
        )
        painter.drawText(
            text_rect,
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
