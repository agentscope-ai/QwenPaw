# -*- coding: utf-8 -*-
"""Trusted installation roots active in the current interpreter."""

from __future__ import annotations

import os
from pathlib import Path
import site
import sys
import sysconfig


def shared_dependency_paths() -> tuple[Path, ...]:
    """Share active system/user sites without inheriting arbitrary paths."""
    candidates = [
        *site.getsitepackages(),
        sysconfig.get_path("purelib"),
        sysconfig.get_path("platlib"),
    ]
    if site.ENABLE_USER_SITE is True:
        user = site.getusersitepackages()
        candidates.extend([user] if isinstance(user, str) else user)
    trusted = {
        Path(os.path.normcase(os.path.realpath(path)))
        for path in candidates
        if path
    }
    return tuple(
        dict.fromkeys(
            path
            for item in sys.path
            if item
            and (path := Path(os.path.normcase(os.path.realpath(item))))
            in trusted
            and path.is_dir()
        ),
    )
