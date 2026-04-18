# -*- coding: utf-8 -*-
"""Fancy startup display utilities using rich."""
from typing import Optional, Tuple

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree


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
    console.print()

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

    console.print(panel)
    console.print()
