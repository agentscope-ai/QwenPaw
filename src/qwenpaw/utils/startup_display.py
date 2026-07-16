# -*- coding: utf-8 -*-
"""Fancy startup display utilities using rich."""
from typing import Optional, Tuple

from rich import box
from rich.console import Console
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


class CustomAgentStartupProgress:
    """Render bounded custom-agent startup progress on interactive TTYs."""

    def __init__(
        self,
        total: int,
        console: Console | None = None,
    ) -> None:
        self._total = total
        self._console = console or Console()
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def __enter__(self) -> "CustomAgentStartupProgress":
        if self._total <= 0 or not self._console.is_terminal:
            return self

        try:
            self._progress = Progress(
                TextColumn("{task.description}", markup=False),
                BarColumn(),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                console=self._console,
                transient=False,
            )
            self._progress.start()
            self._task_id = self._progress.add_task(
                "Starting custom agents",
                total=self._total,
            )
        except OSError:
            self._progress = None
            self._task_id = None
        return self

    def advance(self, agent_id: str) -> None:
        """Advance after one custom agent reaches a terminal state."""
        if self._progress is None or self._task_id is None:
            return
        try:
            self._progress.update(
                self._task_id,
                advance=1,
                description=f"Starting custom agents: {agent_id}",
            )
        except OSError:
            self._stop()

    def __exit__(self, *_args) -> None:
        self._stop()

    def _stop(self) -> None:
        """Stop rendering without allowing console errors to abort startup."""
        if self._progress is None:
            return
        try:
            self._progress.stop()
        except OSError:
            pass
        finally:
            self._progress = None
            self._task_id = None


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

    if api_info:
        host, port = api_info
        url = f"http://{host}:{port}"

        # Create tree structure (Docker/K8s style)
        tree = Tree(
            "[bold green]✓[/bold green] [bold]QwenPaw[/bold]",
            guide_style="bright_black",
        )
        tree.add("[dim]Status:[/dim]  [bold green]Ready[/bold green]")
        tree.add(
            f"[dim]Address:[/dim] [blue underline]{url}[/blue underline]",
        )
        if elapsed_seconds is not None:
            tree.add(
                f"[dim]Startup:[/dim] [yellow]{elapsed_seconds:.3f}s[/yellow]",
            )

        # Wrap in clean panel (Apple style)
        panel = Panel(
            tree,
            border_style="green",
            box=box.ROUNDED,
            padding=(1, 2),
            expand=False,
        )
    else:
        # Simple ready message without URL
        tree = Tree(
            "[bold green]✓[/bold green] [bold]QwenPaw[/bold]",
            guide_style="bright_black",
        )
        tree.add("[dim]Status:[/dim]  [bold green]Ready[/bold green]")
        if elapsed_seconds is not None:
            tree.add(
                f"[dim]Startup:[/dim] [yellow]{elapsed_seconds:.3f}s[/yellow]",
            )

        panel = Panel(
            tree,
            border_style="green",
            box=box.ROUNDED,
            padding=(1, 2),
            expand=False,
        )

    _safe_print(console, panel)
    _safe_print(console)
