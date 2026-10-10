# -*- coding: utf-8 -*-
"""Environment keys owned by the managed runtime boundary."""

import os
import sys
from pathlib import Path


_CONTROL_NAMES = {
    "BASH_ENV",
    "BASHOPTS",
    "COMSPEC",
    "ENV",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "PATH",
    "PATHEXT",
    "PSMODULEPATH",
    "SHELL",
    "SHELLOPTS",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "TEMP",
    "TMP",
    "TMPDIR",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "VIRTUAL_ENV",
    "WINDIR",
    "ZDOTDIR",
}
_CONTROL_PREFIXES = (
    "CONDA_",
    "DYLD_",
    "LD_",
    "PIP_",
    "PYTHON",
    "UV_",
    "QWENPAW_",
    "BASH_FUNC_",
)


def user_environment_key_allowed(name: str) -> bool:
    """Reject interpreter, installer, shell and boundary control settings."""
    identity = name.upper()
    return identity not in _CONTROL_NAMES and not identity.startswith(
        _CONTROL_PREFIXES,
    )


def system_environment() -> dict[str, str]:
    """Inherit only OS essentials, never host shell or package settings."""
    allowed = {"LANG", "LC_ALL", "LC_CTYPE"}
    if sys.platform == "win32":
        allowed.update({"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE"})
    environment = {
        key.upper(): value
        for key, value in os.environ.items()
        if key.upper() in allowed
    }
    if sys.platform == "win32":
        windows = Path(environment["SYSTEMROOT"])
        system = windows / "System32"
        environment["PATH"] = os.pathsep.join(
            [
                str(system),
                str(windows),
                str(system / "WindowsPowerShell/v1.0"),
            ],
        )
        environment["COMSPEC"] = str(system / "cmd.exe")
        environment["PATHEXT"] = ".COM;.EXE;.BAT;.CMD"
    else:
        environment["PATH"] = os.defpath
    return environment
