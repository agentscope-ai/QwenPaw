# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def directory_link():
    """Exercise directory redirects without requiring Windows elevation."""

    def create(target: Path, link: Path) -> None:
        if os.name == "nt":
            # Junctions are real filesystem redirects and need no symlink
            # privilege. They must be rejected by the same storage guards.
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)

    return create


@pytest.fixture
def file_symlink():
    """Skip only file-link cases if the OS refuses link creation."""

    def create(target: Path, link: Path) -> None:
        try:
            link.symlink_to(target)
        except OSError as error:
            if os.name == "nt" and error.winerror == 1314:
                pytest.skip(
                    "Windows file symlinks require Developer Mode "
                    "or elevation",
                )
            raise

    return create
