# -*- coding: utf-8 -*-
"""Slash-command auto-suggestion: an inline ghost completion plus a
filtered dropdown list.

The agent advertises its commands over ACP (``available_commands_update``);
:class:`CommandSuggester` drives the single inline ghost completion on the
``TextArea`` and :class:`CommandMenu` renders the navigable dropdown. Both
share the same command list, set via :meth:`set_commands`.
"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.suggester import Suggester
from textual.widgets import OptionList, TextArea
from textual.widgets.option_list import Option

from ..events import SlashCommand


def _query(value: str) -> str | None:
    """The command prefix being typed, or ``None`` if not applicable.

    The menu suggests whole slash-command lines, not only command names, so
    arguments can be completed too (``/theme cy`` → ``/theme cyberpunk``).
    """
    if not value.startswith("/"):
        return None
    return value[1:].lstrip()


def _matches(commands: list[SlashCommand], query: str) -> list[SlashCommand]:
    q = query.lower()
    if " " not in q:
        return [
            c
            for c in commands
            if " " not in c.name and c.name.lower().startswith(q)
        ]
    return [c for c in commands if c.name.lower().startswith(q)]


class CommandSuggester(Suggester):
    """Inline ghost completion for the top matching command."""

    def __init__(self) -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self._commands: list[SlashCommand] = []

    def set_commands(self, commands: list[SlashCommand]) -> None:
        self._commands = list(commands)

    async def get_suggestion(self, value: str) -> str | None:
        query = _query(value)
        if not query:  # empty query → nothing to complete yet
            return None
        hits = _matches(self._commands, query)
        return f"/{hits[0].name}" if hits else None


class CommandMenu(OptionList):
    """Dropdown of matching commands, navigated from the focused input.

    Focus stays on the ``TextArea``; the owning app routes ↑/↓/⏎/⇥/esc here
    via :meth:`cursor_up`, :meth:`cursor_down` and :attr:`selected`.
    """

    # The input keeps focus so typing continues uninterrupted.
    can_focus = False

    DEFAULT_CSS = """
    CommandMenu {
        layer: overlay;
        dock: bottom;
        height: auto;
        max-height: 9;
        margin: 0 2 4 2;
        border: round #ff7ad9;
        background: #101827 92%;
        display: none;
    }
    CommandMenu > .option-list--option-highlighted {
        background: #2b1741;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="cmd-menu")
        self._commands: list[SlashCommand] = []

    def set_commands(self, commands: list[SlashCommand]) -> None:
        self._commands = list(commands)

    def update_for(self, value: str) -> None:
        """Refilter and show/hide the dropdown for the current input."""
        query = _query(value)
        hits = _matches(self._commands, query) if query is not None else []
        if query is not None and " " in query:
            normalized = query.rstrip().lower()
            if any(cmd.name.lower() == normalized for cmd in hits):
                self.display = False
                return
        if not hits:
            self.display = False
            return
        self.clear_options()
        for cmd in hits:
            label = Text()
            label.append(f"/{cmd.name}", style="bold #b48cff")
            if cmd.description:
                label.append(f"  {cmd.description}", style="#8a8a8a")
            self.add_option(Option(label, id=cmd.name))
        self.highlighted = 0
        self.display = True

    @property
    def selected(self) -> str | None:
        """The highlighted command name, or ``None`` when empty."""
        if not self.display or self.highlighted is None:
            return None
        return self.get_option_at_index(self.highlighted).id

    def cursor_up(self) -> None:
        self.action_cursor_up()

    def cursor_down(self) -> None:
        self.action_cursor_down()


class PromptInput(TextArea):
    """The chat input, wired to drive an open :class:`CommandMenu`.

    ``_on_key`` runs before ``TextArea``'s own bindings, so intercepting the
    navigation keys here (and stopping them) keeps ⏎/⇥/↑/↓/esc from reaching
    submit, focus-change or interrupt while the dropdown is open.
    """

    def __init__(self, menu: CommandMenu, **kwargs) -> None:
        super().__init__(**kwargs)
        self._menu = menu
        self._ignore_change_events = 0
        self._suppress_paste_tail = ""

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, text: str) -> None:
        self.text = text

    def set_programmatic_value(
        self,
        text: str,
        *,
        cursor_end: bool = False,
    ) -> None:
        self._ignore_change_events += 1
        self.text = text
        if cursor_end:
            self.move_cursor(self.document.end)

    def consume_programmatic_change(self) -> bool:
        if self._ignore_change_events <= 0:
            return False
        self._ignore_change_events -= 1
        return True

    # pylint: disable-next=too-many-return-statements
    async def _on_key(self, event: events.Key) -> None:
        if self._consume_suppressed_paste_tail(event):
            return
        if await self._route_permission_key(event):
            return

        if self._menu.display:
            if event.key == "down":
                self._menu.cursor_down()
            elif event.key == "up":
                self._menu.cursor_up()
            elif event.key == "escape":
                self._menu.display = False
            elif event.key in ("enter", "tab"):
                name = self._menu.selected
                if name is None:
                    return
                self.set_programmatic_value(f"/{name} ", cursor_end=True)
                self._menu.display = False
            else:
                await super()._on_key(event)
                return
            event.prevent_default()
            event.stop()
            return

        app = self.app
        if event.key == "up" and not self.value:
            event.prevent_default()
            event.stop()
            await app.action_recall_queued()
            return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            await app._submit_prompt()  # pylint: disable=protected-access
            return
        if event.key in {"shift+enter", "ctrl+j"}:
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)

    async def _route_permission_key(self, event: events.Key) -> bool:
        app = self.app
        if not getattr(app, "_permission_active", lambda: False)():
            return False
        if event.key not in ("down", "up", "enter", "tab", "escape"):
            return False
        event.prevent_default()
        event.stop()
        await app._handle_permission_key(  # pylint: disable=protected-access
            event.key,
        )
        return True

    async def _on_paste(self, event: events.Paste) -> None:
        app = self.app
        handler = getattr(app, "_handle_prompt_paste", None)
        if handler is None:
            await super()._on_paste(event)
            return
        event.stop()
        event.prevent_default()
        replacement = await handler(event.text)
        if replacement is None:
            if result := self._replace_via_keyboard(
                event.text,
                *self.selection,
            ):
                self.move_cursor(result.end_location)
                self.focus()
            return
        self._suppress_paste_tail = event.text
        if result := self._replace_via_keyboard(replacement, *self.selection):
            self.move_cursor(result.end_location)
            self.focus()

    def _consume_suppressed_paste_tail(self, event: events.Key) -> bool:
        if not self._suppress_paste_tail:
            return False
        character = getattr(event, "character", None)
        if character and self._suppress_paste_tail.startswith(character):
            self._suppress_paste_tail = self._suppress_paste_tail[
                len(character) :
            ]
            event.stop()
            event.prevent_default()
            return True
        self._suppress_paste_tail = ""
        return False
