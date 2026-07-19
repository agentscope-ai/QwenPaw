# -*- coding: utf-8 -*-
"""Fancy startup display utilities using rich."""
import logging
from typing import Optional, Tuple, cast

from rich import box
from rich.console import Console, Group
from rich.file_proxy import FileProxy
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TaskProgressColumn,
    TextColumn,
)
from rich.tree import Tree


def _safe_print(console: Console, *args, **kwargs) -> None:
    """Call ``console.print`` with an OSError fallback for legacy Windows.

    On legacy Windows consoles Rich can raise
    ``OSError: [Errno 22] Invalid argument``.  When that happens we fall
    back to the built-in ``print`` so the application does not crash.
    """
    try:
        console.print(*args, **kwargs)
    except OSError:
        print(*args, **kwargs)


class AgentStartupDisplay:
    """Keep startup status visible below terminal logs on interactive TTYs."""

    def __init__(
        self,
        api_info: Optional[Tuple[str, int]] = None,
        console: Console | None = None,
    ) -> None:
        self._api_info = api_info
        self._console = console or Console(stderr=True)
        self._live: Live | None = None
        self._progress = self._create_progress()
        self._task_id: TaskID | None = None
        self._phase = "Starting core agents"
        self._elapsed_seconds: float | None = None
        self._redirected_handlers: list[
            tuple[logging.StreamHandler, object]
        ] = []

    def start(self) -> "AgentStartupDisplay":
        """Start the fixed terminal region when a TTY is available."""
        if self._live is not None or not self._console.is_terminal:
            return self

        try:
            self._live = Live(
                self._renderable(),
                console=self._console,
                auto_refresh=False,
                transient=True,
                redirect_stdout=True,
                redirect_stderr=True,
            )
            self._live.start()
            self._redirect_terminal_log_handlers()
        except OSError:
            self.stop()
        return self

    def mark_core_ready(self, elapsed_seconds: float) -> None:
        """Show that core agents are ready while custom agents continue."""
        self._phase = "Core agents ready"
        self._elapsed_seconds = elapsed_seconds
        self._refresh()

    def start_custom_agents(self, total: int) -> None:
        """Add the bounded custom-agent progress bar."""
        self._phase = "Starting custom agents"
        if total > 0 and self._task_id is None:
            self._task_id = self._progress.add_task(
                "Waiting for custom agents",
                total=total,
            )
        self._refresh()

    def advance(self, agent_id: str) -> None:
        """Advance after one custom agent reaches a terminal state."""
        if self._task_id is None:
            return
        try:
            self._progress.update(
                self._task_id,
                advance=1,
                description=f"Starting custom agents: {agent_id}",
            )
            self._refresh()
        except OSError:
            self.stop()

    def mark_finalizing(self) -> None:
        """Show that agent startup finished and services are finalizing."""
        self._phase = "Finalizing services"
        self._refresh()

    def complete(self, elapsed_seconds: float) -> None:
        """Keep a ready panel live, or print one for non-TTY output."""
        self._phase = "Ready"
        self._elapsed_seconds = elapsed_seconds
        if self._live is None:
            print_ready_banner(self._api_info, elapsed_seconds)
        else:
            self._refresh()

    def stop(self) -> None:
        """Stop rendering and restore redirected terminal log handlers."""
        live = self._live
        self._live = None
        if live is None:
            self._restore_terminal_log_handlers()
            return
        try:
            live.stop()
        except OSError:
            pass
        finally:
            self._restore_terminal_log_handlers()

    @staticmethod
    def _create_progress() -> Progress:
        """Create the progress renderable without starting a nested Live."""
        return Progress(
            TextColumn("{task.description}", markup=False),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            auto_refresh=False,
        )

    def _renderable(self) -> Group:
        """Build the current fixed startup panel and optional progress."""
        renderables = [
            _build_startup_panel(
                self._api_info,
                self._elapsed_seconds,
                status=self._phase,
                ready=self._phase == "Ready",
            ),
        ]
        if self._task_id is not None and self._phase != "Ready":
            renderables.append(self._progress)
        return Group(*renderables)

    def _refresh(self) -> None:
        """Refresh the live region without affecting startup on I/O errors."""
        if self._live is None:
            return
        try:
            self._live.update(self._renderable(), refresh=True)
        except OSError:
            self.stop()

    def _redirect_terminal_log_handlers(self) -> None:
        """Route terminal logs above Live while leaving file logs intact."""
        if self._live is None:
            return
        redirected_ids: set[int] = set()
        for logger in _iter_loggers():
            for handler in logger.handlers:
                if id(handler) in redirected_ids:
                    continue
                if not _is_terminal_stream_handler(
                    handler,
                    self._console.file,
                ):
                    continue
                stream_handler = cast(logging.StreamHandler, handler)
                stream = stream_handler.stream
                stream_handler.setStream(FileProxy(self._console, stream))
                self._redirected_handlers.append((stream_handler, stream))
                redirected_ids.add(id(stream_handler))

    def _restore_terminal_log_handlers(self) -> None:
        """Restore every handler stream changed for the Live display."""
        for handler, stream in reversed(self._redirected_handlers):
            try:
                handler.setStream(stream)
            except (AttributeError, ValueError):
                pass
        self._redirected_handlers.clear()


def _iter_loggers() -> list[logging.Logger]:
    """Return root and currently registered named loggers."""
    loggers = [logging.getLogger()]
    loggers.extend(
        logger
        for logger in logging.root.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    )
    return loggers


def _is_terminal_stream_handler(
    handler: logging.Handler,
    console_file: object,
) -> bool:
    """Return whether a handler writes to the interactive terminal."""
    if not isinstance(handler, logging.StreamHandler) or isinstance(
        handler,
        logging.FileHandler,
    ):
        return False
    stream = getattr(handler, "stream", None)
    if stream is console_file:
        return True
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def _build_startup_panel(
    api_info: Optional[Tuple[str, int]],
    elapsed_seconds: Optional[float],
    *,
    status: str,
    ready: bool,
) -> Panel:
    """Build a startup status panel shared by Live and final output."""
    status_color = "green" if ready else "yellow"
    marker = "✓" if ready else "•"
    tree = Tree(
        f"[bold {status_color}]{marker}[/bold {status_color}] "
        f"[bold]QwenPaw[/bold]",
        guide_style="bright_black",
    )
    tree.add(
        f"[dim]Status:[/dim]  "
        f"[bold {status_color}]{status}[/bold {status_color}]",
    )
    if api_info:
        host, port = api_info
        url = f"http://{host}:{port}"
        tree.add(
            f"[dim]Address:[/dim] [blue underline]{url}[/blue underline]",
        )
    if elapsed_seconds is not None:
        tree.add(
            f"[dim]Startup:[/dim] [yellow]" f"{elapsed_seconds:.3f}s[/yellow]",
        )
    return Panel(
        tree,
        border_style=status_color,
        box=box.ROUNDED,
        padding=(1, 2),
        expand=False,
    )


def print_ready_banner(
    api_info: Optional[Tuple[str, int]] = None,
    elapsed_seconds: Optional[float] = None,
) -> None:
    """Print a fancy QwenPaw ready banner with rich formatting.

    Args:
        api_info: Optional tuple of (host, port) for the server URL.
                 If None, displays a generic ready message.
        elapsed_seconds: Optional startup time in seconds to display.

    Example:
        >>> print_ready_banner(("127.0.0.1", 8088), 2.345)
        # Displays a fancy panel with the server URL and startup time
        >>> print_ready_banner()
        # Displays a generic ready message
    """
    console = Console()

    # Extra spacing before banner
    _safe_print(console)

    panel = _build_startup_panel(
        api_info,
        elapsed_seconds,
        status="Ready",
        ready=True,
    )

    _safe_print(console, panel)
    _safe_print(console)
