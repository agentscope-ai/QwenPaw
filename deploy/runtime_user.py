#!/usr/bin/python3 -I
# -*- coding: utf-8 -*-
"""Run managed applications as the container-visible shared-directory owner.

This must stay stdlib-only: importing QwenPaw before dropping privileges would
create root-owned application state. Supervisor and system services stay root.
"""

from __future__ import annotations

import grp
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys


def shared_identity() -> tuple[Path, int, int]:
    """Read the mapped identity inside Docker, including rootless mounts."""
    working = Path(os.environ["QWENPAW_WORKING_DIR"])
    info = working.lstat()
    if not working.is_absolute() or not stat.S_ISDIR(info.st_mode):
        raise ValueError("QWENPAW_WORKING_DIR must be an absolute directory")
    # An unmapped bind owner is normally exposed as nobody/nogroup. Running
    # as that overflow identity would not restore the Hub's host access.
    if info.st_uid == 65534 or info.st_gid == 65534:
        raise ValueError(
            "Shared data has an unmapped UID/GID. Configure Docker's user "
            "namespace mapping so the Hub's data owner is mapped.",
        )
    return working, info.st_uid, info.st_gid


def repair_tree(root: Path, uid: int, gid: int) -> None:
    """Repair root-owned entries in stopped data without following links.

    Keep permission bits unchanged. Refuse hard-linked regular files rather
    than changing another name's ownership, and never cross nested mounts.
    """
    info = root.lstat()
    if (
        not root.is_absolute()
        or root.resolve() == Path("/")
        or not stat.S_ISDIR(info.st_mode)
    ):
        raise ValueError(f"Refusing ownership repair of {root}")
    mounts = mount_points()
    for directory, directories, files, descriptor in os.fwalk(root):
        directories[:] = [
            name
            for name in directories
            if (
                entry := os.stat(
                    name,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            ).st_dev
            == info.st_dev
            and stat.S_ISDIR(entry.st_mode)
            and Path(directory, name).resolve() not in mounts
        ]
        for name in files:
            entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if entry.st_dev != info.st_dev or not stat.S_ISREG(entry.st_mode):
                continue
            if Path(directory, name).resolve() in mounts:
                continue
            if entry.st_uid != 0 or uid == 0:
                continue
            if entry.st_nlink != 1:
                raise ValueError(
                    f"Refusing ownership repair of hard link {name}",
                )
            os.chown(name, uid, gid, dir_fd=descriptor, follow_symlinks=False)
        if os.fstat(descriptor).st_uid == 0 and uid != 0:
            os.fchown(descriptor, uid, gid)


def mount_points() -> set[Path]:
    """Include nested bind mounts, whose device ID may equal their parent's."""
    info = Path("/proc/self/mountinfo")
    if not info.exists():
        return set()
    return {
        Path(
            re.sub(
                r"\\([0-7]{3})",
                lambda match: chr(int(match[1], 8)),
                line.split()[4],
            ),
        )
        for line in info.read_text(
            encoding="utf-8",
            errors="surrogateescape",
        ).splitlines()
    }


def prepare_account(working: Path, uid: int, gid: int) -> str:
    """Provide an NSS identity for desktop tools when the UID is new."""
    try:
        account = pwd.getpwuid(uid)
    except KeyError:
        try:
            grp.getgrgid(gid)
        except KeyError:
            subprocess.run(
                ["groupadd", "--gid", str(gid), f"qwenpaw-{gid}"],
                check=True,
            )
        subprocess.run(
            [
                "useradd",
                "--no-create-home",
                "--no-user-group",
                "--no-log-init",
                "--uid",
                str(uid),
                "--gid",
                str(gid),
                "--home-dir",
                str(working),
                "--shell",
                "/bin/sh",
                f"qwenpaw-{uid}",
            ],
            check=True,
        )
        account = pwd.getpwuid(uid)
    return account.pw_name


def main(arguments: list[str]) -> None:
    """Drop application privileges, or explicitly repair stopped shared data."""
    if not arguments:
        raise ValueError("Expected a command or --repair-data")
    if os.environ.get("QWENPAW_RUNTIME_MODE") != "hub":
        if arguments == ["--repair-data"]:
            raise ValueError(
                "Ownership repair requires QWENPAW_RUNTIME_MODE=hub",
            )
        os.execvp(arguments[0], arguments)
        return

    working, uid, gid = shared_identity()
    if arguments == ["--repair-data"]:
        if os.geteuid() != 0:
            raise PermissionError("Ownership repair requires container root")
        for root in (
            working,
            Path(os.environ["QWENPAW_SECRET_DIR"]),
            Path(os.environ["QWENPAW_BACKUP_DIR"]),
        ):
            repair_tree(root, uid, gid)
        return

    if os.geteuid() == 0:
        username = prepare_account(working, uid, gid)
        if uid != 0 or gid != os.getegid():
            os.setgroups([])
            os.setgid(gid)
            os.setuid(uid)
    elif (os.geteuid(), os.getegid()) != (uid, gid):
        raise PermissionError("Cannot assume the shared data owner's UID/GID")
    else:
        username = pwd.getpwuid(uid).pw_name
    os.environ.update(
        HOME=str(working),
        USER=username,
        LOGNAME=username,
        QWENPAW_DEPENDENCY_STATE_DIR=str(working / ".dependency-environments"),
    )
    os.chdir(working)
    for name in (
        "QWENPAW_WORKING_DIR",
        "QWENPAW_SECRET_DIR",
        "QWENPAW_BACKUP_DIR",
    ):
        if not os.access(os.environ[name], os.R_OK | os.W_OK | os.X_OK):
            raise PermissionError(
                f"Cannot access {name}; stop the runtime and repair shared "
                "data ownership before restarting. See the Hub documentation.",
            )
    os.execvp(arguments[0], arguments)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"QwenPaw runtime identity: {error}", file=sys.stderr)
        sys.exit(1)
