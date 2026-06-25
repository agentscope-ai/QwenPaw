# -*- coding: utf-8 -*-
"""Inline overlay for tool-permission requests."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..events import PermissionRequest

_MAX_PARAM_LINES = 6
_MAX_PARAM_COLUMNS = 120


class PermissionOverlay(OptionList):
    """Selectable approval prompt shown above the chat input."""

    can_focus = False

    DEFAULT_CSS = """
    PermissionOverlay {
        layer: overlay;
        dock: bottom;
        height: auto;
        max-height: 12;
        margin: 0 2 4 2;
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

        title = Text("Approval required: ", style="bold #ffcf6d")
        title.append(request.title, style="bold")
        self.add_option(Option(title, disabled=True))
        if request.tool_kind:
            self.add_option(
                Option(
                    Text(f"kind: {request.tool_kind}", style="#8a8a8a"),
                    disabled=True,
                ),
            )
        if request.params:
            self.add_option(
                Option(Text("parameters", style="#8a8a8a"), disabled=True),
            )
            for line in _param_lines(request.params):
                self.add_option(
                    Option(Text(line, style="#d8dee9"), disabled=True),
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

    def clear_request(self) -> None:
        self._request = None
        self._option_ids.clear()
        self.clear_options()
        self.display = False

    def cursor_up(self) -> None:
        self.action_cursor_up()

    def cursor_down(self) -> None:
        self.action_cursor_down()

    def _first_action_index(self) -> int | None:
        for index in range(len(self.options)):
            if self.get_option_at_index(index).id in self._option_ids:
                return index
        return None


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
