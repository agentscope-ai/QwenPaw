# -*- coding: utf-8 -*-
"""Managed runtime environment settings and installer version checks."""

import os
import re
import subprocess
import sys
from pathlib import Path


CERTIFI_REQUIREMENT = "certifi>=2026.10.19"


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


def _require_installer_version(
    command: list[str],
    name: str,
    minimum: tuple[int, int, int],
) -> bool:
    """Check the executable in use without downloading or changing packages."""
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if (
        name == "pip"
        and result.returncode
        and ("No module named pip" in result.stderr)
    ):
        return False
    result.check_returncode()
    match = re.match(
        rf"{name} (\d+(?:\.\d+)+)(?:\s|$)",
        result.stdout,
    )
    if not match or tuple(map(int, match[1].split("."))) < minimum:
        version = ".".join(map(str, minimum))
        raise RuntimeError(
            f"Unsafe {name} at {command[0]}; requires >= {version}. "
            "Upgrade this installer or update QwenPaw Desktop.",
        )
    return True


def require_pip(python: str, *, isolated: bool = False) -> bool:
    """Reject old pip in the selected execution mode; return False if absent."""
    return _require_installer_version(
        [
            python,
            *(["-I"] if isolated else []),
            "-B",
            "-m",
            "pip",
            "--version",
        ],
        "pip",
        (26, 2, 2),
    )


def require_uv(uv: str) -> None:
    """Reject an old uv executable before dependency downloads."""
    _require_installer_version([uv, "--version"], "uv", (0, 13, 4))
