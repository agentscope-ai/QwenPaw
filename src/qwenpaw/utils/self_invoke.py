# -*- coding: utf-8 -*-
"""Build argv that re-invokes this QwenPaw installation as a subprocess.

``[sys.executable, "-m", "qwenpaw", ...]`` is only correct when
``sys.executable`` is a Python interpreter. In the packaged Desktop build it is
a frozen PyInstaller binary that has no ``-m``, so that argv dies with
``Error: No such option '-m'`` before writing a byte -- which is what an ACP
client sees as ``transport: Connection closed``.

Re-execing the bundled CPython (the trick ``tauri/entry.py`` uses for plugins
that spawn ``sys.executable -m <pkg>``) cannot help here: qwenpaw itself lives
inside the PyInstaller archive and is not importable from an external
interpreter. The packaged CLI binary takes subcommands directly instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Name of the packaged CLI binary (``scripts/pack-tauri/qwenpaw.spec``, the
# ``cli_exe`` EXE); its sibling in the same COLLECT dir is ``qwenpaw-backend``.
_CLI_STEM = "qwenpaw"


def qwenpaw_cli_command(*args: str) -> list[str]:
    """Return argv running ``qwenpaw <args>`` with this install's own code.

    Keyed on ``sys.frozen`` rather than ``tauri.env.DESKTOP_APP_ENV``: the
    question is whether *this very executable* accepts ``-m``, not whether we
    happen to be running inside the Desktop product. A pip-installed qwenpaw
    launched from a Desktop-spawned terminal inherits that env var but is still
    a normal interpreter.
    """
    if not bool(getattr(sys, "frozen", False)):
        return [sys.executable, "-m", "qwenpaw", *args]

    exe = Path(sys.executable)
    # The packaged CLI binary *is* the click entry point (tauri/cli_entry.py).
    if exe.stem.lower() == _CLI_STEM:
        return [str(exe), *args]

    # The packaged backend binary (tauri/entry.py) ignores argv and starts the
    # API server, so handing it a subcommand would silently boot a server that
    # never speaks the expected protocol on stdio. Use its sibling CLI instead.
    sibling = exe.with_name(_CLI_STEM + exe.suffix)
    if sibling.is_file():
        return [str(sibling), *args]

    raise RuntimeError(
        f"cannot locate the QwenPaw CLI binary next to {exe}; "
        f"unable to spawn 'qwenpaw {' '.join(args)}'",
    )
