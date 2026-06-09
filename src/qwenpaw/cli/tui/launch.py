# -*- coding: utf-8 -*-
"""Launch the QwenPaw TUI.

``qwenpaw``                    open an interactive chat with the active agent
``qwenpaw tui``                same, with explicit options
``qwenpaw tui --agent NAME``   chat with a specific agent
``qwenpaw tui --agent-cmd ..`` drive an explicit ACP agent command (remote/dev)
``qwenpaw tui --resume ID``    resume a previous session and continue it

By default the TUI spawns ``qwenpaw acp`` using the *current* interpreter
(``python -m qwenpaw acp``), so it always drives the same install/venv it ships
in -- no reliance on ``qwenpaw`` being on ``PATH``. ``--agent-cmd`` overrides
this to point at any command that speaks ACP over stdio.

Textual and the transport are imported lazily so ``qwenpaw --help`` and other
subcommands stay fast.
"""

from __future__ import annotations

import shlex
import sys

import click


def _build_transport(
    *,
    agent: str | None,
    agent_cmd: str | None,
    resume: str | None,
):
    """Return ``(transport, description)`` for the requested target.

    The ``--agent`` suffix is *not* appended here: :class:`AcpTransport`
    appends ``--agent <id>`` itself when ``agent`` is set, so doing it here
    too would double it.
    """
    from .transport.acp import AcpTransport

    if agent_cmd:
        command: list[str] | None = shlex.split(agent_cmd)
        description = f"custom: {agent_cmd}"
    else:
        # ``None`` lets AcpTransport use its default:
        # ``[sys.executable, "-m", "qwenpaw", "acp"]`` -- the same interpreter
        # the TUI is running under.
        command = None
        description = f"qwenpaw acp ({sys.executable} -m qwenpaw acp)"

    return (
        AcpTransport(
            agent=agent,
            command=command,
            resume_session_id=resume,
        ),
        description,
    )


def run_tui(
    *,
    agent: str | None = None,
    agent_cmd: str | None = None,
    resume: str | None = None,
) -> None:
    """Build the transport and run the Textual app (blocking)."""
    transport, description = _build_transport(
        agent=agent,
        agent_cmd=agent_cmd,
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
    "--agent-cmd",
    default=None,
    metavar="COMMAND",
    help="Explicit command that speaks ACP over stdio "
    "(e.g. 'qwenpaw acp'). Overrides the default subprocess.",
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
    agent_cmd: str | None,
    resume: str | None,
) -> None:
    """Open the QwenPaw terminal chat UI."""
    run_tui(agent=agent, agent_cmd=agent_cmd, resume=resume)
