# -*- coding: utf-8 -*-
"""Inline overlay for tool-permission requests."""

from __future__ import annotations

import math
import time

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..events import PermissionRequest

_MAX_PARAM_LINES = 6
_MAX_PARAM_COLUMNS = 120
_TITLE_OPTION_ID = "__permission_title"
_IMPORTANT_PARAM_LABELS = {
    "command": "Command",
    "approve_exact_target": "Exact Target",
    "approve_pattern_target": "Pattern Target",
    "path": "Path",
    "file_path": "Path",
}


class PermissionOverlay(OptionList):
    """Selectable approval prompt shown above the chat input."""

    can_focus = True

    DEFAULT_CSS = """
    PermissionOverlay {
        layer: overlay;
        dock: bottom;
        height: auto;
        max-height: 12;
        margin: 0 0 4 0;
        border: round #ffcf6d;
        background: #101827 96%;
        display: none;
    }
    PermissionOverlay > .option-list--option-disabled {
        color: #9ca3af;
    }
    PermissionOverlay > .option-list--option-highlighted {
        background: #25371f;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="permission-overlay")
        self._request: PermissionRequest | None = None
        self._option_ids: set[str] = set()
        self._last_countdown: str | None = None
        self._countdown_timer = None

    @property
    def request(self) -> PermissionRequest | None:
        return self._request

    @property
    def selected(self) -> str | None:
        if not self.display or self.highlighted is None:
            return None
        option_id = self.get_option_at_index(self.highlighted).id
        return option_id if option_id in self._option_ids else None

    @property
    def deny_option_id(self) -> str | None:
        if self._request is None:
            return None
        for option in self._request.options:
            if option.kind.startswith("reject"):
                return option.option_id
        return None

    def show_request(self, request: PermissionRequest) -> None:
        self._request = request
        self._option_ids = {option.option_id for option in request.options}
        self.clear_options()

        self._last_countdown = None
        self.add_option(
            Option(
                self._title_text(request),
                id=_TITLE_OPTION_ID,
                disabled=True,
            ),
        )
        if request.tool_kind:
            self.add_option(
                Option(
                    _labeled_text("Action", request.tool_kind),
                    disabled=True,
                ),
            )
        if request.params:
            self.add_option(
                Option(
                    Text("Review target", style="bold #8fd3ff"),
                    disabled=True,
                ),
            )
            for line in _param_lines(request.params):
                self.add_option(
                    Option(_param_text(line), disabled=True),
                )
        if request.options:
            self.add_option(
                Option(
                    Text(
                        "Choose a session-scoped action",
                        style="#9ca3af",
                    ),
                    disabled=True,
                ),
            )

        for option in request.options:
            label = Text(option.name or option.option_id)
            if option.kind.startswith("allow"):
                label.stylize("bold #6dff9d")
            elif option.kind.startswith("reject"):
                label.stylize("bold #ff6d6d")
            else:
                label.stylize("bold")
            self.add_option(Option(label, id=option.option_id))

        self.display = True
        self.highlighted = self._first_action_index()
        self._start_countdown_timer()

    def clear_request(self) -> None:
        self._stop_countdown_timer()
        self._request = None
        self._option_ids.clear()
        self._last_countdown = None
        self.clear_options()
        self.display = False

    def refresh_countdown(self) -> None:
        request = self._request
        if request is None or request.expires_at is None or not self.display:
            return
        countdown = self._countdown_text(request.expires_at)
        if countdown == self._last_countdown:
            return
        self._last_countdown = countdown
        self.replace_option_prompt(
            _TITLE_OPTION_ID,
            self._title_text(request),
        )
        if countdown == "expired":
            self._stop_countdown_timer()

    def cursor_up(self) -> None:
        self.action_cursor_up()

    def cursor_down(self) -> None:
        self.action_cursor_down()

    def _first_action_index(self) -> int | None:
        for index in range(len(self.options)):
            if self.get_option_at_index(index).id in self._option_ids:
                return index
        return None

    def _title_text(self, request: PermissionRequest) -> Text:
        title = Text("Approval required", style="bold #ffcf6d")
        if request.expires_at is not None:
            countdown = self._countdown_text(request.expires_at)
            self._last_countdown = countdown
            style = "#ffcf6d" if countdown != "expired" else "bold #ff6d6d"
            title.append(" (", style="#8a8a8a")
            title.append(countdown, style=style)
            title.append(")", style="#8a8a8a")
        title.append(": ", style="bold #ffcf6d")
        title.append(request.title, style="bold")
        return title

    @staticmethod
    def _countdown_text(expires_at: float) -> str:
        remaining = math.ceil(expires_at - time.time())
        if remaining <= 0:
            return "expired"
        minutes, seconds = divmod(remaining, 60)
        if minutes:
            return f"expires in {minutes}m{seconds:02d}s"
        return f"expires in {seconds}s"

    def _start_countdown_timer(self) -> None:
        self._stop_countdown_timer()
        if self._request is None or self._request.expires_at is None:
            return
        self._countdown_timer = self.set_interval(
            1.0,
            self.refresh_countdown,
        )

    def _stop_countdown_timer(self) -> None:
        if self._countdown_timer is not None:
            self._countdown_timer.stop()
            self._countdown_timer = None


def _param_lines(params: str) -> list[str]:
    lines = [line.strip() for line in params.splitlines() if line.strip()]
    if not lines:
        return []
    truncated = [_truncate_line(line) for line in lines[:_MAX_PARAM_LINES]]
    omitted = len(lines) - len(truncated)
    if omitted > 0:
        truncated.append(f"... {omitted} more line(s)")
    return truncated


def _truncate_line(line: str) -> str:
    if len(line) <= _MAX_PARAM_COLUMNS:
        return line
    return line[: _MAX_PARAM_COLUMNS - 3] + "..."


def _labeled_text(label: str, value: str) -> Text:
    text = Text()
    text.append(f"{label}: ", style="bold #8fd3ff")
    text.append(_truncate_line(value), style="bold #d8dee9")
    return text


def _param_text(line: str) -> Text:
    if line.startswith("..."):
        return Text(line, style="#9ca3af")
    key, separator, value = line.partition(":")
    if not separator:
        return Text(_truncate_line(line), style="#d8dee9")

    normalized = key.strip()
    label = _IMPORTANT_PARAM_LABELS.get(
        normalized,
        normalized.replace("_", " ").title(),
    )
    value = value.strip()

    label_style = "bold #8fd3ff"
    value_style = "#d8dee9"
    if normalized == "command":
        label_style = "bold #ffcf6d"
        value_style = "bold #f8f8f2"
    elif normalized == "approve_pattern_target":
        label_style = "bold #b48cff"
        value_style = "bold #d8dee9"
    elif normalized == "approve_exact_target":
        label_style = "bold #8fd3ff"
        value_style = "bold #d8dee9"

    text = Text()
    text.append(f"{label}: ", style=label_style)
    text.append(_truncate_line(value), style=value_style)
    return text
