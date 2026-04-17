# -*- coding: utf-8 -*-
"""Fancy startup display utilities using rich."""
from typing import Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


def print_ready_banner(api_info: Optional[Tuple[str, int]] = None) -> None:
    """Print a fancy QwenPaw ready banner with rich formatting.

    Args:
        api_info: Optional tuple of (host, port) for the server URL.
                 If None, displays a generic ready message.

    Example:
        >>> print_ready_banner(("127.0.0.1", 8088))
        # Displays a fancy panel with the server URL
        >>> print_ready_banner()
        # Displays a generic ready message
    """
    console = Console()

    # Create fancy title with gradient effect
    title = Text()
    title.append("✨ ", style="bold yellow")
    title.append("QwenPaw", style="bold cyan")
    title.append(" Ready!", style="bold green")

    if api_info:
        host, port = api_info
        url = f"http://{host}:{port}"

        # Create content with highlighted URL
        content = Text()
        content.append("Server is running at:\n", style="dim")
        content.append(url, style="bold blue underline")

        panel = Panel(
            content,
            title=title,
            border_style="bright_green",
            padding=(1, 2),
        )
    else:
        # Simple ready message without URL
        panel = Panel(
            "Server is ready!",
            title=title,
            border_style="bright_green",
            padding=(1, 2),
        )

    console.print(panel)
