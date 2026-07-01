# -*- coding: utf-8 -*-
"""Transcript message widgets (user / assistant / thinking / errors)."""

from __future__ import annotations

import math
import time

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Collapsible, Markdown, Static

from ._anim import TICK, pulse, spinner
from ._format import summarize_params


class _Bubble(Static):
    """A rounded message card.

    The fill is transparent so the bubble blends into the static background; a
    rounded border outlines it. The background no longer animates, so
    transparency is safe — there is nothing to re-blend against each frame, and
    the rounded corners simply show the background.
    """

    # pylint: disable-next=useless-parent-delegation
    def __init__(self, renderable, *, classes: str = "") -> None:
        super().__init__(renderable, classes=f"msg {classes}".strip())


class UserMessage(_Bubble):
    """A user turn, shown with a prompt glyph."""

    def __init__(self, text: str) -> None:
        body = Text()
        body.append("❯ ", style="bold #6db8ff")
        body.append(text)
        super().__init__(body, classes="user")


class QueuedMessage(_Bubble):
    """A user message waiting its turn while the agent is still working.

    Sent while busy, it sits dimmed in the transcript until the current turn
    ends (then it's delivered) or the user recalls it with ↑ to edit.
    """

    def __init__(self, text: str) -> None:
        body = Text()
        body.append("⏳ ", style="#8a8a8a")
        body.append(text, style="#8a8a8a")
        super().__init__(body, classes="queued")


class AgentLabel(Static):
    """The ``qwenpaw`` lane label, shown once at the start of a turn.

    Kept separate from :class:`AssistantMessage` so a turn that interleaves
    thinking, tools and several answer chunks shows a single label above the
    whole group rather than one per bubble.
    """

    def __init__(self) -> None:
        super().__init__(
            Text("qwenpaw", style="bold #b48cff"),
            classes="agentlabel",
        )


class WelcomeMessage(Static):
    """Startup greeting rendered as embossed terminal pixels (static)."""

    _LOGO_PIXELS = (
        " ███████                              ████████    O O O",
        "███   ███ ███   ███  ██████  ███████  ███   ███  ███████  ███   ███",
        "███   ███ ███   ███ ███  ███ ███  ███ ███   ███ ███   ███ ███   ███",
        "███   ███ ███ █ ███ ████████ ███  ███ █████████ ███   ███ ███ █ ███",
        "███ █ ███ █████████ ███      ███  ███ ███       ███   ███ █████████",
        " ███████   ███ ███   ██████  ███  ███ ███        █████ ██  ███ ███",
        "     ████",
    )

    def __init__(
        self,
        palette: tuple[str, str, str] | None = None,
        accent: str | None = None,
        *,
        workspace_dir: str | None = None,
        project_dir: str | None = None,
    ) -> None:
        # ``_frame`` is the colour-gradient phase and stays fixed at 0: the
        # vertical colour wash is static. The startup *motion* is positional —
        # a one-shot hop where each letter drops in and bounces to its place
        # (see :meth:`on_mount`), independent of the gradient.
        self._frame = 0
        self._accent = accent
        self._workspace_dir = workspace_dir
        self._project_dir = project_dir
        self._gradient_stops = (
            "#bfe1ff",
            "#8fd7ff",
            "#c8b6ff",
            "#ffd08a",
        )
        if palette is not None:
            self._set_palette_colors(palette)
        # Rectangular (space-padded) copy of the pixel grid plus the column
        # span of each glyph, so the hop animation can move one letter at a
        # time. Row colours are cached for the per-frame repaint.
        width = max(len(row) for row in self._LOGO_PIXELS)
        self._grid = tuple(row.ljust(width) for row in self._LOGO_PIXELS)
        self._width = width
        self._segments = _segment_columns(self._grid)
        self._row_colors = self._row_color_cache()
        self._animating = False
        self._anim_elapsed = 0.0
        self._anim_timer = None
        super().__init__(self._render_body(), classes="msg welcome")

    def set_palette(
        self,
        palette: tuple[str, str, str],
        accent: str | None = None,
    ) -> None:
        if accent is not None:
            self._accent = accent
        self._set_palette_colors(palette)
        self._row_colors = self._row_color_cache()
        if self._animating:
            # A hop is in flight; the next frame repaints with the new colours.
            return
        self.update(self._render_body())

    def _row_color_cache(self) -> list[str]:
        return [self._gradient_color(row) for row in range(len(self._grid))]

    def _set_palette_colors(self, palette: tuple[str, str, str]) -> None:
        screen, prompt_bg, chrome = palette
        if self._accent:
            # Brand-coloured logo: a vertical gradient built around the theme
            # accent (e.g. QwenPaw orange), kept saturated rather than washed
            # out so the wordmark reads as the brand colour.
            accent = self._accent
            deep = _mix_hex(accent, screen, 0.45)
            self._gradient_stops = (
                _mix_hex(accent, "#ffffff", 0.42),
                accent,
                _mix_hex(accent, deep, 0.5),
                _mix_hex(accent, "#ffd08a", 0.5),
            )
            return
        cool = _mix_hex(chrome, "#ffffff", 0.62)
        warm = _mix_hex(prompt_bg, "#ffd08a", 0.46)
        bright = _mix_hex(prompt_bg, "#ffffff", 0.56)
        deep = _mix_hex(screen, chrome, 0.52)
        self._gradient_stops = (
            bright,
            cool,
            _mix_hex(cool, warm, 0.42),
            _mix_hex(deep, "#ffffff", 0.48),
        )

    def _render_body(self) -> Text:
        body = Text()
        for row in self._render_pixel_rows():
            body.append(row)
        self._append_context(body)
        return body

    def _append_context(self, body: Text) -> None:
        lines = []
        if self._workspace_dir:
            lines.append(
                (
                    "Agent directory (sessions, memory & skills): ",
                    self._workspace_dir,
                ),
            )
        if self._project_dir:
            lines.append(("Project directory: ", self._project_dir))
        if not lines:
            return
        body.append("\n\n")
        for index, (label, path) in enumerate(lines):
            body.append(label, style="bold #8a8a8a")
            body.append(path, style="#b0b0b0")
            if index + 1 < len(lines):
                body.append("\n")

    def _render_pixel_rows(self) -> list[Text]:
        rows: list[Text] = []
        for index, row in enumerate(self._LOGO_PIXELS):
            line = Text()
            base = self._gradient_color(index)
            for ch in row:
                if ch == " ":
                    line.append(" ")
                elif ch == "O":
                    line.append("█", style=_bright_dot_hex(base))
                else:
                    line.append("█", style=base)
            rows.append(line)
            if index + 1 < len(self._LOGO_PIXELS):
                line.append("\n")
        return rows

    def _gradient_color(self, row_index: int) -> str:
        stops = self._gradient_stops
        position = (row_index * 0.72 + self._frame * 0.26) % len(stops)
        start = int(position)
        amount = position - start
        return _mix_hex(stops[start], stops[(start + 1) % len(stops)], amount)

    # -- startup hop animation ----------------------------------------------
    #
    # Each glyph is a little kitten: it drops in from above and bounces to its
    # resting row, with staggered start times so the wordmark scrambles itself
    # together before settling — playful, and over in well under five seconds.
    # ``_HOPS`` is ``(start_delay_s, drop_rows, gravity, restitution)`` per
    # glyph, left to right; distances are character rows, gravity rows/s².
    _ANIM_TICK = 0.04
    _ANIM_CAP = 2.7
    _HOPS = (
        (0.00, 9.0, 80.0, 0.48),
        (0.14, 7.5, 92.0, 0.50),
        (0.30, 11.0, 74.0, 0.46),
        (0.45, 8.0, 96.0, 0.50),
        (0.62, 10.0, 82.0, 0.52),
        (0.80, 7.5, 100.0, 0.46),
        (0.98, 9.0, 86.0, 0.50),
    )

    def on_mount(self) -> None:
        # Animate only on a live terminal; headless test/CI drivers get the
        # final logo immediately so output stays deterministic.
        if self.app.is_headless:
            return
        self._animating = True
        self._anim_elapsed = 0.0
        self.update(self._compose_frame(0.0)[0])
        self._anim_timer = self.set_interval(self._ANIM_TICK, self._tick)

    def _tick(self) -> None:
        self._anim_elapsed += self._ANIM_TICK
        frame, settled = self._compose_frame(self._anim_elapsed)
        if settled or self._anim_elapsed >= self._ANIM_CAP:
            self._finish_animation()
            return
        self.update(frame)

    def _finish_animation(self) -> None:
        self._animating = False
        if self._anim_timer is not None:
            self._anim_timer.stop()
            self._anim_timer = None
        self.update(self._render_body())

    def _glyph_offset(self, index: int, elapsed: float) -> float:
        delay, drop, gravity, restitution = self._HOPS[index % len(self._HOPS)]
        return _bounce(elapsed - delay, drop, gravity, restitution)

    def _compose_frame(self, elapsed: float) -> tuple[Text, bool]:
        height = len(self._grid)
        # ``None`` cells stay blank; a colour means a lit block at that cell.
        canvas: list[list[str | None]] = [
            [None] * self._width for _ in range(height)
        ]
        settled = True
        for index, (start, end) in enumerate(self._segments):
            offset = self._glyph_offset(index, elapsed)
            if offset > 0.04:
                settled = False
            shift = int(round(offset))
            for row in range(height):
                dest_row = row - shift
                if dest_row < 0 or dest_row >= height:
                    continue
                source = self._grid[row]
                color = self._row_colors[row]
                dest = canvas[dest_row]
                for col in range(start, end):
                    char = source[col]
                    if char == " ":
                        continue
                    dest[col] = (
                        _bright_dot_hex(color) if char == "O" else color
                    )
        body = _canvas_to_text(canvas)
        self._append_context(body)
        return body, settled


def _canvas_to_text(canvas: list[list[str | None]]) -> Text:
    body = Text()
    last = len(canvas) - 1
    for index, row in enumerate(canvas):
        for color in row:
            if color is None:
                body.append(" ")
            else:
                body.append("█", style=color)
        if index != last:
            body.append("\n")
    return body


def _segment_columns(grid: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    """Column span ``[start, end)`` of each glyph, split on blank columns."""
    height = len(grid)
    width = len(grid[0]) if grid else 0

    def blank(col: int) -> bool:
        return all(grid[row][col] == " " for row in range(height))

    segments: list[tuple[int, int]] = []
    col = 0
    while col < width:
        if blank(col):
            col += 1
            continue
        start = col
        while col < width and not blank(col):
            col += 1
        segments.append((start, col))
    return tuple(segments)


def _bounce(
    tau: float,
    drop: float,
    gravity: float,
    restitution: float,
) -> float:
    """Height (rows above the resting row) of a ball dropped at ``tau == 0``.

    The ball falls from ``drop`` rows up, hits the floor and bounces with the
    given ``restitution`` until its energy is spent, returning ``0.0`` once it
    settles. Drives each glyph's hop into place on startup.
    """
    if tau <= 0.0:
        return drop
    first_fall = math.sqrt(2.0 * drop / gravity)
    if tau < first_fall:
        return max(0.0, drop - 0.5 * gravity * tau * tau)
    remaining = tau - first_fall
    speed = gravity * first_fall * restitution
    while speed > 1e-2:
        arc = 2.0 * speed / gravity
        if remaining < arc:
            return max(
                0.0,
                speed * remaining - 0.5 * gravity * remaining * remaining,
            )
        remaining -= arc
        speed *= restitution
    return 0.0


def _mix_hex(left: str, right: str, amount: float) -> str:
    left_rgb = _hex_to_rgb(left)
    right_rgb = _hex_to_rgb(right)
    mixed = tuple(
        round(a + (b - a) * amount)
        for a, b in zip(left_rgb, right_rgb, strict=True)
    )
    return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    cleaned = value.removeprefix("#")
    return (
        int(cleaned[0:2], 16),
        int(cleaned[2:4], 16),
        int(cleaned[4:6], 16),
    )


def _bright_dot_hex(color: str) -> str:
    bright = _mix_hex(color, "#ffffff", 0.82)
    if _relative_luminance(bright) <= _relative_luminance(color):
        return "#ffffff"
    return bright


def _contrast_ratio(left: str, right: str) -> float:
    left_luminance = _relative_luminance(left)
    right_luminance = _relative_luminance(right)
    lighter = max(left_luminance, right_luminance)
    darker = min(left_luminance, right_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _relative_luminance(color: str) -> float:
    channels = []
    for channel in _hex_to_rgb(color):
        value = channel / 255
        if value <= 0.03928:
            channels.append(value / 12.92)
        else:
            channels.append(((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


class AssistantMessage(Widget):
    """Streaming assistant answer rendered as markdown.

    ``append()`` accumulates deltas and re-renders. The lane label is mounted
    separately (see :class:`AgentLabel`) so post-tool answer chunks flow
    under the same label instead of looking like new messages.
    """

    DEFAULT_CSS = """
    AssistantMessage { height: auto; }
    AssistantMessage > Markdown { height: auto; margin: 0; }
    """

    def __init__(self) -> None:
        super().__init__(classes="msg assistant")
        self._text = ""
        self._md = Markdown("")

    def compose(self) -> ComposeResult:
        yield self._md

    async def append(self, delta: str) -> None:
        self._text += delta
        await self._md.update(self._text)

    @property
    def text(self) -> str:
        return self._text


class ThoughtMessage(Collapsible):
    """Dimmed agent thinking lane, collapsed by default.

    The reasoning streams into the (hidden) body; the user can expand the
    header to read it. Reused for plan summaries via the ``title`` argument.

    When ``live=True`` the header animates (spinner + pulsing colour) and
    shows the elapsed time while the agent thinks; calling :meth:`done`
    freezes it to ``💭 thought for Ns``.
    """

    def __init__(
        self,
        title: str = "💭 thinking",
        collapsed: bool = True,
        *,
        live: bool = False,
    ) -> None:
        self._text = ""
        self._live = live
        self._start: float | None = None
        self._timer = None
        self._frame = 0
        self._finished = False
        self._body = Static(Text("", style="italic #8a8a8a"))
        super().__init__(
            self._body,
            title=title,
            collapsed=collapsed,
            classes="msg thought",
        )

    def on_mount(self) -> None:
        if self._live:
            self._start = time.monotonic()
            self._timer = self.set_interval(TICK, self._tick)
            self._tick()

    def _elapsed(self) -> int:
        if self._start is None:
            return 0
        return int(time.monotonic() - self._start)

    def _tick(self) -> None:
        if self._finished:
            return
        self._frame += 1
        head = Text()
        head.append("💭 ", style="")
        head.append(f"thinking {self._elapsed()}s ", style="italic #8a8a8a")
        head.append(spinner(self._frame), style=f"bold {pulse(self._frame)}")
        self.title = head

    def done(self) -> None:
        """Freeze the header to the final elapsed time."""
        if self._finished or not self._live:
            return
        self._finished = True
        if self._timer is not None:
            self._timer.stop()
        self.title = f"💭 thought for {self._elapsed()}s"

    def append(self, delta: str) -> None:
        self._text += delta
        self._body.update(Text(self._text, style="italic #8a8a8a"))


class ActivityLine(_Bubble):
    """Single friendly row for the current hidden thought/tool chain."""

    _TERMINAL = {"completed", "failed"}

    def __init__(self) -> None:
        self._mode = "thinking"
        self._label = "thinking"
        self._status = "in_progress"
        self._summary = ""
        self._frame = 0
        self._timer = None
        self._start = time.monotonic()
        super().__init__(self._render_line(), classes="activity")

    def on_mount(self) -> None:
        self._timer = self.set_interval(TICK, self._tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    def _tick(self) -> None:
        if self._status in self._TERMINAL:
            return
        self._frame += 1
        self.update(self._render_line())

    def set_thinking(self) -> None:
        self._mode = "thinking"
        self._label = "thinking"
        self._status = "in_progress"
        self._summary = ""
        self.update(self._render_line())

    def set_tool(
        self,
        *,
        title: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        params: str | None = None,
    ) -> None:
        self._mode = "tool"
        if title or kind:
            self._label = self._tool_label(title, kind)
        self._status = status or self._status
        if params is not None:
            self._summary = self._tool_summary(params)
        self.update(self._render_line())

    def done(self) -> None:
        if self._status not in self._TERMINAL:
            self._status = "completed"
        if self._mode == "thinking":
            self._label = "thought complete"
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.update(self._render_line())

    def _render_line(self) -> Text:
        text = Text()
        if self._status in self._TERMINAL:
            glyph = "✓" if self._status == "completed" else "✗"
            color = "#6dff9d" if self._status == "completed" else "#ff6d6d"
        else:
            glyph = spinner(self._frame)
            color = pulse(self._frame)
        text.append(f"{glyph} ", style=f"bold {color}")
        if self._mode == "tool":
            text.append("using ", style="#8a8a8a")
            text.append(self._label, style="bold")
        else:
            elapsed = int(time.monotonic() - self._start)
            text.append(f"{self._label} {elapsed}s", style="italic #8a8a8a")
        if self._summary:
            text.append("  ")
            text.append(self._summary, style="#7fb7d9")
        return text

    def _tool_label(self, title: str | None, kind: str | None) -> str:
        value = (title or "").strip()
        if value and value.lower() != "tool":
            return value
        return kind or "tool"

    def _tool_summary(self, params: str | None) -> str:
        return summarize_params(params)


class FileLinkBox(_Bubble):
    """A file the agent sent (e.g. via ``send_file_to_user``).

    Rendered as a distinct, always-visible transcript line (the originating
    tool panel auto-collapses) and clickable: a click opens the file with the
    OS handler via ``App.open_url``.
    """

    DEFAULT_CSS = """
    FileLinkBox:hover { background: #23233a; }
    """

    def __init__(self, name: str, uri: str) -> None:
        self._uri = uri
        body = Text()
        body.append("📎 ", style="bold #6db8ff")
        body.append(name or uri, style="underline #6db8ff")
        body.append("  (click to open)", style="#5a5a5a")
        super().__init__(body, classes="file")

    def on_click(self) -> None:
        try:
            self.app.open_url(self._uri)
        except Exception:  # noqa: BLE001 - opening is best-effort
            pass


class PushMessageBox(_Bubble):
    """A server-initiated proactive message."""

    def __init__(self, text: str) -> None:
        body = Text()
        body.append("✦ ", style="bold #ffcf6d")
        body.append(text, style="#ffcf6d")
        super().__init__(body, classes="push")


class InfoMessage(_Bubble):
    """A friendly local UI notice."""

    def __init__(self, text: str, *, level: str = "info") -> None:
        marker, color = {
            "info": ("•", "#8fd3ff"),
            "ok": ("✓", "#6dff9d"),
            "warn": ("!", "#ffcf6d"),
        }.get(level, ("•", "#8fd3ff"))
        body = Text()
        body.append(f"{marker} ", style=f"bold {color}")
        body.append(text, style=color)
        super().__init__(body, classes=f"info {level}")


class ErrorMessage(_Bubble):
    """A transport/agent error."""

    def __init__(self, text: str) -> None:
        body = Text()
        body.append("⚠ ", style="bold #ff6d6d")
        body.append(text, style="#ff9d9d")
        super().__init__(body, classes="error")
