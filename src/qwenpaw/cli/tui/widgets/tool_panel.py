# -*- coding: utf-8 -*-
"""Collapsible tool-call panel (merges start + update by tool_call_id).

The panel is expanded while the tool is pending/running so the user can watch
it, then auto-collapses to a one-line summary once it completes or fails. The
header (status, title, params summary) stays visible; the body (params +
output) can be re-opened on demand.
"""

from __future__ import annotations

from rich.text import Text
from textual.content import Content
from textual.widgets import Collapsible, Static

from ._anim import TICK, pulse, spinner

_STATUS_GLYPH = {
    "pending": ("◌", "#8a8a8a"),
    "in_progress": ("◍", "#6db8ff"),
    "completed": ("●", "#6dff9d"),
    "failed": ("✗", "#ff6d6d"),
}

_TERMINAL = ("completed", "failed")


class ToolPanel(Collapsible):
    """One tool call. Updated in place as ACP sends progress events."""

    def __init__(
        self,
        tool_call_id: str,
        title: str,
        kind: str | None = None,
        params: str | None = None,
    ) -> None:
        self._id = tool_call_id
        self._title_text = title or "tool"
        self._kind = kind
        self._params = params
        self._status = "pending"
        self._output: str | None = None
        self._frame = 0
        self._timer = None
        self._body = Static(self._render_body())
        super().__init__(
            self._body,
            title=self._render_title(),
            collapsed=False,
            classes="tool",
        )

    def on_mount(self) -> None:
        # Animate the status glyph while the tool is still running.
        self._timer = self.set_interval(TICK, self._tick)

    def _tick(self) -> None:
        if self._status in _TERMINAL:
            if self._timer is not None:
                self._timer.stop()
                self._timer = None
            return
        self._frame += 1
        self.title = self._render_title()

    def update_call(
        self,
        *,
        title: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        output: str | None = None,
        params: str | None = None,
    ) -> None:
        prev = self._status
        if title:
            self._title_text = title
        if kind:
            self._kind = kind
        if status:
            self._status = status
        if output is not None:
            self._output = output
        if params is not None:
            self._params = params
        self.title = self._render_title()
        self._body.update(self._render_body())
        # Auto-collapse once on the transition to a terminal state; leave the
        # user free to re-open it afterwards, and stop the spinner.
        if self._status in _TERMINAL and prev not in _TERMINAL:
            self.collapsed = True
            if self._timer is not None:
                self._timer.stop()
                self._timer = None

    @property
    def is_done(self) -> bool:
        """True once the tool has finished (completed or failed)."""
        return self._status in _TERMINAL

    def _label(self) -> str:
        """Best available name for the tool.

        The ACP ``title`` is the ideal label, but some agents leave it empty
        (so it falls back to the generic ``"tool"``). In that case the tool
        ``kind`` (read / execute / search / …) is far more informative.
        """
        title = (self._title_text or "").strip()
        if title and title.lower() != "tool":
            return title
        return self._kind or "tool"

    def _summary(self) -> str:
        """A compact one-line gist of the params (e.g. the actual command)."""
        if not self._params:
            return ""
        first = self._params.strip().splitlines()[0].strip()
        return first[:72] + " …" if len(first) > 72 else first

    def _render_title(self) -> Content:
        # The glyph + colour already encode status, so we drop the redundant
        # "completed" word and surface the param summary instead — that's what
        # actually tells finished tools apart in the collapsed list.
        if self._status in _TERMINAL:
            glyph, color = _STATUS_GLYPH.get(self._status, ("◌", "#8a8a8a"))
        else:
            # Running: animated spinner + pulsing colour.
            glyph, color = spinner(self._frame), pulse(self._frame)
        parts: list[object] = [
            (f"{glyph} ", f"bold {color}"),
            "🔧 ",
            (self._label(), "bold"),
        ]
        summary = self._summary()
        if summary:
            parts.append(("  " + summary, "#7fb7d9"))
        return Content.assemble(*parts)

    def _render_body(self) -> Text:
        segments: list[Text] = []
        if self._params:
            params = self._params.strip()
            if len(params) > 600:
                params = params[:600] + " …"
            segments.append(Text(params, style="#7fb7d9"))
        if self._output:
            snippet = self._output.strip()
            if len(snippet) > 600:
                snippet = snippet[:600] + " …"
            segments.append(Text(snippet, style="#b0b0b0"))
        if not segments:
            return Text("(no output)", style="#5a5a5a")
        out = Text()
        for i, seg in enumerate(segments):
            if i:
                out.append("\n")
            out.append_text(seg)
        return out
