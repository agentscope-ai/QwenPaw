# -*- coding: utf-8 -*-
"""Reusable safety check primitives.

Called by ACP permissions, ToolGuard guardians, and other security layers
to eliminate duplicated safety rule definitions.
"""
from __future__ import annotations

import os
import posixpath
import re
import shlex
from pathlib import Path, PurePath, PurePosixPath
from typing import Literal

DestructiveKind = Literal["catastrophic", "system_power"]

# Token boundary after a catastrophic path (whitespace, shell metachar, or
# closing quote / backtick).  Also treat ``\`` + quote as end so nested
# ``bash -c \"rm -rf /mnt/c/Users\"`` still matches (but bare ``\`` must
# NOT end a token — Windows ``C:\Users\me\project`` uses ``\`` separators).
_PATH_END = r"(?=[\s|;|&)\"'`]|\\[\"']|$)"

# After a recursive ``rm``, these targets are treated as catastrophic.
#
# Design notes:
# - Bare ``/`` / ``/*`` must be complete arguments (so ``/tmp`` is safe).
# - User *home roots* stay blocked (``/Users``, ``/Users/<user>``, ``~``,
#   ``~user``, ``$HOME``), plus home-content globs that wipe the home
#   (``/Users/<user>/*``, ``/Users/<user>/./*``, ``~/*``, ``~/./*``,
#   ``~user/*``, ``$HOME/*``, …).  Deeper concrete paths under the home
#   (typical workspaces such as ``/Users/<user>/proj/build`` or
#   ``~user/proj``) are NOT shared-catastrophic — otherwise default
#   auto-deny hard-rejects normal absolute-path cleanups on macOS/Linux.
#   YAML rules can still flag those for approval.
# - Critical system trees (``/etc``, ``/usr``, …) stay blocked in full.
# - macOS firmlink prefix ``/System/Volumes/Data/...`` is *not* matched by
#   the ``/system`` regex (negative lookahead).  Those spellings are
#   classified via resolve + :func:`_logical_posix_parts` so workspace /
#   temp cleanups under the firmlink are not default auto-denied, while
#   ``/System``, ``/System/Library``, and firmlink home roots stay blocked.
# - Temp trees stay allowed on *both* the regex and resolve paths:
#   ``/tmp``, ``/var/tmp``, ``/var/folders``, ``/private/tmp``,
#   ``/private/var/tmp``, ``/private/var/folders``.  Other ``/var/...`` /
#   ``/private/...`` stay blocked (regex must mirror
#   :func:`_is_safe_temp_tree`, otherwise macOS canonical
#   ``/private/tmp/...`` / ``/private/var/tmp/...`` is auto-denied).
# - ``/mnt``, ``/media``, ``/run``, ``/srv`` are root-only (plus ``/*``
#   content globs) — NOT full-subtree.  Emulated-Windows *workspaces*
#   (WSL ``/mnt/<d>/Users/<user>/project``, Git Bash ``/c/Users/.../proj``,
#   Cygwin ``/cygdrive/c/...``) stay allowed, but drive/Users/Windows
#   wipe equivalents stay blocked.
# - ``/Volumes`` (macOS external / mounted disks) is depth-capped like
#   home: ``/Volumes``, ``/Volumes/<vol>``, and volume-content globs are
#   catastrophic; deeper project paths such as
#   ``/Volumes/External/project/build`` stay allowed.
# - Path forms like ``/./``, ``//``, ``foo/..``, ``~/././*``, ``~/..`` are
#   handled by expanding ``~`` / ``$HOME`` *then* normalizing each rm
#   target (see :func:`_normalize_rm_path_token`).  Never ``normpath``
#   before expand — ``~/..`` would collapse to ``.`` and bypass.  Do not
#   add more literal bypass regexes.
# - Glued end-of-options forms like ``--/*`` / ``--/`` are accepted via
#   an optional ``--`` prefix (real long-options stay in the flag group).
_ONE_SEGMENT = r"[^/\s|;|&)\"']+"
# macOS volume names commonly contain spaces (``My Disk``); allow them
# inside a single path segment so ``"/Volumes/My Disk/proj"`` is not
# truncated at the space and mis-classified as a volume-root wipe.
_VOLUME_SEGMENT = r"[^/\"';|&)]+"
# Home-content wipe globs: ``/*`` and the equivalent ``/./*``.
_HOME_STAR_GLOB = r"(?:/\*|/\./\*)"
# Suffix after WSL/Git Bash/Cygwin drive prefix (raw-string; bash -c safe).
_EMULATED_DRIVE_SUFFIX = (
    r"(?:"
    + r"/?"
    + _PATH_END
    + r"|/\*"
    + r"|/[Ww]indows(?:/|"
    + _PATH_END
    + r")"
    + r"|/[Uu]sers(?:/"
    + _ONE_SEGMENT
    + r")?"
    + _HOME_STAR_GLOB
    + r"?/?"
    + _PATH_END
    + r")"
)
_RM_CATASTROPHIC_TARGET = (
    r"(?:"
    r"['\"]?"
    # Optional glued ``--`` before a path-like token (``--/*``, ``--/``).
    r"(?:--(?=[/\.~*$%]))?"
    r"(?:"
    # / or /*
    + r"/(?:" + _PATH_END + r"|\*)"
    # Home roots + home-content globs:
    #   /home, /Users, /home/<user>, /Users/<user>,
    #   /home/*, /Users/<user>/*, /Users/<user>/./* , …
    # (NOT /Users/<user>/project/...).
    + r"|/(?:home|users)(?:/"
    + _ONE_SEGMENT
    + r")?"
    + _HOME_STAR_GLOB
    + r"?/?"
    + _PATH_END
    # Critical system trees (full subtree).  ``system`` is separate so the
    # macOS firmlink prefix ``/System/Volumes/Data/...`` can fall through
    # to resolve + _logical_posix_parts (same policy as /Users, /tmp, …).
    + r"|/(?:root|boot|dev|applications|etc|usr|bin|sbin|lib|"
    r"opt|windows|library|proc|sys)"
    + r"(?:/|"
    + _PATH_END
    + r")"
    + r"|/system(?!/volumes/data(?:/|\b))(?:/|"
    + _PATH_END
    + r")"
    # Emulated Windows drive wipes (raw match so bash -c "rm -rf /mnt/c"
    # still hits; depth-capped like resolve path).
    + r"|/mnt/[A-Za-z]"
    + _EMULATED_DRIVE_SUFFIX
    + r"|/cygdrive/[A-Za-z]"
    + _EMULATED_DRIVE_SUFFIX
    + r"|/[A-Za-z]"
    + _EMULATED_DRIVE_SUFFIX
    # Mount/runtime roots only (+ /*), not full subtree (WSL /mnt/c/...).
    + r"|/(?:mnt|media|run|srv)" + _HOME_STAR_GLOB + r"?/?" + _PATH_END
    # macOS /Volumes: volume root + content globs only, not project paths.
    # Atomic volume segment prevents backtracking to a whitespace PATH_END
    # inside names like ``My Disk`` (otherwise ``/Volumes/My`` false-hits).
    + r"|/volumes(?:/(?>"
    + _VOLUME_SEGMENT
    + r")(?:"
    + _HOME_STAR_GLOB
    + r")?/?"
    + r"|"
    + _HOME_STAR_GLOB
    + r")?"
    + _PATH_END
    # /var/* except temp trees /var/tmp and /var/folders
    + r"|/var(?!/(?:tmp|folders)\b)(?:/|" + _PATH_END + r")"
    # /private/* except /private/tmp and /private/var/{tmp,folders}
    + r"|/private(?!/(?:tmp|var/(?:tmp|folders))\b)(?:/|" + _PATH_END + r")"
    # ~ / ~/ / ~/* / ~/./*  (not ~/proj)
    + r"|~" + _HOME_STAR_GLOB + r"?/?" + _PATH_END
    # ~user / ~user/* / ~user/./*  (not ~user/proj)
    + r"|~" + _ONE_SEGMENT + _HOME_STAR_GLOB + r"?/?" + _PATH_END
    # $HOME / $HOME/* / $HOME/./*
    + r"|\$(?:\{HOME\}|HOME)" + _HOME_STAR_GLOB + r"?/?" + _PATH_END
    # %USERPROFILE% / %USERPROFILE%\* / %USERPROFILE%\./*
    + r"|%USERPROFILE%(?:[\\/](?:\./)?\*)?"
    + _PATH_END
    + r"|\*"
    + r")"
    + r"['\"]?"
    + r")"
)

_RM_RECURSIVE_LOOKAHEAD = r"(?=[^\n]*(?:-[a-z]*r[a-z]*|--recursive|-Recurse))"

# Real rm options only — do NOT treat ``--/*`` / ``--/`` as flags.
_RM_OPTION_TOKEN = r"(?:-[a-zA-Z][\w]*|--[a-zA-Z][\w-]*|--(?=[\s\"';|&)]|$))"

# Windows catastrophic targets (parity with Unix /Users + /Windows).
# Accept ``\`` and ``/`` separators (PowerShell accepts both).  ``..``
# spellings are handled by :func:`_windows_resolved_target_is_catastrophic`.
# - drive root: C:\ / C:/ / C:\* / C:/*
# - users root: C:\Users, C:/Users/*, C:\Users\me, …
#   (NOT C:\Users\me\project\...)
# - Windows tree: C:\Windows / C:/Windows and full subtree
_WIN_SEP = r"[\\/]"
_WIN_ONE_SEGMENT = r"[^\\/\"\s|;|&)]+"
_WIN_CATASTROPHIC_TARGET = (
    r"(?:"
    + r"['\"]?[A-Za-z]:"
    + _WIN_SEP
    + r"?(?:\*|['\"]|"
    + _PATH_END
    + r")"
    + r"|['\"]?[A-Za-z]:"
    + _WIN_SEP
    + r"Users"
    + r"(?:"
    + _WIN_SEP
    + _WIN_ONE_SEGMENT
    + r")?"
    + r"(?:"
    + _WIN_SEP
    + r"\*)?"
    + _WIN_SEP
    + r"?"
    + r"['\"]?"
    + _PATH_END
    + r"|['\"]?[A-Za-z]:"
    + _WIN_SEP
    + r"Windows(?:"
    + _WIN_SEP
    + r"[^\"\s|;|&)]*)?['\"]?"
    + _PATH_END
    + r")"
)

# Drive-letter path token (for extract + normalize); allows ``..`` segments.
# Require a path boundary before the letter and a ``\`` / ``/`` after ``:``
# (or a bare ``C:`` at end-of-arg).  Never match inside ``$env:TEMP``,
# ``version:1``, ``namespace:pkg``, ``foo:bar``, etc.
_RE_WIN_PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_$])"
    r"("
    r"[A-Za-z]:(?:[\\/][^\\/\"'\s|;|&)]*)+"  # C:\... or C:/...
    r"|[A-Za-z]:(?=[\s|;|&)\"']|$)"  # bare C: as its own argument
    r")",
    re.IGNORECASE,
)

# cmd percent-env paths (rd/del) — home / system / drive equivalents.
_WIN_ENV_TAIL = r"(?:[\\/][^\\/\"'\s|;|&)%]*)*[\\/]?"
_RE_WIN_ENV_PATH_TOKEN = re.compile(
    r"(?:"
    r"%(?:USERPROFILE|PUBLIC|SystemRoot|WINDIR|SystemDrive)%"
    + _WIN_ENV_TAIL
    + r"|%HOMEDRIVE%(?:[\\/]?%HOMEPATH%)"
    + _WIN_ENV_TAIL
    + r")",
    re.IGNORECASE,
)
# PowerShell home / system / drive forms (and HOMEDRIVE+HOMEPATH combos).
_RE_PS_HOME_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])" + r"("
    # Bare ``~`` / ``~/path`` only — never carve ``~`` out of ``~alice/...``.
    + r"~(?=[\\/]|[\s|;|&)\"']|$)"
    + r"(?:[\\/][^\\/\"'\s|;|&)]*)*"
    + r"|\$HOME(?:[\\/][^\\/\"'\s|;|&)]*)*"
    + r"|\$\{HOME\}(?:[\\/][^\\/\"'\s|;|&)]*)*"
    + r"|\$env:(?:USERPROFILE|PUBLIC|SystemRoot|WinDir|SystemDrive)"
    + r"(?:[\\/][^\\/\"'\s|;|&)]*)*"
    + r"|\$env:HOMEDRIVE(?:[\\/]?\$env:HOMEPATH)"
    + r"(?:[\\/][^\\/\"'\s|;|&)]*)*"
    + r")",
    re.IGNORECASE,
)

# Align with rule_guardian: unwrap $(which rm) / `which rm` / ${RM:-rm}.
_RM_INDIRECT_UNWRAP: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\$\([^)]*\brm\b[^)]*\)", re.IGNORECASE), "rm"),
    (re.compile(r"`[^`]*\brm\b[^`]*`", re.IGNORECASE), "rm"),
    (re.compile(r"\$\{[^}]*:-rm\}", re.IGNORECASE), "rm"),
    (re.compile(r"\$\{[^}]*\brm\b[^}]*\}", re.IGNORECASE), "rm"),
)

_RE_WIN_RECURSIVE_CMD = re.compile(
    r"(?:"
    r"\b(?:Remove-Item|ri)\b(?=[^\n]*-(?:Recurse|r)\b)"
    r"|\bdel\b(?=[^\n]*/[sS]\b)"
    r"|\b(?:rd|rmdir)\b(?=[^\n]*/[sS]\b)"
    r"|\brm\b(?=[^\n]*-Recurse\b)"
    r")",
    re.IGNORECASE,
)

# Patterns that warrant default ToolGuard auto-deny (and ACP hard-block).
_CATASTROPHIC_PATTERNS: tuple[str, ...] = (
    (
        r"\brm\b"
        + _RM_RECURSIVE_LOOKAHEAD
        + r"(?:\s+"
        + _RM_OPTION_TOKEN
        + r")+\s+"
        + _RM_CATASTROPHIC_TARGET
    ),
    (
        r"\b(?:Remove-Item|ri)\b(?=[^\n]*-(?:Recurse|r)\b)"
        + r"[^\n]*"
        + _WIN_CATASTROPHIC_TARGET
    ),
    (r"\brm\b(?=[^\n]*-Recurse\b)" + r"[^\n]*" + _WIN_CATASTROPHIC_TARGET),
    # Require recursive (/s) so bare ``del C:\`` / ``rd C:\`` are not hit.
    r"\bdel\b(?=[^\n]*/[sS]\b)\s+(?:/[a-zA-Z]+\s+)*"
    + _WIN_CATASTROPHIC_TARGET,
    (
        r"\b(?:rd|rmdir)\b(?=[^\n]*/[sS]\b)\s+(?:/[a-zA-Z]+\s+)*"
        + _WIN_CATASTROPHIC_TARGET
    ),
    r"\bformat\s+[A-Za-z]:",
    # Command-position only — avoids ``npm run mkfs`` false positives.
    r"(?:^|[\n;|&]\s*)(?:sudo\s+)?mkfs(?:\.[a-z0-9_]+)?\b",
    r"(?:^|[\n;|&]\s*)(?:sudo\s+)?mke2fs\b",
    r"(?:^|[\n;|&]\s*)(?:sudo\s+)?dd\s+.*\b(?:if|of)=/dev/",
    r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
)

# Still hard-blocked by ACP / surfaced for approval, but NOT auto-denied
# by default (bare-word ``reboot`` must not DENY ``npm run reboot``).
_SYSTEM_POWER_PATTERNS: tuple[str, ...] = (
    r"(?:^|[\n;|&]\s*)(?:sudo\s+)?(?:shutdown|reboot|halt|poweroff)\b",
)

_CATASTROPHIC_COMPILED = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _CATASTROPHIC_PATTERNS
)
_SYSTEM_POWER_COMPILED = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _SYSTEM_POWER_PATTERNS
)

_RE_RECURSIVE_RM = re.compile(
    r"\brm\b(?=[^\n]*(?:-[a-z]*r[a-z]*|--recursive|-Recurse))",
    re.IGNORECASE,
)

# Kept for callers/tests that iterate blocked pattern strings.
BLOCKED_COMMAND_PATTERNS: tuple[str, ...] = (
    _CATASTROPHIC_PATTERNS + _SYSTEM_POWER_PATTERNS
)

# Full-subtree catastrophic tops (home / volumes / mount-runtime are
# depth-capped separately).
_CATASTROPHIC_TOP_LEVEL = frozenset(
    {
        "root",
        "boot",
        "dev",
        "applications",
        "etc",
        "usr",
        "bin",
        "sbin",
        "lib",
        "opt",
        "system",
        "windows",
        "library",
        "proc",
        "sys",
        "private",
        "var",
    },
)

# /home, /Users, /home/<user>, /Users/<user> only (len 2 or 3).
_HOME_TOP_LEVEL = frozenset({"home", "users"})

# /Volumes, /Volumes/<volume> only (len 2 or 3).  Deeper paths are
# common workspaces on external / mounted disks.
_VOLUMES_TOP_LEVEL = "volumes"

# /mnt, /media, /run, /srv roots only (len == 2).  Deeper paths are
# common workspaces (WSL ``/mnt/c/...``, USB ``/media/...``).
_MOUNT_RUNTIME_TOP_LEVEL = frozenset({"mnt", "media", "run", "srv"})


def _coerce_posix_root_parts(parts: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize host Path roots so POSIX absolute paths compare as ``/``.

    On Windows, ``Path('/etc')`` / ``PureWindowsPath('/etc')`` yield
    ``('\\\\', 'etc')`` rather than ``('/', 'etc')``.  Without coercion,
    resolve fallbacks miss catastrophic POSIX targets in CI on Windows.
    """
    if parts and parts[0] in {"/", "\\"}:
        return ("/", *parts[1:])
    return parts


def _logical_posix_parts_from(parts: tuple[str, ...]) -> tuple[str, ...]:
    """Strip macOS ``/System/Volumes/Data`` firmlink from POSIX parts."""
    parts = _coerce_posix_root_parts(parts)
    if (
        len(parts) >= 5
        and parts[0] == "/"
        and parts[1] == "System"
        and parts[2] == "Volumes"
        and parts[3] == "Data"
    ):
        return ("/", *parts[4:])
    return parts


def _logical_posix_parts(resolved: Path | PurePath) -> tuple[str, ...]:
    """Strip macOS ``/System/Volumes/Data`` firmlink from POSIX parts.

    On macOS, ``Path('/home/...').resolve()`` often lands under
    ``/System/Volumes/Data/home/...``.  Classification must see the
    logical ``/home/...`` path, otherwise every ``/home`` workspace wipe
    is mis-labeled as a ``/System`` wipe.
    """
    return _logical_posix_parts_from(resolved.parts)


def _is_safe_temp_tree(parts: tuple[str, ...]) -> bool:
    """Return True for typical temp / pytest workspace roots."""
    if len(parts) >= 2 and parts[1] == "tmp":
        return True
    if (
        len(parts) >= 3
        and parts[1] == "var"
        and parts[2] in {"tmp", "folders"}
    ):
        return True
    if len(parts) >= 3 and parts[1] == "private" and parts[2] == "tmp":
        return True
    # macOS: /var/tmp -> /private/var/tmp; /var/folders -> same under
    # /private/var/folders.
    if (
        len(parts) >= 4
        and parts[1] == "private"
        and parts[2] == "var"
        and parts[3] in {"tmp", "folders"}
    ):
        return True
    return False


def _is_resolved_path_catastrophic(resolved: Path | PurePath) -> bool:
    """Return True when a fully resolved path is a catastrophic wipe target."""
    # pylint: disable=too-many-return-statements
    raw_parts = _coerce_posix_root_parts(resolved.parts)
    if not raw_parts:
        return False

    # POSIX / Windows root.
    if (resolved.anchor and len(raw_parts) == 1) or raw_parts == ("/",):
        return True

    parts = _logical_posix_parts_from(resolved.parts)
    if _is_safe_temp_tree(parts):
        return False

    # Windows native Path parts (when running on Windows).
    if _windows_drive_parts_are_catastrophic(resolved.parts):
        return True

    # POSIX: ('/', 'etc', ...)
    if parts[0] != "/" or len(parts) < 2:
        return False
    top = parts[1].lower()
    # Home trees: only the home root itself, not workspace subpaths.
    # ('/', 'Users') or ('/', 'Users', 'alice') → catastrophic
    # ('/', 'Users', 'alice', 'proj') → not
    if top in _HOME_TOP_LEVEL:
        return len(parts) <= 3
    # macOS volumes: /Volumes or /Volumes/<vol> only — not project paths
    # under an external disk (e.g. /Volumes/External/project/build).
    if top == _VOLUMES_TOP_LEVEL:
        return len(parts) <= 3
    # Emulated Windows: WSL /mnt/<d>, Git Bash /<d>, Cygwin /cygdrive/<d>.
    if _is_emulated_windows_path_catastrophic(parts):
        return True
    # Mount/runtime roots only (WSL *project* paths under /mnt/c/... allowed).
    if top in _MOUNT_RUNTIME_TOP_LEVEL:
        return len(parts) == 2
    return top in _CATASTROPHIC_TOP_LEVEL


def _is_posix_abs_token_catastrophic(token: str) -> bool:
    """Classify a ``/…`` token with PurePosixPath (host-OS independent).

    Host ``Path('/etc')`` on Windows uses a ``\\\\`` root and may resolve to
    ``C:\\etc``, which is *not* a Windows-drive wipe.  Policy for shell
    commands that spell POSIX absolute targets must follow POSIX parts.
    """
    return _is_resolved_path_catastrophic(PurePosixPath(token))


def _windows_drive_parts_are_catastrophic(parts: tuple[str, ...]) -> bool:
    """Return True for ``C:`` / ``C:\\Users`` / ``C:\\Windows``-style parts."""
    if not parts:
        return False
    drive = parts[0]
    # Path may yield ``C:`` (POSIX) or ``C:\\`` (Windows).
    if not (len(drive) >= 2 and drive[0].isalpha() and drive[1] == ":"):
        return False
    if len(parts) == 1:
        return True
    top = parts[1].lower()
    if top == "windows":
        return True
    if top == "users":
        # C:\Users or C:\Users\me — not C:\Users\me\project
        return len(parts) <= 3
    return False


def _emulated_drive_suffix_is_catastrophic(suffix: tuple[str, ...]) -> bool:
    """Classify path segments after ``/mnt/c``, ``/c``, or ``/cygdrive/c``."""
    if not suffix:
        return True  # drive root
    top = suffix[0].lower()
    if top == "windows":
        return True
    if top == "users":
        # Users or Users/<user> — not deeper project paths.
        return len(suffix) <= 2
    return False


def _is_emulated_windows_path_catastrophic(parts: tuple[str, ...]) -> bool:
    """WSL / Git Bash / Cygwin paths equivalent to Windows drive wipes.

    Blocked: ``/mnt/c``, ``/c/Users``, ``/cygdrive/c/Windows/System32``, …
    Allowed: ``/mnt/c/Users/alice/project/build``, ``/c/Users/alice/proj``.
    """
    if not parts or parts[0] != "/":
        return False
    # WSL: /mnt/<drive>/...
    if (
        len(parts) >= 3
        and parts[1].lower() == "mnt"
        and len(parts[2]) == 1
        and parts[2].isalpha()
    ):
        return _emulated_drive_suffix_is_catastrophic(parts[3:])
    # Cygwin: /cygdrive/<drive>/...
    if (
        len(parts) >= 3
        and parts[1].lower() == "cygdrive"
        and len(parts[2]) == 1
        and parts[2].isalpha()
    ):
        return _emulated_drive_suffix_is_catastrophic(parts[3:])
    # Git Bash / MSYS: /<drive>/...
    if len(parts) >= 2 and len(parts[1]) == 1 and parts[1].isalpha():
        return _emulated_drive_suffix_is_catastrophic(parts[2:])
    return False


def _parse_windows_path_parts(token: str) -> tuple[str, ...] | None:
    """Parse ``C:/Users/me`` / ``C:\\Users\\me`` into drive-letter parts."""
    unified = token.replace("\\", "/").rstrip("/")
    match = re.match(r"^([A-Za-z]:)(/.*)?$", unified)
    if match is None:
        return None
    drive = match.group(1).upper()
    rest = match.group(2) or ""
    segs = tuple(seg for seg in rest.split("/") if seg and seg != ".")
    return (drive, *segs)


def _windows_token_is_catastrophic(token: str) -> bool:
    """Classify a normalized Windows drive-letter token (no Path.resolve)."""
    parts = _parse_windows_path_parts(token)
    if parts is None:
        return False
    return _windows_drive_parts_are_catastrophic(parts)


def _system_drive_env_is_catastrophic(upper: str, prefix: str) -> bool:
    """Classify ``%SystemDrive%`` / ``$env:SystemDrive`` wipe forms."""
    if upper in {prefix, prefix + "/*"}:
        return True
    if not upper.startswith(prefix + "/"):
        return False
    rest = [s for s in upper[len(prefix) + 1 :].split("/") if s]
    if not rest or rest == ["*"]:
        return True
    if rest[0] == "WINDOWS":
        return True
    if rest[0] == "USERS":
        return len(rest) <= 2 or (len(rest) == 3 and rest[2] == "*")
    return False


def _windows_env_token_is_catastrophic(token: str) -> bool:
    """Classify Windows env-form home / system / drive wipe tokens."""
    # pylint: disable=too-many-return-statements
    unified = token.replace("\\", "/").rstrip("/")
    upper = unified.upper()

    # %SystemRoot% / %WINDIR% / $env:SystemRoot / $env:windir (+ /..).
    for prefix in (
        "%SYSTEMROOT%",
        "%WINDIR%",
        "$ENV:SYSTEMROOT",
        "$ENV:WINDIR",
    ):
        if upper == prefix or upper.startswith(prefix + "/"):
            return True

    # %SystemDrive% / $env:SystemDrive → same policy as C:\ .
    for prefix in ("%SYSTEMDRIVE%", "$ENV:SYSTEMDRIVE"):
        if _system_drive_env_is_catastrophic(upper, prefix):
            return True

    # Bare home-equivalent env roots (%USERPROFILE%, %PUBLIC%,
    # %HOMEDRIVE%%HOMEPATH%, $env:… counterparts).
    home_match = _RE_UNEXPANDED_HOME_PREFIX.match(unified)
    if home_match is not None and home_match.end() == len(unified):
        return True

    return _unexpanded_home_targets_home_or_above(unified)


_RE_RM_LONG_OPT = re.compile(r"^--[a-zA-Z][\w-]*$")
_RE_RM_SHORT_OPT = re.compile(r"^-[a-zA-Z][\w]*$")


def _strip_glued_endopts_prefix(token: str) -> str:
    """Turn glued ``--/*`` / ``--/`` into the underlying path token."""
    if token.startswith("--") and len(token) > 2 and token[2] in "/\\.~*$%":
        return token[2:]
    return token


def _is_rm_option_token(token: str, *, end_of_opts: bool) -> bool:
    """Return True for real ``rm`` flags; path-like ``--/*`` is not a flag."""
    if end_of_opts:
        return False
    if token == "--":
        return True
    if _RE_RM_SHORT_OPT.fullmatch(token) or _RE_RM_LONG_OPT.fullmatch(token):
        return True
    return False


# Applied to *normalized* tokens (``/./*`` already collapsed to ``/*``).
_RE_HOME_CONTENT_GLOB = re.compile(
    r"^(?:"
    r"/(?:home|users)(?:/[^/]+)?/\*"
    r"|~[^/]*/\*"  # ~/* and ~user/*
    r"|\$(?:\{HOME\}|HOME)/\*"
    r"|\$env:(?:USERPROFILE|PUBLIC)[\\/]\*"
    r"|%(?:USERPROFILE|PUBLIC)[\\/]\*"
    r"|%HOMEDRIVE%(?:[\\/]?%HOMEPATH%)[\\/]\*"
    r"|\$env:HOMEDRIVE(?:[\\/]?\$env:HOMEPATH)[\\/]\*"
    r")$",
    re.IGNORECASE,
)

# Bare named-user home: ~alice (not ~/project, not ~alice/project).
_RE_NAMED_USER_HOME = re.compile(r"^~[^/]+/?$")

# Home / system prefixes that must not be ``normpath``'d before classify
# (otherwise ``%WINDIR%/..`` / ``%USERPROFILE%\..`` collapse to ``.``).
_RE_UNEXPANDED_HOME_PREFIX = re.compile(
    r"^(?:"
    r"~[^/]*"
    r"|\$(?:\{HOME\}|HOME)"
    r"|\$env:(?:USERPROFILE|PUBLIC)"
    r"|%(?:USERPROFILE|PUBLIC)%"
    r"|%HOMEDRIVE%(?:[\\/]?%HOMEPATH%)"
    r"|\$env:HOMEDRIVE(?:[\\/]?\$env:HOMEPATH)"
    r")(?=/|$)",
    re.IGNORECASE,
)
_RE_UNEXPANDED_WIN_SYS_PREFIX = re.compile(
    r"^(?:"
    r"%(?:SystemRoot|WINDIR|SystemDrive)%"
    r"|\$env:(?:SystemRoot|WinDir|SystemDrive)"
    r")(?=/|$)",
    re.IGNORECASE,
)


def _collapse_slashes_and_dot(token: str) -> str:
    """Fold ``//`` and ``/./`` only — never resolve ``..``."""
    unified = token.replace("\\", "/")
    while "//" in unified:
        unified = unified.replace("//", "/")
    while "/./" in unified:
        unified = unified.replace("/./", "/")
    if unified.endswith("/."):
        unified = unified[:-2] if len(unified) > 2 else "/"
    return unified


def _expand_rm_path_token(token: str) -> str:
    """Expand ``$VAR`` / ``~`` / ``~user`` when the account is known."""
    expanded = os.path.expandvars(token)
    try:
        return os.path.expanduser(expanded)
    except (OSError, RuntimeError, ValueError):
        return expanded


def _normalize_rm_path_token(token: str) -> str:
    """Expand home/vars, then normalize for home / glob / resolve checks.

    ``..`` must not be collapsed before ``~`` / ``$HOME`` expansion — otherwise
    ``~/..`` becomes ``.`` and is skipped, bypassing the ``/Users`` wipe check.
    When the home prefix still cannot be expanded, only ``//`` / ``/./`` are
    folded (``..`` is left for :func:`_unexpanded_home_targets_home_or_above`).

    Windows drive-letter tokens (``C:/Users/alice/..``) are slash-unified and
    ``normpath``'d without ``Path.resolve()`` — on POSIX hosts ``C:`` paths are
    not absolute and resolve would incorrectly join the process cwd.
    """
    token = _strip_glued_endopts_prefix(token)
    if not token or token == "*":
        return token
    # Drive-letter paths: never expanduser/resolve via Path on POSIX.
    if re.match(r"^[A-Za-z]:", token):
        unified = _collapse_slashes_and_dot(token)
        return posixpath.normpath(unified)
    # Unexpanded Windows env forms: keep ``..`` (``%WINDIR%/..`` → not ``.``).
    collapsed = _collapse_slashes_and_dot(token)
    if _RE_UNEXPANDED_HOME_PREFIX.match(
        collapsed,
    ) or _RE_UNEXPANDED_WIN_SYS_PREFIX.match(collapsed):
        return collapsed
    expanded = _expand_rm_path_token(token)
    unified = _collapse_slashes_and_dot(expanded)
    if _RE_UNEXPANDED_HOME_PREFIX.match(
        unified,
    ) or _RE_UNEXPANDED_WIN_SYS_PREFIX.match(unified):
        return unified
    return posixpath.normpath(unified)


def _is_literal_home_or_env_wipe(token: str) -> bool:
    """True for bare home / env wipe tokens (no path resolve needed)."""
    if token == "*" or token in {"~", "$HOME", "${HOME}"}:
        return True
    if _is_home_content_glob_wipe(token):
        return True
    if _RE_NAMED_USER_HOME.fullmatch(token):
        return True
    if _unexpanded_home_targets_home_or_above(token):
        return True
    return _windows_env_token_is_catastrophic(token)


def _is_glob_parent_catastrophic(parent: str, *, base: Path) -> bool:
    """True when a ``DIR/*`` parent's wipe target is catastrophic."""
    # pylint: disable=too-many-return-statements
    if parent in {"~", "$HOME", "${HOME}"}:
        return True
    if _RE_NAMED_USER_HOME.fullmatch(parent):
        return True
    if _unexpanded_home_targets_home_or_above(parent):
        return True
    if _windows_token_is_catastrophic(parent):
        return True
    if _windows_env_token_is_catastrophic(parent):
        return True
    resolved_parent = _resolve_path_token(parent, base)
    if resolved_parent is not None and _is_resolved_path_catastrophic(
        resolved_parent,
    ):
        return True
    # Literal POSIX / emulated-Windows path (host-independent parts).
    if parent.startswith("/"):
        return _is_posix_abs_token_catastrophic(parent)
    return False


def _token_is_catastrophic_after_normalize(
    normalized: str,
    *,
    base: Path,
) -> bool:
    """Shared post-normalize checks for rm / Windows destructive targets."""
    # pylint: disable=too-many-return-statements
    if not normalized or normalized == ".":
        return False
    if _is_literal_home_or_env_wipe(normalized):
        return True

    parent, is_glob = _split_trailing_glob(normalized)
    if is_glob:
        return _is_glob_parent_catastrophic(parent, base=base)

    if _windows_token_is_catastrophic(normalized):
        return True
    if _windows_env_token_is_catastrophic(normalized):
        return True

    resolved = _resolve_path_token(normalized, base)
    if resolved is not None and _is_resolved_path_catastrophic(resolved):
        return True
    # POSIX absolute / emulated-Windows paths: classify via PurePosixPath
    # so Windows hosts do not miss ``/etc`` / ``/mnt/c/Windows`` when
    # ``Path.resolve()`` rewrites them onto the current drive.
    if normalized.startswith("/"):
        return _is_posix_abs_token_catastrophic(normalized)
    return False


def _unexpanded_home_targets_home_or_above(token: str) -> bool:
    """True when an unexpanded ``~`` / ``$HOME`` path lands on home or above.

    Used for ``~unknown/..`` / ``%USERPROFILE%\\..`` where expand failed, so
    ``normpath`` must not eat the ``..`` segments.
    """
    unified = token.replace("\\", "/").rstrip("/")
    match = _RE_UNEXPANDED_HOME_PREFIX.match(unified)
    if match is None:
        return False
    rest = unified[match.end() :]
    if not rest:
        return False
    # depth 0 == home root; negative == parent of home (e.g. /Users).
    depth = 0
    saw_dotdot = False
    for seg in rest.split("/"):
        if not seg or seg == ".":
            continue
        if seg == "..":
            saw_dotdot = True
            depth -= 1
            if depth < 0:
                return True
        elif seg in {"*", ".*"}:
            # ``~/*`` / ``~unknown/.*`` — home-content wipe.
            return depth <= 0
        else:
            depth += 1
    return saw_dotdot and depth <= 0


def _is_home_content_glob_wipe(token: str) -> bool:
    """Return True for home-content globs (``/Users/alice/*``, ``~/*``, …)."""
    return bool(_RE_HOME_CONTENT_GLOB.fullmatch(token))


def _split_trailing_glob(normalized: str) -> tuple[str, bool]:
    """Split ``DIR/*`` / ``DIR/.*`` into parent + glob flag."""
    if normalized.endswith("/*"):
        parent = normalized[:-2]
        return (parent if parent else "/"), True
    if normalized.endswith("/.*"):
        parent = normalized[:-3]
        return (parent if parent else "/"), True
    return normalized, False


def _resolve_path_token(token: str, base: Path) -> Path | None:
    """Resolve an already-expanded / normalized *token* against *base*."""
    try:
        # Re-expand in case caller passed a still-literal home/var token.
        expanded = _expand_rm_path_token(token)
        candidate = Path(expanded)
        if not candidate.is_absolute():
            candidate = base / candidate
        return candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _resolve_base_dir(cwd: str | Path | None) -> Path:
    """Prefer explicit *cwd*, then ToolGuard workspace, then process cwd."""
    if cwd is not None:
        try:
            return Path(cwd).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return Path(cwd).expanduser().absolute()
    try:
        # Lazy import: rule_guardian imports this module at load time.
        from qwenpaw.security.tool_guard.guardians.rule_guardian import (
            _get_workspace_root,
        )

        return _get_workspace_root().resolve()
    except Exception:
        return Path.cwd()


def _extract_win_path_tokens(text: str) -> list[str]:
    """Extract boundary-safe ``C:\\...`` / ``C:/...`` tokens from *text*."""
    out: list[str] = []
    for match in _RE_WIN_PATH_TOKEN.finditer(text):
        token = match.group(1).rstrip("\\/") or match.group(1)
        out.append(token)
    return out


def _extract_win_env_and_home_tokens(text: str) -> list[str]:
    """Extract percent-env / PowerShell home and system path tokens."""
    out: list[str] = []
    for match in _RE_WIN_ENV_PATH_TOKEN.finditer(text):
        token = match.group(0).rstrip("\\/") or match.group(0)
        out.append(token)
    for match in _RE_PS_HOME_TOKEN.finditer(text):
        token = match.group(1).rstrip("\\/") or match.group(1)
        out.append(token)
    return out


def _extract_recursive_rm_targets(command: str) -> list[str]:
    """Best-effort path tokens from recursive ``rm`` command segments."""
    targets: list[str] = []
    for segment in re.split(r"[|&;]", command):
        if not _RE_RECURSIVE_RM.search(segment):
            continue
        # Raw Windows paths before POSIX shlex eats ``\\`` (``C:\\Users`` →
        # ``C:Users``).  Forward-slash forms are also picked up here.
        targets.extend(_extract_win_path_tokens(segment))
        targets.extend(_extract_win_env_and_home_tokens(segment))
        try:
            tokens = shlex.split(segment, posix=os.name != "nt")
        except ValueError:
            tokens = segment.split()
        rm_idx = next(
            (
                i
                for i, tok in enumerate(tokens)
                if tok == "rm" or tok.endswith("/rm")
            ),
            None,
        )
        if rm_idx is None:
            continue
        end_of_opts = False
        for tok in tokens[rm_idx + 1 :]:
            if tok == "--" and not end_of_opts:
                end_of_opts = True
                continue
            if _is_rm_option_token(tok, end_of_opts=end_of_opts):
                continue
            targets.append(_strip_glued_endopts_prefix(tok))
    return targets


def _extract_windows_destructive_targets(command: str) -> list[str]:
    """Path tokens from recursive Remove-Item / del / rd / rm -Recurse."""
    targets: list[str] = []
    for segment in re.split(r"[|&;]", command):
        if not _RE_WIN_RECURSIVE_CMD.search(segment):
            continue
        targets.extend(_extract_win_path_tokens(segment))
        targets.extend(_extract_win_env_and_home_tokens(segment))
    return targets


def _rm_resolved_target_is_catastrophic(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> bool:
    """Classify rm targets after expand-then-normalize.

    Expand ``~`` / ``$HOME`` *before* ``normpath`` so ``~/..`` becomes
    ``/Users`` (not ``.``).  Unexpanded home prefixes only fold ``//`` /
    ``/./``; ``..`` climbs are handled explicitly.  Also covers WSL
    ``/mnt/<drive>/...`` and ``rm`` of Windows drive-letter paths.
    """
    if not _RE_RECURSIVE_RM.search(command):
        return False
    base = _resolve_base_dir(cwd)
    for token in _extract_recursive_rm_targets(command):
        normalized = _normalize_rm_path_token(token)
        if _token_is_catastrophic_after_normalize(normalized, base=base):
            return True
    return False


def _windows_resolved_target_is_catastrophic(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> bool:
    """Classify Windows destructive targets via normalize (not literal regex).

    Handles ``C:/Users``, ``C:\\Users\\alice\\..``, and similar spellings that
    bypass ``_WIN_CATASTROPHIC_TARGET`` literal matching.
    """
    if not _RE_WIN_RECURSIVE_CMD.search(command):
        return False
    base = _resolve_base_dir(cwd)
    for token in _extract_windows_destructive_targets(command):
        normalized = _normalize_rm_path_token(token)
        if _token_is_catastrophic_after_normalize(normalized, base=base):
            return True
    return False


def _unwrap_indirect_rm(command: str) -> str:
    """Rewrite ``$(which rm)`` / ``${RM:-rm}``-style indirection to ``rm``."""
    out = command
    for pattern, replacement in _RM_INDIRECT_UNWRAP:
        out = pattern.sub(replacement, out)
    return out


def _classify_command_text(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> DestructiveKind | None:
    """Classify a single command string (no indirect-rm rewriting)."""
    if any(p.search(command) for p in _CATASTROPHIC_COMPILED):
        return "catastrophic"
    if _rm_resolved_target_is_catastrophic(command, cwd=cwd):
        return "catastrophic"
    if _windows_resolved_target_is_catastrophic(command, cwd=cwd):
        return "catastrophic"
    if any(p.search(command) for p in _SYSTEM_POWER_COMPILED):
        return "system_power"
    return None


def classify_destructive_command(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> DestructiveKind | None:
    """Classify a shell command's destructive risk.

    Parameters
    ----------
    cwd:
        Directory used to resolve relative ``rm`` targets (e.g. ``../``).
        Prefer the shell/workspace cwd.  When omitted, falls back to the
        ToolGuard workspace root, then ``Path.cwd()``.

    Returns
    -------
    ``"catastrophic"``
        Wipe / mkfs / dd / fork-bomb style commands.  Safe for default
        ToolGuard auto-deny.
    ``"system_power"``
        ``shutdown`` / ``reboot`` / … in command position.  Still blocked
        by ACP hard-block and surfaced for approval, but not auto-denied
        by default (avoids ``npm run reboot`` hard failures).
    ``None``
        Not matched.
    """
    if not command or not command.strip():
        return None
    # Classify *both* the original and the unwrapped form.  Unwrap alone
    # would turn ``$(rm -rf /)`` into bare ``rm`` and drop the wipe target;
    # original alone would miss ``$(which rm) -rf /``.
    kind = _classify_command_text(command, cwd=cwd)
    if kind == "catastrophic":
        return "catastrophic"
    unwrapped = _unwrap_indirect_rm(command)
    if unwrapped != command:
        unwrapped_kind = _classify_command_text(unwrapped, cwd=cwd)
        if unwrapped_kind == "catastrophic":
            return "catastrophic"
        if kind is None:
            kind = unwrapped_kind
    return kind


def is_command_catastrophic(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> bool:
    """Return True for wipe/mkfs/dd/fork-bomb commands (auto-deny worthy)."""
    return classify_destructive_command(command, cwd=cwd) == "catastrophic"


def is_command_destructive(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> bool:
    """Check whether *command* matches a known dangerous pattern.

    Includes both catastrophic wipes and command-position system power
    commands (for ACP hard-block parity).
    """
    return classify_destructive_command(command, cwd=cwd) is not None


def is_path_outside_boundary(
    path: str | Path,
    cwd: str | Path,
    *,
    cwd_is_resolved: bool = False,
    path_is_resolved: bool = False,
) -> bool:
    """Return ``True`` if *path* resolves outside *cwd*.

    Uses :py:meth:`pathlib.PurePath.relative_to` rather than
    string-prefix matching, which is vulnerable to sibling-directory
    bypasses (``/foo/bar_evil/...`` would prefix-match ``/foo/bar``).

    Pass ``cwd_is_resolved=True`` / ``path_is_resolved=True`` when the
    caller has already ``resolve()``-d the value, to avoid extra
    filesystem syscalls on the hot ToolGuard path.

    **Cross-platform note:** On Windows, paths on different drive
    letters (e.g. ``C:\\workspace`` vs ``D:\\evil``) are correctly
    rejected because ``relative_to()`` raises ``ValueError`` when
    the drives differ.
    """
    if cwd_is_resolved:
        cwd_resolved = Path(cwd)
    else:
        cwd_resolved = Path(cwd).resolve()

    if path_is_resolved:
        resolved = Path(path)
    else:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = cwd_resolved / candidate
        try:
            resolved = candidate.resolve()
        except OSError:
            return True

    try:
        resolved.relative_to(cwd_resolved)
        return False
    except ValueError:
        return True
