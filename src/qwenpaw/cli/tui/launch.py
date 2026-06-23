# -*- coding: utf-8 -*-
"""Launch the QwenPaw TUI.

``qwenpaw``                    open an interactive chat with the active agent
``qwenpaw tui``                same, with explicit options
``qwenpaw tui --agent NAME``   chat with a specific agent
``qwenpaw tui --resume ID``    resume a previous session and continue it

The TUI spawns ``qwenpaw acp`` using the *current* interpreter
(``python -m qwenpaw acp --local-diagnostics``), so it always drives the same
install/venv it ships in -- no reliance on ``qwenpaw`` being on ``PATH``.

Textual and the transport are imported lazily so ``qwenpaw --help`` and other
subcommands stay fast.
"""

from __future__ import annotations

import sys

import click


def _build_transport(
    *,
    agent: str | None,
    resume: str | None,
):
    """Return ``(transport, description)`` for the requested target.

    ``command=None`` lets :class:`AcpTransport` use its default,
    ``[sys.executable, "-m", "qwenpaw", "acp", "--local-diagnostics"]`` --
    the same interpreter the TUI is running under. The ``--agent`` suffix is
    *not* appended here: ``AcpTransport`` appends ``--agent <id>`` itself when
    ``agent`` is set, so doing it here too would double it.
    """
    from .transport.acp import AcpTransport

    description = (
        f"qwenpaw acp ({sys.executable} -m qwenpaw acp --local-diagnostics)"
    )

    return (
        AcpTransport(
            agent=agent,
            command=None,
            resume_session_id=resume,
        ),
        description,
    )


def run_tui(
    *,
    agent: str | None = None,
    resume: str | None = None,
) -> None:
    """Build the transport and run the Textual app (blocking)."""
    transport, description = _build_transport(
        agent=agent,
        resume=resume,
    )

    from .app import PawApp

    PawApp(
        transport,
        agent=agent or "default",
        target=description,
        resume_session_id=resume,
    ).run()


@click.command(
    "tui",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--agent",
    default=None,
    help="Agent ID to chat with (defaults to the active agent).",
)
@click.option(
    "--resume",
    default=None,
    metavar="SESSION_ID",
    help="Resume a previous session by id (use /resume in-app to browse). "
    "Replays that session's transcript and continues it.",
)
def tui_cmd(
    agent: str | None,
    resume: str | None,
) -> None:
    """Open the QwenPaw terminal chat UI."""
    run_tui(agent=agent, resume=resume)
