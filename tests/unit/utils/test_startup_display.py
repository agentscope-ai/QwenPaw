# -*- coding: utf-8 -*-
"""Tests for startup terminal displays."""
# pylint: disable=protected-access
from io import StringIO
import logging
from unittest.mock import patch

from rich.console import Console
from rich.file_proxy import FileProxy

from qwenpaw.utils.startup_display import AgentStartupDisplay


def test_startup_display_renders_progress_on_terminal() -> None:
    output = StringIO()
    console = Console(
        file=output,
        force_terminal=True,
        color_system=None,
        width=100,
    )
    display = AgentStartupDisplay(
        ("127.0.0.1", 8088),
        console=console,
    ).start()

    try:
        display.mark_core_ready(1.25)
        display.start_custom_agents(1)
        display.advance("research")
        display.stop()
        console.print(display._renderable())
        rendered = output.getvalue()
        assert "Starting custom agents: research" in rendered
        assert "1/1" in rendered
        assert "http://127.0.0.1:8088" in rendered
    finally:
        display.stop()


def test_startup_display_is_silent_without_tty() -> None:
    output = StringIO()
    console = Console(file=output, force_terminal=False)
    display = AgentStartupDisplay(console=console).start()

    display.mark_core_ready(1.0)
    display.start_custom_agents(1)
    display.advance("research")
    display.stop()

    assert output.getvalue() == ""


def test_startup_display_prints_final_banner_without_tty() -> None:
    console = Console(file=StringIO(), force_terminal=False)
    display = AgentStartupDisplay(console=console).start()

    with patch(
        "qwenpaw.utils.startup_display.print_ready_banner",
    ) as print_banner:
        display.complete(2.0)

    print_banner.assert_called_once_with(None, 2.0)


def test_startup_display_preserves_file_logging(tmp_path) -> None:
    terminal_output = StringIO()
    console = Console(
        file=terminal_output,
        force_terminal=True,
        color_system=None,
        width=100,
    )
    terminal_handler = logging.StreamHandler(terminal_output)
    log_path = tmp_path / "qwenpaw.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    formatter = logging.Formatter("%(levelname)s | %(message)s")
    terminal_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger = logging.getLogger("qwenpaw.test.startup_display")
    old_handlers = logger.handlers[:]
    old_level = logger.level
    old_propagate = logger.propagate
    logger.handlers = [terminal_handler, file_handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    display = AgentStartupDisplay(console=console)

    try:
        with patch(
            "qwenpaw.utils.startup_display.print_ready_banner",
        ) as print_banner:
            display.start()
            assert isinstance(terminal_handler.stream, FileProxy)
            assert file_handler.stream is not None
            assert not isinstance(file_handler.stream, FileProxy)

            logger.info("startup log")
            display.mark_core_ready(1.0)
            display.start_custom_agents(1)
            display.advance("research")
            display.complete(2.0)
            assert isinstance(terminal_handler.stream, FileProxy)
            print_banner.assert_not_called()
            display.stop()

        assert terminal_handler.stream is terminal_output
        assert log_path.read_text(encoding="utf-8") == ("INFO | startup log\n")
        assert "startup log" in terminal_output.getvalue()
    finally:
        display.stop()
        terminal_handler.close()
        file_handler.close()
        logger.handlers = old_handlers
        logger.setLevel(old_level)
        logger.propagate = old_propagate
