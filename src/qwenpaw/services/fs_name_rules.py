# -*- coding: utf-8 -*-
"""How one directory's filesystem compares the names inside it.

Two spellings can address the same directory entry, and *which* spellings
depends on the filesystem rather than on the operating system:

* **Case.** ``README.md`` and ``readme.md`` are one file on NTFS and on a
  default APFS volume, two files on ext4 — and also two on a
  case-sensitive APFS volume, or on a Windows directory carrying the
  per-directory case-sensitivity flag.
* **Unicode normalization.** macOS folds NFC and NFD, so one name spelled
  composed and decomposed is one entry there and two on Linux.

This module answers that question for **names that do not exist yet**,
which is what upload-conflict checking needs: before writing two uploads
into a directory, would the filesystem treat their names as one entry and
let the second silently replace the first? Inspecting existing entries
cannot answer that, so :func:`probe_name_rules` creates two spellings of a
throwaway name and looks at whether the second appears.

**For comparing directories that already exist, do not use this.** Ask the
filesystem which entry a path reaches, by comparing ``(st_dev, st_ino)`` —
:func:`qwenpaw.services.project_directory.dir_key` does. Identity is exact
where name rules are a heuristic: it is right across case folding, Unicode
normalization, symlinks, bind mounts and mount points, none of which a
name comparison gets right on its own. Name rules are only the fallback
for a path that has no entry to identify.
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NameRules:
    """Whether a directory distinguishes case and Unicode normalization.

    ``sensitive`` means the filesystem keeps the spellings apart, which is
    also the safe default: treating two names as distinct can at worst
    surface a duplicate, while wrongly merging them discards one of them.
    """

    case_sensitive: bool = True
    normalization_sensitive: bool = True

    def key(self, name: str) -> str:
        """The comparison key for *name* under these rules.

        Normalization is applied before the case fold because
        ``casefold()`` can itself change how a string decomposes; folding
        first would leave two spellings of one name with different keys.
        """
        comparable = (
            name
            if self.normalization_sensitive
            else unicodedata.normalize("NFC", name)
        )
        return comparable if self.case_sensitive else comparable.casefold()


# The answer when the filesystem cannot be asked. Windows and macOS fold
# case, macOS folds normalization: right for the default volumes of each
# and a guess everywhere else, which is why it is a fallback rather than
# the answer. Cygwin reports its own ``sys.platform`` while ``os.name``
# stays ``posix``, so both are checked.
_PLATFORM_RULES = NameRules(
    case_sensitive=not (
        os.name == "nt" or sys.platform in ("darwin", "win32", "cygwin")
    ),
    normalization_sensitive=sys.platform != "darwin",
)


def platform_name_rules() -> NameRules:
    """The per-platform guess, for paths whose filesystem cannot answer."""
    return _PLATFORM_RULES


def _aliases_by_write(directory: Path, first: str, second: str) -> bool:
    """Whether two spellings address the same entry, by creating one.

    Creates *first* and reports whether *second* then resolves, then
    removes it again. Answers for names that do not exist yet, which is
    the whole point: inspecting existing entries cannot.
    """
    first_path = directory / first
    second_path = directory / second
    descriptor = os.open(
        first_path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    os.close(descriptor)
    try:
        return second_path.exists()
    finally:
        first_path.unlink(missing_ok=True)


def probe_name_rules(directory: Path) -> NameRules:
    """Ask *directory*'s filesystem how it compares the names inside it.

    Writes and removes two throwaway dotfiles, so *directory* must exist
    and be writable; on any ``OSError`` the platform guess stands. This is
    filesystem I/O — call it from a worker thread, never from a coroutine.

    Deliberately not cached. The answer can change under a running process
    (a remount, a changed mount option, a Windows per-directory flag), and
    the caller runs this once per upload request, so caching would buy one
    syscall pair in exchange for serving a stale answer for the lifetime
    of the process.
    """
    token = secrets.token_hex(8)
    try:
        case_aliases = _aliases_by_write(
            directory,
            f".qwenpaw-case-{token}-a",
            f".QWENPAW-CASE-{token}-A",
        )
        # Both spellings are written as escapes on purpose: as literal
        # characters the two are indistinguishable in the source, and any
        # tool that normalized this file would collapse them into one
        # name, turning the probe into a tautology.
        normalization_aliases = _aliases_by_write(
            directory,
            f".qwenpaw-unicode-{token}-\u00e9",
            f".qwenpaw-unicode-{token}-e\u0301",
        )
    except OSError:
        logger.debug(
            "Could not probe name rules for %s; using the platform guess",
            directory,
            exc_info=True,
        )
        return _PLATFORM_RULES
    return NameRules(
        case_sensitive=not case_aliases,
        normalization_sensitive=not normalization_aliases,
    )


__all__ = [
    "NameRules",
    "platform_name_rules",
    "probe_name_rules",
]
