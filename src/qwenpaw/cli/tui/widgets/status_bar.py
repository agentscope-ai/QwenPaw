# -*- coding: utf-8 -*-
"""Top status bar: agent, model, session, token usage, busy state."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from ._anim import TICK, pulse, spinner

# Public field name -> internal attribute. Internal names are namespaced with
# ``_sb_`` so they never clash with Textual ``Widget`` internals (``_size``,
# ``size``, ``region`` ...).
_FIELDS = (
    "agent",
    "model",
    "session",
    "used",
    "size",
    "ctx_threshold",
    "tok_in",
    "tok_out",
    "tok_out_approx",
    "state",
    "qwenpaw_version",
)


def _fmt_count(n: int) -> str:
    """Compact, readable token count: ``842`` · ``6.4k`` · ``1.5M``.

    Exact below 1,000; abbreviated above so the bar stays tidy when a long
    session runs into the hundreds of thousands or millions of tokens.
    """
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{n / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"


# --- live context-usage bar -------------------------------------------------
# Renders e.g. ``  ctx [█████░╵░░] 650k / 1M`` into the status line.
# ``used``/``size`` are the *current* tokens-in-context and the model context
# window (distinct from the cumulative ``tok ↑↓`` tallies). A fixed 10-cell
# track shows how full the window is; the fill colour ramps green -> amber ->
# red with raw occupancy. When the auto-compaction ``threshold`` is known (it
# is user-configurable, so the agent reports it), a faint ``╵`` tick marks the
# cell where context starts getting evicted — watch the fill approach it. The
# tick is gated on the true ratio (not the rounded fill), so it stays visible
# right up to the threshold; once occupancy reaches it the tick is absorbed,
# and when compaction fires the bar simply shrinks. Every glyph is single-cell,
# so the fill area is always ``_CTX_BAR_WIDTH`` cells and ``line.cell_len``
# stays correct for the right-alignment math in ``_compose_line``.
_CTX_BAR_WIDTH = 10  # fill cells

_CTX_GREEN = "#6dff9d"  # plenty of headroom
_CTX_AMBER = "#ffcf6d"  # window filling up
_CTX_RED = "#ff6d6d"  # window nearly full
_CTX_TRACK = "#3a3a3a"  # unfilled track (dim, echoes version badge bg)
_CTX_MARK = "#6d6d6d"  # auto-compaction threshold tick on the empty track
_CTX_LABEL = "#8a8a8a"  # "ctx", brackets, "used / size" label


def _append_ctx_bar(
    line: Text,
    used: int,
    size: int,
    threshold: float = 0.0,
) -> None:
    """Append a compact context-usage bar to ``line`` (no-op if unknown).

    Degrades gracefully: appends nothing when the window or occupancy is
    unknown (``size == 0`` or ``used == 0``), so the surrounding layout and the
    right-alignment math are unchanged. The ratio is clamped to ``[0, 1]`` so a
    stale ``used > size`` renders a full bar instead of overflowing the
    fixed-width track. ``threshold`` (0-1) is the configured auto-compaction
    ratio; when in range and not yet reached, a ``╵`` tick marks that cell.
    ``threshold == 0`` (or out of range) renders no tick — e.g. compaction
    disabled, or the threshold is unknown.
    """
    if not used or not size:  # window or occupancy unknown -> show nothing
        return

    # Clamp to [0, 1] so a stale ``used > size`` can't overflow the track.
    ratio = used / size
    ratio = 0.0 if ratio < 0.0 else 1.0 if ratio > 1.0 else ratio

    # Colour by how full the window is.
    if ratio >= 0.85:
        color = _CTX_RED  # window nearly full
    elif ratio >= 0.6:
        color = _CTX_AMBER  # filling up
    else:
        color = _CTX_GREEN  # healthy headroom

    # Whole cells only. Round to nearest, but never show a live context as an
    # empty bar, and never overflow the fixed track.
    filled = int(ratio * _CTX_BAR_WIDTH + 0.5)
    if filled == 0:
        filled = 1
    elif filled > _CTX_BAR_WIDTH:
        filled = _CTX_BAR_WIDTH
    empty = _CTX_BAR_WIDTH - filled

    # Threshold marker cell, shown only while occupancy is still below it (gate
    # on the true ratio, not the rounded fill, so the tick doesn't vanish
    # early). ``filled <= mark`` then holds, keeping every repeat count
    # non-negative and the fill area exactly ``_CTX_BAR_WIDTH`` cells.
    mark = min(_CTX_BAR_WIDTH - 1, int(threshold * _CTX_BAR_WIDTH + 0.5))
    show_mark = 0.0 < threshold < 1.0 and ratio < threshold and filled <= mark

    line.append("  ctx ", style=_CTX_LABEL)
    line.append("[", style=_CTX_LABEL)
    if show_mark:
        line.append("█" * filled, style=color)
        line.append("░" * (mark - filled), style=_CTX_TRACK)
        line.append("╵", style=_CTX_MARK)
        line.append("░" * (_CTX_BAR_WIDTH - mark - 1), style=_CTX_TRACK)
    else:
        line.append("█" * filled, style=color)
        line.append("░" * empty, style=_CTX_TRACK)
    line.append("] ", style=_CTX_LABEL)
    line.append(f"{_fmt_count(used)} / {_fmt_count(size)}", style=_CTX_LABEL)


class StatusBar(Static):
    """A one-line header rendered from a few fields via :meth:`set`."""

    def __init__(self) -> None:
        self._frame = 0
        self._timer = None
        self._sb_agent = "default"
        self._sb_model = "—"
        self._sb_session = "—"
        self._sb_used = 0
        self._sb_size = 0
        self._sb_ctx_threshold = 0.0
        self._sb_tok_in = 0
        self._sb_tok_out = 0
        self._sb_tok_out_approx = False
        self._sb_state = "starting"
        self._sb_qwenpaw_version = "—"
        # Pass an initial renderable so the first arrange has a valid visual.
        super().__init__(self._compose_line(), classes="statusbar")

    def on_mount(self) -> None:
        self._timer = self.set_interval(TICK, self._tick)

    def _tick(self) -> None:
        if self._sb_state not in {
            "connecting",
            "starting",
            "warming",
            "waiting",
            "thinking",
            "interrupting",
        }:
            return
        self._frame += 1
        self.update(self._compose_line())

    def set(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            if key in _FIELDS and value is not None:
                setattr(self, f"_sb_{key}", value)
        # Only repaint once mounted; before that the __init__ renderable
        # stands in (and tests can read ``summary`` without an app).
        if self.is_mounted:
            self.update(self._compose_line())

    @property
    def summary(self) -> str:
        """Plain-text view of the bar (handy for tests)."""
        return self._compose_line().plain

    def _compose_line(self) -> Text:
        state_color = {
            "connecting": "#ffcf6d",
            "starting": "#ffcf6d",
            "warming": "#ffcf6d",
            "waiting": "#ffcf6d",
            "ready": "#6dff9d",
            "thinking": "#6db8ff",
            "interrupting": "#ffcf6d",
            "error": "#ff6d6d",
        }.get(self._sb_state, "#8a8a8a")

        line = Text()
        # Version badge — top-left (replaces the old "paw" badge).
        line.append(
            f" QwenPaw {self._sb_qwenpaw_version} ",
            style="bold on #2a2a3a",
        )
        line.append("  agent:", style="#8a8a8a")
        line.append(f"{self._sb_agent}", style="bold")
        line.append("  ", style="")
        line.append(f"{self._sb_model}", style="#b48cff")
        line.append("  session:", style="#8a8a8a")
        line.append(f"{str(self._sb_session)[:8]}", style="")
        # Live context-usage bar (replaces the old plain ``tokens:`` text).
        # No-op when used/size are unknown, so the right-alignment math below
        # is unaffected.
        _append_ctx_bar(
            line,
            self._sb_used,
            self._sb_size,
            self._sb_ctx_threshold,
        )
        if self._sb_tok_in or self._sb_tok_out:
            line.append("  tok", style="#8a8a8a")
            # Show input only once it's known (it can't be estimated live),
            # so it never flashes ``↑0`` while the first reply streams; the
            # confirmed total then carries forward across later turns.
            if self._sb_tok_in:
                line.append(
                    f" ↑{_fmt_count(self._sb_tok_in)}",
                    style="#7fb7d9",
                )
            if self._sb_tok_out:
                approx = "~" if self._sb_tok_out_approx else ""
                line.append(
                    f" ↓{approx}{_fmt_count(self._sb_tok_out)}",
                    style="#6dff9d",
                )
        if self._sb_state in {
            "connecting",
            "starting",
            "warming",
            "waiting",
            "thinking",
            "interrupting",
        }:
            glyph = spinner(self._frame)
            state_color = pulse(self._frame)
        elif self._sb_state == "error":
            glyph = "✗"
        else:
            glyph = "●"
        # State indicator — pushed to the right edge.
        right = Text()
        right.append(f"{glyph} {self._sb_state}", style=f"bold {state_color}")
        mounted = getattr(self, "_is_mounted", False)
        width = self.size.width if mounted else 0
        gap = max(3, width - line.cell_len - right.cell_len)
        line.append(" " * gap)
        line.append(right)
        return line
