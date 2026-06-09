# -*- coding: utf-8 -*-
"""Transcript message widgets (user / assistant / thinking / errors)."""

from __future__ import annotations

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Collapsible, Markdown, Static

from ._anim import TICK, pulse, spinner


class _Bubble(Static):
    """A rounded message card.

    The fill is transparent so the bubble blends into the static background; a
    rounded border outlines it. The background no longer animates, so
    transparency is safe — there is nothing to re-blend against each frame, and
    the rounded corners simply show the background.
    """

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
    ) -> None:
        # ``_frame`` is fixed at 0: the logo colour is static (no animation),
        # so the gradient is a fixed vertical wash with the embossed shading.
        self._frame = 0
        self._accent = accent
        self._gradient_stops = (
            "#bfe1ff",
            "#8fd7ff",
            "#c8b6ff",
            "#ffd08a",
        )
        if palette is not None:
            self._set_palette_colors(palette)
        super().__init__(self._render_body(), classes="msg welcome")

    def set_palette(
        self, palette: tuple[str, str, str], accent: str | None = None
    ) -> None:
        if accent is not None:
            self._accent = accent
        self._set_palette_colors(palette)
        self.update(self._render_body())

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
        return body

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


def _mix_hex(left: str, right: str, amount: float) -> str:
    left_rgb = _hex_to_rgb(left)
    right_rgb = _hex_to_rgb(right)
    mixed = tuple(
        round(a + (b - a) * amount)
        for a, b in zip(left_rgb, right_rgb, strict=True)
    )
    return "#{:02x}{:02x}{:02x}".format(*mixed)


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
        if not params:
            return ""
        first = params.strip().splitlines()[0].strip()
        return first[:72] + " ..." if len(first) > 72 else first


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
