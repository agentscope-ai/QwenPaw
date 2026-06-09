# -*- coding: utf-8 -*-
"""The paw terminal chat application (Textual)."""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import os
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import TextArea

from .__version__ import __version__
from .events import (
    AvailableCommands,
    BackendWarmed,
    Connected,
    PermissionRequest,
    PlanUpdate,
    PushMessage,
    SessionSummary,
    SessionTitle,
    SlashCommand,
    TextDelta,
    ThoughtDelta,
    TokenUsage,
    ToolCall,
    TransportError,
    TurnEnded,
    Usage,
    UserTurn,
)
from .paths import state_dir
from .themes import (
    THEME_GALLERY,
    ThemeInfo,
    accent_for_prompt,
    find_theme,
    mix_hex,
    palette_for_prompt,
)
from .transport.base import TuiTransport
from .widgets import (
    ActivityLine,
    AgentLabel,
    AssistantMessage,
    CommandMenu,
    CommandSuggester,
    ErrorMessage,
    FileLinkBox,
    InfoMessage,
    PermissionModal,
    PromptInput,
    PushMessageBox,
    QueuedMessage,
    SessionPicker,
    StatusBar,
    ThemePicker,
    ThoughtMessage,
    ToolPanel,
    UserMessage,
    WelcomeMessage,
)


class PawApp(App):
    """Streaming chat over a :class:`TuiTransport` (ACP)."""

    CSS = """
    Screen {
        layers: base overlay;
        background: #12202a;
        color: $text;
    }
    .statusbar {
        layer: base;
        dock: top;
        height: 1;
        background: #183246 92%;
        color: $text;
    }
    #transcript { padding: 1 2 4 2; background: transparent; }
    /* Messages are transparent 'bubbles': the fill matches the static screen
       background, so the text and bubble blend into the overall background and
       only a subtle rounded border outlines each one. The background no longer
       animates, so transparency is safe — there is nothing to re-blend against
       each frame. */
    .msg {
        height: auto; margin-bottom: 1; padding: 0 1; color: $text;
        background: transparent; border: round $bubble-border;
    }
    .msg.user, .msg.queued {
        width: auto; max-width: 100%; border: round $bubble-user-border;
    }
    .msg.assistant { padding: 0; }
    .msg.assistant > Markdown { background: transparent; padding: 0 1; }
    .msg.assistant > Markdown > *:last-child { margin-bottom: 0; }
    .msg.welcome {
        margin: 1 0 2 0; padding: 1 2;
        background: transparent; border: none;
    }
    /* One agent label per turn, sitting tight above the activity below it. */
    .agentlabel { height: 1; margin: 0 0 0 1; }
    /* Tool calls + thinking are Collapsible widgets; transparent with a
       rounded outline like the other bubbles. */
    .tool, .msg.thought {
        height: auto; padding: 0; margin: 0 0 1 0;
        background: transparent; border: round $bubble-border;
    }
    .tool > CollapsibleTitle, .msg.thought > CollapsibleTitle {
        padding: 0 1; background: transparent;
    }
    .tool Contents, .msg.thought Contents {
        padding: 0 1; background: transparent;
    }
    .msg.activity { height: auto; }
    .tool.hidden, .msg.thought.hidden, .msg.activity.hidden {
        display: none;
    }
    .msg.info { margin-bottom: 0; }
    #prompt {
        layer: base;
        dock: bottom;
        border: round #68d391;
        background: #182433 94%;
        height: 3;
        max-height: 10;
    }
    #prompt:focus { border: round #ffcf6d; }
    """

    BINDINGS = [
        Binding("escape", "interrupt", "Cancel/interrupt", show=True),
        Binding("up", "recall_queued", "Edit queued", show=False),
        # Kept functional for power users but no longer advertised in the
        # input bar — the glyph was unfamiliar to most users.
        Binding("ctrl+t", "toggle_tools", "Hide/show tools", show=False),
        Binding("ctrl+i", "toggle_inspection", "Inspect", show=True),
        Binding("ctrl+c", "quit", "Quit", show=True, priority=True),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
    ]

    def __init__(
        self,
        transport: TuiTransport,
        *,
        agent: str = "default",
        target: str | None = None,
        resume_session_id: str | None = None,
    ) -> None:
        super().__init__()
        self._transport = transport
        self._agent = agent
        self._target = target
        # When launched with --resume, the transport opens this session and
        # replays its history; skip the welcome banner so the two don't mix.
        self._resume_session_id = resume_session_id
        self._assistant: AssistantMessage | None = None
        self._thought: ThoughtMessage | None = None
        self._activity: ActivityLine | None = None
        # Whether the "qwenpaw" label has been shown for the current turn.
        self._labeled = False
        self._tools: dict[str, ToolPanel] = {}
        self._tools_hidden = False
        self._inspection_mode = False
        self._busy = False
        self._backend_warmed = False
        self._awaiting_backend_update = False
        # Per-turn flags so a turn that produces nothing the user can see (a
        # silent backend failure, e.g. an unusable model) reports an error
        # instead of quietly returning to "ready". ``_turn_saw_error`` avoids a
        # duplicate "no response" message when a TransportError already showed.
        self._turn_saw_output = False
        self._turn_saw_error = False
        # Messages typed while the agent is busy wait here (FIFO) and are sent
        # automatically as each turn ends. Each entry pairs the text with its
        # dimmed transcript widget so it can be removed when sent or recalled.
        self._queued: list[tuple[str, QueuedMessage]] = []
        # (tool_call_id, uri) pairs already surfaced as a FileLinkBox, so a
        # repeated tool update doesn't mount the same link twice.
        self._file_links_seen: set[tuple[str, str]] = set()
        # Running token totals for the session (summed across LLM calls).
        # ``_tok_out`` is the confirmed output total; ``_stream_chars`` counts
        # characters streamed since the last confirmed usage, for a live
        # (approximate) output-token estimate while a call is in flight.
        self._tok_in = 0
        self._tok_out = 0
        self._stream_chars = 0
        self._suggester = CommandSuggester()
        self._menu = CommandMenu()
        self._agent_commands: list[SlashCommand] = []
        self._local_commands = _local_commands()
        # Recent resumable sessions, surfaced as `/resume <id>` auto-suggest
        # entries (populated from the backend once connected).
        self._recent_sessions: list[SessionSummary] = []
        self._session_commands: list[SlashCommand] = []
        self._set_command_catalog()
        # The model QwenPaw reports it is using (read-only, for the status bar
        # and error messages). paw does not select or configure models.
        self._model = ""
        self._theme_prompt = self._load_theme_prompt()

    # -- layout --------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield StatusBar(tui_version=__version__)
        yield VerticalScroll(id="transcript")
        yield self._menu
        yield PromptInput(
            self._menu,
            placeholder=(
                "type a message  "
                "(/ commands · enter send/queue · shift+enter newline · "
                "paste files/long text)"
            ),
            id="prompt",
            show_line_numbers=False,
            soft_wrap=True,
        )

    async def on_mount(self) -> None:
        self.query_one("#prompt", PromptInput).focus()
        self._status().set(agent=self._agent)
        self._apply_theme_prompt(self._theme_prompt, notify=False)
        if self._resume_session_id is not None:
            await self._mount(
                InfoMessage("Resumed previous session — replaying history…")
            )
        else:
            await self._mount(
                WelcomeMessage(
                    palette_for_prompt(self._theme_prompt),
                    accent_for_prompt(self._theme_prompt),
                )
            )
        self._consume()

    # -- helpers -------------------------------------------------------------
    def _status(self) -> StatusBar:
        return self.query_one(StatusBar)

    def _transcript(self) -> VerticalScroll:
        return self.query_one("#transcript", VerticalScroll)

    def _set_command_catalog(self) -> None:
        seen: set[str] = set()
        commands: list[SlashCommand] = []
        for command in [
            *self._local_commands,
            *self._session_commands,
            *self._agent_commands,
        ]:
            if command.name in seen:
                continue
            seen.add(command.name)
            commands.append(command)
        self._suggester.set_commands(commands)
        self._menu.set_commands(commands)

    # Cap for the `/resume` auto-suggest list (most recent N chats).
    _RECENT_SESSION_LIMIT = 10

    def _set_recent_sessions(self, sessions: list[SessionSummary]) -> None:
        """Refresh the `/resume <id>` auto-suggest entries (most recent N).

        Each becomes a ``resume <short-id>`` command whose description is the
        session title, so it surfaces in the menu exactly like ``/theme <id>``.
        """
        self._recent_sessions = list(sessions[: self._RECENT_SESSION_LIMIT])
        self._session_commands = [
            SlashCommand(
                f"resume {session.session_id[:8]}",
                session.title or "(untitled)",
            )
            for session in self._recent_sessions
        ]
        self._set_command_catalog()

    @work(group="recent-sessions", exclusive=True)
    async def _refresh_recent_sessions(self) -> None:
        """Pull recent sessions from the backend for the auto-suggest list."""
        try:
            sessions = await self._transport.list_sessions()
        except Exception:  # noqa: BLE001 - best-effort; suggestions are extra
            return
        self._set_recent_sessions(sessions)

    async def _mount(self, widget) -> None:
        await self._transcript().mount(widget)
        self._scroll_transcript_end()

    def _scroll_transcript_end(self, *, defer: bool = False) -> None:
        if defer:
            self.call_after_refresh(
                lambda: self._transcript().scroll_end(animate=False)
            )
            return
        self._transcript().scroll_end(animate=False)

    async def _ensure_activity_line(self) -> ActivityLine:
        await self._ensure_turn_label()
        if self._activity is None:
            self._activity = ActivityLine()
            self._apply_activity_visibility()
            await self._mount(self._activity)
        return self._activity

    def _apply_activity_visibility(self) -> None:
        for activity in self.query(ActivityLine):
            activity.set_class(self._inspection_mode, "hidden")
        if self._activity is not None:
            self._activity.set_class(self._inspection_mode, "hidden")

    def _apply_thought_visibility(self, thought: ThoughtMessage) -> None:
        thought.collapsed = not self._inspection_mode
        thought.set_class(not self._inspection_mode, "hidden")

    def _apply_tool_visibility(self, panel: ToolPanel) -> None:
        hidden = not self._inspection_mode
        if self._inspection_mode and self._tools_hidden and panel.is_done:
            hidden = True
        panel.set_class(hidden, "hidden")

    async def _ensure_turn_label(self) -> None:
        """Mount the ``qwenpaw`` label once per turn, above the first piece
        of assistant activity (thinking, a tool, or the answer)."""
        if not self._labeled:
            self._labeled = True
            await self._mount(AgentLabel())

    def _set_terminal_title(self, title: str) -> None:
        """Set the terminal tab/window title via an OSC escape sequence."""
        driver = getattr(self, "_driver", None)
        if driver is not None:
            try:
                driver.write(f"\x1b]2;{title}\x07")
            except Exception:  # noqa: BLE001 - cosmetic, never fatal
                pass

    # -- input ---------------------------------------------------------------
    async def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if not isinstance(event.text_area, PromptInput):
            return
        if event.text_area.consume_programmatic_change():
            return
        self._menu.update_for(event.text_area.value)
        self._resize_prompt(event.text_area.value)

    def on_input_changed(self, event) -> None:
        self._menu.update_for(event.value)

    async def _submit_prompt(self) -> None:
        prompt = self.query_one("#prompt", PromptInput)
        text = prompt.value.strip()
        if not text:
            return
        prompt.set_programmatic_value("")
        self._resize_prompt("")
        self._menu.display = False
        if text.startswith("/"):
            await self._handle_local_command(text)
            return
        if self._busy:
            # Queue it; it's delivered automatically when the turn ends. The
            # user can recall it with ↑ to edit before it's picked up.
            widget = QueuedMessage(text)
            await self._mount(widget)
            self._queued.append((text, widget))
            return
        await self._submit(text)

    async def _submit(self, text: str) -> None:
        """Deliver one user turn now."""
        await self._mount(UserMessage(text))
        # Reset per-turn lane state so a fresh assistant bubble (and a single
        # new "qwenpaw" label) is created for the reply.
        self._assistant = None
        self._thought = None
        self._activity = None
        self._labeled = False
        self._busy = True
        self._awaiting_backend_update = True
        self._turn_saw_output = False
        self._turn_saw_error = False
        self._status().set(state=self._current_work_state())
        try:
            await self._transport.send(text)
        except Exception as exc:  # noqa: BLE001
            self._busy = False
            self._awaiting_backend_update = False
            self._status().set(state="ready")
            await self._mount(ErrorMessage(str(exc)))
            await self._drain_queue()

    async def _drain_queue(self) -> None:
        """Send the next queued message, if the agent is free to take it."""
        if self._busy or not self._queued:
            return
        text, widget = self._queued.pop(0)
        widget.remove()
        await self._submit(text)

    # -- actions -------------------------------------------------------------
    async def action_interrupt(self) -> None:
        if self._busy:
            # Reflect the request immediately; the agent may take a moment to
            # observe the cancel and end the turn (then state → ready).
            self._status().set(state="interrupting")
            await self._transport.interrupt()
            return
        # Idle: esc cancels the current input draft (and any open menu).
        prompt = self.query_one("#prompt", PromptInput)
        if prompt.value:
            prompt.value = ""
            self._menu.display = False

    async def action_recall_queued(self) -> None:
        """Pull the most recently queued message back into the input to edit.

        Only when the menu is closed and the input is empty, so it never
        clobbers text the user is mid-way through typing.
        """
        if self._menu.display or not self._queued:
            return
        prompt = self.query_one("#prompt", PromptInput)
        if prompt.value:
            return
        text, widget = self._queued.pop()
        widget.remove()
        prompt.set_programmatic_value(text, cursor_end=True)

    def action_toggle_tools(self) -> None:
        """Hide (or reveal) every finished tool panel for a clean transcript.

        Running tools stay visible; completed/failed ones are display:none'd
        but remain mounted so toggling back restores them for inspection.
        """
        self._tools_hidden = not self._tools_hidden
        hidden = 0
        for panel in self.query(ToolPanel):
            if panel.is_done:
                self._apply_tool_visibility(panel)
                hidden += 1
        verb = "Hid" if self._tools_hidden else "Showing"
        self.notify(f"{verb} {hidden} finished tool(s)", timeout=2)

    def action_toggle_inspection(self) -> None:
        """Switch between friendly transcript mode and deeper inspection."""
        self._inspection_mode = not self._inspection_mode
        for thought in self.query(ThoughtMessage):
            thought.collapsed = not self._inspection_mode
            thought.set_class(not self._inspection_mode, "hidden")
        for panel in self.query(ToolPanel):
            self._apply_tool_visibility(panel)
        self._apply_activity_visibility()
        self._scroll_transcript_end(defer=True)
        mode = "inspection" if self._inspection_mode else "friendly"
        self.notify(f"{mode} mode", timeout=2)

    async def action_quit(self) -> None:
        try:
            await self._transport.close()
        finally:
            self.exit()

    async def _handle_local_command(self, raw: str) -> None:
        command, _, rest = raw.partition(" ")
        match command:
            case "/help":
                await self._mount(
                    InfoMessage(
                        "Type /resume to pick a recent session from the "
                        "suggestions (or /resume list to browse all), "
                        "/theme <prompt> to personalize the background, "
                        "or /inspect for details. Model and provider "
                        "commands (e.g. /model) are handled by QwenPaw."
                    )
                )
            case "/resume":
                await self._handle_resume_command(rest.strip())
            case "/theme":
                await self._handle_theme_command(rest.strip())
            case "/inspect":
                self.action_toggle_inspection()
            case _:
                # Everything else (including QwenPaw's own slash commands such
                # as /model and /clear) is forwarded to the agent.
                if self._busy:
                    widget = QueuedMessage(raw)
                    await self._mount(widget)
                    self._queued.append((raw, widget))
                    return
                await self._submit(raw)

    async def _handle_theme_command(self, rest: str) -> None:
        if not rest or rest in {"gallery", "list"}:
            await self.push_screen(
                ThemePicker(), callback=self._apply_theme_picker_result
            )
            return
        theme = find_theme(rest)
        self._apply_theme(theme or rest)

    def _apply_theme_picker_result(
        self, result: ThemeInfo | str | None
    ) -> None:
        self.query_one("#prompt", PromptInput).focus()
        if result is None:
            return
        self._apply_theme(result)

    def _apply_theme(self, theme: ThemeInfo | str) -> None:
        if isinstance(theme, ThemeInfo):
            self._apply_theme_prompt(theme.prompt)
            self.notify(f"{theme.emoji} {theme.name}", timeout=2)
            return
        self._apply_theme_prompt(theme)

    async def _handle_resume_command(self, rest: str = "") -> None:
        if self._busy:
            await self._mount(
                InfoMessage(
                    "Finish or interrupt the current turn before resuming.",
                    level="warn",
                )
            )
            return
        try:
            sessions = await self._transport.list_sessions()
        except Exception as exc:  # noqa: BLE001 - surface, don't crash
            await self._mount(
                InfoMessage(f"Could not list sessions: {exc}", level="warn")
            )
            return
        # Keep the auto-suggest entries fresh from this same fetch.
        self._set_recent_sessions(sessions)
        if not sessions:
            await self._mount(
                InfoMessage("No previous sessions yet.", level="info")
            )
            return

        # `/resume <id>` (e.g. picked from the auto-suggest list) resumes
        # directly; bare `/resume` (or `/resume list`) opens the full picker.
        if rest and rest.lower() not in {"list", "all", "browse"}:
            session_id = self._resolve_session_ref(rest, sessions)
            if session_id is None:
                await self._mount(
                    InfoMessage(
                        f"No session matches '{rest}'. Try /resume list.",
                        level="warn",
                    )
                )
                return
            self.query_one("#prompt", PromptInput).focus()
            await self._resume_session(session_id)
            return

        def _on_pick(session_id: str | None) -> None:
            self.query_one("#prompt", PromptInput).focus()
            if session_id is None:
                return
            self.run_worker(self._resume_session(session_id), exclusive=False)

        await self.push_screen(SessionPicker(sessions), callback=_on_pick)

    @staticmethod
    def _resolve_session_ref(
        ref: str, sessions: list[SessionSummary]
    ) -> str | None:
        """Map a `/resume` argument to a full session id.

        The auto-suggest entries use a short id (first 8 chars), so match by
        prefix first; fall back to an exact id so a full id still works.
        """
        for session in sessions:
            if session.session_id == ref:
                return session.session_id
        for session in sessions:
            if session.session_id.startswith(ref):
                return session.session_id
        return None

    async def _resume_session(self, session_id: str) -> None:
        # Wipe the current (fresh) transcript so the replayed history isn't
        # mixed with the welcome banner, then reset all per-turn lane state.
        await self._transcript().remove_children()
        self._assistant = None
        self._thought = None
        self._activity = None
        self._labeled = False
        self._tools.clear()
        self._file_links_seen.clear()
        self._tok_in = 0
        self._tok_out = 0
        self._stream_chars = 0
        self._refresh_tokens()
        # Mounted before the load so it sits above the replayed transcript;
        # the replay updates only land once load_session is awaited below.
        await self._mount(
            InfoMessage("Resumed previous session — replaying history…")
        )
        try:
            await self._transport.load_session(session_id)
        except Exception as exc:  # noqa: BLE001
            await self._mount(ErrorMessage(f"Could not resume: {exc}"))
            return
        self._status().set(session=session_id)
        self._set_terminal_title(f"QwenPaw {session_id[:8]}")

    async def _handle_prompt_paste(self, text: str) -> str | None:
        try:
            attachments = _attachments_from_paste(text)
        except ValueError as exc:
            await self._mount(
                InfoMessage(f"Could not attach paste: {exc}", level="warn")
            )
            return None
        if attachments:
            paths = [_copy_paste_attachment(item) for item in attachments]
            await self._mount(
                InfoMessage(
                    f"Attached {len(paths)} pasted file"
                    f"{'s' if len(paths) != 1 else ''}.",
                    level="ok",
                )
            )
            return "\n".join(f"[attached file: {path}]" for path in paths)
        embedded = _replace_embedded_file_references(text)
        if embedded is not None:
            replacement, paths = embedded
            await self._mount(
                InfoMessage(
                    f"Attached {len(paths)} pasted file"
                    f"{'s' if len(paths) != 1 else ''}.",
                    level="ok",
                )
            )
            return replacement
        if _should_store_pasted_text(text):
            path = _store_pasted_text(text)
            await self._mount(
                InfoMessage(
                    f"Stored pasted text ({len(text)} characters).", level="ok"
                )
            )
            return f"[pasted text: {path}]"
        return None

    def _resize_prompt(self, value: str) -> None:
        prompt = self.query_one("#prompt", PromptInput)
        width = max(20, prompt.size.width or 80)
        rows = _prompt_height(value, width=width)
        prompt.styles.height = max(3, min(10, rows + 2))

    def _theme_path(self) -> Path:
        return state_dir() / "theme.json"

    def _load_theme_prompt(self) -> str:
        try:
            data = json.loads(self._theme_path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return os.getenv("PAW_BACKGROUND_PROMPT", "original")
        return str(data.get("prompt") or "original")

    def get_css_variables(self) -> dict[str, str]:
        """Expose palette-derived bubble outline colours to the stylesheet.

        Message bubbles are transparent; only their rounded border is coloured.
        These variables keep the CSS declarative while the border tones follow
        the active theme (re-evaluated via ``refresh_css`` on theme change).
        """
        variables = super().get_css_variables()
        screen, prompt_bg, chrome = palette_for_prompt(
            getattr(self, "_theme_prompt", "") or "original"
        )
        variables.update(
            {
                "bubble-border": mix_hex(
                    mix_hex(screen, chrome, 0.55), "#ffffff", 0.12
                ),
                "bubble-user-border": mix_hex(
                    mix_hex(prompt_bg, chrome, 0.7), "#ffffff", 0.16
                ),
            }
        )
        return variables

    def _apply_theme_prompt(self, prompt: str, *, notify: bool = True) -> None:
        self._theme_prompt = prompt
        colors = palette_for_prompt(prompt)
        # Re-evaluate the bubble border variables for the new palette. Done
        # before the imperative style writes below so those stay authoritative.
        self.refresh_css()
        # Static background — the theme's base shade, no animation.
        self.screen.styles.background = colors[0]
        self._transcript().styles.background = "transparent"
        self.query_one("#prompt", PromptInput).styles.background = colors[1]
        self.query_one(StatusBar).styles.background = colors[2]
        for welcome in self.query(WelcomeMessage):
            welcome.set_palette(colors, accent_for_prompt(prompt))
        try:
            self._theme_path().write_text(
                json.dumps({"prompt": prompt}), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001
            pass
        if notify:
            theme = find_theme(prompt)
            label = f"{theme.emoji} {theme.name}" if theme else prompt
            self.notify(f"Theme: {label}", timeout=2)

    # -- event pump ----------------------------------------------------------
    @work(exclusive=True)
    async def _consume(self) -> None:
        try:
            connected = await self._transport.start()
            self._on_connected(connected)
            async for event in self._transport.events():
                await self._dispatch(event)
        except Exception as exc:  # noqa: BLE001
            self._status().set(state="error")
            await self._mount(ErrorMessage(f"transport: {exc}"))

    def _on_connected(self, ev: Connected) -> None:
        self._backend_warmed = not ev.warming
        if ev.model:
            self._model = ev.model
        self._status().set(
            session=ev.session_id,
            agent=ev.agent or self._agent,
            model=ev.model or "—",
            qwenpaw_version=ev.qwenpaw_version or "—",
            state="ready" if self._backend_warmed else "warming",
        )
        # Start with the session id; replaced by the real title once the
        # agent reports one (see SessionTitle).
        self._set_terminal_title(f"QwenPaw {str(ev.session_id)[:8]}")
        # Populate the `/resume` auto-suggest list from past sessions.
        self._refresh_recent_sessions()

    # Rough bytes-per-token for the live output estimate (~4 chars/token for
    # typical text; intentionally crude — it's marked approximate and is
    # replaced by the exact count when the call's usage arrives).
    _CHARS_PER_TOKEN = 4

    def _refresh_tokens(self) -> None:
        """Push token totals to the status bar, including the in-flight
        estimate for output tokens still streaming."""
        est = self._stream_chars // self._CHARS_PER_TOKEN
        self._status().set(
            tok_in=self._tok_in,
            tok_out=self._tok_out + est,
            tok_out_approx=est > 0,
        )

    async def _dispatch(self, event) -> None:
        if isinstance(event, TextDelta):
            self._mark_backend_update()
            await self._ensure_turn_label()
            # The visible answer beginning means thinking is done; freeze the
            # thought lane and its activity row (otherwise the row keeps
            # animating "thinking" while the answer streams) and drop both so
            # reasoning that resumes later starts a fresh block.
            if self._thought is not None:
                self._thought.done()
                self._thought = None
            if self._activity is not None:
                self._activity.done()
                self._activity = None
            if self._assistant is None:
                self._assistant = AssistantMessage()
                await self._mount(self._assistant)
            await self._assistant.append(event.text)
            self._scroll_transcript_end()
            self._stream_chars += len(event.text)
            self._refresh_tokens()

        elif isinstance(event, ThoughtDelta):
            self._mark_backend_update()
            await self._ensure_turn_label()
            activity = await self._ensure_activity_line()
            activity.set_thinking()
            # A new thinking block: any answer text after it should mount
            # below, so close the current assistant bubble.
            self._assistant = None
            if self._thought is None:
                self._thought = ThoughtMessage(live=True)
                self._thought.add_class("hidden")
                await self._mount(self._thought)
                self._apply_thought_visibility(self._thought)
            self._thought.append(event.text)
            # Reasoning counts toward output tokens too.
            self._stream_chars += len(event.text)
            self._refresh_tokens()

        elif isinstance(event, ToolCall):
            self._mark_backend_update()
            activity = await self._ensure_activity_line()
            activity.set_tool(
                title=event.title,
                kind=event.kind,
                status=event.status,
                params=event.params,
            )
            panel = self._tools.get(event.tool_call_id)
            if panel is None:
                await self._ensure_turn_label()
                # A new tool ends the current thinking block and closes the
                # assistant bubble, so transcript widgets stay in the order
                # content was produced (text → tool → text reads top-down).
                if self._thought is not None:
                    self._thought.done()
                    self._thought = None
                self._assistant = None
                panel = ToolPanel(
                    event.tool_call_id,
                    event.title,
                    event.kind,
                    params=event.params,
                )
                self._tools[event.tool_call_id] = panel
                panel.add_class("hidden")
                await self._mount(panel)
                self._apply_tool_visibility(panel)
            panel.update_call(
                title=event.title,
                kind=event.kind,
                status=event.status,
                output=event.output,
                params=event.params,
            )
            self._apply_tool_visibility(panel)
            # Surface any files the tool returned (e.g. send_file_to_user) as
            # their own clickable transcript line, since the panel collapses.
            for link in event.links:
                key = (event.tool_call_id, link.uri)
                if key in self._file_links_seen:
                    continue
                self._file_links_seen.add(key)
                await self._mount(FileLinkBox(link.name, link.uri))

        elif isinstance(event, UserTurn):
            # A user turn replayed from a resumed session. Close any open
            # assistant lane so the next replayed reply starts its own bubble.
            if self._thought is not None:
                self._thought.done()
                self._thought = None
            if self._activity is not None:
                self._activity.done()
                self._activity = None
            self._assistant = None
            self._labeled = False
            await self._mount(UserMessage(event.text))

        elif isinstance(event, SessionTitle):
            self._set_terminal_title(f"QwenPaw {event.title}")

        elif isinstance(event, AvailableCommands):
            self._agent_commands = list(event.commands)
            self._set_command_catalog()

        elif isinstance(event, PushMessage):
            await self._mount(PushMessageBox(event.text))

        elif isinstance(event, Usage):
            self._status().set(used=event.used, size=event.size)

        elif isinstance(event, TokenUsage):
            # Exact usage for the just-finished call replaces our estimate.
            self._tok_in += event.input_tokens
            self._tok_out += event.output_tokens
            self._stream_chars = 0
            if event.model:
                self._model = event.model
                self._status().set(model=event.model)
            self._refresh_tokens()

        elif isinstance(event, PlanUpdate):
            # Render the plan inline as a thought-style summary for now.
            lines = "\n".join(
                f"  {'✓' if e.status == 'completed' else '•'} {e.content}"
                for e in event.entries
            )
            if lines:
                box = ThoughtMessage(title="📋 plan", collapsed=False)
                box.append(lines)
                await self._mount(box)

        elif isinstance(event, PermissionRequest):
            self._on_permission(event)

        elif isinstance(event, TransportError):
            self._awaiting_backend_update = False
            self._turn_saw_error = True
            self._status().set(state="error")
            await self._mount(ErrorMessage(event.message))

        elif isinstance(event, BackendWarmed):
            self._backend_warmed = True
            if not event.success and event.message:
                await self._mount(
                    InfoMessage(
                        f"Backend warmup skipped: {event.message}",
                        level="warn",
                    )
                )
            self._status().set(state=self._current_work_state())

        elif isinstance(event, TurnEnded):
            self._busy = False
            self._awaiting_backend_update = False
            if self._thought is not None:
                self._thought.done()
            if self._activity is not None:
                self._activity.done()
            self._assistant = None
            self._thought = None
            self._activity = None
            self._labeled = False
            self._tools.clear()
            # Drop any leftover estimate (e.g. a turn with no usage report).
            self._stream_chars = 0
            self._refresh_tokens()
            self._status().set(state="ready")
            # A turn that ended without any visible output (and without an
            # error already shown) is a silent backend failure — surface it so
            # an unusable model doesn't just look like nothing happened.
            if (
                not self._turn_saw_output
                and not self._turn_saw_error
                and event.stop_reason != "cancelled"
            ):
                self._status().set(state="error")
                await self._mount(
                    ErrorMessage(self._no_response_text(event.stop_reason))
                )
            # Hand off to the next message the user queued while we worked.
            await self._drain_queue()
            # The just-finished exchange makes this (or a resumed) session the
            # newest; refresh the /resume auto-suggest list to reflect it.
            self._refresh_recent_sessions()

    def _mark_backend_update(self) -> None:
        # Reached on every text / thought / tool event, i.e. anything the user
        # can see — so the turn produced a visible response.
        self._turn_saw_output = True
        if not self._awaiting_backend_update:
            return
        self._awaiting_backend_update = False
        self._backend_warmed = True
        self._status().set(state="thinking")

    def _current_work_state(self) -> str:
        if not self._busy:
            return "ready"
        if self._awaiting_backend_update:
            return "waiting" if self._backend_warmed else "warming"
        return "thinking"

    def _no_response_text(self, stop_reason: str | None) -> str:
        model = self._model or "the model"
        extra = (
            f" (stop reason: {stop_reason})"
            if stop_reason and stop_reason not in {"end_turn", "stop"}
            else ""
        )
        return (
            f"No response from {model}{extra}. The model or its API key "
            "may be misconfigured in QwenPaw — check it with `qwenpaw "
            "doctor` or `qwenpaw models config-key`."
        )

    def _on_permission(self, event: PermissionRequest) -> None:
        def _resolve(option_id: str | None) -> None:
            self.run_worker(
                self._transport.resolve_permission(
                    event.request_id, option_id
                ),
                exclusive=False,
            )

        self.push_screen(PermissionModal(event), _resolve)

    async def on_unmount(self) -> None:
        await self._transport.close()


def _local_commands() -> list[SlashCommand]:
    """Slash commands handled by the TUI itself. Model/provider commands are
    QwenPaw's and are forwarded to the agent, not listed here."""
    commands = [
        SlashCommand("help", "show QwenPaw TUI shortcuts"),
        SlashCommand("resume", "resume a previous session"),
        SlashCommand("theme", "open theme gallery or apply a vibe"),
        SlashCommand("inspect", "toggle deeper thought/tool detail"),
    ]
    commands.extend(
        SlashCommand(
            f"theme {theme.id}",
            f"{theme.emoji} {theme.name}",
        )
        for theme in THEME_GALLERY
    )
    return commands


_LONG_PASTE_CHAR_THRESHOLD = 2000
_LONG_PASTE_LINE_THRESHOLD = 12
_ATTACHMENT_DIR = "attachments"


@dataclass(frozen=True)
class _PasteAttachment:
    name: str
    source_path: Path | None = None
    data: bytes | None = None


@dataclass(frozen=True)
class _PasteFileReference:
    start: int
    end: int
    path: Path


def _should_store_pasted_text(text: str) -> bool:
    if not text:
        return False
    return (
        len(text) >= _LONG_PASTE_CHAR_THRESHOLD
        or text.count("\n") + 1 >= _LONG_PASTE_LINE_THRESHOLD
    )


def _attachments_from_paste(text: str) -> list[_PasteAttachment]:
    stripped = text.strip()
    if not stripped:
        return []
    data_attachment = _data_url_attachment(stripped)
    if data_attachment is not None:
        return [data_attachment]
    candidates = _paste_file_candidates(stripped)
    if not candidates:
        return []
    attachments: list[_PasteAttachment] = []
    for candidate in candidates:
        path = _path_from_file_reference(candidate)
        if not _is_file(path):
            return []
        attachments.append(_PasteAttachment(name=path.name, source_path=path))
    return attachments


def _replace_embedded_file_references(
    text: str,
) -> tuple[str, list[Path]] | None:
    references = _embedded_file_references(text)
    if not references:
        return None
    chunks: list[str] = []
    copied: list[Path] = []
    cursor = 0
    for ref in references:
        destination = _copy_paste_attachment(
            _PasteAttachment(name=ref.path.name, source_path=ref.path)
        )
        copied.append(destination)
        chunks.append(text[cursor : ref.start])
        chunks.append(f"[attached file: {destination}]")
        cursor = ref.end
    chunks.append(text[cursor:])
    return "".join(chunks), copied


def _embedded_file_references(text: str) -> list[_PasteFileReference]:
    references: list[_PasteFileReference] = []
    index = 0
    while index < len(text):
        if not _looks_like_path_start(text, index):
            index += 1
            continue
        reference = _longest_file_reference(text, index)
        if reference is None:
            index += 1
            continue
        references.append(reference)
        index = reference.end
    return references


def _looks_like_path_start(text: str, index: int) -> bool:
    return (
        text[index] == "/"
        or (text[index] == "~" and text[index : index + 2] == "~/")
        or text.startswith("file://", index)
    )


def _longest_file_reference(
    text: str, start: int
) -> _PasteFileReference | None:
    line_end = text.find("\n", start)
    if line_end == -1:
        line_end = len(text)
    for end in range(line_end, start, -1):
        fragment = text[start:end]
        trimmed = fragment.rstrip(".,;:)]}")
        trim_end = start + len(trimmed)
        path = _path_from_text_fragment(trimmed)
        if path is not None:
            return _PasteFileReference(start, trim_end, path)
    return None


def _path_from_text_fragment(value: str) -> Path | None:
    value = value.strip()
    if not value:
        return None
    direct = _path_from_file_reference(_strip_wrapping_quotes(value))
    if _is_file(direct):
        return direct
    try:
        parts = shlex.split(value)
    except ValueError:
        return None
    if len(parts) != 1:
        return None
    parsed = _path_from_file_reference(parts[0])
    return parsed if _is_file(parsed) else None


def _paste_file_candidates(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        return [_strip_wrapping_quotes(line) for line in lines]
    whole = _strip_wrapping_quotes(text)
    whole_path = _path_from_file_reference(whole)
    if _is_file(whole_path):
        return [whole]
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = []
    if len(parts) > 1:
        return parts
    return [whole]


def _path_from_file_reference(value: str) -> Path | None:
    if value.startswith("file://"):
        parsed = urlparse(value)
        if parsed.netloc and parsed.netloc not in {"localhost", "127.0.0.1"}:
            return None
        return Path(unquote(parsed.path)).expanduser()
    return Path(value).expanduser()


def _is_file(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        return path.is_file()
    except OSError:
        return False


def _data_url_attachment(value: str) -> _PasteAttachment | None:
    match = re.fullmatch(
        r"data:([^;,]+)?(;base64)?,(.*)", value, flags=re.DOTALL
    )
    if match is None:
        return None
    media_type = match.group(1) or "application/octet-stream"
    if match.group(2) != ";base64":
        raise ValueError("pasted data URLs must be base64 encoded")
    try:
        data = base64.b64decode(match.group(3), validate=True)
    except binascii.Error as exc:
        raise ValueError(f"invalid base64 data URL: {exc}") from exc
    extension = mimetypes.guess_extension(media_type) or ".bin"
    prefix = (
        "pasted-image" if media_type.startswith("image/") else "pasted-file"
    )
    return _PasteAttachment(name=f"{prefix}{extension}", data=data)


def _copy_paste_attachment(attachment: _PasteAttachment) -> Path:
    destination = _unique_attachment_path(attachment.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if attachment.source_path is not None:
        shutil.copy2(attachment.source_path, destination)
    elif attachment.data is not None:
        destination.write_bytes(attachment.data)
    else:
        destination.write_bytes(b"")
    return destination


def _store_pasted_text(text: str) -> Path:
    destination = _unique_attachment_path("pasted-text.txt")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    return destination


def _unique_attachment_path(name: str) -> Path:
    path = Path(name)
    suffix = path.suffix
    stem = _safe_attachment_stem(path.stem or "pasted-file")
    return state_dir() / _ATTACHMENT_DIR / f"{stem}-{uuid4().hex[:10]}{suffix}"


def _safe_attachment_stem(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return normalized[:64] or "pasted-file"


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _prompt_height(value: str, *, width: int) -> int:
    rows = 1
    usable = max(20, width - 4)
    for line in value.splitlines() or [""]:
        rows += max(0, (len(line) - 1) // usable)
    return rows + value.count("\n")
