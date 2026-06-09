# -*- coding: utf-8 -*-
"""Picker for resuming a previous session."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

from ..events import SessionSummary


def _relative_time(iso: str) -> str:
    """Render an ISO-8601 timestamp as a compact 'x ago' label."""
    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - when
    secs = int(delta.total_seconds())
    if secs < 0:
        secs = 0
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    return when.strftime("%Y-%m-%d")


class SessionPicker(ModalScreen[str | None]):
    """Pick a past session to resume. Dismisses with its ``session_id``."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    CSS = """
    SessionPicker {
        align: center middle;
        background: transparent;
    }
    #session-modal {
        width: 72%;
        height: 26;
        background: #101827;
        border: thick #68d391;
        padding: 1 2;
    }
    #session-title {
        height: 1;
        color: #d1ffe6;
    }
    #session-search {
        margin-top: 1;
    }
    #session-list {
        height: 1fr;
        margin-top: 1;
    }
    #session-help {
        height: 2;
        color: #9fb0c2;
    }
    """

    def __init__(self, sessions: list[SessionSummary]) -> None:
        super().__init__()
        self._sessions = sessions
        self.item_sessions: dict[str, SessionSummary] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="session-modal"):
            yield Static("Resume a previous session", id="session-title")
            yield Input(placeholder="Search by title", id="session-search")
            yield ListView(*self._session_items(), id="session-list")
            yield Static(
                "Enter resumes the highlighted session. Esc cancels.",
                id="session-help",
            )

    async def on_mount(self) -> None:
        self.query_one("#session-list", ListView).index = 0
        self.query_one("#session-search", Input).focus()

    def on_key(self, event: events.Key) -> None:
        # Search keeps focus for typing, so the single-line Input ignores
        # up/down (they bubble here) — route them to move the list selection.
        if event.key not in ("up", "down"):
            return
        session_list = self.query_one("#session-list", ListView)
        if event.key == "down":
            session_list.action_cursor_down()
        else:
            session_list.action_cursor_up()
        event.stop()
        event.prevent_default()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "session-search":
            return
        event.stop()
        await self._refresh(event.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "session-search":
            return
        event.stop()
        item = self.query_one("#session-list", ListView).highlighted_child
        if item is not None and item.id in self.item_sessions:
            self.dismiss(self.item_sessions[item.id].session_id)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if event.item.id in self.item_sessions:
            self.dismiss(self.item_sessions[event.item.id].session_id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def _refresh(self, query: str) -> None:
        session_list = self.query_one("#session-list", ListView)
        await session_list.clear()
        for item in self._session_items(query):
            await session_list.append(item)
        session_list.index = 0 if session_list.children else None

    def _session_items(self, query: str = "") -> list[ListItem]:
        self.item_sessions = {}
        needle = query.casefold().strip()
        matches = [
            session
            for session in self._sessions
            if needle in session.title.casefold()
        ]
        if not matches:
            message = (
                "No sessions match" if needle else "No previous sessions yet"
            )
            return [ListItem(Static(message), disabled=True)]
        items: list[ListItem] = []
        for index, session in enumerate(matches):
            item_id = f"session-{index}"
            self.item_sessions[item_id] = session
            label = Text()
            label.append(session.title or "(untitled)", style="bold #d1ffe6")
            when = _relative_time(session.updated_at)
            if when:
                label.append(f"   {when}", style="#9fb0c2")
            items.append(ListItem(Static(label), id=item_id))
        return items
