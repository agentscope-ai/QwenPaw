# -*- coding: utf-8 -*-
"""Pilot-driven smoke tests for the Textual app with a fake transport."""

from __future__ import annotations

# Tests poke at the app's internals and use terse fixtures.
# pylint: disable=protected-access,not-an-iterable,disallowed-name
# pylint: disable=consider-using-with,unnecessary-lambda
# pylint: disable=use-implicit-booleaness-not-comparison

import asyncio

import pytest

from textual.widgets import ListView

from qwenpaw.cli.tui.app import PawApp
from qwenpaw.cli.tui.events import (
    AvailableCommands,
    BackendWarmed,
    Connected,
    FileLink,
    PermissionOption,
    PermissionRequest,
    SessionSummary,
    SessionTitle,
    SlashCommand,
    TextDelta,
    ThoughtDelta,
    TokenUsage,
    ToolCall,
    TurnEnded,
    UserTurn,
)
from qwenpaw.cli.tui.widgets import (
    ActivityLine,
    AgentLabel,
    AssistantMessage,
    CommandMenu,
    ErrorMessage,
    FileLinkBox,
    InfoMessage,
    PermissionOverlay,
    QueuedMessage,
    SessionPicker,
    StatusBar,
    ThoughtMessage,
    ToolPanel,
    UserMessage,
    WelcomeMessage,
    ThemePicker,
)

pytestmark = [pytest.mark.unit, pytest.mark.p1]


class FakeTransport:
    """In-process transport that scripts a canned turn for the UI."""

    def __init__(self, *, resume_session_id: str | None = None) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self.sent: list[str] = []
        self.interrupted = False
        self.resolved: list[tuple[str, str | None]] = []
        self.closed = False
        self._permission_mode = "none"
        # Resume support: past sessions to offer, and a record of loads.
        self.sessions: list[SessionSummary] = []
        self.loaded: list[str] = []
        self._resume_session_id = resume_session_id

    async def start(self) -> Connected:
        if self._resume_session_id is not None:
            await self.load_session(self._resume_session_id)
            return Connected(
                session_id=self._resume_session_id,
                agent="default",
                qwenpaw_version="9.8.7",
            )
        return Connected(
            session_id="sess-abc",
            agent="default",
            model="qwen-max",
            qwenpaw_version="9.8.7",
        )

    async def send(self, text: str) -> None:
        self.sent.append(text)
        if "permission" in text:
            await self._queue.put(
                PermissionRequest(
                    request_id="r1",
                    title="dangerous_tool",
                    params="command: rm -rf /tmp/nope",
                    options=[
                        PermissionOption("allow", "Allow", "allow_once"),
                        PermissionOption("deny", "Deny", "reject_once"),
                    ],
                ),
            )
            return
        for chunk in ("Hello ", "there"):
            await self._queue.put(TextDelta(chunk))
        await self._queue.put(
            ToolCall(
                "t1",
                "read_file",
                kind="read",
                status="completed",
                output="data",
            ),
        )
        await self._queue.put(TurnEnded(stop_reason="end_turn"))

    async def interrupt(self) -> None:
        self.interrupted = True
        await self._queue.put(TurnEnded(stop_reason="cancelled"))

    async def list_sessions(self) -> list[SessionSummary]:
        return list(self.sessions)

    async def load_session(self, session_id: str) -> None:
        self.loaded.append(session_id)
        # Replay a tiny saved transcript, like the real backend does.
        await self._queue.put(UserTurn("How do I write a loop in Rust?"))
        await self._queue.put(TextDelta("Use a `for` loop."))
        await self._queue.put(UserTurn("Thanks!"))

    def events(self):
        async def _gen():
            while True:
                item = await self._queue.get()
                if item is None:
                    return
                yield item

        return _gen()

    async def resolve_permission(self, request_id, option_id):
        self.resolved.append((request_id, option_id))
        await self._queue.put(TextDelta(f"[{option_id}]"))
        await self._queue.put(TurnEnded())

    async def close(self):
        self.closed = True
        await self._queue.put(None)


class SlowStartTransport(FakeTransport):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def start(self) -> Connected:
        await self.release.wait()
        return await super().start()


class WarmingTransport(FakeTransport):
    async def start(self) -> Connected:
        connected = await super().start()
        return Connected(
            session_id=connected.session_id,
            agent=connected.agent,
            model=connected.model,
            qwenpaw_version=connected.qwenpaw_version,
            warming=True,
        )


class QuietTransport(FakeTransport):
    async def send(self, text: str) -> None:
        self.sent.append(text)


class WarmingQuietTransport(WarmingTransport):
    async def send(self, text: str) -> None:
        self.sent.append(text)


@pytest.mark.asyncio
async def test_basic_turn_renders():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        # status bar picked up the Connected event
        assert "qwen-max" in app.query_one("StatusBar").summary

        prompt = app.query_one("#prompt")
        prompt.value = "hi"
        await pilot.press("enter")
        # let the scripted events drain
        for _ in range(10):
            await pilot.pause()
            if not app._busy:
                break

        assert transport.sent == ["hi"]
        assert any(isinstance(w, UserMessage) for w in app.query(UserMessage))
        assistant = app.query(AssistantMessage).first()
        assert assistant.text == "Hello there"
        tools = list(app.query(ToolPanel))
        assert tools and tools[0]._status == "completed"


class EmptyTurnTransport(FakeTransport):
    """A turn that ends with no content — e.g. an unusable model."""

    async def send(self, text: str) -> None:
        self.sent.append(text)
        await self._queue.put(TurnEnded(stop_reason="end_turn"))


@pytest.mark.asyncio
async def test_empty_turn_surfaces_error():
    """A turn with no visible output reports an error, not a silent return."""
    transport = EmptyTurnTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._model = "dashscope:qwen3-max"
        app.query_one("#prompt").value = "hi"
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if not app._busy:
                break

        assert not app._busy  # not stuck busy
        errors = list(app.query(ErrorMessage))
        assert errors, "expected an error message for an empty turn"
        assert "No response" in errors[-1].content.plain
        assert "dashscope:qwen3-max" in errors[-1].content.plain


@pytest.mark.asyncio
async def test_cancelled_empty_turn_is_not_an_error():
    """Interrupting a turn before any output must not look like a failure."""
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._dispatch(TurnEnded(stop_reason="cancelled"))
        await pilot.pause()
        assert not list(app.query(ErrorMessage))


@pytest.mark.asyncio
async def test_message_bubbles_are_transparent():
    """Message bubbles blend into the background.

    The background is a static colour and the bubble fills are transparent, so
    text and bubble are consistent with the overall background; only a rounded
    border outlines each one.
    """
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#prompt").value = "hi"
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if not app._busy:
                break

        bubbles = [
            app.query(UserMessage).first(),
            app.query(AssistantMessage).first(),
            app.query(AssistantMessage).first().query_one("Markdown"),
            app.query(ToolPanel).first(),
        ]
        for bubble in bubbles:
            assert (
                bubble.styles.background.a == 0
            ), f"{type(bubble).__name__} background is not transparent"


@pytest.mark.asyncio
async def test_assistant_bubble_has_no_trailing_blank_row():
    """A single-line answer is border + one text row + border = 3 rows.

    A trailing markdown paragraph margin would make it 4 (uneven bottom
    padding); the last-child margin reset keeps top and bottom even.
    """
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#prompt").value = "hi"
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if not app._busy:
                break

        assistant = app.query(AssistantMessage).first()
        assert assistant.region.height == 3


@pytest.mark.asyncio
async def test_running_tool_expanded_then_collapsed_when_done():
    """A tool stays open while running, then auto-collapses on completion."""
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()

        await app._dispatch(
            ToolCall(
                "t1",
                "execute_shell_command",
                kind="execute",
                status="in_progress",
                params="command: ls -la",
            ),
        )
        await pilot.pause()
        panel = app.query(ToolPanel).first()
        assert panel.collapsed is False  # running → expanded

        await app._dispatch(
            ToolCall(
                "t1",
                "execute_shell_command",
                kind="execute",
                status="completed",
                output="total 0",
            ),
        )
        await pilot.pause()
        assert panel.collapsed is True  # done → collapsed, re-openable


@pytest.mark.asyncio
async def test_tool_name_persists_after_completion_update():
    """The agent only sends the name on the start event; the completion
    update (title="") must not overwrite it back to a placeholder."""
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        # start: real name; completion: no title, just status + output
        await app._dispatch(
            ToolCall("t1", "execute_shell_command", status="in_progress"),
        )
        await app._dispatch(
            ToolCall("t1", "", status="completed", output="done"),
        )
        await pilot.pause()
        panel = app.query(ToolPanel).first()
        assert "execute_shell_command" in panel.title.plain


@pytest.mark.asyncio
async def test_finished_tool_header_is_informative():
    """A completed tool with a generic title still shows kind + params."""
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._dispatch(
            ToolCall(
                "t1",
                "tool",
                kind="execute",
                status="completed",
                params="command: ls -la /tmp\nshell: zsh",
                output="x",
            ),
        )
        await pilot.pause()
        panel = app.query(ToolPanel).first()
        title = panel.title.plain
        assert "execute" in title  # falls back to kind, not bare "tool"
        assert "ls -la /tmp" in title  # primary param surfaced
        assert "completed" not in title  # redundant status word dropped


@pytest.mark.asyncio
async def test_toggle_hides_finished_tools_only():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._dispatch(
            ToolCall("done", "read_file", kind="read", status="completed"),
        )
        await app._dispatch(
            ToolCall("live", "grep", kind="search", status="in_progress"),
        )
        await pilot.pause()
        done = app._tools["done"]
        live = app._tools["live"]
        assert done.has_class("hidden")
        assert live.has_class("hidden")

        await pilot.press("ctrl+i")
        assert not done.has_class("hidden")
        assert not live.has_class("hidden")

        await pilot.press("ctrl+t")
        assert done.has_class("hidden")  # finished → hidden
        assert not live.has_class("hidden")  # running → still visible

        await pilot.press("ctrl+t")
        assert not done.has_class("hidden")  # toggled back for inspection


@pytest.mark.asyncio
async def test_thinking_collapsed_by_default():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._dispatch(ThoughtDelta("pondering the question"))
        await pilot.pause()
        thought = app.query(ThoughtMessage).first()
        assert thought.collapsed is True
        assert thought.has_class("hidden")
        activity = app.query(ActivityLine).first()
        assert "thinking" in activity.content.plain


@pytest.mark.asyncio
async def test_new_thoughts_expand_when_inspection_mode_is_active():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+i")
        await app._dispatch(ThoughtDelta("show the details"))
        await pilot.pause()

        thought = app.query(ThoughtMessage).first()
        assert thought.collapsed is False
        assert not thought.has_class("hidden")
        assert app.query(ActivityLine).first().has_class("hidden")


@pytest.mark.asyncio
async def test_friendly_mode_collapses_tool_chain_to_one_activity_line():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._dispatch(ThoughtDelta("planning"))
        await app._dispatch(
            ToolCall(
                "t1",
                "read_file",
                kind="read",
                status="completed",
                params="path: README.md",
                output="...",
            ),
        )
        await app._dispatch(
            ToolCall(
                "t2",
                "execute_shell_command",
                kind="execute",
                status="in_progress",
                params="command: pytest -q",
            ),
        )
        await pilot.pause()

        activities = list(app.query(ActivityLine))
        assert len(activities) == 1
        assert "execute_shell_command" in activities[0].content.plain
        assert "pytest -q" in activities[0].content.plain
        assert all(panel.has_class("hidden") for panel in app.query(ToolPanel))
        assert app.query(ThoughtMessage).first().has_class("hidden")

        await pilot.press("ctrl+i")
        assert activities[0].has_class("hidden")
        assert all(
            not panel.has_class("hidden") for panel in app.query(ToolPanel)
        )
        assert not app.query(ThoughtMessage).first().has_class("hidden")


@pytest.mark.asyncio
async def test_activity_line_stops_thinking_when_answer_streams():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._dispatch(ThoughtDelta("pondering"))
        await pilot.pause()
        activity = app.query(ActivityLine).first()
        assert "thinking" in activity.content.plain

        # Once the visible answer begins, the activity row must stop animating
        # "thinking" — the thought chain is complete.
        await app._dispatch(TextDelta("Here is the answer."))
        await pilot.pause()
        assert "thinking" not in activity.content.plain
        assert "thought complete" in activity.content.plain
        # The reference is dropped so resumed reasoning starts a fresh line.
        assert app._activity is None


@pytest.mark.asyncio
async def test_permission_overlay_resolves_with_keyboard_selection():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt")
        prompt.value = "do permission thing"
        await pilot.press("enter")

        # The overlay should appear above the input with the tool parameters.
        overlay = app.query_one(PermissionOverlay)
        for _ in range(10):
            await pilot.pause()
            if overlay.display:
                break
        assert overlay.display
        option_text = "\n".join(
            getattr(overlay.get_option_at_index(index).prompt, "plain", "")
            for index in range(len(overlay.options))
        )
        assert "command: rm -rf /tmp/nope" in option_text

        # Down selects Deny, then Enter resolves the highlighted option.
        await pilot.press("down")
        await pilot.pause()
        assert overlay.selected == "deny"
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if transport.resolved:
                break

        assert transport.resolved == [("r1", "deny")]


@pytest.mark.asyncio
async def test_slash_command_suggestions():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._dispatch(
            AvailableCommands(
                commands=[
                    SlashCommand("model", "switch model"),
                    SlashCommand("agent", "change agent"),
                    SlashCommand("clear", "clear session"),
                ],
            ),
        )
        menu = app.query_one(CommandMenu)
        prompt = app.query_one("#prompt")

        # Plain text → no dropdown.
        prompt.value = "hi"
        await pilot.pause()
        assert not menu.display

        # "/" opens the dropdown with local commands plus agent commands.
        prompt.value = "/"
        await pilot.pause()
        assert menu.display
        assert menu.option_count >= 3
        command_names = [command.name for command in app._suggester._commands]
        assert {"model", "agent", "clear", "theme"}.issubset(command_names)

        # Inline ghost completion offers the top match.
        assert await app._suggester.get_suggestion("/mod") == "/model"

        # Typing narrows the list.
        prompt.value = "/a"
        await pilot.pause()
        assert menu.display
        assert menu.selected == "agent"

        # Tab accepts the highlighted command (note trailing space) and the
        # menu steps aside instead of submitting.
        await pilot.press("tab")
        assert prompt.value == "/agent "
        assert not menu.display
        assert transport.sent == []


@pytest.mark.asyncio
async def test_slash_command_suggests_theme_arguments():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        menu = app.query_one(CommandMenu)
        prompt = app.query_one("#prompt")

        prompt.value = "/theme c"
        await pilot.pause()
        assert menu.display
        assert menu.selected == "theme cyberpunk"

        await pilot.press("tab")
        assert prompt.value == "/theme cyberpunk "
        assert transport.sent == []


@pytest.mark.asyncio
async def test_welcome_message_mounts_with_qwenpaw_greeting():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        welcome = app.query(WelcomeMessage).first()
        plain = welcome.content.plain
        assert "█" in plain
        assert "▀" not in plain
        assert plain.count("█") > 150
        assert "QwenPaw 9.8.7" not in plain
        assert "works for you" not in plain
        assert "/theme" not in plain
        assert len(plain.splitlines()) >= 6
        status = app.query_one(StatusBar).summary
        assert "QwenPaw 9.8.7" in status
        # The TUI version is no longer shown — only QwenPaw's.
        assert "TUI" not in status


@pytest.mark.asyncio
async def test_welcome_logo_animates_then_restores_on_live_terminal(
    monkeypatch,
):
    # ``run_test`` is headless, which skips the hop; pretend it's a live
    # terminal so ``on_mount`` starts the animation, then drive the frame
    # loop deterministically (each ``_tick`` advances a fixed step, so we
    # don't have to wait wall-clock seconds).
    monkeypatch.setattr(
        PawApp,
        "is_headless",
        property(lambda self: False),
    )
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        welcome = app.query(WelcomeMessage).first()
        assert welcome._animating is True
        assert welcome._anim_timer is not None

        for _ in range(500):
            if not welcome._animating:
                break
            welcome._tick()

        assert welcome._animating is False
        assert welcome._anim_timer is None
        # The settled logo is the same as the static one.
        plain = welcome.content.plain
        assert plain.count("█") == welcome._render_body().plain.count("█")


@pytest.mark.asyncio
async def test_status_stays_starting_until_backend_connects():
    transport = SlowStartTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "starting" in app.query_one(StatusBar).summary
        assert "ready" not in app.query_one(StatusBar).summary

        transport.release.set()
        for _ in range(10):
            await pilot.pause()
            if "ready" in app.query_one(StatusBar).summary:
                break
        assert "ready" in app.query_one(StatusBar).summary


@pytest.mark.asyncio
async def test_status_stays_warming_until_backend_warmup_finishes():
    transport = WarmingTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        summary = app.query_one(StatusBar).summary
        assert "warming" in summary
        assert "ready" not in summary

        await app._dispatch(BackendWarmed())
        summary = app.query_one(StatusBar).summary
        assert "ready" in summary
        assert "warming" not in summary


@pytest.mark.asyncio
async def test_first_turn_shows_warming_until_backend_updates():
    transport = WarmingQuietTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._submit("hello")
        assert transport.sent == ["hello"]
        summary = app.query_one(StatusBar).summary
        assert "warming" in summary
        assert "thinking" not in summary

        await app._dispatch(TextDelta("hi"))
        summary = app.query_one(StatusBar).summary
        assert "thinking" in summary


@pytest.mark.asyncio
async def test_theme_command_opens_gallery_without_chat_turn():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt")
        prompt.value = "/theme gallery"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ThemePicker)
        assert transport.sent == []
        app.screen.dismiss(None)


@pytest.mark.asyncio
async def test_resume_with_no_sessions_shows_info():
    transport = FakeTransport()  # no past sessions
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#prompt").value = "/resume "
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, SessionPicker)
        infos = [i.content.plain for i in app.query(InfoMessage)]
        assert any("No previous sessions yet" in text for text in infos)
        assert transport.sent == []  # never forwarded to the agent


@pytest.mark.asyncio
async def test_resume_opens_picker_and_replays_selected_session():
    transport = FakeTransport()
    transport.sessions = [
        SessionSummary(
            session_id="old-1",
            title="Earlier chat about Rust",
            updated_at="2026-01-01T00:00:00+00:00",
        ),
    ]
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#prompt").value = "/resume list"
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if isinstance(app.screen, SessionPicker):
                break
        assert isinstance(app.screen, SessionPicker)

        # Pick the only session.
        app.screen.dismiss("old-1")
        # ``FakeTransport.load_session`` sets ``transport.loaded`` BEFORE
        # pushing replay events, so polling that flag races the consume
        # worker on event loops with different scheduling
        # (ProactorEventLoop on Windows vs. SelectorEventLoop elsewhere).
        # Poll the final observable state instead: the last replayed
        # user turn has been mounted as a UserMessage.
        for _ in range(20):
            await pilot.pause()
            rendered = " ".join(
                u.content.plain for u in app.query(UserMessage)
            )
            if "Thanks!" in rendered:
                break

        assert transport.loaded == ["old-1"]
        # Give the UI time to render all replayed events.
        for _ in range(20):
            await pilot.pause()
            if len(app.query(UserMessage)) >= 2:
                break
        # Welcome banner is cleared; the replayed transcript renders instead.
        assert not list(app.query(WelcomeMessage))
        user_msgs = [u.content.plain for u in app.query(UserMessage)]
        assert "How do I write a loop in Rust?" in " ".join(user_msgs)
        assert "Thanks!" in " ".join(user_msgs)
        assistant = app.query(AssistantMessage).first()
        assert "Use a `for` loop." in assistant.text
        assert transport.sent == []
        assert "old-1" in app.query_one(StatusBar).summary


@pytest.mark.asyncio
async def test_session_picker_arrow_keys_move_selection():
    transport = FakeTransport()
    transport.sessions = [
        SessionSummary(session_id="s1", title="First chat"),
        SessionSummary(session_id="s2", title="Second chat"),
        SessionSummary(session_id="s3", title="Third chat"),
    ]
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#prompt").value = "/resume list"
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if isinstance(app.screen, SessionPicker):
                break
        assert isinstance(app.screen, SessionPicker)
        # Search input has focus, yet ↓/↑ move the list selection.
        assert app.screen.query_one("#session-list", ListView).index == 0
        await pilot.press("down")
        await pilot.pause()
        assert app.screen.query_one("#session-list", ListView).index == 1
        await pilot.press("down")
        await pilot.pause()
        assert app.screen.query_one("#session-list", ListView).index == 2
        await pilot.press("up")
        await pilot.pause()
        assert app.screen.query_one("#session-list", ListView).index == 1

        # Enter resumes whatever is highlighted (the 2nd session).
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if transport.loaded:
                break
        assert transport.loaded == ["s2"]


@pytest.mark.asyncio
async def test_theme_picker_arrow_keys_move_selection():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#prompt").value = "/theme gallery"
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if isinstance(app.screen, ThemePicker):
                break
        assert isinstance(app.screen, ThemePicker)
        assert app.screen.query_one("#theme-list", ListView).index == 0
        await pilot.press("down")
        await pilot.pause()
        assert app.screen.query_one("#theme-list", ListView).index == 1
        await pilot.press("up")
        await pilot.pause()
        assert app.screen.query_one("#theme-list", ListView).index == 0
        app.screen.dismiss(None)


@pytest.mark.asyncio
async def test_resume_autosuggest_lists_recent_ten():
    transport = FakeTransport()
    # 12 sessions; only the most recent 10 should become suggestions.
    transport.sessions = [
        SessionSummary(
            session_id=f"{i:02d}cdef00" + "0" * 24,
            title=f"Chat {i}",
        )
        for i in range(12)
    ]
    app = PawApp(transport)
    async with app.run_test() as pilot:
        for _ in range(10):
            await pilot.pause()
            if app._session_commands:
                break
        names = [c.name for c in app._menu._commands]
        resume_entries = [n for n in names if n.startswith("resume ")]
        assert len(resume_entries) == 10  # capped at the 10 most recent
        # Short id + the session title as description, like /theme <id>.
        assert "resume 00cdef00" in names
        cmd = next(
            c for c in app._menu._commands if c.name == "resume 00cdef00"
        )
        assert cmd.description == "Chat 0"


@pytest.mark.asyncio
async def test_resume_with_id_arg_resumes_directly_without_picker():
    transport = FakeTransport()
    full_id = "00cdef00" + "0" * 24
    transport.sessions = [SessionSummary(session_id=full_id, title="Chat 0")]
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Trailing space closes the suggest menu so Enter submits the line.
        app.query_one("#prompt").value = "/resume 00cdef00 "
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if transport.loaded:
                break
        # Resolved the short id to the full session and resumed it directly.
        assert transport.loaded == [full_id]
        assert not isinstance(app.screen, SessionPicker)
        assert transport.sent == []


@pytest.mark.asyncio
async def test_resume_flag_skips_welcome_and_replays_at_start():
    transport = FakeTransport(resume_session_id="old-1")
    app = PawApp(transport, resume_session_id="old-1")
    async with app.run_test() as pilot:
        # Wait until the final replayed user turn is rendered. Polling
        # ``transport.loaded`` races the consume worker on event loops
        # with different scheduling (see twin test above).
        for _ in range(20):
            await pilot.pause()
            rendered = " ".join(
                u.content.plain for u in app.query(UserMessage)
            )
            if "Thanks!" in rendered:
                break
        # No welcome banner; the resumed transcript renders instead.
        assert not list(app.query(WelcomeMessage))
        assert transport.loaded == ["old-1"]
        user_msgs = " ".join(u.content.plain for u in app.query(UserMessage))
        assert "How do I write a loop in Rust?" in user_msgs
        assert "Thanks!" in user_msgs
        assert "old-1" in app.query_one(StatusBar).summary


@pytest.mark.asyncio
async def test_named_theme_command_applies_gallery_theme(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("PAW_STATE_DIR", str(tmp_path / "state"))
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt")
        prompt.value = "/theme cyberpunk"
        await pilot.press("enter")
        await pilot.pause()
        saved = (tmp_path / "state" / "theme.json").read_text(encoding="utf-8")
        assert "cyberpunk tiger-paw alley" in saved
        assert transport.sent == []


@pytest.mark.asyncio
async def test_terminal_title_uses_session_then_title():
    transport = FakeTransport()
    app = PawApp(transport)
    titles: list[str] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        # Capture what we write to the terminal.
        app._set_terminal_title = lambda t: titles.append(t)  # type: ignore

        app._on_connected(Connected(session_id="abcd1234ef", agent="a"))
        assert titles[-1] == "QwenPaw abcd1234"

        await app._dispatch(SessionTitle("Fix the parser"))
        await pilot.pause()
        assert titles[-1] == "QwenPaw Fix the parser"


@pytest.mark.asyncio
async def test_single_agent_label_per_turn_above_thinking():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        # thinking → tool → answer: exactly one "qwenpaw" label, and it sits
        # above the first activity (the thinking lane).
        await app._dispatch(ThoughtDelta("hmm"))
        await app._dispatch(
            ToolCall("t1", "grep", kind="search", status="in_progress"),
        )
        await app._dispatch(TextDelta("Done."))
        await pilot.pause()

        labels = list(app.query(AgentLabel))
        assert len(labels) == 1
        assert labels[0].content.plain == "qwenpaw"

        transcript = app.query_one("#transcript")
        types = [
            type(w).__name__
            for w in transcript.children
            if isinstance(
                w,
                (
                    AgentLabel,
                    ActivityLine,
                    ThoughtMessage,
                    ToolPanel,
                    AssistantMessage,
                ),
            )
        ]
        assert types[0] == "AgentLabel"
        assert types[1] == "ActivityLine"


@pytest.mark.asyncio
async def test_text_after_tool_mounts_below_it():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        # text → tool → more text: the transcript should read top-down in
        # that order (the post-tool text must not fold into the first bubble).
        await app._dispatch(TextDelta("Let me check."))
        await app._dispatch(
            ToolCall("t1", "grep", kind="search", status="in_progress"),
        )
        await app._dispatch(TextDelta("Found it."))
        await pilot.pause()

        transcript = app.query_one("#transcript")
        kinds = [
            type(w).__name__
            for w in transcript.children
            if isinstance(w, (AssistantMessage, ToolPanel))
        ]
        assert kinds == ["AssistantMessage", "ToolPanel", "AssistantMessage"]

        bubbles = list(app.query(AssistantMessage))
        assert bubbles[0].text == "Let me check."
        assert bubbles[1].text == "Found it."


@pytest.mark.asyncio
async def test_thinking_finalizes_to_thought_for():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._dispatch(ThoughtDelta("pondering..."))
        await pilot.pause()
        thought = app.query(ThoughtMessage).first()
        assert "thinking" in str(thought.title)
        assert not thought._finished

        # The visible answer beginning finalizes the thinking lane.
        await app._dispatch(TextDelta("Here is the answer."))
        await pilot.pause()
        assert thought._finished
        assert "thought for" in str(thought.title)


@pytest.mark.asyncio
async def test_live_token_estimate_then_exact():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one("StatusBar")

        # Stream 40 chars of assistant text → ~10 token estimate, marked "~".
        await app._dispatch(TextDelta("x" * 40))
        await pilot.pause()
        assert "↓~10" in bar.summary

        # Exact usage for the call replaces the estimate (no tilde).
        await app._dispatch(
            TokenUsage(input_tokens=1200, output_tokens=7, model="m"),
        )
        await pilot.pause()
        assert "↓7" in bar.summary
        assert "↓~" not in bar.summary
        assert "↑1.2k" in bar.summary
        assert app._tok_out == 7 and app._stream_chars == 0


@pytest.mark.asyncio
async def test_interrupt_action():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt")
        prompt.value = (
            "permission please"  # leaves it busy awaiting permission
        )
        await pilot.press("enter")
        await pilot.pause()
        app.query_one(PermissionOverlay).clear_request()
        app._busy = True
        await app.action_interrupt()
        assert transport.interrupted
        # The status bar reflects the request immediately.
        assert "interrupting" in app.query_one("StatusBar").summary


@pytest.mark.asyncio
async def test_escape_keypress_interrupts_when_busy():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._busy = True
        app.query_one("#prompt").focus()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert transport.interrupted


@pytest.mark.asyncio
async def test_escape_clears_input_when_idle():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt")
        prompt.value = "half-typed message"
        prompt.focus()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert prompt.value == ""
        assert not transport.interrupted  # idle esc never interrupts


@pytest.mark.asyncio
async def test_file_link_mounts_clickable_box_once():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        link = FileLink(uri="file:///tmp/report.pdf", name="report.pdf")
        event = ToolCall(
            "t1",
            "send_file_to_user",
            kind="other",
            status="completed",
            output="File sent successfully.",
            links=(link,),
        )
        await app._dispatch(event)
        await pilot.pause()

        boxes = list(app.query(FileLinkBox))
        assert len(boxes) == 1
        assert boxes[0]._uri == "file:///tmp/report.pdf"

        # A repeated update for the same tool call must not duplicate the link.
        await app._dispatch(event)
        await pilot.pause()
        assert len(list(app.query(FileLinkBox))) == 1


@pytest.mark.asyncio
async def test_messages_queue_while_busy_and_drain_on_turn_end():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Pretend the agent is mid-turn.
        app._busy = True
        prompt = app.query_one("#prompt")

        prompt.value = "first queued"
        await pilot.press("enter")
        prompt.value = "second queued"
        await pilot.press("enter")
        await pilot.pause()

        # Both wait in the queue (dimmed), nothing sent yet.
        assert [t for t, _ in app._queued] == ["first queued", "second queued"]
        assert len(list(app.query(QueuedMessage))) == 2
        assert transport.sent == []

        # The turn ends → the first queued message is delivered.
        await app._dispatch(TurnEnded())
        for _ in range(10):
            await pilot.pause()
            if not app._busy:
                break
        # FakeTransport auto-ends each turn, so the second drains too.
        for _ in range(10):
            await pilot.pause()
            if transport.sent == ["first queued", "second queued"]:
                break
        assert transport.sent == ["first queued", "second queued"]
        assert app._queued == []
        assert len(list(app.query(QueuedMessage))) == 0


@pytest.mark.asyncio
async def test_up_recalls_queued_message_to_edit():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._busy = True
        prompt = app.query_one("#prompt")

        prompt.value = "draft to fix"
        await pilot.press("enter")
        await pilot.pause()
        assert len(list(app.query(QueuedMessage))) == 1

        # ↑ pulls the last queued message back into the input for editing.
        await pilot.press("up")
        await pilot.pause()
        assert prompt.value == "draft to fix"
        assert app._queued == []
        assert len(list(app.query(QueuedMessage))) == 0
        assert transport.sent == []


@pytest.mark.asyncio
async def test_multiline_prompt_sends_full_text():
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt")
        prompt.value = "first line\nsecond line"
        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if transport.sent:
                break
        assert transport.sent == ["first line\nsecond line"]


@pytest.mark.asyncio
async def test_model_command_is_forwarded_to_agent():
    """paw no longer manages models — /model is QwenPaw's, so forwarded."""
    transport = QuietTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#prompt").value = "/model dashscope:qwen-max"
        await pilot.press("enter")
        await pilot.pause()
        assert transport.sent == ["/model dashscope:qwen-max"]


@pytest.mark.asyncio
async def test_long_paste_is_stored_as_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PAW_STATE_DIR", str(tmp_path / "state"))
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        replacement = await app._handle_prompt_paste("x" * 2200)
        assert replacement is not None
        path = replacement.removeprefix("[pasted text: ").removesuffix("]")
        assert "pasted-text" in path
        assert open(path, encoding="utf-8").read() == "x" * 2200


@pytest.mark.asyncio
async def test_file_path_paste_is_copied_to_attachment(tmp_path, monkeypatch):
    monkeypatch.setenv("PAW_STATE_DIR", str(tmp_path / "state"))
    source = tmp_path / "note.txt"
    source.write_text("hello", encoding="utf-8")
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        replacement = await app._handle_prompt_paste(str(source))
        assert replacement is not None
        path = replacement.removeprefix("[attached file: ").removesuffix("]")
        assert path.endswith(".txt")
        assert open(path, encoding="utf-8").read() == "hello"


@pytest.mark.asyncio
async def test_embedded_escaped_file_path_paste_is_copied(
    tmp_path,
    monkeypatch,
):
    import sys

    monkeypatch.setenv("PAW_STATE_DIR", str(tmp_path / "state"))
    source = tmp_path / "Screenshot 2026-06-06 at 9.31.17 PM.png"
    source.write_bytes(b"png")
    # On Unix: escape spaces with backslash (shell convention).
    # On Windows: quote the path (shell convention).
    if sys.platform == "win32":
        escaped = f'"{source}"'
    else:
        escaped = str(source).replace(" ", "\\ ")
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        replacement = await app._handle_prompt_paste(
            f"Can you describe this image? {escaped}",
        )
        assert replacement is not None
        assert replacement.startswith("Can you describe this image? ")
        assert str(source) not in replacement
        assert escaped not in replacement
        path = replacement.rsplit("[attached file: ", 1)[1].removesuffix("]")
        assert path.endswith(".png")
        assert open(path, "rb").read() == b"png"


@pytest.mark.asyncio
async def test_theme_prompt_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("PAW_STATE_DIR", str(tmp_path / "state"))
    transport = FakeTransport()
    app = PawApp(transport)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._apply_theme_prompt("rainbow workspace")
        await pilot.pause()
        assert "rainbow workspace" in (
            tmp_path / "state" / "theme.json"
        ).read_text(encoding="utf-8")
