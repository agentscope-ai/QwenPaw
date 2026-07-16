# -*- coding: utf-8 -*-
"""Tests for startup terminal displays."""
from io import StringIO

from rich.console import Console

from qwenpaw.utils.startup_display import CustomAgentStartupProgress


def test_custom_agent_progress_renders_on_terminal() -> None:
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=True,
        color_system=None,
        width=100,
    )

    with CustomAgentStartupProgress(1, console=console) as progress:
        progress.advance("research")

    rendered = output.getvalue()
    assert "Starting custom agents: research" in rendered
    assert "1/1" in rendered


def test_custom_agent_progress_is_silent_without_tty() -> None:
    output = StringIO()
    console = Console(file=output, force_terminal=False)

    with CustomAgentStartupProgress(1, console=console) as progress:
        progress.advance("research")

    assert output.getvalue() == ""
