# -*- coding: utf-8 -*-
"""Trusted installation roots active in the current interpreter."""

from __future__ import annotations

from pathlib import Path
import site
import sys
import sysconfig

from ..dependency_maintenance import canonical


def shared_dependency_paths(paths=None) -> tuple[Path, ...]:
    """Share active system/user sites without inheriting arbitrary paths."""
    candidates = [
        *site.getsitepackages(),
        sysconfig.get_path("purelib"),
        sysconfig.get_path("platlib"),
    ]
    if site.ENABLE_USER_SITE is True:
        user = site.getusersitepackages()
        candidates.extend([user] if isinstance(user, str) else user)
    trusted = {str(canonical(path)) for path in candidates if path}
    return tuple(
        dict(
            (str(path), path)
            for item in (sys.path if paths is None else paths)
            if item
            and str(path := canonical(item)) in trusted
            and path.is_dir()
        ).values(),
    )
