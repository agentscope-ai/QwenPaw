# -*- coding: utf-8 -*-
"""Modal overlay for tool-permission requests."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ..events import PermissionRequest

# allow_* kinds get a positive button, reject_* a negative one.
_VARIANT = {
    "allow_once": "success",
    "allow_always": "success",
    "reject_once": "error",
    "reject_always": "error",
}


class PermissionModal(ModalScreen[str | None]):
    """Asks the user to approve/deny a tool call.

    Dismisses with the chosen ``option_id`` or ``None`` (deny/escape).
    """

    BINDINGS = [("escape", "deny", "Deny")]

    DEFAULT_CSS = """
    PermissionModal { align: center middle; }
    PermissionModal > Vertical {
        width: 64; height: auto; padding: 1 2;
        border: round #b48cff; background: $surface;
    }
    PermissionModal .ptitle { text-style: bold; margin-bottom: 1; }
    PermissionModal .pkind { color: #8a8a8a; margin-bottom: 1; }
    PermissionModal Button { width: 100%; margin-bottom: 1; }
    """

    def __init__(self, request: PermissionRequest) -> None:
        super().__init__()
        self._request = request

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"🔐 {self._request.title}", classes="ptitle")
            if self._request.tool_kind:
                yield Static(
                    f"kind: {self._request.tool_kind}",
                    classes="pkind",
                )
            for option in self._request.options:
                yield Button(
                    option.name,
                    variant=_VARIANT.get(option.kind, "default"),
                    id=f"opt-{option.option_id}",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        option_id = str(event.button.id or "").removeprefix("opt-")
        self.dismiss(option_id or None)

    def action_deny(self) -> None:
        self.dismiss(None)
