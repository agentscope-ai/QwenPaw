# -*- coding: utf-8 -*-
"""Theme gallery picker."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

from ..themes import THEME_GALLERY, ThemeInfo


class ThemePicker(ModalScreen[ThemeInfo | str | None]):
    """Pick a named theme or type a custom prompt."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    ThemePicker {
        align: center middle;
        background: transparent;
    }
    #theme-modal {
        width: 72%;
        height: 26;
        background: #101827;
        border: thick #ff7ad9;
        padding: 1 2;
    }
    #theme-title {
        height: 1;
        color: #ffd1f1;
    }
    #theme-search {
        margin-top: 1;
    }
    #theme-list {
        height: 1fr;
        margin-top: 1;
    }
    #theme-help {
        height: 2;
        color: #9fb0c2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.item_themes: dict[str, ThemeInfo] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-modal"):
            yield Static("Pick a QwenPaw vibe", id="theme-title")
            yield Input(
                placeholder="Search or type a custom theme prompt",
                id="theme-search",
            )
            yield ListView(*self._theme_items(), id="theme-list")
            yield Static(
                "Enter selects. Type anything for a custom generated palette.",
                id="theme-help",
            )

    async def on_mount(self) -> None:
        self.query_one("#theme-list", ListView).index = 0
        self.query_one("#theme-search", Input).focus()

    def on_key(self, event: events.Key) -> None:
        # Search keeps focus for typing, so the single-line Input ignores
        # up/down (they bubble here) — route them to move the list selection.
        if event.key not in ("up", "down"):
            return
        theme_list = self.query_one("#theme-list", ListView)
        if event.key == "down":
            theme_list.action_cursor_down()
        else:
            theme_list.action_cursor_up()
        event.stop()
        event.prevent_default()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "theme-search":
            return
        event.stop()
        await self._refresh(event.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "theme-search":
            return
        event.stop()
        item = self.query_one("#theme-list", ListView).highlighted_child
        if item and item.id in self.item_themes:
            self.dismiss(self.item_themes[item.id])
            return
        value = event.value.strip()
        self.dismiss(value if value else None)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if event.item.id in self.item_themes:
            self.dismiss(self.item_themes[event.item.id])

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def _refresh(self, query: str) -> None:
        theme_list = self.query_one("#theme-list", ListView)
        await theme_list.clear()
        for item in self._theme_items(query):
            await theme_list.append(item)
        theme_list.index = 0 if theme_list.children else None

    def _theme_items(self, query: str = "") -> list[ListItem]:
        self.item_themes = {}
        needle = query.casefold().strip()
        themes = [
            theme
            for theme in THEME_GALLERY
            if needle in theme.name.casefold()
            or needle in theme.id.casefold()
            or needle in theme.prompt.casefold()
        ]
        if not themes:
            return [
                ListItem(
                    Static("Use Enter for a custom prompt"),
                    disabled=True,
                ),
            ]
        items: list[ListItem] = []
        for index, theme in enumerate(themes):
            item_id = f"theme-{index}"
            self.item_themes[item_id] = theme
            label = Text()
            label.append(f"{theme.emoji}  ", style=theme.accent)
            label.append(theme.name, style=f"bold {theme.accent}")
            label.append(f"  /theme {theme.id}", style="#9fb0c2")
            items.append(ListItem(Static(label), id=item_id))
        return items
